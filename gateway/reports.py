"""Authenticated NB PPT report workspace, reusing the report studio engine.

Reports use the model account installed on the gateway host. They do not enter
the PPT/video credit settlement pipeline, whose delivery contract is different.
"""
import asyncio
import base64
import hashlib
import json
import os
import re
import shutil
import time
import uuid
import httpx
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

from gateway.config import BASE_DIR, get_runtime_settings
from gateway.report_contract import PRICES, parse_input, read_quality_feedback
from gateway.delivery import verify_published, delivery_urls
from tools.report_studio.app import STATIC, export_html, local_report
from tools.report_studio.evidence import validate_evidence
from tools.report_studio.generator import ai_report, design_editorial, design_reading, refine_report
from tools.report_studio.models import ExportInput, GenerateInput
from tools.report_studio.overview import validate_overview
from tools.report_studio.overview_generation import create_overview
from tools.report_studio.quality import review_report


API = '/api/reports'
router = APIRouter()


def platform_html(data: ExportInput) -> str:
    # Only trusted, server-owned routing configuration is injected; material is
    # escaped by the shared exporter. Offline downloads omit this configuration.
    return export_html(data).replace('<body>', '<body><script>window.ReportStudioConfig={apiBase:"/api/reports",platform:true};</script>', 1)


