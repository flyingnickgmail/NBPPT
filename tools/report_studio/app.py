"""Run: .venv/bin/python -m tools.report_studio.app (loopback only)."""
import asyncio
import base64
import json
import os
import re
import shutil
import uuid
from collections import OrderedDict
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from .models import Chart, ExportInput, GenerateInput, Report, Section, Source
from .evidence import validate_evidence
from .generator import ai_report, strict_schema, refine_report, design_reading, design_editorial
from .quality import review_report
from .illustrations import illustration_asset
from .chart_design import recommend_design
from .editorial import evidence_catalog
from .overview import validate_overview
from .overview_generation import create_overview_with_reselection as create_overview
from .overview_style import VERSION as OVERVIEW_STANDARD_VERSION

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
MAX_CONTENT = 60000


app = FastAPI(title="灵动报告实验室", docs_url=None, redoc_url=None)
lock = asyncio.Lock()
previews: OrderedDict[str, str] = OrderedDict()
OVERVIEW_JOBS_DIR = ROOT.parent.parent / 'workspace' / 'report-overviews'
overview_tasks = {}


def overview_job_folder(job_id):
    if not re.fullmatch(r'[a-f0-9]{32}', job_id):
        raise HTTPException(404, '任务不存在')
    folder = OVERVIEW_JOBS_DIR / job_id
    if not folder.is_dir():
        raise HTTPException(404, '任务不存在')
    return folder


async def run_overview_job(job_id, data):
    folder = overview_job_folder(job_id)
    async def progress(state, message, **extra):
        payload = {'id': job_id, 'state': state, 'message': message, **extra}
        temp = folder / 'status.tmp'
        temp.write_text(json.dumps(payload, ensure_ascii=False))
        temp.replace(folder / 'status.json')
    try:
        result = await create_overview(data, folder, progress)
        html = export_html(result)
        (folder / 'report.json').write_text(result.model_dump_json(indent=2))
        (folder / 'report.html').write_text(html)
        previews[job_id] = html
        await progress('completed', '全景图已生成并通过模型图文复核，仍请核阅后分享', preview_url='/preview/' + job_id)
    except asyncio.CancelledError:
        await progress('failed', '服务中断，原报告保留，请重新生成')
        raise
    except Exception as exc:
        message = exc.detail if isinstance(exc, HTTPException) else '设计或图片校验未通过，原报告保留，请重试'
        (folder / 'error.json').write_text(json.dumps({'type': type(exc).__name__, 'detail': str(exc)}, ensure_ascii=False))
        await progress('failed', str(message))
    finally:
        lock.release()
        overview_tasks.pop(job_id, None)


@app.middleware("http")
async def local_only(request: Request, call_next):
    # Block DNS rebinding and drive-by requests to this local model runner.
    if request.url.hostname not in {"127.0.0.1", "localhost", "testserver", "::1"}:
        return HTMLResponse("仅允许本机访问", status_code=403)
    origin = request.headers.get("origin")
    if request.method not in {"GET", "HEAD"} and origin and origin != str(request.base_url).rstrip("/"):
        return HTMLResponse("来源不匹配", status_code=403)
    try:
        limit = 10_000_000 if request.url.path in {'/api/export', '/api/preview', '/api/review', '/api/overview', '/api/continue'} else 2_000_000
        oversized = int(request.headers.get("content-length", "0")) > limit
    except ValueError:
        return HTMLResponse("输入长度无效", status_code=400)
    if oversized:
        return HTMLResponse("输入过大", status_code=413)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Security-Policy"] = "default-src 'self' blob:; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-src 'self' blob:; object-src 'none'; base-uri 'none'; frame-ancestors 'self'"
    return response


def none_chart():
    return Chart(kind="none", title="", unit="", points=[], steps=[])


