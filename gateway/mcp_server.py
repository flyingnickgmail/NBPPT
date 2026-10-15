"""Authenticated MCP transport; generation outlives individual client requests."""
import asyncio
import hashlib
import json
import re
import os
from urllib.parse import urlparse
from mcp.server.transport_security import TransportSecuritySettings
from typing import Annotated

import httpx
from mcp.server.mcpserver import Context, MCPServer
from pydantic import Field

from gateway.config import get_runtime_settings, TASK_FREEZE_CREDITS
from gateway.deepseek_compiler import compile_cn_request_to_english_spec, validate_direct_completion
from gateway.delivery import verify_published, delivery_urls, safe_job_id
from gateway.template_registry import list_available_templates


class PresentationJobs:
    """One gateway process owns admission, running tasks and restart recovery."""
    def __init__(self, billing):
        self.billing = billing
        self.tasks = set()
        self.progress = {}
        self.admission_lock = asyncio.Lock()

    def track(self, coro):
        task = asyncio.create_task(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    async def close(self):
        while self.tasks:
            tasks = list(self.tasks)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def create(self, principal, source, template_id, slide_count, request_id):
        if not source.strip() or len(source) > 100000 or not 0 <= slide_count <= 60:
            raise ValueError("原文不能为空且最多10万字；页数须为0（自动）或1–60")
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", request_id):
            raise ValueError("request_id须为8–80位字母、数字、下划线或短横线；重试必须复用")
        if template_id != "auto" and template_id not in {t['id'] for t in list_available_templates()}:
            raise ValueError("未知模板，请先调用list_templates")
        arguments = {"source": source, "template_id": template_id, "slide_count": slide_count}
        fingerprint = hashlib.sha256(json.dumps(arguments, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        job_id = "ppt_" + hashlib.sha256((principal['user_id'] + ':' + request_id).encode()).hexdigest()[:10]

        async def admit():
            async with self.admission_lock:
                existing = await self.billing.get_job(job_id, principal['user_id'])
                if existing:
                    if existing.get('request_hash') != fingerprint:
                        raise ValueError("request_id已用于不同内容，请为新任务选择新编号")
                    return await self.status(principal, job_id)
                await self.billing.try_freeze_credits(principal['api_key'], job_id, 'ppt', source,
                                                     TASK_FREEZE_CREDITS['ppt'], request_hash=fingerprint)
                self.progress[job_id] = {"percent": 0, "message": "已接收，等待生成"}
                self.track(self.execute(job_id, arguments))
                return {"job_id": job_id, "status": "RUNNING", "poll_after_seconds": 30,
                        "message": "任务已提交，使用get_job_status查询；不要重复创建任务。"}
        # A closed MCP request cannot abandon a committed reservation.
        return await asyncio.shield(self.track(admit()))

    async def execute(self, job_id, arguments):
        try:
            runtime = get_runtime_settings()
            spec = await compile_cn_request_to_english_spec(arguments['source'], 'ppt',
                {"slide_count": arguments['slide_count'], "template_id": arguments['template_id'], "execution_mode": "codex_cli"})
            spec['requested_slide_count'] = arguments['slide_count']
            await self.billing.save_compiled_spec(job_id, spec)
            completed = None
            async with httpx.AsyncClient(timeout=httpx.Timeout(120, connect=15), trust_env=False) as client:
                async with client.stream('POST', runtime['overseas_worker_url'] + '/internal/execute-stream',
                    headers={'X-Worker-Secret': runtime['overseas_worker_secret']},
                    json={'job_id': job_id, 'task_type': 'ppt', 'english_spec': spec,
                          'execution_mode': 'codex_cli', 'max_budget_usd': .85,
                          'runtime_keys': {'account_safe_proxy': runtime.get('account_safe_proxy', '')}}) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line.startswith('data: '):
                            continue
                        event = json.loads(line[6:])
                        if event.get('type') == 'error':
                            raise RuntimeError(event.get('message', 'Worker failed'))
                        if event.get('type') == 'progress':
                            self.progress[job_id] = {'percent': min(99, event.get('pct', 0)),
                                                     'message': event.get('message_cn', '')}
                        if event.get('type') == 'completed':
                            if completed is not None:
                                raise ValueError('Worker returned more than one completion')
                            completed = event
            if completed is None:
                raise ValueError('Worker returned no completed delivery')
            actual_spec = validate_direct_completion(completed)
            actual_spec['requested_slide_count'] = arguments['slide_count']
            await self.billing.save_compiled_spec(job_id, actual_spec)
            await self.billing.confirm_settle(job_id, float(completed['total_cost_usd']), completed.get('cdn_urls', {}))
        except asyncio.CancelledError:
            await asyncio.shield(self.billing.cancel_refund(job_id, 'Gateway stopped during generation'))
            raise
        except Exception as exc:
            await self.billing.cancel_refund(job_id, str(exc))
        finally:
            self.progress.pop(job_id, None)

    async def owned_job(self, principal, job_id):
        safe_job_id(job_id)
        job = await self.billing.get_job(job_id, principal['user_id'])
        if not job:
            raise ValueError('任务不存在或无权访问')
        return job

    async def status(self, principal, job_id):
        job = await self.owned_job(principal, job_id)
        result = {'job_id': job_id, 'status': job['status'], 'credits_charged': job['credits_charged']}
        if job['status'] == 'RUNNING':
            result.update(self.progress.get(job_id, {}))
            result['poll_after_seconds'] = 30
        elif job['status'] == 'FAILED':
            result['message'] = '生成或文件验收失败，冻结算力已退回。请联系管理员查看详细日志。'
        elif job['status'] == 'COMPLETED':
            result['percent'] = 100
            result['message'] = '文件检查通过；内容和图片文字仍需人工复核。调用get_job_artifacts获取产物。'
        return result

    async def artifacts(self, principal, job_id):
        job = await self.owned_job(principal, job_id)
        if job['status'] != 'COMPLETED':
            raise ValueError('任务尚未成功完成，没有可交付产物')
        manifest = await asyncio.to_thread(verify_published, job_id, 'ppt',
            json.loads(job['en_compiled_spec']), self.billing.jobs_root / job_id / 'output')
        return {'job_id': job_id, 'file_status': 'PASSED', 'content_status': 'NOT_REVIEWED',
                'slide_count': manifest['planned_slides'], 'artifacts': delivery_urls(job_id, manifest),
                'files': manifest['files'], 'download_auth': 'Use the same Bearer credential as MCP; do not put it in URLs.'}


def build_mcp(jobs):
    server = MCPServer('NBPPT', version='2.0.0', instructions=(
        '先选择模板，再用完整原文创建PPT。模板只约束品牌风格，各页按内容选择布局。'
        '创建后每30秒查询一次进度，成功后获取产物。不得把任务已提交说成已生成。'
        'request_id用于幂等重试，重试同一请求必须复用。文件验收不等同于内容事实核查。'))

    def principal(ctx):
        return ctx.request_context.request.state.principal

    @server.tool()
    async def list_templates() -> dict:
        """列出可用品牌风格参考；不要求每页使用相同版式。"""
        return {'templates': [{k: t.get(k) for k in ('id', 'name', 'description', 'badge')}
                              for t in list_available_templates()]}

    @server.tool()
    async def create_presentation(ctx: Context,
        source: Annotated[str, Field(min_length=1, max_length=100000)],
        request_id: Annotated[str, Field(pattern=r'^[A-Za-z0-9_-]{8,80}$')],
        template_id: str = 'auto', slide_count: Annotated[int, Field(ge=0, le=60)] = 0) -> dict:
        """提交完整原文生成PPT，立即返回job_id。0页表示由内容决定。消耗平台算力点。"""
        return await jobs.create(principal(ctx), source, template_id, slide_count, request_id)

    @server.tool()
    async def get_job_status(ctx: Context, job_id: str) -> dict:
        """查询自己任务的进度和结算状态；RUNNING时30秒后再查。"""
        return await jobs.status(principal(ctx), job_id)

    @server.tool()
    async def get_job_artifacts(ctx: Context, job_id: str) -> dict:
        """完成后再次验证文件摘要，返回PPTX、HTML和逐页PNG的下载路径及摘要。"""
        return await jobs.artifacts(principal(ctx), job_id)

    origin = os.getenv('NBPPT_PUBLIC_ORIGIN', 'http://127.0.0.1:8000')
    parsed = urlparse(origin)
    security = TransportSecuritySettings(enable_dns_rebinding_protection=True,
        allowed_hosts=['127.0.0.1:*', 'localhost:*', '[::1]:*', parsed.netloc],
        allowed_origins=[origin])
    return server.streamable_http_app(json_response=True, stateless_http=True, transport_security=security)