class ReportWorkspace:
    def __init__(self, root: Path):
        self.root = root
        self.tasks = {}
        self.lock = asyncio.Lock()
        self.admission_lock = asyncio.Lock()
        self.admissions = set()

    @staticmethod
    def billing():
        # Resolve the live platform instance, including disposable acceptance DBs.
        from gateway.main import billing
        return billing

    def folder(self, key: str) -> Path:
        if not re.fullmatch(r'[a-f0-9]{32}', key):
            raise HTTPException(404, '报告不存在')
        folder = self.root / key
        if folder.is_symlink() or not folder.resolve().is_relative_to(self.root.resolve()):
            raise HTTPException(404, '报告不存在')
        return folder

    @staticmethod
    def write(path: Path, data: dict):
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        temp.replace(path)

    def owned(self, key: str, owner: str) -> dict:
        try:
            folder = self.folder(key)
            path = folder / 'status.json'
            if path.is_symlink():
                raise ValueError('unsafe metadata')
            status = json.loads(path.read_text())
        except (OSError, ValueError):
            raise HTTPException(404, '报告不存在')
        if status.get('owner') != owner:
            raise HTTPException(404, '报告不存在')
        if status['state'] not in {'completed', 'failed', 'draft'} and key not in self.tasks:
            status.update(state='failed', message='服务已重启，原材料保留；请重新生成。')
            self.write(path, status)
        return status

    @staticmethod
    def public(status: dict) -> dict:
        result = {k: v for k, v in status.items() if k not in {'owner', 'sha256', 'input_sha256', 'request_hash'}}
        result['credits_held'] = status.get('credits_frozen', 0) if status['state'] not in {'completed', 'failed', 'draft'} else 0
        return result

    def create(self, owner: str, title: str, kind: str) -> dict:
        key = uuid.uuid4().hex
        folder = self.folder(key)
        folder.mkdir(parents=True, exist_ok=False)
        status = dict(id=key, owner=owner, title=title or '研究报告', kind=kind,
                      created_at=time.time(), state='planning', message='正在准备材料')
        self.write(folder / 'status.json', status)
        return status

    def save(self, status: dict, data: ExportInput, complete=True):
        html = export_html(data)  # Evidence and artwork version validation.
        folder = self.folder(status['id'])
        raw = data.model_dump_json(indent=2).encode()
        (folder / 'report.json').write_bytes(raw)
        (folder / 'report.html').write_text(html, encoding='utf-8')
        status.update(state='completed' if complete else 'checking', message='报告已保存，请核阅内容后分享。' if complete else '文件已核对，正在结算积分',
                      title=data.report.title, sha256=hashlib.sha256(raw).hexdigest(),
                      preview_url=f"{API}/preview/{status['id']}")
        self.write(folder / 'status.json', status)

    async def start_remote(self, principal, title, kind, data, request_id=None):
        report_user(principal, write=True)
        require_runtime()
        request_id = request_id or uuid.uuid4().hex
        if not re.fullmatch(r'[A-Za-z0-9_-]{8,80}', request_id):
            raise HTTPException(422, '任务请求编号无效')
        raw = data.model_dump_json(indent=2).encode()
        fingerprint = hashlib.sha256(kind.encode() + b':' + raw).hexdigest()
        key = hashlib.sha256((principal['user_id'] + ':report:' + request_id).encode()).hexdigest()[:32]
        task_type = 'report_share' if kind == 'overview' else 'report'
        job_id = ('reportshare_' if kind == 'overview' else 'report_') + key[:10]
        spec = {'generation_contract': 'research-report-v1', 'operation': kind, 'report_id': key,
                'input': data.model_dump(), 'input_sha256': hashlib.sha256(data.model_dump_json().encode()).hexdigest()}
        if kind == 'overview':
            # Carry QA only for this owner's identical report, never across tenants.
            for previous in sorted(self.root.glob('*/status.json'), key=lambda p: p.stat().st_mtime, reverse=True):
                try:
                    old = self.owned(previous.parent.name, principal['user_id'])
                    if old['state'] != 'failed' or old.get('request_hash') != fingerprint:
                        continue
                    old_job = old.get('billing_job_id', '')
                    if not re.fullmatch(r'reportshare_[a-f0-9]{10}', old_job):
                        continue
                    feedback = read_quality_feedback(self.billing().jobs_root / old_job / 'reselection') or read_quality_feedback(self.billing().jobs_root / old_job)
                    if feedback:
                        spec['previous_quality_failure'] = feedback
                        break
                except HTTPException:
                    continue
        parse_input(spec)

        async def admit():
            async with self.admission_lock:
                path = self.folder(key) / 'status.json'
                if path.exists():
                    status = self.owned(key, principal['user_id'])
                    if status.get('request_hash') != fingerprint:
                        raise HTTPException(409, '同一请求编号已用于其他内容')
                    return {'id': key, 'status_url': f'{API}/jobs/{key}'}
                billing = self.billing()
                if await billing.get_job(job_id, principal['user_id']):
                    raise HTTPException(409, '之前的请求受理已中断，请核对历史记录后用新请求编号重试')
                frozen = False
                handed_off = False
                try:
                    try:
                        await billing.try_freeze_credits(principal['api_key'], job_id, task_type, data.content,
                                                        PRICES[task_type], request_hash=fingerprint)
                    except PermissionError:
                        raise HTTPException(403, '生成权限已变更，请重新登录')
                    except ValueError as exc:
                        raise HTTPException(422, str(exc))
                    frozen = True
                    await billing.save_compiled_spec(job_id, spec)
                    folder = self.folder(key)
                    folder.mkdir(parents=True, exist_ok=False)
                    (folder / 'input.json').write_bytes(raw)
                    status = dict(id=key, owner=principal['user_id'], title=title or '研究报告', kind=kind,
                                  created_at=time.time(), state='queued', message='已冻结积分，等待远程执行',
                                  input_sha256=hashlib.sha256(raw).hexdigest(), request_hash=fingerprint,
                                  billing_job_id=job_id, credits_frozen=PRICES[task_type], credits_charged=0)
                    self.write(path, status)
                    self.tasks[key] = asyncio.create_task(self.run_remote(status, spec))
                    handed_off = True
                    return {'id': key, 'status_url': f'{API}/jobs/{key}'}
                finally:
                    if frozen and not handed_off:
                        await asyncio.shield(billing.cancel_refund(job_id, 'Report admission interrupted'))

        admission = asyncio.create_task(admit())
        self.admissions.add(admission)
        admission.add_done_callback(self.admissions.discard)
        return await asyncio.shield(admission)

    async def run_remote(self, status, spec):
        key, job_id = status['id'], status['billing_job_id']
        billing = self.billing()
        path = self.folder(key) / 'status.json'
        try:
            runtime = get_runtime_settings()
            completed = None
            async with asyncio.timeout(3900), httpx.AsyncClient(timeout=httpx.Timeout(90, connect=15), trust_env=False) as client:
                async with client.stream('POST', runtime['overseas_worker_url'] + '/internal/reports/execute-stream',
                                         headers={'X-Worker-Secret': runtime['overseas_worker_secret']},
                                         json={'job_id': job_id, 'spec': spec}) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line.startswith('data: '):
                            continue
                        event = json.loads(line[6:])
                        if event.get('type') == 'error':
                            raise ValueError('Worker report generation failed')
                        if event.get('type') == 'progress':
                            stages = {'planning': '正在从全文选择核心问题与图形表达',
                                      'reselecting': '原表达未通过复核，正在从全文重新选题与设计',
                                      'generating': '执行节点正在生成内容与图形',
                                      'composing': '正在编排图表叙事与封面',
                                      'checking': '正在核对数字、证据、图形与手机可读性'}
                            stage = event.get('stage') if event.get('stage') in stages else 'generating'
                            status.update(state=stage, message=stages[stage])
                            self.write(path, status)
                        if event.get('type') == 'completed':
                            if completed is not None:
                                raise ValueError('Multiple report completions')
                            completed = event
            if completed is None:
                raise ValueError('Report worker returned no completion')
            task_type = 'report_share' if spec['operation'] == 'overview' else 'report'
            root = billing.jobs_root / job_id / 'output'
            manifest = await asyncio.to_thread(verify_published, job_id, task_type, spec, root)
            urls = delivery_urls(job_id, manifest)
            if completed.get('cdn_urls') != urls:
                raise ValueError('Report completion URL mismatch')
            data = ExportInput.model_validate_json((root / 'report.json').read_text())
            self.save(status, data, complete=False)
            settled = await billing.confirm_settle(job_id, None, urls)
            status.update(state='completed', message='报告已保存并结算，请核阅后分享。',
                          credits_charged=settled['charged_credits'])
            self.write(path, status)
        except asyncio.CancelledError:
            await asyncio.shield(billing.cancel_refund(job_id, 'Gateway stopped during report generation'))
            job = await billing.get_job(job_id, status['owner'])
            if job and job['status'] == 'COMPLETED':
                status.update(state='completed', credits_charged=job['credits_charged'], message='报告已保存并结算，请核阅后分享。')
            else:
                status.update(state='failed', message='服务中断，冻结积分已退回；原材料保留。')
            self.write(path, status)
            raise
        except Exception:
            job = await billing.get_job(job_id, status['owner'])
            if job and job['status'] == 'COMPLETED':
                status.update(state='completed', credits_charged=job['credits_charged'], message='报告已保存并结算，请核阅后分享。')
            else:
                await billing.cancel_refund(job_id, 'Report generation or delivery verification failed')
                status.update(state='failed', message='生成或交付校验未通过，冻结积分已退回；原材料保留。')
            self.write(path, status)
        finally:
            self.tasks.pop(key, None)

    def result(self, key: str, owner: str) -> ExportInput:
        status = self.owned(key, owner)
        if status['state'] != 'completed':
            raise HTTPException(409, '报告尚未完成')
        path = self.folder(key) / 'report.json'
        try:
            if path.is_symlink():
                raise ValueError('unsafe artifact')
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != status['sha256']:
                raise ValueError('artifact changed')
            data = ExportInput.model_validate_json(raw)
            validate_evidence(data.report, data.content)
            validate_overview(data)
            return data
        except (OSError, ValueError):
            raise HTTPException(409, '报告文件已改变或无效，请重新生成')

    async def start(self, owner: str, title: str, kind: str, data):
        if self.lock.locked():
            raise HTTPException(409, '已有报告任务正在生成；完成后可继续，历史报告仍可阅读。')
        await self.lock.acquire()
        try:
            status = self.create(owner, title, kind)
            folder = self.folder(status['id'])
            raw = data.model_dump_json(indent=2).encode()
            (folder / 'input.json').write_bytes(raw)
            status['input_sha256'] = hashlib.sha256(raw).hexdigest()
            self.write(folder / 'status.json', status)
            self.tasks[status['id']] = asyncio.create_task(self.run(status, data))
        except Exception:
            self.lock.release()
            raise
        return {'id': status['id'], 'status_url': f"{API}/jobs/{status['id']}"}

    async def run(self, status: dict, data):
        key = status['id']
        folder = self.folder(key)

        async def progress(state, message, **extra):
            status.update(state=state, message=message)
            self.write(folder / 'status.json', status)

        try:
            if status['kind'] == 'overview':
                result = await create_overview(data, folder, progress)
            elif status['kind'] == 'continue':
                await progress('generating', '正在复审内容、选择图表与编排读图')
                data.overview = None
                data.report = await refine_report(data.report, data.content)
                data.report = await design_reading(data.report, data.content)
                data.mode = 'ai'
                result = data
            elif data.mode == 'local':
                result = ExportInput(report=local_report(data.content, data.title), content=data.content,
                                     mode='local', theme=data.theme)
            else:
                await progress('generating', '正在审题、组织内容并核对图表证据')
                report = await ai_report(data.content, data.title)
                # Long materials already receive these passes in ai_report.
                if len(data.content) < 12000:
                    await progress('composing', '正在编排图表叙事与报告封面')
                    report = await design_reading(report, data.content)
                    report = await design_editorial(report, data.content)
                result = ExportInput(report=report, content=data.content, mode='ai', theme=data.theme)
            self.save(status, result)
        except asyncio.CancelledError:
            await progress('failed', '服务中断，输入及已保存报告保留，请重试。')
            raise
        except Exception as exc:
            message = exc.detail if isinstance(exc, HTTPException) and isinstance(exc.detail, str) else '生成或校验未通过；输入及原报告保留，请重试。'
            await progress('failed', message)
        finally:
            self.tasks.pop(key, None)
            self.lock.release()

    async def shutdown(self):
        admissions = list(self.admissions)
        for task in admissions:
            task.cancel()
        await asyncio.gather(*admissions, return_exceptions=True)
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        # A task cancelled before its coroutine first runs cannot execute its
        # finally block. Finish those records and release their lock here.
        for key in list(self.tasks):
            path = self.folder(key) / 'status.json'
            status = json.loads(path.read_text())
            if status.get('billing_job_id'):
                await self.billing().cancel_refund(status['billing_job_id'], 'Report task stopped before execution')
            status.update(state='failed', message='服务中断，输入及已保存报告保留，请重试。')
            self.write(path, status)
            self.tasks.pop(key, None)
        if self.lock.locked():
            self.lock.release()


