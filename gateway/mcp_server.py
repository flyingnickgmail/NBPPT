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
from gateway.template_registry import list_available_templates, match_template_for_prompt
from gateway.ppt_contract import resolve_ppt_engine, require_claude_owner, ProviderUnavailable


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

    async def claude_status(self, principal):
        require_claude_owner(principal.get('user_id'))
        runtime = get_runtime_settings()
        try:
            async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
                response = await client.get(runtime['overseas_worker_url'] + '/internal/claude-status',
                    headers={'X-Worker-Secret': runtime['overseas_worker_secret']})
                response.raise_for_status()
                data = response.json()
            if data.get('state') not in ('ready', 'cooldown', 'blocked', 'unavailable'):
                raise ValueError('Invalid provider state')
            delay = data.get('retry_after_seconds', 0)
            if type(delay) not in (int, float) or not 0 <= delay <= 366 * 86400:
                raise ValueError('Invalid provider cooldown')
            # Do not forward worker-supplied paths, account identifiers or errors.
            labels = {'ready': 'Claude 可以接受任务', 'cooldown': 'Claude 限流冷却中，请等待后重试',
                      'blocked': 'Claude 账号调用已暂停，请持有人处理后手动恢复', 'unavailable': 'Claude 运行环境未就绪'}
            return {'state': data['state'], 'retry_after_seconds': int(delay), 'message': labels[data['state']]}
        except Exception:
            return {'state': 'unavailable', 'retry_after_seconds': 0, 'message': '无法确认 Claude 账号状态，暂停提交'}

    async def require_claude_ready(self, principal):
        status = await self.claude_status(principal)
        if status['state'] != 'ready':
            raise ProviderUnavailable(status['state'], status['message'], status['retry_after_seconds'])

    async def create(self, principal, source, template_id, slide_count, request_id,
                     task_type='ppt', video_duration_sec=30, video_aspect_ratio='16:9',
                     video_voice='melo', video_narration=True, video_subtitles=True,
                     execution_mode='auto'):
        self._require_scope(principal, write=True)
        if task_type not in ('ppt', 'video'):
            raise ValueError('PPT和视频须分别创建任务，以便独立结算和重试')
        if task_type == 'video' and execution_mode not in ('auto', 'codex_cli'):
            raise ValueError('视频尚未开放 Claude 执行，不能替换成其他引擎')
        engine = resolve_ppt_engine(execution_mode) if task_type == 'ppt' else 'codex_cli'
        if engine in ('claude_cli', 'claude_codex'):
            require_claude_owner(principal.get('user_id'))
        if task_type == 'video':
            from gateway.video_contract import VIDEO_VOICES
            if video_voice not in VIDEO_VOICES or type(video_narration) is not bool or type(video_subtitles) is not bool:
                raise ValueError('视频音色或配音、字幕开关无效')
            if video_voice != 'melo' and os.getenv('NBPPT_KOKORO_ENABLED', 'false').lower() != 'true':
                raise ValueError('服务器尚未启用 Kokoro 可选音色，请选择默认中文配音')
        if task_type == 'video' and (type(video_duration_sec) is not int or not 6 <= video_duration_sec <= 60
                                     or video_aspect_ratio not in ('16:9', '9:16')):
            raise ValueError('视频时长须为6–60秒整数，画幅须为16:9或9:16')
        if not source.strip() or len(source) > 100000 or not 0 <= slide_count <= 60:
            raise ValueError("原文不能为空且最多10万字；页数须为0（自动）或1–60")
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", request_id):
            raise ValueError("request_id须为8–80位字母、数字、下划线或短横线；重试必须复用")
        if template_id != "auto" and template_id not in {t['id'] for t in list_available_templates()}:
            raise ValueError("未知模板，请先调用list_templates")
        arguments = {"source": source, "template_id": template_id, "slide_count": slide_count}
        if engine in ('claude_cli', 'claude_codex'):
            arguments['execution_mode'] = engine
        if task_type == 'video':
            arguments.update(task_type='video', slide_count=0, video_duration_sec=video_duration_sec,
                             video_aspect_ratio=video_aspect_ratio, video_voice=video_voice,
                             video_narration=video_narration, video_subtitles=video_subtitles)
        fingerprint_args = dict(arguments)
        for key, default in (('video_voice', 'melo'), ('video_narration', True), ('video_subtitles', True)):
            if fingerprint_args.get(key) == default:
                fingerprint_args.pop(key, None)
        fingerprint = hashlib.sha256(json.dumps(fingerprint_args, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        job_id = task_type + "_" + hashlib.sha256((principal['user_id'] + ':' + request_id).encode()).hexdigest()[:10]

        async def admit():
            async with self.admission_lock:
                existing = await self.billing.get_job(job_id, principal['user_id'])
                if existing:
                    if existing.get('request_hash') != fingerprint:
                        raise ValueError("request_id已用于不同内容，请为新任务选择新编号")
                    return await self.status(principal, job_id)
                if engine in ('claude_cli', 'claude_codex'):
                    await self.require_claude_ready(principal)
                handed_off = False
                try:
                    await self.billing.try_freeze_credits(principal['api_key'], job_id, task_type, source,
                                                         TASK_FREEZE_CREDITS[task_type], request_hash=fingerprint)
                    # Persist the original request before compilation so a failed compile can be retried.
                    await self.billing.save_compiled_spec(job_id, {"_request": arguments})
                    self.progress[job_id] = {"percent": 0, "stage": "queued", "message": "已接收，等待生成"}
                    execution = {**arguments, 'account_owner_user_id': principal['user_id']} if engine in ('claude_cli', 'claude_codex') else arguments
                    self.track(self.execute(job_id, execution))
                    handed_off = True
                    return {"job_id": job_id, "status": "RUNNING", "poll_after_seconds": 30,
                            "message": "任务已提交，使用get_job_status查询；不要重复创建任务。"}
                except asyncio.CancelledError:
                    if not handed_off:
                        await asyncio.shield(self.billing.cancel_refund(job_id, "Gateway stopped during admission"))
                    raise
                except Exception:
                    if not handed_off:
                        await self.billing.cancel_refund(job_id, "Failed to persist generation request")
                    raise
        # A closed MCP request cannot abandon a committed reservation.
        return await asyncio.shield(self.track(admit()))

    async def execute(self, job_id, arguments):
        try:
            task_type = arguments.get('task_type', 'ppt')
            self.progress[job_id] = {"percent": 10, "stage": "planning", "message": "正在规划内容与逐页结构"}
            runtime = get_runtime_settings()
            if task_type == 'video':
                spec = {'generation_contract': 'skill-video-v1', 'original_prompt_cn': arguments['source'],
                        'video_duration_sec': arguments['video_duration_sec'],
                        'video_aspect_ratio': arguments['video_aspect_ratio'],
                        'planner_provider': 'codex_cli', 'video_narration': arguments.get('video_narration', True),
                        'video_voice': arguments.get('video_voice', 'melo'),
                        'video_subtitles': arguments.get('video_subtitles', True),
                        'matched_template': match_template_for_prompt(arguments['source'], arguments['template_id'])}
            else:
                spec = await compile_cn_request_to_english_spec(arguments['source'], 'ppt',
                    {"slide_count": arguments['slide_count'], "template_id": arguments['template_id'], "execution_mode": arguments.get('execution_mode', 'codex_cli')})
                spec['requested_slide_count'] = arguments['slide_count']
                if arguments.get('execution_mode') in ('claude_cli', 'claude_codex'):
                    spec['account_owner_user_id'] = arguments['account_owner_user_id']
            spec['_request'] = {k: v for k, v in arguments.items() if k != 'account_owner_user_id'}
            await self.billing.save_compiled_spec(job_id, spec)
            self.progress[job_id] = {"percent": 10, "stage": "planning", "message": "正在准备视频分镜"} if task_type == 'video' else {"percent": 25, "stage": "generating", "message": "内容规划完成，正在生成页面"}
            completed = None
            async with httpx.AsyncClient(timeout=httpx.Timeout(600, connect=15), trust_env=False) as client:
                async with client.stream('POST', runtime['overseas_worker_url'] + '/internal/execute-stream',
                    headers={'X-Worker-Secret': runtime['overseas_worker_secret']},
                    json={'job_id': job_id, 'task_type': task_type, 'english_spec': spec,
                          'execution_mode': arguments.get('execution_mode', 'codex_cli'), 'max_budget_usd': .85,
                          'runtime_keys': {'account_safe_proxy': runtime.get('account_safe_proxy', '')}}) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line.startswith('data: '):
                            continue
                        event = json.loads(line[6:])
                        if event.get('type') == 'error':
                            if event.get('provider_state') in ('cooldown', 'blocked'):
                                raise ProviderUnavailable(event['provider_state'], 'Claude 账号调用已暂停，本项冻结算力将退回', event.get('retry_after_seconds', 0))
                            raise RuntimeError(event.get('message', 'Worker failed'))
                        if event.get('type') == 'progress':
                            self.progress[job_id] = {'percent': min(99, event.get('pct', 0)),
                                                     'stage': event.get('stage', 'generating'),
                                                     'message': event.get('message_cn', '')}
                        if event.get('type') == 'completed':
                            if completed is not None:
                                raise ValueError('Worker returned more than one completion')
                            completed = event
            if completed is None:
                raise ValueError('Worker returned no completed delivery')
            self.progress[job_id] = {"percent": 96, "stage": "checking", "message": "生成完成，正在严格检查交付文件"}
            if task_type == 'video':
                actual_spec = completed.get('compiled_spec', {})
                # Bind completion to the admitted source/options before independent file QA/settlement.
                for key in ('generation_contract', 'original_prompt_cn', 'video_duration_sec', 'video_aspect_ratio', 'planner_provider', 'video_narration', 'video_voice', 'video_subtitles', 'matched_template'):
                    if actual_spec.get(key) != spec.get(key):
                        raise ValueError('Video completion does not match the admitted request')
                if not actual_spec.get('video_scenes'):
                    raise ValueError('Video completion lacks validated storyboard')
                from gateway.video_contract import validate_video_plan
                validated = validate_video_plan({'task_summary_cn': actual_spec.get('task_summary_cn'),
                                                 'scenes': actual_spec['video_scenes']}, spec)
                if validated != actual_spec['video_scenes']:
                    raise ValueError('Video completion contains unnormalised storyboard')
            else:
                actual_spec = validate_direct_completion(completed, spec)
                if actual_spec.get('generator_engine', 'codex_cli') != arguments.get('execution_mode', 'codex_cli'):
                    raise ValueError('PPT completion does not match the admitted provider')
                actual_spec['requested_slide_count'] = arguments['slide_count']
            actual_spec['_request'] = {k: v for k, v in arguments.items() if k != 'account_owner_user_id'}
            await self.billing.save_compiled_spec(job_id, actual_spec)
            await self.billing.confirm_settle(job_id, float(completed['total_cost_usd']), completed.get('cdn_urls', {}))
        except asyncio.CancelledError:
            await asyncio.shield(self.billing.cancel_refund(job_id, 'Gateway stopped during generation'))
            raise
        except Exception as exc:
            if isinstance(exc, ProviderUnavailable):
                # Persist a safe classification so a completed refund can explain the failure.
                try:
                    current = await self.billing.get_job(job_id)
                    snapshot = json.loads((current or {}).get('en_compiled_spec') or '{}')
                    snapshot['_provider_failure'] = {'state': exc.state, 'retry_after_seconds': exc.retry_after}
                    await self.billing.save_compiled_spec(job_id, snapshot)
                finally:
                    await self.billing.cancel_refund(job_id, str(exc))
                return
            await self.billing.cancel_refund(job_id, str(exc))
        finally:
            self.progress.pop(job_id, None)

    async def owned_job(self, principal, job_id):
        self._require_scope(principal, write=False)
        safe_job_id(job_id)
        job = await self.billing.get_job(job_id, principal['user_id'])
        if not job:
            raise ValueError('任务不存在或无权访问')
        return job

    async def status(self, principal, job_id):
        job = await self.owned_job(principal, job_id)
        result = {'job_id': job_id, 'status': job['status'], 'task_type': job['task_type'],
                  'credits_charged': job['credits_charged'], 'credits_frozen': job['credits_frozen'],
                  # Keep the historical reservation field compatible; expose current money state explicitly.
                  'credits_held': job['credits_frozen'] if job['status'] == 'RUNNING' else 0,
                  'credits_refunded': job['credits_frozen'] - job['credits_charged'] if job['status'] in ('FAILED', 'COMPLETED') else 0,
                  'created_at': job['created_at'], 'completed_at': job['completed_at']}
        spec = json.loads(job['en_compiled_spec'] or '{}')
        request = spec.get('_request')
        if request:
            result['request'] = request
        if job['status'] == 'RUNNING':
            result.update(self.progress.get(job_id, {"percent": 0, "stage": "queued", "message": "任务正在恢复或等待执行"}))
            result['poll_after_seconds'] = 30
        elif job['status'] == 'FAILED':
            result['stage'] = 'failed'
            result['message'] = '生成或文件验收失败，冻结算力已退回。请联系管理员查看详细日志。'
            if spec.get('_provider_failure'):
                result['provider'] = spec['_provider_failure']
                result['message'] = 'Claude 账号限流或授权异常，已停止调用并退回本项冻结算力。处理账号状态后可重试。'
        elif job['status'] == 'COMPLETED':
            result['percent'] = 100
            result['stage'] = 'ready'
            result['message'] = '文件检查通过；内容和图片文字仍需人工复核。调用get_job_artifacts获取产物。'
        return result

    async def retry(self, principal, job_id, request_id):
        self._require_scope(principal, write=True)
        job = await self.owned_job(principal, job_id)
        if job['status'] != 'FAILED':
            raise ValueError('只有失败且已退款的任务可以重试')
        try:
            arguments = json.loads(job['en_compiled_spec'] or '{}')['_request']
        except (KeyError, TypeError, json.JSONDecodeError):
            raise ValueError('旧任务缺少可重试的原始参数，请重新创建任务')
        retry_job_id = job['task_type'] + "_" + hashlib.sha256((principal['user_id'] + ':' + request_id).encode()).hexdigest()[:10]
        if retry_job_id == job_id:
            raise ValueError('重试须使用新的request_id；重复提交原request_id只会返回原任务')
        return await self.create(principal, arguments['source'], arguments['template_id'],
                                 arguments['slide_count'], request_id, task_type=job['task_type'],
                                 video_duration_sec=arguments.get('video_duration_sec', 30),
                                 video_aspect_ratio=arguments.get('video_aspect_ratio', '16:9'),
                                 video_voice=arguments.get('video_voice', 'melo'),
                                 video_narration=arguments.get('video_narration', True),
                                 video_subtitles=arguments.get('video_subtitles', True),
                                 execution_mode=arguments.get('execution_mode', 'auto'))

    async def artifacts(self, principal, job_id):
        job = await self.owned_job(principal, job_id)
        if job['status'] != 'COMPLETED':
            raise ValueError('任务尚未成功完成，没有可交付产物')
        spec = json.loads(job['en_compiled_spec'])
        manifest = await asyncio.to_thread(verify_published, job_id, job['task_type'],
            spec, self.billing.jobs_root / job_id / 'output')
        return {'job_id': job_id, 'task_type': job['task_type'], 'file_status': 'PASSED', 'content_status': 'NOT_REVIEWED',
                'slide_count': manifest['planned_slides'], 'artifacts': delivery_urls(job_id, manifest),
                'video': ({'duration_seconds': spec.get('video_duration_sec'),
                           'aspect_ratio': spec.get('video_aspect_ratio'), 'audio': spec.get('video_audio', False),
                           'subtitles_burned': spec.get('subtitles_burned', False),
                           'narration': spec.get('narration', {})} if job['task_type'] == 'video' else None),
                'files': manifest['files'], 'download_auth': 'Use the same Bearer credential as MCP; do not put it in URLs.'}

    @staticmethod
    def _require_scope(principal, write):
        scope = principal.get('scope', 'generate')
        allowed = {'admin', 'generate'} if write else {'admin', 'generate', 'read'}
        if scope not in allowed:
            raise PermissionError('Credential scope does not allow this operation')


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
        template_id: str = 'auto', slide_count: Annotated[int, Field(ge=0, le=60)] = 0,
        execution_mode: str = 'auto') -> dict:
        """提交完整原文生成PPT，立即返回job_id。0页表示由内容决定。消耗平台算力点。execution_mode=claude_codex 为 Claude 内容策划＋Codex 图片PPT并附文字稿；claude_cli 为原生PPT；auto 为 Codex。Claude 模式仅供绑定持有人。"""
        return await jobs.create(principal(ctx), source, template_id, slide_count, request_id,
                                 execution_mode=execution_mode)

    @server.tool()
    async def create_video(ctx: Context,
        source: Annotated[str, Field(min_length=1, max_length=100000)],
        request_id: Annotated[str, Field(pattern=r'^[A-Za-z0-9_-]{8,80}$')],
        template_id: str = 'auto', duration_seconds: Annotated[int, Field(ge=6, le=60)] = 30,
        aspect_ratio: str = '16:9', voice: str = 'melo', narration: bool = True,
        subtitles: bool = True) -> dict:
        """原文生成中文讲解动画MP4，返回独立job_id；时长6–60秒，画幅16:9或9:16，消耗算力。"""
        return await jobs.create(principal(ctx), source, template_id, 0, request_id,
                                 'video', duration_seconds, aspect_ratio, voice, narration, subtitles)

    @server.tool()
    async def retry_job(ctx: Context, job_id: str,
        request_id: Annotated[str, Field(pattern=r'^[A-Za-z0-9_-]{8,80}$')]) -> dict:
        """仅重试自己已失败并退款的PPT或视频；新request_id只创建一个新任务。"""
        return await jobs.retry(principal(ctx), job_id, request_id)

    @server.tool()
    async def get_job_status(ctx: Context, job_id: str) -> dict:
        """查询自己任务进度与结算；credits_held为当前占用，credits_refunded为已退金额，credits_frozen为历史预冻结。RUNNING时30秒后再查。"""
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
