"""
Domestic Reception Gateway, Master Agent Router, Web Studio Backend & Standard MCP Server (:8000).
Supports:
- Real Personal Account CLI Login (`codex exec` / `claude -p` / `cc-switch GLM-5`)
- Intelligent Template Library & Auto-Matching (`/api/templates`)
- Overseas Account Anti-Ban Sandbox Configuration (`/api/settings/models`)
"""
import json
import pathlib
import uuid
import asyncio
import os
import hashlib
import fcntl
import re
from contextlib import asynccontextmanager
from typing import Optional, Dict, Any, Literal

import httpx
from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ConfigDict

from gateway.config import (
    BASE_DIR,
    DEFAULT_DEMO_API_KEY,
    TASK_FREEZE_CREDITS,
    get_runtime_settings,
    save_runtime_settings,
    mask_key,
)
from gateway.billing_tcc import BillingManager
from gateway.deepseek_compiler import compile_cn_request_to_english_spec, validate_direct_completion, VISUAL_PALETTES

from gateway.auth import COOKIE, authenticate_request, check_origin, create_session, delete_session, secure_cookie
from gateway.delivery import safe_job_id, contained_file
from gateway.template_registry import (
    GORDEN_ROOT,
    list_available_templates,
    list_installed_ppt_skills,
    match_template_for_prompt,
)
from gateway.mcp_server import PresentationJobs, build_mcp
from gateway.reports import router as report_router, workspace as report_workspace