workspace = ReportWorkspace(Path(os.getenv('NBPPT_REPORTS_ROOT', str(BASE_DIR / 'workspace' / 'data' / 'reports'))))


def report_user(principal: dict, write: bool = False) -> str:
    if not principal:
        raise HTTPException(401, '请先登录 NB PPT')
    allowed = {'admin', 'generate'} if write else {'admin', 'generate', 'read'}
    if principal.get('scope', 'generate') not in allowed:
        raise HTTPException(403, '当前密钥为只读权限，不能创建或修改报告')
    return principal['user_id']


def owner(request: Request, write: bool = False) -> str:
    return report_user(getattr(request.state, 'principal', None), write)


def require_runtime():
    runtime = get_runtime_settings()
    if not runtime.get('overseas_worker_url') or len(runtime.get('overseas_worker_secret', '')) < 32:
        raise HTTPException(503, '报告执行节点尚未配置，可先使用原文排版。')


@router.get('/reports', response_class=HTMLResponse)
@router.get('/reports/', response_class=HTMLResponse, include_in_schema=False)
async def studio(request: Request):
    owner(request)
    html = (STATIC / 'index.html').read_text()
    html = html.replace('/static/', '/reports/static/')
    html = html.replace('<body>', '<body class="platform-report"><script>window.ReportStudioConfig={apiBase:"/api/reports",platform:true};</script>', 1)
    html = html.replace('灵动报告实验室', 'NB PPT · 研究报告').replace('灵动<span>报告实验室</span>', 'NB PPT<span>研究报告</span>')
    html = html.replace('本机运行 · 原型版', '友车科技 · 研究报告').replace('原理与使用 ↗', '返回 NB PPT ↗')
    html = html.replace('href="/reports/static/guide.html"', 'href="/"')
    html = html.replace('调用本机已登录的 Codex', '按材料组织观点与图表').replace('材料会发往 Codex 配置的模型服务，使用现有账户额度。', '使用服务端已配置的模型账户额度，报告与分享图分别生成。')
    html = html.replace('全景图任务会在本机保存输入、设计与生成结果，使用已登录模型的账户额度。', '任务输入、设计与结果保存在当前账户的报告中，使用服务端模型账户额度。')
    html = html.replace('</aside>', '<section class="report-history"><h2>我的报告</h2><p id="report-history" role="status">正在读取历史报告…</p></section></aside>', 1)
    html = html.replace('使用服务端已配置的模型账户额度，报告与分享图分别生成。', '报告60积分，分享图40积分；失败全额退回，本地原文排版免费。')
    html = html.replace('任务输入、设计与结果保存在当前账户的报告中，使用服务端模型账户额度。', '报告与分享图在执行节点独立生成；受理时冻结积分，通过文件校验后结算，失败退回。')
    html = html.replace('友车科技 · 研究报告</span>', '友车科技 · 研究报告</span><span id="report-wallet" role="status"></span>')
    return HTMLResponse(html)


