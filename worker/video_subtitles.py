"""Trusted FFmpeg subtitle burning for worker-created WebVTT files."""
from __future__ import annotations

import argparse
import html
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


class SubtitleBurnError(RuntimeError):
    pass


_TIMING = re.compile(
    r"^(\d{2}):(\d{2}):(\d{2})\.(\d{3})\s+-->\s+"
    r"(\d{2}):(\d{2}):(\d{2})\.(\d{3})(?:\s+.*)?$"
)


def _has_symlink_component(path: Path) -> bool:
    current = path
    while current != current.parent:
        if current.is_symlink():
            return True
        current = current.parent
    return False


def _require_input(path: Path, label: str) -> Path:
    path = Path(path)
    if not path.is_absolute():
        raise SubtitleBurnError(f"{label}必须使用绝对路径")
    if _has_symlink_component(path) or not path.is_file() or path.stat().st_size == 0:
        raise SubtitleBurnError(f"{label}必须是非空普通文件且不能经过符号链接")
    return path


def _require_destination(path: Path) -> Path:
    path = Path(path)
    if not path.is_absolute():
        raise SubtitleBurnError("字幕视频输出必须使用绝对路径")
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise SubtitleBurnError("字幕视频输出不能是符号链接或非普通文件")
    parent = path.parent
    if not parent.is_dir() or _has_symlink_component(parent):
        raise SubtitleBurnError("字幕视频输出目录必须存在且不能经过符号链接")
    return path


def _ffmpeg_candidates() -> list[Path]:
    values: list[str] = []
    configured = os.environ.get("NBPPT_FFMPEG")
    if configured:
        values.append(configured)
    values.append("/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg")
    discovered = shutil.which("ffmpeg")
    if discovered:
        values.append(discovered)
    result: list[Path] = []
    for value in values:
        candidate = Path(value)
        if candidate.is_absolute() and candidate.is_file() and os.access(candidate, os.X_OK):
            resolved = candidate.resolve()
            if resolved not in result:
                result.append(resolved)
    return result


def _supports_subtitles(ffmpeg: Path) -> bool:
    try:
        result = subprocess.run([str(ffmpeg), "-hide_banner", "-filters"],
                                capture_output=True, text=True, timeout=15, check=True)
    except (OSError, subprocess.SubprocessError):
        return False
    return any(len(parts := line.split()) >= 3 and parts[1:3] == ["subtitles", "V->V"]
               for line in result.stdout.splitlines())


def _find_ffmpeg() -> Path:
    for candidate in _ffmpeg_candidates():
        if _supports_subtitles(candidate):
            return candidate
    raise SubtitleBurnError("可信 FFmpeg 缺少 subtitles/libass 滤镜")


def _find_ffprobe(ffmpeg: Path) -> Path:
    candidates = [ffmpeg.with_name("ffprobe")]
    discovered = shutil.which("ffprobe")
    if discovered:
        candidates.append(Path(discovered))
    for candidate in candidates:
        if candidate.is_absolute() and candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate.resolve()
    raise SubtitleBurnError("缺少用于字幕视频验收的 FFprobe")


def preflight_subtitles() -> str:
    """Verify the configured encoder can burn subtitles without writing files."""
    ffmpeg = _find_ffmpeg()
    _find_ffprobe(ffmpeg)
    return str(ffmpeg)


def _validate_vtt(path: Path) -> None:
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeError as exc:
        raise SubtitleBurnError("字幕文件不是 UTF-8 WebVTT") from exc
    if "\x00" in content or not content.lstrip("\ufeff").startswith("WEBVTT"):
        raise SubtitleBurnError("字幕文件不是有效的 WebVTT")
    if not re.search(r"\d{2}:\d{2}:\d{2}\.\d{3}\s+-->\s+\d{2}:\d{2}:\d{2}\.\d{3}", content):
        raise SubtitleBurnError("WebVTT 没有可烧录的字幕段")


def _milliseconds(groups: tuple[str, ...]) -> int:
    hours, minutes, seconds, millis = (int(value) for value in groups)
    return ((hours * 60 + minutes) * 60 + seconds) * 1000 + millis