@asynccontextmanager
async def lifespan(app):
    # Recovery assumes one gateway owns the SQLite database. Enforce that contract.
    with open(str(billing.db_path) + ".gateway.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        await billing.initialize()
        await billing.recover_interrupted()
        async with mcp_app.router.lifespan_context(mcp_app):
            try:
                yield
            finally:
                await mcp_jobs.close()
                await report_workspace.shutdown()


app = FastAPI(
    title="Personal Agent ProMedia — Master Agent Gateway & MCP Server",
    version="1.3.0",
    docs_url=None, redoc_url=None, openapi_url=None,
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(report_router)

billing = BillingManager()
mcp_jobs = PresentationJobs(billing)
mcp_app = build_mcp(mcp_jobs)
STATIC_DIR = pathlib.Path(__file__).resolve().parent / "static"
JOBS_ROOT = pathlib.Path(os.getenv('NBPPT_JOBS_ROOT') or BASE_DIR / "workspace" / "jobs")
JOBS_ROOT.mkdir(parents=True, exist_ok=True)


@app.middleware("http")
async def access_control(request: Request, call_next):
    path = request.url.path
    admin_page = path in ('/admin','/static/admin.html')
    report_page = path in ('/reports', '/reports/') or path.startswith('/reports/')
    report_api = path.startswith('/api/reports/')
    protected = report_page or admin_page or path.startswith(("/api/", "/artifacts/")) or path == "/mcp" or path.startswith("/mcp/")
    try:
        if protected and not (path == "/api/session" and request.method == "POST"):
            request.state.principal = await authenticate_request(billing, request)
            if admin_page or path.startswith(("/api/admin/", "/api/settings/", "/api/wallet/keys/")) or path in ("/api/health/details", "/api/wallet/topup", "/api/wallet/keys"):
                if request.state.principal["tier"] != "admin":
                    raise HTTPException(403, "Administrator required")
        if report_api and request.method == 'POST':
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > 10_000_000:
                    raise HTTPException(413, '报告输入过大，请精简材料或缩小图片。')
            request._body = bytes(body)
        response = await call_next(request)
    except HTTPException as exc:
        if path in ('/reports', '/reports/') and exc.status_code == 401:
            response=RedirectResponse('/?next=reports',status_code=303)
        elif admin_page and exc.status_code==401:
            response=RedirectResponse('/?next=admin',status_code=303)
        elif admin_page:
            response=HTMLResponse('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>需要管理员权限</title><h1>需要管理员权限</h1><p>当前密钥没有管理权限，请返回工作台，使用管理员密钥登录。</p><a href="/">返回工作台</a></html>',status_code=exc.status_code)
        else:
            response = JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    except ValueError:
        if not report_api:
            raise
        response=JSONResponse({'detail':'报告未通过材料、图表或版本校验，请核对后重试。'},status_code=422)
    if report_api or report_page:
        response.headers['Content-Security-Policy']="default-src 'self' blob:; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-src 'self' blob:; object-src 'none'; base-uri 'none'; frame-ancestors 'self'"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    if protected:
        response.headers["Cache-Control"] = "no-store"
    if admin_page:
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    return response


class LoginRequest(BaseModel):
    api_key: str


@app.post("/api/session")
async def login(req: LoginRequest, request: Request):
    check_origin(request, required=False)
    if not secure_cookie() and request.url.hostname not in ("localhost", "127.0.0.1", "::1", "testserver"):
        raise HTTPException(400, "Insecure cookies are allowed only on loopback")
    token = await create_session(billing, req.api_key)
    response = JSONResponse({"authenticated": True})
    response.set_cookie(COOKIE, token, httponly=True, secure=secure_cookie(), samesite="strict", max_age=8 * 3600)
    return response


@app.get("/api/session")
async def session_info(request: Request):
    scope = request.state.principal.get("scope", "generate")
    return {"user_id": request.state.principal["user_id"], "admin": request.state.principal["tier"] == "admin",
            "scope": scope, "can_generate": scope in {"admin", "generate"},
            "allow_claude": request.state.principal.get('allow_claude', False),
            "ppt_only": os.getenv("NBPPT_REQUIRE_ISOLATION", "false").lower() == "true"}


@app.delete("/api/session")
async def logout(request: Request):
    await delete_session(billing, request.cookies.get(COOKIE, ""))
    response = JSONResponse({"authenticated": False})
    response.delete_cookie(COOKIE)
    return response


class CreateJobRequest(BaseModel):
    prompt_cn: str = Field(min_length=1, max_length=100000)
    task_type: str = "ppt"  # "ppt", "video", "composite"
    template_id: str = "auto"  # "auto", "gorden:mckinsey-style", "frontend-slides", "ppt-master", "yonyou-ci-bg", etc.
    slide_count: int = Field(default=0, ge=0, le=60)
    visual_style: str = "executive-dark"
    duration_seconds: int = 9
    aspect_ratio: str = "16:9"
    master_reasoning_engine: str = "auto"  # "auto", "codex_login", "claude_login", "deepseek_api"
    execution_mode: str = "auto"


class AsyncCreateJobRequest(BaseModel):
    source: str = Field(min_length=1, max_length=100000)
    template_id: str = "auto"
    slide_count: int = Field(default=0, ge=0, le=60)
    request_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")
    task_type: Literal['ppt', 'video'] = 'ppt'
    execution_mode: Literal['auto', 'codex_cli', 'claude_cli', 'claude_codex'] = 'auto'
    video_duration_sec: int = Field(default=30, ge=6, le=600, strict=True)
    video_preset: Literal['legacy','short','exec_pitch'] = 'legacy'
    video_input_id: str = Field(default='',max_length=64)
    video_render_engine: Literal['auto','html_chromium','registered_video'] = 'auto'
    video_visual_mode: str = "motion"
    video_aspect_ratio: Literal['16:9', '9:16'] = '16:9'
    video_voice: Literal['melo', 'kokoro_female', 'kokoro_male', 'microsoft_yunxi', 'microsoft_xiaoxiao', 'microsoft_yunjian', 'approved_local'] = 'melo'
    video_voice_rate: Literal['-6%','+0%','+10%'] = '-6%'
    video_narration: bool = Field(default=True, strict=True)
    video_subtitles: bool = Field(default=True, strict=True)


class RetryJobRequest(BaseModel):
    request_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")


class TopupRequest(BaseModel):
    amount: int = 500
    channel: str = "微信支付 Native"


class CreateKeyRequest(BaseModel):
    name: str = Field(default="独立账户密钥", min_length=1, max_length=80)
    allow_claude: bool = Field(default=False, strict=True)
    daily_credit_limit: int = Field(default=240, ge=1, le=5000, strict=True)


class ModelSettingsUpdate(BaseModel):
    master_reasoning_engine: Optional[str] = None
    deepseek_api_key: Optional[str] = None
    deepseek_base_url: Optional[str] = None
    deepseek_model: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    anthropic_base_url: Optional[str] = None
    claude_model: Optional[str] = None
    openai_api_key: Optional[str] = None
    jimeng_api_key: Optional[str] = None
    overseas_worker_url: Optional[str] = None
    overseas_worker_secret: Optional[str] = None
    account_safe_mode: Optional[bool] = None
    account_safe_proxy: Optional[str] = None
    allow_sandbox_fallback: Optional[bool] = None


@app.get("/", response_class=HTMLResponse)
async def serve_web_studio():
    index_file = STATIC_DIR / "index.html"
    if not index_file.exists():
        return HTMLResponse("<h1>Web Studio UI missing</h1>", status_code=404)
    return HTMLResponse(index_file.read_text(encoding="utf-8"))


@app.get('/admin', response_class=HTMLResponse)
async def serve_admin():
    return HTMLResponse((STATIC_DIR/'admin.html').read_text(encoding='utf-8'))


@app.get("/api/templates")
async def get_templates():
    return {
        "skills": list_installed_ppt_skills(),
        "templates": list_available_templates(),
    }


def production_capabilities(principal=None):
    from gateway.ppt_contract import available_ppt_engines
    from gateway.voice_input import capability
    from gateway.exec_pitch_inputs import enabled as exec_enabled
    from gateway.product_visuals import configured as visuals_configured
    return {
        "voice_input": capability(),
        "ppt": {"supported": True, "freeze_credits": TASK_FREEZE_CREDITS["ppt"],
                "progress": True, "preview_after_validation": True, "retry": True,
                "execution_modes": available_ppt_engines(allow_claude=(principal or {}).get('allow_claude', False))},
        "video": {"supported": True, "freeze_credits": TASK_FREEZE_CREDITS["video"],
                  "progress": True, "preview_after_validation": True, "retry": True,
                  "planner_providers": {"codex_cli": True, "claude_cli": "claude_cli" in available_ppt_engines(allow_claude=(principal or {}).get("allow_claude",False))},
                  "narration": "melo_tts", "voices": ["melo"] + (["microsoft_yunxi", "microsoft_xiaoxiao", "microsoft_yunjian"] if os.getenv("NBPPT_MICROSOFT_EDGE_ENABLED","false").lower()=="true" else []) + (["kokoro_female", "kokoro_male"] if os.getenv("NBPPT_KOKORO_ENABLED", "false").lower() == "true" else []),
                  "microsoft_synthesis_rates":['-6%','+0%','+10%'],
                  "manuscript": True, "voice_input": True,
                  "presets": {"legacy":{"max_seconds":180,"long_form_provider":"claude_cli"},
                              "short":{"max_seconds":60},
                              "exec_pitch":{"enabled":exec_enabled(),"max_seconds":600,"min_shots_at_480s":40,
                                            "max_shots":240,"max_sections":30,"input":"registered_local","voice":"approved_local",
                                            "default_render_engine":"html_chromium","render_engines":["html_chromium","registered_video"],
                                            "product_visuals":{"supported":True,"configured":visuals_configured(),
                                                "input":"registered_manifest","missing_behavior":"block",
                                                "kinds":["crm_screenshot","brand_still","brand_broll","brand_logo"]}}},
                  "burned_subtitles": True, "duration_range": [6, 180], "long_form_provider": "claude_cli", "visual_modes": ["motion"] + (["live_action"] if os.getenv("NBPPT_SCENE_SOURCE")=="search" or pathlib.Path(os.getenv("NBPPT_SCENE_CATALOG","/nonexistent")).is_file() else []), "aspect_ratios": ["16:9", "9:16"]},
        "composite": {"supported": True, "freeze_credits": TASK_FREEZE_CREDITS["ppt"] + TASK_FREEZE_CREDITS["video"],
                      "progress": True, "preview_after_validation": True, "retry": True,
                      "submission": "independent_jobs"},
    }


@app.get("/api/capabilities")
async def get_capabilities(request: Request):
    modes = production_capabilities(request.state.principal)
    result = {"delivery_modes": modes, "partial_preview": False, "independent_deliveries": True}
    if 'claude_cli' in modes['ppt']['execution_modes']:
        result['providers'] = {'claude_cli': await mcp_jobs.claude_status(request.state.principal)}
    return result


@app.get('/api/providers/claude/status')
async def claude_provider_status(request: Request):
    try:
        return await mcp_jobs.claude_status(request.state.principal)
    except (ValueError, PermissionError) as exc:
        job_error(exc)


@app.get("/api/gorden-preview/{slug}")
async def serve_gorden_preview(slug: str):
    safe_slug = "".join(c for c in slug if c.isalnum() or c in ("-", "_"))
    preview_file = (GORDEN_ROOT / "templates" / safe_slug / "preview.png").resolve()
    if not preview_file.exists():
        raise HTTPException(status_code=404, detail="GordenPPTSkill preview not found")
    return FileResponse(preview_file, media_type="image/png")


@app.get("/health")
async def public_health():
    return {"status": "alive"}


@app.get("/api/health/details")
async def gateway_health():
    settings = get_runtime_settings()
    worker_url = settings["overseas_worker_url"]
    worker_ok = False
    worker_info = {}
    try:
        async with httpx.AsyncClient(timeout=3.0, trust_env=False) as client:
            r = await client.get(f"{worker_url}/health")
            if r.status_code == 200:
                worker_ok = True
                worker_info = r.json()
    except Exception:
        pass
    local_cli = settings.get("local_cli_status", {})
    return {
        "status": "healthy",
        "gateway": "domestic-mcp-gateway",
        "overseas_worker_connected": worker_ok,
        "overseas_worker_url": worker_url,
        "overseas_worker": worker_info,
        "local_cli_status": local_cli,
        "models_configured": {
            "master_reasoning_engine": settings.get("master_reasoning_engine", "auto"),
            "codex_logged_in": bool(local_cli.get("codex_logged_in")),
            "codex_model": local_cli.get("codex_model", "gpt-6-astra"),
            "deepseek_configured": bool(settings.get("deepseek_api_key")),
            "anthropic_configured": bool(settings.get("anthropic_api_key")),
            "claude_model": settings.get("claude_model", "glm-5"),
            "openai_configured": bool(settings.get("openai_api_key")),
            "jimeng_configured": bool(settings.get("jimeng_api_key")),
            "account_safe_mode": settings.get("account_safe_mode", True),
            "account_safe_proxy": bool(settings.get("account_safe_proxy")),
            "allow_sandbox_fallback": settings.get("allow_sandbox_fallback", True),
        },
        "installed_ppt_skills": list_installed_ppt_skills(),
        "templates": list_available_templates(),
        "palettes": list(VISUAL_PALETTES.keys()),
    }


@app.get("/api/settings/models")
async def get_model_settings():
    s = get_runtime_settings()
    return {
        "master_reasoning_engine": s.get("master_reasoning_engine", "auto"),
        "local_cli_status": s.get("local_cli_status", {}),
        "deepseek_api_key_masked": mask_key(s["deepseek_api_key"]),
        "deepseek_configured": bool(s["deepseek_api_key"]),
        "deepseek_base_url": s["deepseek_base_url"],
        "deepseek_model": s["deepseek_model"],
        "anthropic_api_key_masked": mask_key(s["anthropic_api_key"]),
        "anthropic_configured": bool(s["anthropic_api_key"]),
        "anthropic_base_url": s["anthropic_base_url"],
        "claude_model": s["claude_model"],
        "openai_api_key_masked": mask_key(s["openai_api_key"]),
        "openai_configured": bool(s["openai_api_key"]),
        "jimeng_api_key_masked": mask_key(s["jimeng_api_key"]),
        "jimeng_configured": bool(s["jimeng_api_key"]),
        "overseas_worker_url": s["overseas_worker_url"],
        "account_safe_mode": s.get("account_safe_mode", True),
        "account_safe_proxy": "***" if s.get("account_safe_proxy") else "",
        "allow_sandbox_fallback": s["allow_sandbox_fallback"],
    }


@app.post("/api/settings/models")
async def update_model_settings(req: ModelSettingsUpdate):
    save_runtime_settings(req.model_dump(exclude_none=True))
    return await get_model_settings()


@app.get("/api/wallet")
async def get_wallet(request: Request):
    try:
        return await billing.get_wallet_overview(request.state.principal["api_key"])
    except PermissionError as e:
        raise HTTPException(status_code=401, detail=str(e))


@app.post("/api/wallet/topup")
async def topup_wallet(req: TopupRequest, request: Request):
    api_key = request.state.principal["api_key"]
    try:
        res = await billing.topup_credits(api_key, req.amount, req.channel)
        overview = await billing.get_wallet_overview(api_key)
        return {"topup": res, "wallet": overview}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/wallet/keys")
async def create_key(req: CreateKeyRequest, request: Request):
    api_key = request.state.principal["api_key"]
    try:
        new_k = await billing.create_new_api_key(api_key, req.name, allow_claude=req.allow_claude, daily_credit_limit=req.daily_credit_limit)
        overview = await billing.get_wallet_overview(api_key)
        return {"new_key": new_k, "wallet": overview}
    except (ValueError, PermissionError) as exc:
        job_error(exc)


@app.get('/api/wallet/keys')
async def managed_keys(request: Request):
    return {'keys': await billing.list_managed_keys(request.state.principal['api_key'])}


class KeyPermissionRequest(BaseModel):
    allow_claude: bool = Field(strict=True)


@app.patch('/api/wallet/keys/{key_id}')
async def update_key_permissions(key_id: str, req: KeyPermissionRequest, request: Request):
    if not re.fullmatch(r'[a-f0-9]{64}', key_id):
        raise HTTPException(422, 'Invalid key_id')
    try:
        return await billing.set_key_claude_permission(request.state.principal['api_key'], key_id, req.allow_claude)
    except LookupError as exc:
        raise HTTPException(404, str(exc))
    except (ValueError, PermissionError) as exc:
        job_error(exc)


class RevokeKeyRequest(BaseModel):
    key_id: str = Field(pattern=r'^[a-f0-9]{64}$')


@app.post('/api/wallet/keys/revoke')
async def revoke_key(req: RevokeKeyRequest, request: Request):
    try:
        return await billing.revoke_api_key(request.state.principal, req.key_id)
    except LookupError as exc:
        raise HTTPException(404,str(exc))
    except (ValueError,PermissionError) as exc:
        job_error(exc)


class AdminCreateKeyRequest(CreateKeyRequest):
    model_config = ConfigDict(extra='forbid')
    request_id: str = Field(pattern=r'^[A-Za-z0-9_-]{8,80}$')
    initial_credits: int = Field(default=0,ge=0,le=1000000,strict=True)
    scope: Literal['generate','read'] = 'generate'


class AdminUpdateKeyRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: str = Field(pattern=r'^[A-Za-z0-9_-]{8,80}$')
    name: Optional[str] = Field(default=None,min_length=1,max_length=80)
    daily_credit_limit: Optional[int] = Field(default=None,ge=1,le=5000,strict=True)
    scope: Optional[Literal['generate','read']] = None
    allow_claude: Optional[bool] = Field(default=None,strict=True)


class AdminCreditRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: str = Field(pattern=r'^[A-Za-z0-9_-]{8,80}$')
    delta: int = Field(ge=-1000000,le=1000000,strict=True)
    note: str = Field(min_length=1,max_length=200)


class AdminRevokeRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: str = Field(pattern=r'^[A-Za-z0-9_-]{8,80}$')


@app.get('/api/admin/keys')
async def admin_keys(request: Request):
    return {'keys':await billing.list_managed_keys(request.state.principal['api_key'])}


@app.get('/api/admin/actions')
async def admin_actions(request: Request):
    return {'actions':await billing.list_admin_actions(request.state.principal['api_key'])}


@app.post('/api/admin/keys')
async def admin_create_key(req: AdminCreateKeyRequest,request: Request):
    try:
        return {'new_key':await billing.create_new_api_key(request.state.principal['api_key'],req.name,
            **req.model_dump(exclude={'name'}))}
    except (ValueError,PermissionError) as exc:
        job_error(exc)


@app.patch('/api/admin/keys/{key_id}')
async def admin_update_key(key_id: str,req: AdminUpdateKeyRequest,request: Request):
    try:
        return await billing.update_managed_key(request.state.principal['api_key'],key_id,
            req.model_dump(exclude={'request_id'},exclude_none=True),req.request_id)
    except LookupError as exc:
        raise HTTPException(404,str(exc))
    except (ValueError,PermissionError) as exc:
        job_error(exc)


@app.post('/api/admin/keys/{key_id}/credits')
async def admin_adjust_credits(key_id: str,req: AdminCreditRequest,request: Request):
    try:
        return await billing.adjust_managed_credits(request.state.principal['api_key'],key_id,req.delta,req.note,req.request_id)
    except LookupError as exc:
        raise HTTPException(404,str(exc))
    except (ValueError,PermissionError) as exc:
        job_error(exc)


@app.post('/api/admin/keys/{key_id}/revoke')
async def admin_revoke_key(key_id: str,req: AdminRevokeRequest,request: Request):
    try:
        return await billing.revoke_api_key(request.state.principal,key_id,req.request_id)
    except LookupError as exc:
        raise HTTPException(404,str(exc))
    except (ValueError,PermissionError) as exc:
        job_error(exc)


@app.get("/api/jobs")
async def get_recent_jobs(request: Request, limit: int = 12):
    if request.state.principal.get("scope", "generate") not in {"admin", "generate", "read"}:
        raise HTTPException(403, "Credential scope does not allow reading jobs")
    jobs = await billing.list_jobs(request.state.principal["user_id"], limit=limit)
    return {"jobs": jobs}


def job_error(exc: Exception, *, conflict: bool = False):
    from gateway.ppt_contract import ProviderUnavailable
    if isinstance(exc, ProviderUnavailable):
        raise HTTPException(exc.status_code, {'message': str(exc), 'provider_state': exc.state,
            'retry_after_seconds': exc.retry_after}, headers={'Retry-After': str(exc.retry_after)} if exc.retry_after else None)
    if isinstance(exc, PermissionError):
        raise HTTPException(403, str(exc))
    raise HTTPException(409 if conflict else 422, str(exc))


@app.post('/api/voice/transcribe')
async def transcribe_voice(request: Request):
    from gateway.voice_input import transcribe
    try:
        return await transcribe(request,request.state.principal)
    except PermissionError as exc:
        raise HTTPException(403,str(exc))
    except (ValueError,TimeoutError) as exc:
        raise HTTPException(422,str(exc) or '语音转写超时')


@app.post("/api/jobs")
async def create_job(req: AsyncCreateJobRequest, request: Request):
    try:
        return await mcp_jobs.create(request.state.principal, req.source, req.template_id,
                                     req.slide_count, req.request_id, req.task_type,
                                     req.video_duration_sec, req.video_aspect_ratio,
                                     req.video_voice, req.video_narration, req.video_subtitles,
                                     execution_mode=req.execution_mode, video_visual_mode=req.video_visual_mode, video_voice_rate=req.video_voice_rate,
                                     video_preset=req.video_preset,video_input_id=req.video_input_id,video_render_engine=req.video_render_engine)
    except (ValueError, PermissionError) as exc:
        job_error(exc, conflict="request_id已用于" in str(exc))


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str, request: Request):
    try:
        return await mcp_jobs.status(request.state.principal, job_id)
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except ValueError as exc:
        raise HTTPException(404, str(exc))


@app.get("/api/jobs/{job_id}/artifacts")
async def get_job_artifacts(job_id: str, request: Request):
    try:
        return await mcp_jobs.artifacts(request.state.principal, job_id)
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except ValueError as exc:
        code = 409 if "尚未成功完成" in str(exc) else 404
        raise HTTPException(code, str(exc))


@app.post("/api/jobs/{job_id}/retry")
async def retry_job(job_id: str, req: RetryJobRequest, request: Request):
    try:
        return await mcp_jobs.retry(request.state.principal, job_id, req.request_id)
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except ValueError as exc:
        message = str(exc)
        if "不存在或无权访问" in message:
            raise HTTPException(404, message)
        if "只有失败" in message or "新的request_id" in message or "缺少可重试" in message:
            raise HTTPException(409, message)
        raise HTTPException(422, message)


@app.post("/api/jobs/stream")
async def stream_create_job(req: CreateJobRequest, request: Request):
    if request.state.principal.get("scope", "generate") not in {"admin", "generate"}:
        raise HTTPException(403, "Credential scope does not allow generation")
    if os.getenv('NBPPT_REQUIRE_ISOLATION', 'false').lower() == 'true' and req.task_type != 'ppt':
        raise HTTPException(422, '当前部署仅开放隔离运行的 Codex PPT 生成')
    if req.task_type == 'ppt':
        from gateway.ppt_contract import resolve_ppt_engine
        try:
            resolve_ppt_engine(req.execution_mode)
            if req.execution_mode in ('claude_cli', 'claude_codex'):
                await mcp_jobs.require_claude_access(request.state.principal)
                await mcp_jobs.require_claude_ready(request.state.principal)
        except (ValueError, PermissionError) as exc:
            job_error(exc)
    api_key = request.state.principal["api_key"]
    task_type = req.task_type if req.task_type in TASK_FREEZE_CREDITS else "ppt"
    freeze_amount = TASK_FREEZE_CREDITS[task_type]
    job_id = f"{task_type}_{uuid.uuid4().hex[:10]}"
    runtime_cfg = get_runtime_settings()
    worker_url = runtime_cfg["overseas_worker_url"]
    worker_secret = runtime_cfg["overseas_worker_secret"]

    async def event_pipeline():
        try:
            freeze_info = await billing.try_freeze_credits(
                api_key, job_id, task_type, req.prompt_cn, freeze_amount,
                require_claude=req.execution_mode in ('claude_cli', 'claude_codex')
            )
            bal_after = freeze_info["balance_after_freeze"]
            msg_try = f"[TCC 预授权] 已冻结 {freeze_amount} 算力点（可用余额 {bal_after} 点）"
            yield f"data: {json.dumps({'type': 'progress', 'pct': 8, 'job_id': job_id, 'message_cn': msg_try, 'freeze_info': freeze_info}, ensure_ascii=False)}\n\n"

            # Step 1: Match Template
            match_preview = match_template_for_prompt(req.prompt_cn, req.template_id)
            if req.execution_mode in ('claude_cli', 'claude_codex') and req.template_id == 'auto':
                match_preview = {'template': {'id': 'auto', 'name': 'Claude 自主设计'},
                                 'match_reason_cn': 'Claude 按内容自主设计，不强制匹配母版'}
            matched_tpl = match_preview["template"]
            match_reason = match_preview["match_reason_cn"]
            yield f"data: {json.dumps({'type': 'progress', 'pct': 14, 'job_id': job_id, 'message_cn': f'[母版库智能路由] {match_reason}'}, ensure_ascii=False)}\n\n"

            # Step 2: Master Agent Logical Structuring
            local_cli = runtime_cfg.get("local_cli_status", {})
            engine_choice = req.master_reasoning_engine or runtime_cfg.get("master_reasoning_engine", "auto")
            if engine_choice in ("codex_login", "auto") and local_cli.get("codex_logged_in"):
                engine_desc = f"本机已登录个人 Codex 账号 ({local_cli.get('codex_model', 'gpt-6-astra')})"
            elif runtime_cfg.get("anthropic_api_key"):
                engine_desc = f"Claude/Anthropic 推理引擎 ({runtime_cfg.get('claude_model', 'glm-5')})"
            elif runtime_cfg.get("deepseek_api_key"):
                engine_desc = f"DeepSeek 推理引擎 ({runtime_cfg.get('deepseek_model')})"
            else:
                engine_desc = "本地金字塔结构化大纲引擎"

            role_desc = (
                "正在梳理【金字塔总大纲 + 每页结论与论据】，无需视频算力"
                if task_type == "ppt"
                else "正在梳理【逻辑大纲 + Claude 图形化动效分镜脚本】"
            )
            if task_type == "ppt":
                engine_desc = "Claude 策划 → Codex 绘图" if req.execution_mode == "claude_codex" else "Claude 自由创作" if req.execution_mode == "claude_cli" else "Codex 技能直出"
                role_desc = "Claude 先写出完整论证与讲稿，再交给 Codex 绘图" if req.execution_mode == "claude_codex" else "保留完整原文与客户风格，由生成代理统一规划和绘图"
            yield f"data: {json.dumps({'type': 'progress', 'pct': 20, 'job_id': job_id, 'message_cn': f'[主控 Agent 强逻辑推理] 调用 {engine_desc}，{role_desc}...'}, ensure_ascii=False)}\n\n"

            en_spec = await compile_cn_request_to_english_spec(
                req.prompt_cn,
                task_type,
                {
                    "template_id": req.template_id,
                    "slide_count": req.slide_count,
                    "visual_style": matched_tpl["id"],
                    "duration_seconds": req.duration_seconds,
                    "aspect_ratio": req.aspect_ratio,
                    "master_reasoning_engine": engine_choice,
                    "execution_mode": req.execution_mode,
                },
            )
            en_spec["requested_slide_count"] = req.slide_count
            if req.execution_mode in ('claude_cli', 'claude_codex'):
                from gateway.ppt_contract import claude_runtime_owner
                en_spec['account_owner_user_id'] = claude_runtime_owner()
            await billing.save_compiled_spec(job_id, en_spec)

            summary_cn = en_spec.get("task_summary_cn", "")
            real_badge = "原文已保留，等待生成代理创作" if en_spec.get('generation_contract') == 'skill-direct-v1' else ("真实大模型推理完成" if en_spec.get("is_real_llm") else "结构化推理完成")
            if en_spec.get("generation_contract") == "skill-direct-v1":
                real_badge = "原文已准备，等待实际内容规划与创作"
            msg_spec = f"[{real_badge}] {summary_cn} · 引擎：{en_spec.get('compiler_engine')}"
            yield f"data: {json.dumps({'type': 'spec_compiled', 'pct': 26, 'job_id': job_id, 'message_cn': msg_spec, 'en_spec': en_spec}, ensure_ascii=False)}\n\n"

            final_worker_evt: Optional[Dict[str, Any]] = None
            async with httpx.AsyncClient(timeout=600.0, trust_env=False) as client:
                async with client.stream(
                    "POST",
                    f"{worker_url}/internal/execute-stream",
                    headers={"X-Worker-Secret": worker_secret},
                    json={
                        "job_id": job_id,
                        "task_type": task_type,
                        "max_budget_usd": 0.85,
                        "execution_mode": req.execution_mode,
                        "english_spec": en_spec,
                        "runtime_keys": {'account_safe_proxy': runtime_cfg.get('account_safe_proxy', '')} if en_spec.get('generation_contract') == 'skill-direct-v1' else runtime_cfg,
                    },
                ) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        evt = json.loads(line[6:])
                        if evt.get("type") == "progress":
                            prog_payload = {
                                "type": "progress",
                                "pct": evt["pct"],
                                "job_id": job_id,
                                "message_cn": evt["message_cn"],
                            }
                            if evt.get("cdn_urls"):
                                prog_payload["cdn_urls"] = evt["cdn_urls"]
                            yield f"data: {json.dumps(prog_payload, ensure_ascii=False)}\n\n"
                        elif evt.get("type") == "completed":
                            final_worker_evt = evt
                        elif evt.get("type") == "error":
                            raise RuntimeError(evt.get("message", "算力底座执行异常"))

            if not final_worker_evt:
                raise RuntimeError("未收到算力底座完成信号")

            if en_spec.get("generation_contract") == "skill-direct-v1":
                en_spec = validate_direct_completion(final_worker_evt, en_spec)
                await billing.save_compiled_spec(job_id, en_spec)

            settle_info = await billing.confirm_settle(
                job_id,
                float(final_worker_evt.get("total_cost_usd", 0.10)),
                final_worker_evt.get("cdn_urls", {}),
            )

            done_payload = {
                "type": "completed",
                "pct": 100,
                "job_id": job_id,
                "message_cn": (
                    f"[交付完成] 实扣 {settle_info['charged_credits']} 算力点"
                    f"（退回差额 +{settle_info['refunded_diff_credits']} 点 · 折算成本 ${settle_info['overseas_cost_usd']:.4f}）"
                ),
                "cdn_urls": final_worker_evt.get("cdn_urls", {}),
                "billing": settle_info,
                "en_spec": en_spec,
                "qa_report": final_worker_evt.get("qa_report"),
                "used_real_claude_cli": final_worker_evt.get("used_real_claude_cli", False),
            }
            yield f"data: {json.dumps(done_payload, ensure_ascii=False)}\n\n"

        except asyncio.CancelledError:
            await asyncio.shield(billing.cancel_refund(job_id, "Client disconnected"))
            raise
        except Exception as exc:
            refund_info = await billing.cancel_refund(job_id, str(exc))
            err_payload = {
                "type": "error",
                "job_id": job_id,
                "message_cn": f"[TCC Cancel] 任务中断，已全额退回算力点。原因：{exc}",
                "refund_info": refund_info,
            }
            yield f"data: {json.dumps(err_payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_pipeline(), media_type="text/event-stream")


@app.get("/artifacts/{job_id}/{file_path:path}")
async def serve_job_artifact(job_id: str, file_path: str, request: Request):
    job = await billing.get_job(job_id, request.state.principal["user_id"])
    if not job or job["status"] != "COMPLETED":
        raise HTTPException(404, "Artifact not found")
    try:
        safe_job_id(job_id)
        root = JOBS_ROOT / job_id / "output"
        manifest = json.loads(contained_file(root, "delivery.json").read_text())
        entry = next((f for f in manifest["files"] if f["path"] == file_path), None)
        if entry is None:
            raise ValueError("Not published")
        target = contained_file(root, file_path)
        digest = await asyncio.to_thread(lambda: hashlib.sha256(target.read_bytes()).hexdigest())
        if target.stat().st_size != entry["size"] or digest != entry["sha256"]:
            raise ValueError("Artifact changed after verification")
    except (ValueError, OSError, KeyError):
        raise HTTPException(404, "Artifact not found")

    suffix = target.suffix.lower()
    media_type = "application/octet-stream"
    headers = {}
    if suffix == ".pptx":
        media_type = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        headers["Content-Disposition"] = f'attachment; filename="{target.name}"'
    elif suffix == ".html":
        media_type = "text/html; charset=utf-8"
        headers["Content-Security-Policy"] = "sandbox allow-scripts; default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'none'; form-action 'none'; base-uri 'none'"
    elif suffix == ".mp4":
        media_type = "video/mp4"
    elif suffix == ".png":
        media_type = "image/png"
    elif suffix == ".vtt":
        media_type = "text/vtt; charset=utf-8"
    elif suffix in (".md", ".json"):
        media_type = "text/plain; charset=utf-8" if suffix == ".md" else "application/json"
        headers["Content-Disposition"] = f'attachment; filename="{target.name}"'

    return FileResponse(target, media_type=media_type, headers=headers)


# Mount after application routes; SDK handles initialization, notifications and transport.
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/", mcp_app)
