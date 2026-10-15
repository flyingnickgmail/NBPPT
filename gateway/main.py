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
from contextlib import asynccontextmanager
from typing import Optional, Dict, Any

import httpx
from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

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

billing = BillingManager()
mcp_jobs = PresentationJobs(billing)
mcp_app = build_mcp(mcp_jobs)
STATIC_DIR = pathlib.Path(__file__).resolve().parent / "static"
JOBS_ROOT = BASE_DIR / "workspace" / "jobs"
JOBS_ROOT.mkdir(parents=True, exist_ok=True)


@app.middleware("http")
async def access_control(request: Request, call_next):
    path = request.url.path
    protected = path.startswith(("/api/", "/artifacts/")) or path == "/mcp" or path.startswith("/mcp/")
    try:
        if protected and not (path == "/api/session" and request.method == "POST"):
            request.state.principal = await authenticate_request(billing, request)
            if path.startswith("/api/settings/") or path in ("/api/health/details", "/api/wallet/topup"):
                if request.state.principal["tier"] != "admin":
                    raise HTTPException(403, "Administrator required")
        response = await call_next(request)
    except HTTPException as exc:
        response = JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    if protected:
        response.headers["Cache-Control"] = "no-store"
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
    return {"user_id": request.state.principal["user_id"], "admin": request.state.principal["tier"] == "admin"}


@app.delete("/api/session")
async def logout(request: Request):
    await delete_session(billing, request.cookies.get(COOKIE, ""))
    response = JSONResponse({"authenticated": False})
    response.delete_cookie(COOKIE)
    return response


class CreateJobRequest(BaseModel):
    prompt_cn: str
    task_type: str = "ppt"  # "ppt", "video", "composite"
    template_id: str = "auto"  # "auto", "gorden:mckinsey-style", "frontend-slides", "ppt-master", "yonyou-ci-bg", etc.
    slide_count: int = Field(default=0, ge=0, le=100)
    visual_style: str = "executive-dark"
    duration_seconds: int = 9
    aspect_ratio: str = "16:9"
    master_reasoning_engine: str = "auto"  # "auto", "codex_login", "claude_login", "deepseek_api"
    execution_mode: str = "auto"


class TopupRequest(BaseModel):
    amount: int = 500
    channel: str = "微信支付 Native"


class CreateKeyRequest(BaseModel):
    name: str = "Cursor / Claude Desktop 生产密钥"


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


@app.get("/api/templates")
async def get_templates():
    return {
        "skills": list_installed_ppt_skills(),
        "templates": list_available_templates(),
    }


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
        new_k = await billing.create_new_api_key(api_key, req.name)
        overview = await billing.get_wallet_overview(api_key)
        return {"new_key": new_k, "wallet": overview}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/jobs")
async def get_recent_jobs(request: Request, limit: int = 12):
    jobs = await billing.list_jobs(request.state.principal["user_id"], limit=limit)
    return {"jobs": jobs}


@app.post("/api/jobs/stream")
async def stream_create_job(req: CreateJobRequest, request: Request):
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
                api_key, job_id, task_type, req.prompt_cn, freeze_amount
            )
            bal_after = freeze_info["balance_after_freeze"]
            msg_try = f"[TCC 预授权] 已冻结 {freeze_amount} 算力点（可用余额 {bal_after} 点）"
            yield f"data: {json.dumps({'type': 'progress', 'pct': 8, 'job_id': job_id, 'message_cn': msg_try, 'freeze_info': freeze_info}, ensure_ascii=False)}\n\n"

            # Step 1: Match Template
            match_preview = match_template_for_prompt(req.prompt_cn, req.template_id)
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
            if task_type == "ppt" and req.execution_mode != "claude_cli":
                engine_desc = "Codex 技能直出"
                role_desc = "保留完整原文与客户风格，由生成代理统一规划和绘图"
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
            await billing.save_compiled_spec(job_id, en_spec)

            summary_cn = en_spec.get("task_summary_cn", "")
            real_badge = "真实大模型推理完成" if en_spec.get("is_real_llm") else "结构化推理完成"
            if en_spec.get("generation_contract") == "skill-direct-v1":
                real_badge = "原文已准备，等待 Codex 实际规划"
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
                        "runtime_keys": runtime_cfg,
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
                en_spec = validate_direct_completion(final_worker_evt)
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
        if target.stat().st_size != entry["size"] or hashlib.sha256(target.read_bytes()).hexdigest() != entry["sha256"]:
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

    return FileResponse(target, media_type=media_type, headers=headers)


# Mount after application routes; SDK handles initialization, notifications and transport.
app.mount("/", mcp_app)