def local_report(content: str, title: str = "") -> Report:
    """Lossless plain-text / Markdown segmentation; no simulated AI or numbers."""
    lines = content.strip().splitlines()
    detected = next((re.sub(r"^#+\s*", "", x).strip() for x in lines if x.startswith("# ")), "")
    sections = []
    current = Section(label="原文", title="内容概览", paragraphs=[], bullets=[], chart=none_chart())
    for line in lines:
        heading = re.match(r"^#{1,6}\s+(.+)", line)
        if heading:
            if current.paragraphs or current.bullets:
                sections.append(current)
            current = Section(label=heading[1][:60], title=heading[1][:200], paragraphs=[], bullets=[], chart=none_chart())
        elif line.strip():
            # Chunk long material instead of silently dropping it at display limits.
            if len(current.paragraphs) + len(current.bullets) >= 20:
                sections.append(current)
                current = Section(label="原文续", title=current.title, paragraphs=[], bullets=[], chart=none_chart())
            bullet = re.match(r"^\s*[-*]\s+(.+)", line)
            (current.bullets if bullet else current.paragraphs).append(bullet[1] if bullet else line)
    if current.paragraphs or current.bullets:
        sections.append(current)
    if not sections:
        sections = [current]
    if len(sections) > 24:
        raise ValueError("章节超过 24 个，请合并章节后再生成；原文没有被截断。")
    summary = next((p for s in sections for p in s.paragraphs if not p.startswith("|")), "按原文结构排版；完整材料见文末。")[:1500]
    urls = list(dict.fromkeys(re.findall(r"https?://[^\s<>\]\)]+", content)))[:60]
    return Report(title=title or detected[:180] or "我的研究报告", subtitle="从材料到观点，让信息清晰可见。", summary=summary,
                  metrics=[], sections=sections, sources=[Source(label=f"材料链接 {i+1}", url=u[:2000]) for i,u in enumerate(urls)])


def export_html(data: ExportInput) -> str:
    validate_evidence(data.report, data.content)
    validate_overview(data)
    payload = json.dumps(data.model_dump(), ensure_ascii=False).replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    css = '\n'.join((STATIC / name).read_text() for name in ('report.css', 'editorial.css', 'charts.css', 'editorial_cover.css', 'scatter.css', 'analytical.css', 'qualitative.css', 'qualified.css', 'reading.css', 'overview.css'))
    js = (STATIC / "report.js").read_text()
    visuals = (STATIC / 'qualified.js').read_text() + '\n' + (STATIC / "qualitative.js").read_text() + '\n' + (STATIC / "visuals.js").read_text()
    series = (STATIC / "series.js").read_text()
    story = (STATIC / "story.js").read_text() if data.report.story or data.report.spatial else ''
    space = ((STATIC / 'space_gpu.js').read_text() + '\n' + (STATIC / 'space.js').read_text()) if data.report.spatial else ''
    recipes = (STATIC / 'brand.js').read_text() + '\n' + (STATIC / 'recipes.js').read_text() + '\n' + (STATIC / 'editorial_cover.js').read_text()
    if (STATIC / 'chart_motion.js').exists():
        recipes += '\n' + (STATIC / 'chart_motion.js').read_text()
    facts = json.dumps(evidence_catalog(data.report) if data.report.editorial else {}, ensure_ascii=False).replace('<', '\\u003c')
    recipes += '\nwindow.ReportCoverFacts=' + facts + ';'
    recipes += '\n' + (STATIC / 'rankings.js').read_text()
    recipes += '\n' + (STATIC / 'scatter.js').read_text()
    recipes += '\n' + (STATIC / 'analytical.js').read_text() + '\n' + (STATIC / 'reading.js').read_text()
    recipes += '\n' + (STATIC / 'overview.js').read_text() + '\n' + (STATIC / 'overview_generate.js').read_text()
    design = json.dumps(recommend_design(data.report), ensure_ascii=False).replace('<', '\\u003c')
    artwork = json.dumps(None if data.report.story or data.report.spatial else illustration_asset(data.report.illustration), ensure_ascii=True).replace("<", "\\u003c")
    geography = (STATIC / "geography.js").read_text() if any(v.kind == "worldmap" for s in data.report.sections for v in s.visuals) else ''
    return f'<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="referrer" content="no-referrer"><title>交互报告</title><style>{css}</style><body><div id="report"></div><script id="report-data" type="application/json">{payload}</script><script>window.ReportIllustration={artwork};window.ReportDesign={design};\n{geography}\n{recipes}\n{series}\n{story}\n{space}\n{visuals}\n{js}\nReportView.mount(JSON.parse(document.getElementById("report-data").textContent));</script></body></html>'