def _vtt_timestamp(milliseconds: int) -> str:
    seconds, millis = divmod(milliseconds, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"


def _caption_chunks(text: str, width: int, height: int) -> list[str]:
    # Conservative fixed limits keep libass wrapping within two lines. 9:16
    # gets shorter lines; 16:9 can use the wider caption band.
    per_line = 18 if height > width else 34
    capacity = per_line * 2
    characters = list(text)
    chunks: list[str] = []
    for offset in range(0, len(characters), capacity):
        group = characters[offset:offset + capacity]
        first = "".join(group[:per_line])
        second = "".join(group[per_line:])
        chunks.append(first + ("\n" + second if second else ""))
    return chunks


def _caption_style(width: int, height: int) -> str:
    """Convert desired output pixels to libass' default 288-line script space."""
    target_font_px = 34 if height > width else 30
    target_bottom_px = 28
    font_size = max(6, round(target_font_px * 288 / height))
    margin_v = max(2, round(target_bottom_px * 288 / height))
    return (f"FontName=Noto Sans CJK SC,FontSize={font_size},PrimaryColour=&H00FFFFFF,"
            "OutlineColour=&H90000000,BorderStyle=3,Outline=1,Shadow=0,"
            f"Alignment=2,MarginL=36,MarginR=36,MarginV={margin_v}")


def _prepare_burn_vtt(source: Path, destination: Path, width: int, height: int) -> None:
    """Split cues for a two-line safe band without changing the source VTT."""
    content = source.read_text(encoding="utf-8").lstrip("\ufeff")
    blocks = re.split(r"\n\s*\n", content.strip())
    if not blocks or not blocks[0].startswith("WEBVTT"):
        raise SubtitleBurnError("字幕文件不是有效的 WebVTT")
    output = ["WEBVTT", ""]
    previous_end = 0
    for block in blocks[1:]:
        lines = block.splitlines()
        timing_index = next((index for index, line in enumerate(lines) if "-->" in line), -1)
        if timing_index < 0:
            continue  # NOTE/STYLE metadata does not become visible text.
        match = _TIMING.fullmatch(lines[timing_index].strip())
        if not match:
            raise SubtitleBurnError("WebVTT 字幕时间格式无效")
        start = _milliseconds(match.groups()[:4])
        end = _milliseconds(match.groups()[4:])
        if start < previous_end or end <= start:
            raise SubtitleBurnError("WebVTT 字幕时间重叠或倒序")
        previous_end = end
        raw_text = " ".join(line.strip() for line in lines[timing_index + 1:] if line.strip())
        text = re.sub(r"\s+", " ", html.unescape(raw_text)).strip()
        if not text:
            raise SubtitleBurnError("WebVTT 包含空字幕段")
        chunks = _caption_chunks(text, width, height)
        duration = end - start
        # Twelve visible characters per second plus a minimum dwell time keeps
        # silent-video captions readable. Impossible cues fail instead of being
        # clipped, accelerated, or silently dropped.
        visible_characters = len(re.sub(r"[\s，。；：、！？,.!?;:]", "", text))
        if duration < max(len(chunks) * 800, round(visible_characters / 12 * 1000)):
            raise SubtitleBurnError("字幕内容超过当前时间段的两行可读容量")
        for index, chunk in enumerate(chunks):
            chunk_start = start + round(duration * index / len(chunks))
            chunk_end = start + round(duration * (index + 1) / len(chunks))
            escaped = html.escape(chunk, quote=False)
            output.extend([f"{_vtt_timestamp(chunk_start)} --> {_vtt_timestamp(chunk_end)}",
                           escaped, ""])
    if len(output) == 2:
        raise SubtitleBurnError("WebVTT 没有可烧录的字幕段")
    destination.write_text("\n".join(output), encoding="utf-8")


def _probe_media(ffprobe: Path, path: Path) -> dict:
    result = subprocess.run([str(ffprobe), "-v", "error", "-show_streams", "-show_format",
                             "-of", "json", str(path)], capture_output=True, text=True,
                            timeout=30, check=False)
    if result.returncode != 0:
        raise SubtitleBurnError("字幕视频媒体检查失败：" + result.stderr.strip()[-800:])
    try:
        return json.loads(result.stdout)
    except (TypeError, json.JSONDecodeError) as exc:
        raise SubtitleBurnError("字幕视频媒体检查没有返回有效结果") from exc


def _video_dimensions(media: dict) -> tuple[int, int]:
    try:
        stream = next(value for value in media["streams"] if value.get("codec_type") == "video")
        width, height = int(stream["width"]), int(stream["height"])
    except (KeyError, StopIteration, TypeError, ValueError) as exc:
        raise SubtitleBurnError("源视频缺少可核验的画面尺寸") from exc
    if width <= 0 or height <= 0:
        raise SubtitleBurnError("源视频画面尺寸无效")
    return width, height


def _verify_media_equivalence(ffprobe: Path, source: Path, rendered: Path) -> None:
    before, after = _probe_media(ffprobe, source), _probe_media(ffprobe, rendered)
    before_types = [stream.get("codec_type") for stream in before.get("streams", [])
                    if stream.get("codec_type") in {"video", "audio"}]
    after_types = [stream.get("codec_type") for stream in after.get("streams", [])
                   if stream.get("codec_type") in {"video", "audio"}]
    if not before_types or "video" not in before_types or before_types != after_types:
        raise SubtitleBurnError("字幕烧录前后的音视频流不一致")
    try:
        before_duration = float(before["format"]["duration"])
        after_duration = float(after["format"]["duration"])
    except (KeyError, TypeError, ValueError) as exc:
        raise SubtitleBurnError("字幕烧录前后缺少可核验的媒体时长") from exc
    if before_duration <= 0 or abs(before_duration - after_duration) > max(.1, before_duration * .005):
        raise SubtitleBurnError("字幕烧录前后的媒体时长不一致")


def burn_subtitles(video: Path, subtitles: Path, destination: Path) -> Path:
    """Burn the complete trusted WebVTT into a newly encoded MP4 atomically.

    The inputs and destination must be absolute paths outside symlink trees.  A
    unique working directory prevents a retry from reusing an earlier render;
    the destination is replaced only after a complete decode check succeeds.
    """
    video = _require_input(video, "源视频")
    subtitles = _require_input(subtitles, "字幕文件")
    destination = _require_destination(destination)
    if video.resolve() == destination.resolve() or subtitles.resolve() == destination.resolve():
        raise SubtitleBurnError("字幕输出不能覆盖输入文件")
    _validate_vtt(subtitles)
    ffmpeg = _find_ffmpeg()
    ffprobe = _find_ffprobe(ffmpeg)
    source_media = _probe_media(ffprobe, video)
    width, height = _video_dimensions(source_media)

    with tempfile.TemporaryDirectory(prefix=".subtitle-burn-", dir=destination.parent) as temp_value:
        work = Path(temp_value)
        local_video = work / "source.mp4"
        local_vtt = work / "captions.vtt"
        candidate = work / "rendered.mp4"
        shutil.copyfile(video, local_video)
        _prepare_burn_vtt(subtitles, local_vtt, width, height)
        # The filter receives only a fixed, worker-owned filename. User/content
        # paths never enter the FFmpeg expression or a shell.
        style = _caption_style(width, height)
        command = [str(ffmpeg), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                   "-threads", "2", "-filter_threads", "2", "-filter_complex_threads", "2",
                   "-i", local_video.name, "-vf", f"subtitles={local_vtt.name}:force_style='{style}'",
                   "-map", "0:v:0", "-map", "0:a?", "-map_metadata", "-1",
                   "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                   "-threads", "2", "-pix_fmt", "yuv420p", "-c:a", "copy",
                   "-movflags", "+faststart",
                   candidate.name]
        try:
            result = subprocess.run(command, cwd=work, capture_output=True, text=True,
                                    timeout=300, check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            raise SubtitleBurnError(f"字幕烧录失败：{exc}") from exc
        if result.returncode != 0 or not candidate.is_file() or candidate.stat().st_size == 0:
            detail = result.stderr.strip()[-800:] or "FFmpeg 没有生成有效文件"
            raise SubtitleBurnError("字幕烧录失败：" + detail)
        _verify_media_equivalence(ffprobe, local_video, candidate)
        verify = subprocess.run([str(ffmpeg), "-hide_banner", "-loglevel", "error", "-xerror",
                                 "-nostdin", "-threads", "2", "-i", candidate.name,
                                 "-map", "0:v:0", "-map", "0:a?", "-f", "null", "-"],
                                cwd=work, capture_output=True, text=True, timeout=300, check=False)
        if verify.returncode != 0:
            raise SubtitleBurnError("字幕视频完整解码失败：" + verify.stderr.strip()[-800:])
        os.replace(candidate, destination)
    return destination


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True)
    parser.add_argument("--subtitles", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        output = burn_subtitles(Path(args.video), Path(args.subtitles), Path(args.output))
        print(json.dumps({"type": "completed", "output": str(output)}, ensure_ascii=False), flush=True)
        return 0
    except Exception as exc:
        print(json.dumps({"type": "error", "message": str(exc)}, ensure_ascii=False), flush=True)
        return 1


__all__ = ["SubtitleBurnError", "burn_subtitles", "preflight_subtitles"]


if __name__ == "__main__":
    raise SystemExit(main())