@router.get('/reports/static/{asset:path}')
async def static_asset(asset: str, request: Request):
    owner(request)
    path = (STATIC / asset).resolve()
    if not path.is_relative_to(STATIC.resolve()) or not path.is_file():
        raise HTTPException(404)
    from fastapi.responses import FileResponse
    return FileResponse(path)


@router.get(API + '/health')
async def health(request: Request):
    owner(request)
    runtime = get_runtime_settings()
    wallet = await workspace.billing().get_wallet_overview(request.state.principal['api_key'])
    return {'status': 'ok', 'codex_installed': bool(runtime.get('overseas_worker_url')) and len(runtime.get('overseas_worker_secret', '')) >= 32, 'platform': True,
            'ai_unavailable_reason': '报告执行节点尚未配置，可先使用原文排版。',
            'prices': PRICES, 'credits_available': wallet['user']['credits_available'], 'remote_execution': True,
            'can_generate': request.state.principal.get('scope', 'generate') in {'admin', 'generate'},
            'limit': 60000, 'version': '0.32.0', 'busy': workspace.lock.locked()}


@router.get(API + '/sample')
async def sample(request: Request):
    owner(request)
    return json.loads((STATIC.parent / 'sample.json').read_text())


@router.post(API + '/draft', status_code=201)
async def draft(data: GenerateInput, request: Request):
    status = workspace.create(owner(request, write=True), data.title or '从主页带入的材料', 'draft')
    folder = workspace.folder(status['id'])
    raw = data.model_dump_json(indent=2).encode()
    (folder / 'input.json').write_bytes(raw)
    status.update(state='draft', message='主页材料已载入，请生成报告。',
                  input_sha256=hashlib.sha256(raw).hexdigest())
    workspace.write(folder / 'status.json', status)
    return {'id': status['id'], 'url': '/reports?draft=' + status['id']}


