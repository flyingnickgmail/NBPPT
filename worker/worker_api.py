"""
Stage 2 & Stage 3 — Direct Agent Executor (`Codex` / `Claude`) & Master Agent QA Inspector (:8001).

Workflow:
1. Receives the detailed PPT plan (`slide_script.md`) & crafted prompt (`codex_direct_prompt` / `claude_direct_prompt`) from Stage 1.
2. Stage 2 (Generator Agent):
   - `codex_cli` (Default): Sends the prompt directly to `codex exec` (`gpt-6-astra`), which invokes its
     built-in `image_gen` tool to generate pure-image 16:9 consulting slides and assembles the `.pptx`
     via `~/.codex/skills/client-ci-ppt-image-deck/scripts/images_to_pptx.py`.
   - `claude_cli`: Uses the owner-bound restricted native PPT flow; the legacy Claude entry is rejected.
3. Stage 3 (Master Agent QA Inspection):
   - Verifies all generated slide images (`1672x941` PNGs) and `.pptx` packaging,
   - Builds the full-screen image presentation `.html`,
   - Produces a structured `qa_report` before signing off.
"""
import asyncio
import json
import os
import pathlib
import random
import shutil
import subprocess
import sys
import tempfile
import time
import secrets
import signal
from html import escape
import base64
from typing import Optional, Dict, Any, List

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from PIL import Image
from dotenv import load_dotenv
from pptx import Presentation

from worker.oss_uploader import upload_job_artifacts_to_cdn
from gateway.delivery import inspect_delivery, delivery_urls, safe_job_id
from pptx.util import Inches

BASE_DIR = pathlib.Path(__file__).resolve().parent.parent
if os.getenv("NBPPT_REQUIRE_ISOLATION", "false").lower() != "true":
    load_dotenv(BASE_DIR / ".env")
SKILLS_ROOT = BASE_DIR / "worker" / "agent_skills" / ".claude" / "skills"
WORKSPACE_JOBS_DIR = pathlib.Path(os.getenv('NBPPT_JOBS_ROOT') or BASE_DIR / "workspace" / "jobs")
WORKSPACE_JOBS_DIR.mkdir(parents=True, exist_ok=True)

WORKER_SECRET = os.getenv("OVERSEAS_WORKER_SECRET", "")
CLAUDE_BIN = (
    os.getenv("CLAUDE_BIN")
    or shutil.which("claude")
    or next(
        (
            p
            for p in [
                str(pathlib.Path.home() / ".local" / "bin" / "claude"),
                "/usr/local/bin/claude",
                "/usr/bin/claude",
            ]
            if pathlib.Path(p).exists()
        ),
        "/usr/local/bin/claude",
    )
)
CODEX_BIN = (
    os.getenv("CODEX_BIN")
    or shutil.which("codex")
    or next(
        (
            p
            for p in [
                "/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex",
                "/usr/local/bin/codex",
                "/usr/bin/codex",
            ]
            if pathlib.Path(p).exists()
        ),
        "/usr/local/bin/codex",
    )
)
CODEX_GENERATED_IMAGES_DIR = pathlib.Path.home() / ".codex" / "generated_images"
IMAGES_TO_PPTX_SCRIPT = pathlib.Path.home() / ".codex" / "skills" / "client-ci-ppt-image-deck" / "scripts" / "images_to_pptx.py"
MD_TO_CI_PPTX_SCRIPT = pathlib.Path.home() / ".codex" / "skills" / "client-ci-ppt-image-deck" / "scripts" / "markdown_script_to_ci_pptx.mjs"

# Local capacity bound. Claude also uses its process-shared account lease.
ACCOUNT_SAFE_SEMAPHORE = asyncio.Semaphore(1)

app = FastAPI(title="Personal Agent Direct Codex/Claude Executor & QA Worker", version="2.0.0", docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[],
    allow_methods=["*"],
    allow_headers=["*"],
)

from gateway.report_contract import WorkerReportRequest, parse_input