@app.get("/")
async def index():
    return HTMLResponse((STATIC / "index.html").read_text())


@app.get("/api/health")
async def health():
    return {"status": "ok", "codex_installed": bool(shutil.which("codex")), "limit": MAX_CONTENT, "version": "0.32.0"}


@app.get("/api/sample")
async def sample():
    return json.loads((ROOT / "sample.json").read_text())


@app.post("/api/generate")
async def generate(data: GenerateInput):
    if not data.content.strip():
        raise HTTPException(422, "请先输入材料。")
    if data.mode == "ai":
        if lock.locked():
            raise HTTPException(409, "已有报告正在生成，请稍后再试。")
        async with lock:
            report = await ai_report(data.content, data.title)
    else:
        try:
            report = local_report(data.content, data.title)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    return {"report": report.model_dump(), "content": data.content, "theme": data.theme, "mode": data.mode}


@app.post("/api/export")
async def export(data: ExportInput):
    try:
        return HTMLResponse(export_html(data))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.post('/api/continue')
async def continue_report(data: ExportInput):
    """Continue an imported validated report; never recreate its initial content."""
    try:
        validate_evidence(data.report, data.content)
        if lock.locked():
            raise HTTPException(409, '已有报告或全景图正在生成，请等待完成')
        async with lock:
            report = await refine_report(data.report, data.content)
            report = await design_reading(report, data.content)
            # The independent overview action designs the shareable cover.
            # Do not repeat an optional legacy cover call after body review.
        result = data.model_copy(deep=True)
        result.report, result.overview, result.mode = report, None, 'ai'
        return result.model_dump()
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.post("/api/preview")
async def preview(data: ExportInput):
    try:
        html = export_html(data)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    key = uuid.uuid4().hex
    previews[key] = html
    while len(previews) > 20:
        previews.popitem(last=False)
    return {"url": f"/preview/{key}"}


@app.post("/api/review")
async def review(data: ExportInput):
    try:
        return review_report(data.report, data.content)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.post('/api/overview', status_code=202)