@router.post(API + '/generate', status_code=202)
async def generate(data: GenerateInput, request: Request):
    owner(request, write=True)
    return await submit_generation(data, request.state.principal, request.headers.get('X-Request-ID'))


async def submit_generation(data: GenerateInput, principal: dict, request_id=None):
    if not data.content.strip():
        raise HTTPException(422, '请先输入材料')
    if data.mode == 'ai':
        return await workspace.start_remote(principal, data.title, 'generate', data, request_id)
    return await workspace.start(report_user(principal, write=True), data.title, 'generate', data)


@router.post(API + '/continue', status_code=202)
async def continue_report(data: ExportInput, request: Request):
    user = owner(request, write=True)
    validate_evidence(data.report, data.content)
    require_runtime()
    return await workspace.start_remote(request.state.principal, data.report.title, 'continue', data, request.headers.get('X-Request-ID'))


@router.post(API + '/overview', status_code=202)
async def overview(data: ExportInput, request: Request):
    user = owner(request, write=True)
    validate_evidence(data.report, data.content)
    data.overview = None
    require_runtime()
    return await workspace.start_remote(request.state.principal, data.report.title, 'overview', data, request.headers.get('X-Request-ID'))


@router.get(API + '/jobs')
async def history(request: Request):
    return list_reports(owner(request))


def list_reports(user: str):
    items = []
    for path in workspace.root.glob('*/status.json'):
        try:
            status = workspace.owned(path.parent.name, user)
            items.append(workspace.public(status))
        except HTTPException:
            continue
    return {'items': sorted(items, key=lambda s: s['created_at'], reverse=True)[:20]}


@router.get(API + '/jobs/{key}')
@router.get(API + '/overview/{key}')
async def status(key: str, request: Request):
    return workspace.public(workspace.owned(key, owner(request)))


@router.get(API + '/jobs/{key}/result')
@router.get(API + '/overview/{key}/result')
async def result(key: str, request: Request):
    return workspace.result(key, owner(request)).model_dump()


@router.get(API + '/jobs/{key}/download')
async def download_report(key: str, request: Request):
    data = workspace.result(key, owner(request))
    return HTMLResponse(export_html(data), headers={'Content-Disposition': 'attachment; filename="research-report.html"'})


