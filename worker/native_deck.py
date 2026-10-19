"""Render the actual editable deck offline, then publish faithful image previews."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from PIL import Image, ImageStat

from gateway.delivery import inspect_delivery
from gateway.native_ppt import validate_native_pptx, walk_shapes
from worker.isolation import isolated_command


def renderer_tools():
    tools = {}
    for name, override, candidates in (
        ("soffice", "NBPPT_SOFFICE", ("soffice", "libreoffice")),
        ("pdftoppm", "NBPPT_PDFTOPPM", ("pdftoppm",)),
    ):
        value = os.getenv(override) or next((shutil.which(x) for x in candidates if shutil.which(x)), None)
        if not value or not Path(value).is_file():
            raise ValueError(f"原生 PPT 文件验收缺少 {name}，停止生成，不使用模板兜底")
        tools[name] = str(Path(value).absolute())
    fc = shutil.which('fc-match')
    if not fc:
        raise ValueError("原生 PPT 缺少 fontconfig 字体验收工具")
    matched = subprocess.run([fc, '-f', '%{family}', 'Noto Sans CJK SC'], capture_output=True, timeout=10)
    if matched.returncode or 'Noto Sans CJK SC' not in matched.stdout.decode('utf-8', errors='replace'):
        raise ValueError("原生 PPT 缺少 Noto Sans CJK SC；禁止用未知字体替代后假报验收通过")
    return tools


def runtime_paths():
    # Operator-owned environment, never paths from the user request.
    python = Path(os.getenv("NBPPT_PPT_PYTHON") or sys.executable).absolute()
    if not python.is_file():
        raise ValueError("PPT Python 运行时不存在")
    return [python.parent.parent]


def validate_job_location(jobs_root, profile):
    # The official sandbox's deny rules take precedence over nested allows.
    # Keep generated work outside login homes rather than weakening credential protection.
    root = Path(jobs_root).resolve()
    if any(root.is_relative_to(p.resolve()) for p in (profile.home, Path.home())):
        raise ValueError("Claude 任务目录须位于登录 HOME 之外；请在两端设置相同 NBPPT_JOBS_ROOT")


async def run_renderer(command, job_dir, timeout=120):
    from worker.direct_generation import stop_process
    args, _ = isolated_command(command, job_dir, [], agent="renderer")
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "LANG", "FONTCONFIG_FILE", "TMPDIR")}
    proc = await asyncio.create_subprocess_exec(*args, cwd=job_dir, env=env,
        stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE, start_new_session=True)
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout)
        if proc.returncode:
            (job_dir / "renderer-private.log").write_bytes(stdout + stderr)
            raise ValueError("实际 PPTX 渲染失败，不能交付未验收文件")
    finally:
        await stop_process(proc)


def actual_outline(deck):
    result = []
    for number, page in enumerate(deck.slides, 1):
        text_shapes = [x for x in walk_shapes(page.shapes) if x.has_text_frame and x.text.strip()]
        size = lambda x: max((r.font.size or 0 for p in x.text_frame.paragraphs for r in p.runs), default=0)
        title = max(text_shapes, key=size).text.strip() if text_shapes else f"第 {number} 页"
        result.append({"slide_num": number, "action_title_cn": title,
                       "visible_text_cn": "\n".join(x.text for x in text_shapes),
                       "page_type": "agent-designed", "evidence_status": "NOT_REVIEWED"})
    return result


async def package_native(job_id, job_dir, spec):
    candidate = job_dir / "draft/presentation.pptx"
    if not candidate.resolve().is_relative_to(job_dir.resolve()):
        raise ValueError("PPTX 不能引用任务外的文件")
    deck = validate_native_pptx(candidate, spec.get("slide_count", 0))
    slides = actual_outline(deck)
    render = job_dir / "rendered"
    render.mkdir(exist_ok=False)
    tools = await asyncio.to_thread(renderer_tools)
    await run_renderer([tools["soffice"], f"-env:UserInstallation={(job_dir / 'render-profile').as_uri()}",
        "--headless", "--norestore", "--convert-to", "pdf", "--outdir", str(render), str(candidate)], job_dir)
    pdf = render / "presentation.pdf"
    if pdf.is_symlink() or not pdf.is_file() or not pdf.stat().st_size:
        raise ValueError("PPTX 没有生成实际渲染文件")
    await run_renderer([tools["pdftoppm"], "-png", "-scale-to-x", "1672", "-scale-to-y", "941", str(pdf), str(render / "page")], job_dir)
    pages = sorted(render.glob("page-*.png"), key=lambda p: int(p.stem.split("-")[-1]))
    if len(pages) != len(slides):
        raise ValueError("PPTX 实际渲染页数不一致")
    output = job_dir / "delivery-staging"
    (output / "assets").mkdir(parents=True, exist_ok=False)
    images, hashes = [], set()
    for number, page in enumerate(pages, 1):
        if page.is_symlink() or page.stat().st_nlink != 1:
            raise ValueError("PPTX 渲染图片不安全")
        with Image.open(page) as im:
            im.load()
            if im.format != "PNG" or im.size != (1672, 941) or max(ImageStat.Stat(im.convert("RGB")).stddev) < .1:
                raise ValueError("PPTX 渲染为空白或尺寸不正确")
            digest = hashlib.sha256(im.convert("RGB").tobytes()).hexdigest()
            if digest in hashes:
                raise ValueError("PPTX 包含完全重复页面")
            hashes.add(digest)
        target = output / f"assets/slide_preview_{number}.png"
        shutil.copyfile(page, target)
        images.append(target)
    shutil.copyfile(candidate, output / f"{job_id}_deck.pptx")
    actual = {**spec, "presentation_format": "native-pptx-v1", "slide_count": len(slides),
              "slide_outline": slides, "compiler_engine": "Claude 自由创作", "is_real_llm": True}
    from worker.worker_api import _build_fullscreen_image_html_deck
    _build_fullscreen_image_html_deck(actual, images, output / f"{job_id}_deck_interactive.html")
    qa = {"status": "PASSED", "planned_slides": len(slides), "delivered_slides": len(slides),
          "pptx_slides_count": len(slides), "slide_resolution": "1672×941",
          "presentation_format": "native-pptx-v1",
          "checks_cn": ["实际 PPTX 已重新打开并离线渲染", "PPTX、预览和网页页数一致，非空且无重复像素", "压缩规模、宏、外部资源与文件摘要已检查"],
          "verdict_cn": "文件验收通过；内容、字体细节与美感仍需人工审阅"}
    (output / "qa_report.json").write_text(json.dumps(qa, ensure_ascii=False))
    manifest = inspect_delivery(job_id, "ppt", actual, output)
    (output / "delivery.json").write_text(json.dumps(manifest, ensure_ascii=False))
    output.rename(job_dir / "output")
    return actual, qa