async def start_overview(data: ExportInput):
    try:
        validate_evidence(data.report, data.content)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if not shutil.which('codex'):
        raise HTTPException(503, '未找到本机 Codex 生成工具')
    if lock.locked():
        raise HTTPException(409, '已有报告或全景图正在生成，请等待完成')
    await lock.acquire()
    job_id = uuid.uuid4().hex
    folder = OVERVIEW_JOBS_DIR / job_id
    try:
        folder.mkdir(parents=True)
        data.overview = None
        # Resume only a failed, source-identical job whose design already passed.
        # Use this job's saved candidate, never global/newest generated images.
        for previous in sorted(OVERVIEW_JOBS_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if previous == folder or not previous.is_dir():
                continue
            try:
                if json.loads((previous / 'status.json').read_text())['state'] != 'failed':
                    continue
                if (previous / 'publication-version.txt').read_text() != OVERVIEW_STANDARD_VERSION:
                    continue
                old = json.loads((previous / 'input.json').read_text())
                if old['report'] != data.report.model_dump() or old['content'] != data.content:
                    continue
                reviews = sorted(previous.glob('plan-review-*.json'))
                design_review = json.loads(reviews[-1].read_text()) if reviews else {}
                if not design_review.get('approved') or design_review.get('issues'):
                    # Reuse a failed draft only as a draft: it must go through
                    # citation checks AND a fresh model review before production.
                    drafts = sorted(previous.glob('design-plan-*.json'))
                    if drafts:
                        shutil.copyfile(drafts[-1], folder / 'draft-plan.json')
                        (folder / 'draft-source.json').write_text(json.dumps({'job_id': previous.name}))
                        break
                    continue
                visual_reviews = sorted(previous.glob('review-*.json'))
                if not visual_reviews:
                    continue
                last_review = visual_reviews[-1]
                candidate = previous / last_review.name.replace('review-', 'candidate-').replace('.json', '.png')
                if not candidate.is_file():
                    continue
                design = sorted(previous.glob('design-plan-*.json'))[-1]
                shutil.copyfile(design, folder / 'resume-plan.json')
                shutil.copyfile(design, folder / 'design-plan-0.json')
                shutil.copyfile(reviews[-1], folder / 'plan-review-0.json')
                if not json.loads(last_review.read_text()).get('unrelated_image', False):
                    shutil.copyfile(candidate, folder / 'resume-image.png')
                    shutil.copyfile(last_review, folder / 'resume-review.json')
                production_plans = sorted(previous.glob('production-plan-*.json'))
                if production_plans and json.loads(production_plans[-1].read_text()).get('mode') == 'diagram':
                    shutil.copyfile(production_plans[-1], folder / 'resume-production.json')
                (folder / 'resume-source.json').write_text(json.dumps({'job_id': previous.name}))
                break
            except (OSError, ValueError, KeyError, IndexError):
                continue
        (folder / 'input.json').write_text(data.model_dump_json(indent=2))
        (folder / 'publication-version.txt').write_text(OVERVIEW_STANDARD_VERSION)
        (folder / 'status.json').write_text(json.dumps({'id': job_id, 'state': 'planning', 'message': '正在准备全文设计'}))
        overview_tasks[job_id] = asyncio.create_task(run_overview_job(job_id, data))
    except Exception:
        lock.release()
        raise
    return {'id': job_id, 'status_url': '/api/overview/' + job_id}


@app.get('/api/overview/{job_id}')
async def overview_status(job_id: str):
    folder = overview_job_folder(job_id)
    if not (folder / 'status.json').is_file():
        return {'id': job_id, 'state': 'failed', 'message': '任务保存中断，原报告保留，请重新生成'}
    status = json.loads((folder / 'status.json').read_text())
    if status['state'] not in {'completed', 'failed'} and job_id not in overview_tasks:
        status.update(state='failed', message='服务重启使生成中断，原报告保留，请重新生成')
    return status


@app.get('/api/overview/{job_id}/result')
async def overview_result(job_id: str):
    status = await overview_status(job_id)
    if status['state'] != 'completed':
        raise HTTPException(409, '任务尚未完成')
    return json.loads((overview_job_folder(job_id) / 'report.json').read_text())


@app.get("/preview/{key}")
async def read_preview(key: str):
    if key not in previews:
        try:
            folder = overview_job_folder(key)
        except HTTPException:
            raise HTTPException(404, "预览已失效，请重新生成或导入报告。")
        if not (folder / 'report.html').is_file() or (await overview_status(key))['state'] != 'completed':
            raise HTTPException(404, '报告尚未完成')
        previews[key] = (folder / 'report.html').read_text()
    return HTMLResponse(previews[key])


@app.get('/preview/{key}/overview.png')
async def download_overview(key: str):
    if key not in previews:
        await read_preview(key)
    html = previews.get(key, '')
    match = re.search(r'<script id="report-data" type="application/json">(.*?)</script>', html, re.S)
    if not match:
        raise HTTPException(404, '预览不存在')
    overview = json.loads(match[1]).get('overview')
    if not overview:
        raise HTTPException(404, '这份报告没有全景图')
    return Response(base64.b64decode(overview['data_url'].split(',', 1)[1]), media_type='image/png',
                    headers={'Content-Disposition': 'attachment; filename="report-overview.png"'})


app.mount("/static", StaticFiles(directory=STATIC), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("REPORT_PORT", "8766")))
