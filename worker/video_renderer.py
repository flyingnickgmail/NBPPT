"""Trusted, deterministic renderer for validated Chinese motion-video plans.

The planning agent never supplies code, paths, fonts, filters, or commands.  This
module reads one worker-created JSON file and invokes FFmpeg without a shell.
"""
from __future__ import annotations

import argparse
import html
import json
import os
from pathlib import Path
import re
import shutil
import selectors
import subprocess
import sys
import time

from PIL import Image, ImageDraw, ImageFont


FPS = 24
FONT_CANDIDATES = (
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/PingFang.ttc",
)
LAYOUTS = {"title", "comparison", "process"}
DEFAULT_PALETTE = {"bg": "#F5F7F8", "surface": "#FFFFFF", "border": "#CAD9DD",
                   "primary": "#08717A", "accent": "#D45B45", "text": "#172C35",
                   "muted": "#6A7B82"}
PORTRAIT_CONTENT_BOTTOM = .80
PORTRAIT_SUBTITLE_TOP = .84


class RenderError(RuntimeError):
    pass


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = list(FONT_CANDIDATES)
    if bold:
        candidates = [p.replace("Regular", "Bold") for p in candidates] + candidates
    for name in candidates:
        if Path(name).is_file():
            return ImageFont.truetype(name, size=size, index=0)
    raise RenderError("未安装可用的中文字体（需要 Noto Sans CJK 或系统黑体）")


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    """Wrap every character; no ellipsis and no silent text loss."""
    lines: list[str] = []
    for paragraph in text.splitlines() or [""]:
        current = ""
        for char in paragraph:
            candidate = current + char
            if current and draw.textbbox((0, 0), candidate, font=font)[2] > max_width:
                lines.append(current)
                current = char
            else:
                current = candidate
        lines.append(current)
    return lines


def _draw_wrapped(draw, xy, text, font, fill, max_width, spacing=12, max_lines=None, max_bottom=None):
    lines = _wrap(draw, text, font, max_width)
    if max_lines is not None and len(lines) > max_lines:
        raise RenderError("视频文字超过可信渲染器的完整排版容量")
    draw.multiline_text(xy, "\n".join(lines), font=font, fill=fill, spacing=spacing)
    box = draw.multiline_textbbox(xy, "\n".join(lines), font=font, spacing=spacing)
    if box[2] > xy[0] + max_width + 1 or (max_bottom is not None and box[3] > max_bottom):
        raise RenderError("视频文字超出可信渲染器的像素边界")
    return box[3] - box[1]


def _trusted_palette(plan: dict) -> dict[str, str]:
    raw = plan.get("matched_template", {})
    raw = raw.get("template", raw) if isinstance(raw, dict) else {}
    raw = raw.get("palette", {}) if isinstance(raw, dict) else {}
    if not isinstance(raw, dict):
        raise RenderError("模板色板必须是对象")
    palette = dict(DEFAULT_PALETTE)
    for name in DEFAULT_PALETTE:
        if name in raw:
            value = raw[name]
            if not isinstance(value, str) or not re.fullmatch(r"#[0-9A-Fa-f]{6}", value):
                raise RenderError(f"模板色板 {name} 不是 #RRGGBB")
            palette[name] = value.upper()
    return palette