@app.post('/internal/reports/execute-stream')
async def execute_report(req: WorkerReportRequest, x_worker_secret: Optional[str] = Header(None)):
    if len(WORKER_SECRET) < 32 or WORKER_SECRET == 'super-secret-mtls-token-2026' or not secrets.compare_digest(x_worker_secret or '', WORKER_SECRET):
        raise HTTPException(403, 'Unauthorized worker secret')
    try:
        parse_input(req.spec)
        expected = 'reportshare_' if req.spec['operation'] == 'overview' else 'report_'
        if not req.job_id.startswith(expected):
            raise ValueError('Report task mismatch')
    except ValueError:
        raise HTTPException(422, 'Invalid report request')
    from worker.report_generation import report_stream
    return StreamingResponse(report_stream(req, WORKSPACE_JOBS_DIR, CODEX_BIN, ACCOUNT_SAFE_SEMAPHORE), media_type='text/event-stream')


class JobExecutionRequest(BaseModel):
    job_id: str
    task_type: str = "ppt"
    max_budget_usd: float = 0.85
    execution_mode: str = "codex_cli"  # "codex_cli", "claude_cli", "auto"
    english_spec: dict
    runtime_keys: Optional[Dict[str, Any]] = None


async def run_python_skill_script(script_path: pathlib.Path, args: list, cwd: pathlib.Path, env: dict) -> dict:
    cmd = [sys.executable, str(script_path)] + args
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(cwd),
        env=env,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
    finally:
        await stop_process(proc)
    if proc.returncode != 0:
        err_text = stderr.decode("utf-8", errors="ignore")
        raise RuntimeError(f"Script {script_path.name} failed: {err_text[:400]}")
    out_text = stdout.decode("utf-8", errors="ignore").strip().splitlines()
    for line in reversed(out_text):
        if line.strip().startswith("{"):
            try:
                return json.loads(line.strip())
            except Exception:
                pass
    return {"status": "ok"}


async def stop_process(proc):
    if proc is not None and proc.returncode is None:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await proc.wait()


def _collect_new_codex_images(since_ts: float, assets_dir: pathlib.Path, target_count: int) -> List[pathlib.Path]:
    """Only accept explicitly numbered files in this job's private assets directory."""
    def _num_key(p: pathlib.Path) -> int:
        digits = "".join(ch for ch in p.stem if ch.isdigit())
        return int(digits) if digits else 999

    existing = sorted(
        list(assets_dir.glob("slide_preview_[1-9]*.png")),
        key=_num_key,
    )
    return existing


def _render_pptx_slides_via_qlmanage(pptx_path: pathlib.Path, assets_dir: pathlib.Path, max_slides: int = 8) -> List[pathlib.Path]:
    """Render each slide of a `.pptx` into `slide_preview_1.png ...` using macOS `/usr/bin/qlmanage`."""
    ql_bin = pathlib.Path("/usr/bin/qlmanage")
    if not ql_bin.exists() or not pptx_path.exists():
        return []
    try:
        prs_full = Presentation(str(pptx_path))
        n_slides = min(len(prs_full.slides), max_slides)
        if n_slides == 0:
            return []
        assets_dir.mkdir(parents=True, exist_ok=True)
        out_list: List[pathlib.Path] = []
        with tempfile.TemporaryDirectory(prefix="promedia_ql_") as tmp_dir_str:
            tmp_dir = pathlib.Path(tmp_dir_str)
            single_files: List[str] = []
            for idx in range(1, n_slides + 1):
                p_single = Presentation(str(pptx_path))
                sldIdLst = p_single.slides._sldIdLst
                sld_ids = list(sldIdLst)
                target_el = sld_ids[idx - 1]
                for sld in list(sldIdLst):
                    sldIdLst.remove(sld)
                sldIdLst.append(target_el)
                sp = tmp_dir / f"s_{idx}.pptx"
                p_single.save(str(sp))
                single_files.append(str(sp))

            subprocess.run(
                [str(ql_bin), "-t", "-s", "1280", "-o", str(tmp_dir)] + single_files,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=35,
            )
            for idx in range(1, n_slides + 1):
                gen_png = tmp_dir / f"s_{idx}.pptx.png"
                if gen_png.exists():
                    dest = assets_dir / f"slide_preview_{idx}.png"
                    shutil.copyfile(gen_png, dest)
                    out_list.append(dest)
        return out_list
    except Exception:
        return []