@router.get(API + '/jobs/{key}/input')
async def saved_input(key: str, request: Request):
    status = workspace.owned(key, owner(request))
    path = workspace.folder(key) / 'input.json'
    try:
        if path.is_symlink():
            raise ValueError('unsafe input')
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != status['input_sha256']:
            raise ValueError('input changed')
        model = GenerateInput if status['kind'] in {'generate', 'draft'} else ExportInput
        return model.model_validate_json(raw).model_dump()
    except (OSError, ValueError, KeyError):
        raise HTTPException(409, '原始输入不可用，请重新导入材料')


@router.post(API + '/preview')
async def preview(data: ExportInput, request: Request):
    # Imports become owned, immutable snapshots; never accept a client owner ID.
    export_html(data)
    user = owner(request, write=True)
    digest = hashlib.sha256(data.model_dump_json(indent=2).encode()).hexdigest()
    for path in workspace.root.glob('*/status.json'):
        try:
            existing = workspace.owned(path.parent.name, user)
            if existing.get('sha256') == digest and existing['state'] == 'completed':
                workspace.result(existing['id'], user)
                return {'url': existing['preview_url']}
        except HTTPException:
            continue
    status = workspace.create(user, data.report.title, 'import')
    workspace.save(status, data)
    return {'url': status['preview_url']}


@router.get(API + '/preview/{key}')
async def read_preview(key: str, request: Request):
    return HTMLResponse(platform_html(workspace.result(key, owner(request))))


@router.get(API + '/preview/{key}/overview.png')
async def download_overview(key: str, request: Request):
    data = workspace.result(key, owner(request))
    if not data.overview:
        raise HTTPException(404, '本报告尚无分享图')
    return Response(base64.b64decode(data.overview.data_url.split(',', 1)[1]), media_type='image/png',
                    headers={'Content-Disposition': 'attachment; filename="report-overview.png"'})


@router.post(API + '/export')
async def export(data: ExportInput, request: Request):
    owner(request)
    return HTMLResponse(export_html(data))


@router.post(API + '/review')
async def review(data: ExportInput, request: Request):
    owner(request)
    return review_report(data.report, data.content)


def register_report_tools(server, principal):
    """Register against the current MCP transport and current request principal."""
    from typing import Annotated, Literal
    from mcp.server.mcpserver import Context
    from pydantic import Field

    @server.tool()
    async def generate_research_report(ctx: Context,
        content: Annotated[str, Field(min_length=1, max_length=60000)],
        title: str = '', mode: Literal['ai', 'local'] = 'ai', request_id: str = '') -> dict:
        """按来源材料远程生成交互研究报告，报告60积分、分享图40积分，失败退款。重发请求须复用request_id。"""
        return await submit_generation(GenerateInput(content=content, title=title, mode=mode), principal(ctx), request_id or None)

    @server.tool()
    async def get_research_report(ctx: Context, job_id: str = '') -> dict:
        """不传编号时列出自己报告；传编号时查询状态及完成后的下载路径。"""
        user = report_user(principal(ctx))
        if not job_id:
            return list_reports(user)
        state = workspace.public(workspace.owned(job_id, user))
        if state['state'] == 'completed':
            data = workspace.result(job_id, user)
            state.update(summary=data.report.summary,
                         html_url=f'{API}/jobs/{job_id}/download',
                         result_url=f'{API}/jobs/{job_id}/result',
                         image_url=f'{API}/preview/{job_id}/overview.png' if data.overview else None)
        return state

    @server.tool()
    async def generate_report_share_image(ctx: Context, job_id: str, request_id: str = '') -> dict:
        """根据自己已保存报告生成分享图，创建新版本，不覆盖原报告。"""
        user = report_user(principal(ctx), write=True)
        require_runtime()
        data = workspace.result(job_id, user)
        data.overview = None
        return await workspace.start_remote(principal(ctx), data.report.title, 'overview', data, request_id or None)

    @server.tool()
    async def continue_research_report(ctx: Context, job_id: str, request_id: str = '') -> dict:
        """继续复审自己已保存报告的内容和图表叙事，创建新版本。"""
        user = report_user(principal(ctx), write=True)
        require_runtime()
        data = workspace.result(job_id, user)
        data.overview = None
        return await workspace.start_remote(principal(ctx), data.report.title, 'continue', data, request_id or None)