def _base_canvas(width: int, height: int, scene_num: int, palette: dict) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (width, height), palette["bg"])
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, width, max(10, height // 70)), fill=palette["primary"])
    draw.ellipse((int(width * .72), -int(height * .28), int(width * 1.08), int(height * .36)), fill=palette["surface"])
    portrait = height > width
    footer_y = int(height * .805)
    draw.text((int(width * .055), footer_y), f"NBPPT  ·  {scene_num:02d}",
              font=_font(max(16, min(width, height) // 45)), fill=palette["muted"])
    # Burned captions live below this rule. Scene content must never occupy the
    # caption band; portrait exports also use a native layout rather than a
    # shrunken landscape frame.
    rule_y = int(height * PORTRAIT_SUBTITLE_TOP)
    draw.line((int(width * .055), rule_y, int(width * .945), rule_y),
              fill=palette["border"], width=max(1, height // 640))
    return image, draw


def _fit_text(draw: ImageDraw.ImageDraw, text: str, max_width: int, max_height: int,
              max_size: int, min_size: int, bold: bool = False,
              max_lines: int | None = None) -> tuple[ImageFont.FreeTypeFont, list[str], int]:
    """Return a font/line set that preserves all text inside a pixel box."""
    fallback = None
    for size in range(max_size, min_size - 1, -1):
        font = _font(size, bold=bold)
        lines = _wrap(draw, text, font, max_width)
        if max_lines is not None and len(lines) > max_lines:
            continue
        spacing = max(5, size // 4)
        box = draw.multiline_textbbox((0, 0), "\n".join(lines), font=font, spacing=spacing)
        if box[2] <= max_width + 1 and box[3] - box[1] <= max_height:
            if len(lines) > 1 and len(lines[-1].strip()) < 3:
                if fallback is None:
                    fallback = (font, lines, spacing)
                continue
            return font, lines, spacing
    if fallback is not None:
        return fallback
    raise RenderError("视频文字超过可信渲染器的完整排版容量")


def _draw_fitted(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, fill: str,
                 max_width: int, max_height: int, max_size: int, min_size: int,
                 bold: bool = False, max_lines: int | None = None,
                 center_vertical: bool = False) -> int:
    font, lines, spacing = _fit_text(draw, text, max_width, max_height, max_size,
                                     min_size, bold=bold, max_lines=max_lines)
    rendered = "\n".join(lines)
    if center_vertical:
        local_box = draw.multiline_textbbox((0, 0), rendered, font=font, spacing=spacing)
        xy = (xy[0], xy[1] + (max_height - (local_box[3] - local_box[1])) // 2 - local_box[1])
    draw.multiline_text(xy, rendered, font=font, fill=fill, spacing=spacing)
    box = draw.multiline_textbbox(xy, rendered, font=font, spacing=spacing)
    return box[3] - box[1]


def _render_portrait_scene(scene: dict, width: int, height: int,
                           destination: Path, palette: dict) -> None:
    """Compose a native 9:16 scene while keeping a clean caption band."""
    image, draw = _base_canvas(width, height, scene["scene_num"], palette)
    margin = int(width * .075)
    inner_width = width - 2 * margin
    content_bottom = int(height * PORTRAIT_CONTENT_BOTTOM)
    title_y = int(height * .075)
    title_h = _draw_fitted(draw, (margin, title_y), scene["title"], palette["text"],
                           inner_width, int(height * .14), max_size=54, min_size=34,
                           bold=True, max_lines=3)
    cursor = title_y + title_h + int(height * .025)
    layout = scene["layout"]
    items = scene["items"]

    if layout == "title":
        items_top = int(height * .54) if items else content_bottom
        body_space = items_top - cursor - int(height * .02)
        _draw_fitted(draw, (margin, cursor), scene["body"], palette["muted"],
                     inner_width, body_space, max_size=42, min_size=25, max_lines=9)
        if items:
            gap = int(height * .012)
            available = content_bottom - items_top - gap * (len(items) - 1)
            chip_h = available // len(items)
            if chip_h < 62:
                raise RenderError("竖版标题项目超过像素容量")
            for index, item in enumerate(items):
                row_y = items_top + index * (chip_h + gap)
                draw.rounded_rectangle((margin, row_y, width - margin, row_y + chip_h),
                                       radius=18, fill=palette["surface"],
                                       outline=palette["border"], width=2)
                text_y = row_y + int(chip_h * .16)
                _draw_fitted(draw, (margin + 22, text_y), item, palette["primary"],
                             inner_width - 44, int(chip_h * .68), max_size=36,
                             min_size=22, bold=True, max_lines=3, center_vertical=True)
    elif layout == "comparison":
        if len(items) != 2:
            raise RenderError("对比版式必须包含两个对比项")
        body_h = _draw_fitted(draw, (margin, cursor), scene["body"], palette["muted"],
                              inner_width, int(height * .15), max_size=36,
                              min_size=23, max_lines=5)
        cards_top = cursor + body_h + int(height * .025)
        gap = int(height * .025)
        card_h = (content_bottom - cards_top - gap) // 2
        if card_h < 120:
            raise RenderError("竖版对比项目超过像素容量")
        for index, item in enumerate(items):
            card_y = cards_top + index * (card_h + gap)
            draw.rounded_rectangle((margin, card_y, width - margin, card_y + card_h),
                                   radius=22, fill=palette["surface"],
                                   outline=palette["border"], width=2)
            color = palette["primary"] if index == 0 else palette["accent"]
            draw.rectangle((margin, card_y, margin + 14, card_y + card_h), fill=color)
            _draw_fitted(draw, (margin + 36, card_y + 28), item, palette["text"],
                         inner_width - 72, card_h - 56, max_size=42, min_size=24,
                         bold=True, max_lines=6, center_vertical=True)
    elif layout == "process":
        if not 2 <= len(items) <= 5:
            raise RenderError("流程版式必须包含二至五个步骤")
        body_h = _draw_fitted(draw, (margin, cursor), scene["body"], palette["muted"],
                              inner_width, int(height * .14), max_size=34,
                              min_size=22, max_lines=5)
        flow_y = cursor + body_h + int(height * .025)
        gap = int(height * .011)
        step_h = (content_bottom - flow_y - gap * (len(items) - 1)) // len(items)
        if step_h < 72:
            raise RenderError("竖版流程项目超过像素容量")
        for index, item in enumerate(items):
            row_y = flow_y + index * (step_h + gap)
            draw.rounded_rectangle((margin, row_y, width - margin, row_y + step_h),
                                   radius=18, fill=palette["surface"],
                                   outline=palette["border"], width=2)
            badge = min(46, step_h - 24)
            badge_y = row_y + (step_h - badge) // 2
            draw.ellipse((margin + 18, badge_y, margin + 18 + badge, badge_y + badge),
                         fill=palette["primary"])
            draw.text((margin + 18 + badge // 2, badge_y + badge // 2), str(index + 1),
                      font=_font(max(16, badge // 2), True), fill="white", anchor="mm")
            text_x = margin + 18 + badge + 22
            _draw_fitted(draw, (text_x, row_y + 14), item, palette["text"],
                         width - margin - 20 - text_x, step_h - 28,
                         max_size=34, min_size=20, bold=True, max_lines=3, center_vertical=True)
    else:
        raise RenderError("不支持的视频版式")
    image.save(destination, format="PNG", optimize=True)


def _render_scene(scene: dict, width: int, height: int, destination: Path, palette: dict) -> None:
    if height > width:
        _render_portrait_scene(scene, width, height, destination, palette)
        return
    image, draw = _base_canvas(width, height, scene["scene_num"], palette)
    margin = int(width * .075)
    title_size = max(38, int(min(width, height) * .075))
    title_font = _font(title_size, bold=True)
    while title_size > 38 and len(_wrap(draw, scene["title"], title_font, int(width * .78))) > 2:
        title_size -= 1
        title_font = _font(title_size, bold=True)
    body_font = _font(max(24, int(height * .042)))
    item_font = _font(max(22, int(height * .037)), bold=True)
    title_height = _draw_wrapped(draw, (margin, int(height * .13)), scene["title"], title_font,
                                 palette["text"], int(width * .78), spacing=10, max_lines=2,
                                 max_bottom=int(height * .35))
    y = int(height * .13) + title_height + int(height * .055)
    layout = scene["layout"]
    items = scene["items"]

    if layout == "title":
        _draw_wrapped(draw, (margin, y), scene["body"], body_font, palette["muted"],
                      int(width * .72), max_lines=5, max_bottom=int(height * .61))
        if items:
            portrait = height > width
            chip_y = int(height * (.66 if portrait else .64))
            gap = int(height * .012) if portrait else int(width * .018)
            chip_w = width - 2 * margin if portrait else int((width * .82 - (len(items) - 1) * gap) / len(items))
            chip_h = int((height * .22 - (len(items) - 1) * gap) / len(items)) if portrait else int(height * .11)
            for index, item in enumerate(items):
                x = margin if portrait else margin + index * (chip_w + gap)
                row_y = chip_y + index * (chip_h + gap) if portrait else chip_y
                chip_size = min(item_font.size, 36) if portrait else item_font.size
                chip_font = _font(chip_size, bold=True)
                while chip_size > 24 and len(_wrap(draw, item, chip_font, chip_w - 36)) > 2:
                    chip_size -= 1
                    chip_font = _font(chip_size, bold=True)
                draw.rounded_rectangle((x, row_y, x + chip_w, row_y + chip_h),
                                       radius=16, fill=palette["surface"], outline=palette["border"])
                _draw_wrapped(draw, (x + 18, row_y + 12), item, chip_font, palette["primary"],
                              chip_w - 36, spacing=6, max_lines=2, max_bottom=row_y + chip_h - 8)
    elif layout == "comparison":
        if len(items) != 2:
            raise RenderError("对比版式必须包含两个对比项")
        if height > width:
            gap = int(height * .025)
            card_h = int(height * .18)
            card_w = width - 2 * margin
            for index, item in enumerate(items):
                card_y = y + index * (card_h + gap)
                draw.rounded_rectangle((margin, card_y, margin + card_w, card_y + card_h), radius=22,
                                       fill=palette["surface"], outline=palette["border"], width=2)
                draw.rectangle((margin, card_y, margin + 14, card_y + card_h),
                               fill=(palette["primary"] if index == 0 else palette["accent"]))
                _draw_wrapped(draw, (margin + 32, card_y + 28), item, item_font, palette["text"],
                              card_w - 64, max_lines=3, max_bottom=card_y + card_h - 20)
            body_y = y + 2 * (card_h + gap) + int(height * .02)
        else:
            gap = int(width * .035)
            card_w = int((width - 2 * margin - gap) / 2)
            for index, item in enumerate(items):
                x = margin + index * (card_w + gap)
                draw.rounded_rectangle((x, y, x + card_w, int(height * .67)), radius=22,
                                       fill=palette["surface"], outline=palette["border"], width=2)
                draw.rectangle((x, y, x + card_w, y + int(height * .025)),
                               fill=(palette["primary"] if index == 0 else palette["accent"]))
                _draw_wrapped(draw, (x + 28, y + 42), item, item_font, palette["text"],
                              card_w - 56, max_lines=3, max_bottom=int(height * .64))
            body_y = int(height * .71)
        _draw_wrapped(draw, (margin, body_y), scene["body"], body_font, palette["muted"],
                      width - 2 * margin, max_lines=3, max_bottom=int(height * .79))
    elif layout == "process":
        if not 2 <= len(items) <= 5:
            raise RenderError("流程版式必须包含二至五个步骤")
        body_height = _draw_wrapped(draw, (margin, y), scene["body"], body_font, palette["muted"],
                                    width - 2 * margin, max_lines=3, max_bottom=int(height * .48))
        if height > width:
            flow_y = max(y + body_height + int(height * .035), int(height * .42))
            gap = int(height * .012)
            step_h = int((height * .86 - flow_y - gap * (len(items) - 1)) / len(items))
            if step_h < 70:
                raise RenderError("竖版流程项目超过像素容量")
            for index, item in enumerate(items):
                row_y = flow_y + index * (step_h + gap)
                draw.rounded_rectangle((margin, row_y, width - margin, row_y + step_h), radius=18,
                                       fill=palette["surface"], outline=palette["border"], width=2)
                draw.ellipse((margin + 16, row_y + 14, margin + 58, row_y + 56), fill=palette["primary"])
                draw.text((margin + 37, row_y + 19), str(index + 1),
                          font=_font(max(16, height // 50), True), fill="white", anchor="ma")
                _draw_wrapped(draw, (margin + 78, row_y + 18), item, item_font, palette["text"],
                              width - 2 * margin - 98, max_lines=2, max_bottom=row_y + step_h - 12)
        else:
            flow_y = int(height * .62)
            step_w = int((width - 2 * margin - (len(items) - 1) * width * .018) / len(items))
            for index, item in enumerate(items):
                x = margin + index * (step_w + int(width * .018))
                draw.rounded_rectangle((x, flow_y, x + step_w, flow_y + int(height * .13)),
                                       radius=18, fill=palette["surface"], outline=palette["border"], width=2)
                draw.ellipse((x + 16, flow_y + 16, x + 58, flow_y + 58), fill=palette["primary"])
                draw.text((x + 30, flow_y + 21), str(index + 1), font=_font(max(16, height // 38), True),
                          fill="white", anchor="ma")
                _draw_wrapped(draw, (x + 72, flow_y + 18), item, item_font, palette["text"],
                              step_w - 88, max_lines=3, max_bottom=flow_y + int(height * .13) - 10)
    else:
        raise RenderError("不支持的视频版式")
    image.save(destination, format="PNG", optimize=True)


def _vtt_time(seconds: int) -> str:
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.000"


def _write_subtitles(path: Path, scenes: list[dict], narration_captions: bool = False) -> None:
    output = ["WEBVTT", ""]
    cursor = 0
    for scene in scenes:
        end = cursor + scene["duration_sec"]
        text = scene["title"] + "\n" + scene["body"]
        if scene["items"]:
            text += "\n" + "；".join(scene["items"])
        if narration_captions:
            text = scene["narration"]
        output.extend([f"{_vtt_time(cursor)} --> {_vtt_time(end)}", html.escape(text), ""])
        cursor = end
    path.write_text("\n".join(output), encoding="utf-8")


def _limit_ffmpeg():
    if sys.platform != "linux":
        return
    import resource
    resource.setrlimit(resource.RLIMIT_CPU, (180, 180))
    resource.setrlimit(resource.RLIMIT_FSIZE, (256 * 1024 * 1024, 256 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    resource.setrlimit(resource.RLIMIT_NPROC, (32, 32))


def _encode(scene_files: list[Path], scenes: list[dict], output: Path, width: int, height: int) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RenderError("FFmpeg 未安装")
    command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
               "-filter_complex_threads", "1", "-filter_threads", "1"]
    for path, scene in zip(scene_files, scenes):
        command += ["-threads", "1", "-loop", "1", "-framerate", str(FPS), "-t", str(scene["duration_sec"]), "-i", str(path)]
    filters = []
    streams = []
    for index, scene in enumerate(scenes):
        frames = scene["duration_sec"] * FPS
        # The plan cannot provide filters. Every still receives the same restrained zoom.
        filters.append(
            f"[{index}:v]scale={width}:{height},zoompan="
            f"z='1+0.035*on/{max(1, frames - 1)}':x='iw/2-(iw/zoom/2)':"
            f"y='ih/2-(ih/zoom/2)':d=1:s={width}x{height}:fps={FPS},"
            f"trim=duration={scene['duration_sec']},setpts=PTS-STARTPTS[v{index}]"
        )
        streams.append(f"[v{index}]")
    filters.append("".join(streams) + f"concat=n={len(scenes)}:v=1:a=0[outv]")
    command += ["-filter_complex", ";".join(filters), "-map", "[outv]", "-an",
                "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-threads", "2",
                "-pix_fmt", "yuv420p", "-r", str(FPS), "-movflags", "+faststart",
                "-progress", "pipe:1", "-nostats", str(output)]
    total_frames = sum(scene["duration_sec"] for scene in scenes) * FPS
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                               start_new_session=False, preexec_fn=_limit_ffmpeg if os.name == "posix" else None)
    deadline = time.monotonic() + max(120, sum(s["duration_sec"] for s in scenes) * 8)
    last_frame = 0
    try:
        assert process.stdout is not None
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while process.poll() is None:
                if time.monotonic() > deadline:
                    raise TimeoutError("FFmpeg 渲染超时")
                for key_event, _ in selector.select(timeout=1):
                    line = key_event.fileobj.readline()
                    key, _, value = line.strip().partition("=")
                    if key == "frame" and value.isdigit():
                        frame = min(total_frames, int(value))
                        if frame >= last_frame + FPS or frame == total_frames:
                            last_frame = frame
                            print(json.dumps({"type": "progress", "frame": frame,
                                              "total_frames": total_frames,
                                              "pct": round(frame * 100 / total_frames, 1)}), flush=True)
        stderr = process.stderr.read() if process.stderr else ""
        if process.wait(timeout=10) != 0:
            raise RenderError("FFmpeg 编码失败：" + stderr[-800:])
    except BaseException:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        raise


def render_video(job_dir: Path, job_id: str, plan: dict) -> dict:
    raw_job_dir = Path(job_dir)
    if raw_job_dir.is_symlink():
        raise RenderError("渲染目录与任务编号不匹配")
    job_dir = raw_job_dir.resolve()
    if not re.fullmatch(r"video_[a-f0-9]{10}", job_id) or job_dir.name != job_id:
        raise RenderError("渲染目录与任务编号不匹配")
    staging = job_dir / "staging"
    assets = staging / "assets"
    if (not staging.is_dir() or staging.is_symlink() or
            not staging.resolve().is_relative_to(job_dir)):
        raise RenderError("视频暂存目录不安全")
    if assets.exists() and (not assets.is_dir() or assets.is_symlink() or
                            not assets.resolve().is_relative_to(staging.resolve())):
        raise RenderError("视频资源目录不安全")
    frames_dir = staging / ".video-frames"
    assets.mkdir(parents=True, exist_ok=True)
    frames_dir.mkdir(parents=True, exist_ok=False)
    width, height = int(plan["video_width"]), int(plan["video_height"])
    scenes = plan["video_scenes"]
    palette = _trusted_palette(plan)
    if plan.get("fps") != FPS or plan.get("video_audio") is not False:
        raise RenderError("渲染计划必须是 24fps 无音轨")
    scene_files: list[Path] = []
    try:
        for scene in scenes:
            destination = frames_dir / f"scene_{scene['scene_num']:02d}.png"
            _render_scene(scene, width, height, destination, palette)
            scene_files.append(destination)
        shutil.copyfile(scene_files[0], assets / "video_poster.png")
        _write_subtitles(staging / "subtitles.vtt", scenes, plan.get("subtitle_content") == "narration")
        video = staging / f"{job_id}_video.mp4"
        _encode(scene_files, scenes, video, width, height)
        if not video.is_file() or video.stat().st_size == 0:
            raise RenderError("视频编码没有生成有效文件")
        return {"video": video, "poster": assets / "video_poster.png",
                "subtitles": staging / "subtitles.vtt"}
    finally:
        shutil.rmtree(frames_dir, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-dir", required=True)
    parser.add_argument("--job-id", required=True)
    args = parser.parse_args()
    try:
        raw_job_dir = Path(args.job_dir)
        if raw_job_dir.is_symlink():
            raise RenderError("渲染目录与任务编号不匹配")
        job_dir = raw_job_dir.resolve()
        plan_path = job_dir / "validated_video_plan.json"
        if plan_path.is_symlink() or not plan_path.is_file() or not plan_path.resolve().is_relative_to(job_dir):
            raise RenderError("缺少可信的视频计划")
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        render_video(job_dir, args.job_id, plan)
        print(json.dumps({"type": "completed"}), flush=True)
        return 0
    except Exception as exc:
        print(json.dumps({"type": "error", "message": str(exc)}, ensure_ascii=False), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