def _build_fullscreen_image_html_deck(spec: Dict[str, Any], slide_pngs: List[pathlib.Path], out_html: pathlib.Path):
    """Build a clean full-viewport HTML viewer for the generated pure-image slides."""
    title = escape(spec.get("task_summary_cn", "Pure-Image Presentation"))
    total = max(1, len(slide_pngs))
    slides_dom = []
    for idx, png in enumerate(slide_pngs, 1):
        slides_dom.append(
            f"""
            <section class="slide {'active' if idx == 1 else ''}">
              <img src="data:image/png;base64,{base64.b64encode(png.read_bytes()).decode('ascii')}" alt="Slide {idx}" />
            </section>
            """
        )

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>{title}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: #141413; color: #F6F5F1; font-family: -apple-system, "PingFang SC", sans-serif; height: 100vh; width: 100vw; overflow: hidden; display: flex; flex-direction: column; }}
  .prog {{ position: fixed; top: 0; left: 0; height: 3px; background: #C8102E; transition: width 220ms ease; z-index: 30; }}
  .stage {{ flex: 1; display: flex; align-items: center; justify-content: center; padding: 1.5vh 2vw; }}
  .slide {{ display: none; width: 100%; height: 100%; align-items: center; justify-content: center; }}
  .slide.active {{ display: flex; }}
  .slide img {{ max-width: 100%; max-height: 100%; object-fit: contain; border-radius: 6px; box-shadow: 0 20px 60px rgba(0,0,0,0.45); background: #FFFFFF; }}
  .bar {{ position: fixed; bottom: 16px; right: 24px; display: flex; align-items: center; gap: 8px; z-index: 40; background: rgba(20,20,19,0.78); backdrop-filter: blur(8px); padding: 6px 12px; border-radius: 8px; border: 1px solid rgba(255,255,255,0.14); font-size: 12px; }}
  button {{ background: transparent; color: #F6F5F1; border: 1px solid rgba(255,255,255,0.2); border-radius: 5px; padding: 4px 10px; cursor: pointer; font-size: 12px; }}
  button:hover {{ background: rgba(255,255,255,0.1); }}
</style>
</head>
<body>
  <div class="prog" id="prog" style="width: {100 / total:.1f}%"></div>
  <div class="stage">{''.join(slides_dom)}</div>
  <div class="bar">
    <span id="pg">1 / {total}</span>
    <button onclick="go(-1)">← 上一页</button>
    <button onclick="go(1)">下一页 →</button>
    <button onclick="fs()">全屏 (F)</button>
  </div>
  <script>
    let c = 0;
    const s = document.querySelectorAll('.slide');
    const n = s.length;
    function show(i) {{
      c = Math.max(0, Math.min(n - 1, i));
      s.forEach((el, idx) => el.classList.toggle('active', idx === c));
      document.getElementById('pg').textContent = (c + 1) + ' / ' + n;
      document.getElementById('prog').style.width = (((c + 1) / n) * 100) + '%';
    }}
    function go(d) {{ show(c + d); }}
    function fs() {{
      if (!document.fullscreenElement) document.documentElement.requestFullscreen().catch(()=>{{}});
      else document.exitFullscreen().catch(()=>{{}});
    }}
    window.addEventListener('keydown', e => {{
      if (e.key === 'ArrowRight' || e.key === ' ') go(1);
      if (e.key === 'ArrowLeft') go(-1);
      if (e.key.toLowerCase() === 'f') fs();
    }});
  </script>
</body>
</html>"""
    out_html.write_text(html, encoding="utf-8")


def master_agent_qa_inspect(
    job_id: str,
    spec: Dict[str, Any],
    output_dir: pathlib.Path,
    assets_dir: pathlib.Path,
    generator_label: str,
    since_ts: float,
) -> Dict[str, Any]:
    """
    Stage 3 — Master Agent Final QA Review & Packaging:
    1. Collects all slide images generated by Codex/Claude into `assets/slide_preview_1.png ...`.
    2. Packages pure-image slides into `<job_id>_deck.pptx` using `images_to_pptx.py` if needed.
    3. Verifies resolution, slide count, and file integrity, returning a structured `qa_report`.
    """
    target_count = len(spec.get("slide_outline", []))
    final_pptx = output_dir / f"{job_id}_deck.pptx"
    alt_pptx = output_dir / "final_deck.pptx"
    if alt_pptx.exists() and not final_pptx.exists():
        shutil.copyfile(alt_pptx, final_pptx)

    # Collect pure-image slides from Codex if generated
    slide_pngs = _collect_new_codex_images(since_ts, assets_dir, target_count)

    # If pure-image slides were generated by Codex, assemble them into `<job_id>_deck.pptx` via `images_to_pptx.py`
    if slide_pngs and not final_pptx.exists():
        deck = Presentation()
        deck.slide_width, deck.slide_height = Inches(16), Inches(9)
        for png in slide_pngs:
            slide = deck.slides.add_slide(deck.slide_layouts[6])
            slide.shapes.add_picture(str(png), 0, 0, width=deck.slide_width, height=deck.slide_height)
        deck.save(final_pptx)

    # If Claude generated a `.pptx` first without slide PNGs, export slide PNGs via macOS `qlmanage`
    if not slide_pngs and final_pptx.exists():
        slide_pngs = _render_pptx_slides_via_qlmanage(final_pptx, assets_dir, max_slides=target_count)

    # Build full-screen interactive HTML presentation
    out_html = output_dir / f"{job_id}_deck_interactive.html"
    if slide_pngs:
        _build_fullscreen_image_html_deck(spec, slide_pngs, out_html)

    # Inspect dimensions & build QA report
    manifest = inspect_delivery(job_id, spec.get("task_type", "ppt"), spec, output_dir)
    resolutions = []
    for p in slide_pngs:
        try:
            with Image.open(p) as im:
                resolutions.append(f"{im.width}×{im.height}")
        except Exception:
            pass

    pptx_size_kb = round(final_pptx.stat().st_size / 1024, 1) if final_pptx.exists() else 0.0
    pptx_slides_cnt = 0
    if final_pptx.exists():
        try:
            pptx_slides_cnt = len(Presentation(str(final_pptx)).slides)
        except Exception as exc:
            raise ValueError("PPTX parsing failed") from exc

    passed = manifest["file_status"] == "PASSED"
    res_str = resolutions[0] if resolutions else "16:9 HD"
    planner_name = spec.get("compiler_engine", "Claude 内容规划引擎")

    return {
        "status": "PASSED" if passed else "PARTIAL",
        "content_status": "NOT_REVIEWED",
        "manifest": manifest,
        "planner_agent": planner_name,
        "generator_agent": generator_label,
        "planned_slides": target_count,
        "delivered_slides": len(slide_pngs),
        "pptx_slides_count": pptx_slides_cnt,
        "slide_resolution": res_str,
        "pptx_size_kb": pptx_size_kb,
        "checks_cn": [
            f"文件页数检查：{len(slide_pngs)}/{target_count} 页；文字、业务数据及结论尚未审核",
            f"图片文件检查：{res_str}；不代表文字清晰度、裁切或占位符检查",
            f"PPTX 封装核验：已封装为 {pptx_slides_cnt} 页标准 .pptx（文件大小 {pptx_size_kb} KB）与全屏网页演示稿",
        ] if spec.get("task_type", "ppt") != "video" else ["视频容器和视频流可解析，时长与比例符合约定；内容未审核"],
        "verdict_cn": (
            "文件检查通过；内容真实性与文字质量未审核。"
        ),
    }


@app.get("/health")
async def health_check():
    return {"status": "alive"}


@app.get('/internal/claude-status')
async def claude_status(x_worker_secret: Optional[str] = Header(None)):
    if len(WORKER_SECRET) < 32 or not secrets.compare_digest(x_worker_secret or '', WORKER_SECRET):
        raise HTTPException(403, 'Unauthorized worker secret')
    try:
        from gateway.ppt_contract import require_claude_owner
        from worker.claude_account import ClaudeProfile, AccountGate, verify_login
        from worker.native_deck import renderer_tools, validate_job_location
        require_claude_owner(os.getenv('NBPPT_CLAUDE_OWNER_USER_ID'))
        await asyncio.to_thread(renderer_tools)
        profile = ClaudeProfile.configured()
        validate_job_location(WORKSPACE_JOBS_DIR, profile)
        await verify_login(CLAUDE_BIN, profile)
        return AccountGate.configured(profile).status()
    except Exception:
        return {'state': 'unavailable', 'retry_after_seconds': 0, 'message': 'Claude 运行环境未就绪'}


@app.post("/internal/execute-stream")
async def execute_stream(req: JobExecutionRequest, x_worker_secret: Optional[str] = Header(None)):
    if len(WORKER_SECRET) < 32 or WORKER_SECRET == "super-secret-mtls-token-2026" or not secrets.compare_digest(x_worker_secret or "", WORKER_SECRET):
        raise HTTPException(status_code=403, detail="Unauthorized worker secret")

    try:
        safe_job_id(req.job_id)
    except ValueError:
        raise HTTPException(422, "Invalid job identifier")
    if req.task_type not in ("ppt", "video", "composite"):
        raise HTTPException(422, "Unsupported task type")

    if req.english_spec.get("generation_contract") == "skill-direct-v1":
        if req.task_type != "ppt" or not req.job_id.startswith("ppt_"):
            raise HTTPException(422, "PPT contract requires a PPT job")
        from worker.direct_generation import generate_deck_stream
        from gateway.ppt_contract import resolve_ppt_engine
        try:
            engine = resolve_ppt_engine(req.english_spec.get("generator_engine", req.execution_mode))
            if req.execution_mode != "auto" and req.execution_mode != engine:
                raise ValueError("PPT 生成引擎与任务约定不一致")
            if engine in ('claude_cli', 'claude_codex'):
                from gateway.ppt_contract import require_claude_owner
                require_claude_owner(req.english_spec.get('account_owner_user_id'))
        except PermissionError as exc:
            raise HTTPException(403, str(exc))
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        return StreamingResponse(
            generate_deck_stream(req, WORKSPACE_JOBS_DIR, CODEX_BIN, ACCOUNT_SAFE_SEMAPHORE, CLAUDE_BIN),
            media_type="text/event-stream",
        )

    if req.english_spec.get("generation_contract") in ("skill-video-v1", "story-video-v2"):
        if req.task_type != "video" or not req.job_id.startswith("video_"):
            raise HTTPException(422, "Video contract requires a video job")
        from worker.video_generation import generate_video_stream
        return StreamingResponse(
            generate_video_stream(req, WORKSPACE_JOBS_DIR, CODEX_BIN, ACCOUNT_SAFE_SEMAPHORE, CLAUDE_BIN),
            media_type="text/event-stream",
        )

    if req.execution_mode in ('claude_cli', 'claude_codex'):
        raise HTTPException(422, "Claude requires the owner-bound native PPT contract")
    if os.getenv("NBPPT_REQUIRE_ISOLATION", "false").lower() == "true":
        raise HTTPException(422, "Production currently supports isolated Codex PPT generation only")
    job_dir = WORKSPACE_JOBS_DIR / req.job_id
    try:
        job_dir.mkdir(exist_ok=False)
    except FileExistsError:
        raise HTTPException(409, "Job already exists; output cannot be overwritten")
    output_dir = job_dir / "staging"
    assets_dir = output_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    spec_file = job_dir / "task_spec.json"
    req.english_spec["task_type"] = req.task_type
    spec_file.write_text(json.dumps(req.english_spec, ensure_ascii=False, indent=2), encoding="utf-8")

    slide_script_md = req.english_spec.get("markdown_slide_script", "")
    script_file = job_dir / "slide_script.md"
    script_file.write_text(slide_script_md, encoding="utf-8")

    child_env = os.environ.copy()
    for private_name in ("NBPPT_ADMIN_API_KEY", "OVERSEAS_WORKER_SECRET"):
        child_env.pop(private_name, None)
    r_keys = req.runtime_keys or {}
    if r_keys.get("anthropic_api_key"):
        child_env["ANTHROPIC_API_KEY"] = r_keys["anthropic_api_key"]
        child_env["ANTHROPIC_AUTH_TOKEN"] = r_keys["anthropic_api_key"]
    if r_keys.get("anthropic_base_url"):
        child_env["ANTHROPIC_BASE_URL"] = r_keys["anthropic_base_url"]
    if r_keys.get("claude_model"):
        child_env["ANTHROPIC_MODEL"] = r_keys["claude_model"]

    safe_proxy = str(r_keys.get("account_safe_proxy", "")).strip()
    account_safe = bool(r_keys.get("account_safe_mode", True))
    matched_tpl = req.english_spec.get("matched_template", {})
    tpl_name = matched_tpl.get("name", "标准商业视觉体系")
    target_slides = len(req.english_spec.get("slide_outline", [])) or 3

    # Decide generator agent: "codex_cli" (default) or "claude_cli"
    exec_mode = req.execution_mode if req.execution_mode in ("codex_cli", "claude_cli") else "codex_cli"

    async def sse_generator():
        proc = None
        used_real_claude_cli = False
        total_cost_usd = 0.0
        job_start_ts = time.time()
        generator_label = "Codex CLI (gpt-6-astra · image_gen 纯图片PPT)"
        try:
            yield f"data: {json.dumps({'type': 'progress', 'pct': 28, 'message_cn': f'[阶段一完成] 已将详细 PPT 脚本写入 slide_script.md · 视觉体系：《{tpl_name}》'}, ensure_ascii=False)}\n\n"

            async with ACCOUNT_SAFE_SEMAPHORE:
                if account_safe:
                    jitter = round(random.uniform(0.4, 0.9), 2)
                    yield f"data: {json.dumps({'type': 'progress', 'pct': 32, 'message_cn': f'[执行队列] 单进程容量限制 Semaphore(1) 已生效 · 兼容间隔 {jitter}s'}, ensure_ascii=False)}\n\n"
                    await asyncio.sleep(jitter)

                if req.task_type in ("ppt", "composite"):
                    if exec_mode == "codex_cli" and pathlib.Path(CODEX_BIN).exists():
                        generator_label = "Codex CLI (gpt-6-astra · 内置 image_gen 直接生成纯图片 PPT)"
                        codex_prompt = req.english_spec.get("codex_direct_prompt", "")
                        (job_dir / "agent_prompt.txt").write_text(codex_prompt, encoding="utf-8")

                        yield f"data: {json.dumps({'type': 'progress', 'pct': 38, 'message_cn': f'[阶段二 · 交由 Codex 直接生成] 已将 {target_slides} 页高清纯图片 PPT 提示词发给本机 Codex (gpt-6-astra)，正在调用内置 image_gen 逐页出图...'}, ensure_ascii=False)}\n\n"

                        codex_env = child_env.copy()
                        codex_env["HOME"] = str(pathlib.Path.home())
                        if safe_proxy:
                            codex_env["HTTP_PROXY"] = safe_proxy
                            codex_env["HTTPS_PROXY"] = safe_proxy
                            codex_env["ALL_PROXY"] = safe_proxy

                        cfg_path = pathlib.Path.home() / ".codex" / "config.toml"
                        cfg_text = cfg_path.read_text(encoding="utf-8", errors="ignore") if cfg_path.exists() else ""

                        codex_cmd = [
                            CODEX_BIN,
                            "exec",
                            "-m",
                            "gpt-6-astra",
                            "-c",
                            'model_reasoning_effort="low"',
                        ]
                        for mcp_name in (
                            "chrome-devtools",
                            "context7",
                            "magic",
                            "sequential-thinking",
                            "playwright",
                            "ce-context7",
                            "gitnexus",
                        ):
                            if f"mcp_servers.{mcp_name}" in cfg_text or f'mcp_servers."{mcp_name}"' in cfg_text:
                                codex_cmd.extend(["-c", f"mcp_servers.{mcp_name}.enabled=false"])

                        codex_cmd.extend(
                            [
                                "--dangerously-bypass-approvals-and-sandbox",
                                "--skip-git-repo-check",
                                codex_prompt,
                            ]
                        )

                        codex_log_path = job_dir / "codex_exec.log"
                        with open(codex_log_path, "wb") as codex_log_fp:
                            proc = await asyncio.create_subprocess_exec(
                                *codex_cmd,
                                cwd=str(job_dir),
                                env=codex_env,
                                stdin=asyncio.subprocess.DEVNULL,
                                stdout=codex_log_fp,
                                stderr=codex_log_fp,
                                start_new_session=True,
                            )

                            last_reported_count = 0
                            elapsed = 0.0
                            timeout_sec = max(180.0, target_slides * 65.0)
                            while proc.returncode is None and elapsed < timeout_sec:
                                await asyncio.sleep(2.5)
                                elapsed += 2.5
                                cur_imgs = _collect_new_codex_images(job_start_ts, assets_dir, target_slides)
                                if len(cur_imgs) > last_reported_count:
                                    last_reported_count = len(cur_imgs)
                                    pct_now = min(86, 40 + int((last_reported_count / max(1, target_slides)) * 46))
                                    live_cdn = {}  # Unverified files are never published.
                                    yield f"data: {json.dumps({'type': 'progress', 'pct': pct_now, 'message_cn': f'[Codex image_gen 实时出图] 已完成第 {last_reported_count}/{target_slides} 页 16:9 纯图片幻灯片渲染...', 'cdn_urls': live_cdn}, ensure_ascii=False)}\n\n"
                                elif int(elapsed) % 15 == 0:
                                    pct_wait = min(82, 40 + int((elapsed / timeout_sec) * 40))
                                    yield f"data: {json.dumps({'type': 'progress', 'pct': pct_wait, 'message_cn': f'[Codex 正在绘制幻灯片] gpt-6-astra 正在渲染第 { min(last_reported_count + 1, target_slides) }/{target_slides} 页高清咨询排版图 ({int(elapsed)}s)...'}, ensure_ascii=False)}\n\n"

                            if proc.returncode is None:
                                await stop_process(proc)
                                raise TimeoutError("Codex generation timed out")
                            if proc.returncode != 0:
                                raise RuntimeError("Codex generation failed; see private job log")

                        final_imgs = _collect_new_codex_images(job_start_ts, assets_dir, target_slides)
                        if not final_imgs:
                            generator_label = "本地脚本降级生成"
                            ppt_script = SKILLS_ROOT / "pptx-pro" / "scripts" / "build_deck.py"
                            final_pptx = output_dir / f"{req.job_id}_deck.pptx"
                            if ppt_script.exists():
                                yield f"data: {json.dumps({'type': 'progress', 'pct': 82, 'message_cn': '[Codex 兜底保障引擎] 正在使用高精矢量渲染引擎构建 16:9 幻灯片与预览图...'}, ensure_ascii=False)}\n\n"
                                await run_python_skill_script(
                                    ppt_script,
                                    ["--spec", str(spec_file), "--assets", str(assets_dir), "--out", str(final_pptx)],
                                    cwd=job_dir,
                                    env=codex_env,
                                )
                        total_cost_usd += 0.08 * target_slides

                    else:
                        # Claude CLI direct execution mode ("claude_cli")
                        generator_label = f"Claude Code CLI ({r_keys.get('claude_model', 'glm-5')} · 直接调用技能生成 PPTX)"
                        claude_prompt = req.english_spec.get("claude_direct_prompt", "").replace("./output/", "./staging/")
                        (job_dir / "agent_prompt.txt").write_text(claude_prompt, encoding="utf-8")

                        yield f"data: {json.dumps({'type': 'progress', 'pct': 42, 'message_cn': f'[阶段二 · 交由 Claude 直接生成] 已将详细脚本 slide_script.md 发送给 Claude CLI，正在构建 PPTX...'}, ensure_ascii=False)}\n\n"

                        claude_env = child_env.copy()
                        # Do not route domestic Zhipu GLM through overseas proxy
                        if "bigmodel.cn" in str(r_keys.get("anthropic_base_url", "")):
                            for pk in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
                                claude_env.pop(pk, None)

                        if pathlib.Path(CLAUDE_BIN).exists():
                            proc = await asyncio.create_subprocess_exec(
                                CLAUDE_BIN,
                                "-p",
                                "--dangerously-skip-permissions",
                                claude_prompt,
                                cwd=str(job_dir),
                                env=claude_env,
                                stdin=asyncio.subprocess.DEVNULL,
                                stdout=asyncio.subprocess.PIPE,
                                stderr=asyncio.subprocess.PIPE,
                                start_new_session=True,
                            )
                            try:
                                await asyncio.wait_for(proc.communicate(), timeout=75.0)
                            except asyncio.TimeoutError:
                                await stop_process(proc)
                                raise TimeoutError("Claude generation timed out")
                            if proc.returncode != 0:
                                raise RuntimeError("Claude generation failed")
                            used_real_claude_cli = True

                        # Ensure the CI PPTX is built if Claude CLI returned early
                        final_pptx = output_dir / f"{req.job_id}_deck.pptx"
                        alt_pptx = output_dir / "final_deck.pptx"
                        if not final_pptx.exists() and not alt_pptx.exists():
                            generator_label = "本地脚本降级生成"
                            tpl_id = str(matched_tpl.get("id", ""))
                            if tpl_id.startswith("gorden:"):
                                ppt_script = SKILLS_ROOT / "pptx-pro" / "scripts" / "build_deck.py"
                                await run_python_skill_script(
                                    ppt_script,
                                    ["--spec", str(spec_file), "--assets", str(assets_dir), "--out", str(final_pptx)],
                                    cwd=job_dir,
                                    env=claude_env,
                                )
                            elif MD_TO_CI_PPTX_SCRIPT.exists():
                                proc = await asyncio.create_subprocess_exec(
                                    "node",
                                    str(MD_TO_CI_PPTX_SCRIPT),
                                    "--source",
                                    str(script_file),
                                    "--out",
                                    str(final_pptx),
                                    cwd=str(job_dir),
                                    env=claude_env,
                                    start_new_session=True,
                                )
                                await asyncio.wait_for(proc.wait(), timeout=120)
                                if proc.returncode != 0:
                                    raise RuntimeError("PPTX packaging failed")
                                if not final_pptx.exists():
                                    ppt_script = SKILLS_ROOT / "pptx-pro" / "scripts" / "build_deck.py"
                                    await run_python_skill_script(
                                        ppt_script,
                                        ["--spec", str(spec_file), "--assets", str(assets_dir), "--out", str(final_pptx)],
                                        cwd=job_dir,
                                        env=claude_env,
                                    )
                        total_cost_usd += 0.06

                # Optional Video Generation if requested
                if req.task_type in ("video", "composite"):
                    yield f"data: {json.dumps({'type': 'progress', 'pct': 84, 'message_cn': '[Claude 图形化视频引擎] 正在渲染 20fps 程序化矢量动效视频...'}, ensure_ascii=False)}\n\n"
                    vid_script = SKILLS_ROOT / "jimeng-video" / "scripts" / "jimeng_pipeline.py"
                    vid_out = output_dir / f"{req.job_id}_video.mp4"
                    await run_python_skill_script(
                        vid_script,
                        ["--spec", str(spec_file), "--out", str(vid_out)],
                        cwd=job_dir,
                        env=child_env,
                    )
                    total_cost_usd += 0.085

            # Stage 3: Master Agent Final QA Inspection & Sign-Off
            yield f"data: {json.dumps({'type': 'progress', 'pct': 90, 'message_cn': '[阶段三 · 文件检查] 正在核验文件完整性、图片尺寸和页数；不审核内容真实性。'}, ensure_ascii=False)}\n\n"
            qa_report = master_agent_qa_inspect(
                req.job_id,
                req.english_spec,
                output_dir,
                assets_dir,
                generator_label,
                job_start_ts,
            )
            yield f"data: {json.dumps({'type': 'progress', 'pct': 96, 'message_cn': qa_report['verdict_cn']}, ensure_ascii=False)}\n\n"

            manifest = inspect_delivery(req.job_id, req.task_type, req.english_spec, output_dir)
            (output_dir / "delivery.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
            output_dir.rename(job_dir / "output")
            cdn_urls = delivery_urls(req.job_id, manifest)

            completed_event = {
                "type": "completed",
                "pct": 100,
                "total_cost_usd": round(max(0.05, total_cost_usd), 4),
                "used_real_claude_cli": used_real_claude_cli,
                "cdn_urls": cdn_urls,
                "qa_report": qa_report,
            }
            yield f"data: {json.dumps(completed_event, ensure_ascii=False)}\n\n"

        except Exception as exc:
            err_event = {"type": "error", "message": str(exc)}
            yield f"data: {json.dumps(err_event, ensure_ascii=False)}\n\n"
        finally:
            await stop_process(proc)

    return StreamingResponse(sse_generator(), media_type="text/event-stream")
