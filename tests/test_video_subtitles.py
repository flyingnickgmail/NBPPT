import json
import shutil
from pathlib import Path
import subprocess
import sys

import pytest
from PIL import Image

from worker import video_subtitles
from worker.video_subtitles import SubtitleBurnError, burn_subtitles


FFMPEG_FULL = Path("/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg")
if not FFMPEG_FULL.is_file():
    FFMPEG_FULL = Path(shutil.which("ffmpeg") or "/missing-ffmpeg")
FFPROBE_FULL = FFMPEG_FULL.with_name("ffprobe")


def _require_full_ffmpeg():
    if not FFMPEG_FULL.is_file() or not FFPROBE_FULL.is_file():
        pytest.skip("ffmpeg-full with libass is required")


def _video(path: Path, duration: float = 2.0, size: str = "720x1280") -> None:
    _require_full_ffmpeg()
    subprocess.run([str(FFMPEG_FULL), "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", f"color=c=0x21435b:s={size}:d={duration}:r=24",
                    "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                    "-shortest", str(path)], check=True, timeout=60)


def _vtt(path: Path, text: str = "完整字幕逐字烧录", end: int = 2) -> str:
    value = ("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\n第一段字幕\n\n"
             f"00:00:01.000 --> 00:00:{end:02d}.000\n{text}\n")
    path.write_text(value, encoding="utf-8")
    return value


def test_fractional_frame_cues_do_not_round_past_the_cut(tmp_path):
    source=tmp_path/'source.vtt';prepared=tmp_path/'burn.vtt'
    original='WEBVTT\n\n00:00:00.000 --> 00:00:09.542\n前段\n\n00:00:09.542 --> 00:00:16.417\n后段\n'
    source.write_text(original)
    video_subtitles._prepare_burn_vtt(source,prepared,1280,720)
    text=prepared.read_text()
    assert '00:00:09.540 --> 00:00:16.410' in text
    assert source.read_text()==original


def test_actual_first_frame_after_fractional_cut_has_the_new_caption(tmp_path,monkeypatch):
    import numpy as np
    source=tmp_path/'source.mp4';captions=tmp_path/'captions.vtt';output=tmp_path/'out.mp4'
    _video(source,duration=4,size='1280x720');monkeypatch.setenv('NBPPT_FFMPEG',str(FFMPEG_FULL))
    # 52/24 is 2.166667; the source VTT's nearest millisecond is 2.167.
    captions.write_text('WEBVTT\n\n00:00:00.000 --> 00:00:02.167\n前\n\n00:00:02.167 --> 00:00:04.000\n后段字幕已经切换\n')
    burn_subtitles(source,captions,output)
    arrays=[]
    for frame in (51,52,53):
        png=tmp_path/f'{frame}.png'
        subprocess.run([str(FFMPEG_FULL),'-v','error','-nostdin','-i',str(output),'-vf',f'select=eq(n\\,{frame})',
            '-frames:v','1',str(png)],check=True,capture_output=True)
        with Image.open(png) as im:arrays.append(np.asarray(im.convert('RGB').crop((100,600,1180,710))).astype(float))
    before,at,after=arrays
    assert np.mean(np.abs(before-at))>2
    assert np.mean(np.abs(at-after))<1


def test_burns_complete_vtt_preserves_streams_and_replaces_stale_output(tmp_path, monkeypatch):
    source = tmp_path / "source.mp4"
    captions = tmp_path / "captions.vtt"
    output = tmp_path / "output.mp4"
    _video(source, duration=4.0)
    _vtt(captions, text="字幕安全区验证" * 4, end=4)
    output.write_bytes(b"stale-cache")
    monkeypatch.setenv("NBPPT_FFMPEG", str(FFMPEG_FULL))

    assert burn_subtitles(source, captions, output) == output
    assert output.read_bytes()[:11] != b"stale-cache"
    probe = subprocess.run([str(FFPROBE_FULL), "-v", "error", "-show_streams",
                            "-show_format", "-of", "json", str(output)],
                           capture_output=True, text=True, check=True, timeout=30)
    info = json.loads(probe.stdout)
    picture = next(stream for stream in info["streams"] if stream["codec_type"] == "video")
    assert (picture["width"], picture["height"]) == (720, 1280)
    assert any(stream["codec_type"] == "audio" for stream in info["streams"])
    assert abs(float(info["format"]["duration"]) - 4.0) < .1

    frame = tmp_path / "caption.png"
    subprocess.run([str(FFMPEG_FULL), "-hide_banner", "-loglevel", "error", "-y",
                    "-ss", "2.5", "-i", str(output), "-frames:v", "1", str(frame)],
                   check=True, timeout=30)
    with Image.open(frame).convert("RGB") as image:
        # Text stays in the reserved lower band instead of becoming a separate
        # stale/translated subtitle asset.
        lower = image.crop((20, 900, 700, 1250))
        colors = lower.getcolors(maxcolors=720 * 1280) or []
        assert any(r > 220 and g > 220 and b > 220 for _, (r, g, b) in colors)
        bright_rows = [y for y in range(image.height) for x in range(20, image.width - 20)
                       if all(channel > 220 for channel in image.getpixel((x, y)))]
        assert bright_rows and min(bright_rows) >= int(image.height * .84)
        assert max(bright_rows) <= image.height - 20
        assert max(bright_rows) - min(bright_rows) >= 35
    assert not list(tmp_path.glob(".subtitle-burn-*"))


@pytest.mark.parametrize("kind", ["relative", "empty", "symlink"])
def test_rejects_unsafe_or_empty_inputs(tmp_path, kind):
    source = tmp_path / "source.mp4"
    captions = tmp_path / "captions.vtt"
    output = tmp_path / "output.mp4"
    source.write_bytes(b"video")
    _vtt(captions)
    if kind == "relative":
        source = Path("source.mp4")
    elif kind == "empty":
        source.write_bytes(b"")
    else:
        target = tmp_path / "real.mp4"
        target.write_bytes(b"video")
        source.unlink()
        source.symlink_to(target)
    with pytest.raises(SubtitleBurnError):
        burn_subtitles(source, captions, output)


def test_missing_subtitles_filter_fails_before_output(tmp_path, monkeypatch):
    source = tmp_path / "source.mp4"
    captions = tmp_path / "captions.vtt"
    output = tmp_path / "output.mp4"
    source.write_bytes(b"video")
    _vtt(captions)
    monkeypatch.setattr(video_subtitles, "_supports_subtitles", lambda _: False)
    with pytest.raises(SubtitleBurnError, match="subtitles/libass"):
        burn_subtitles(source, captions, output)
    assert not output.exists()


def test_malformed_video_cannot_replace_previous_output(tmp_path, monkeypatch):
    _require_full_ffmpeg()
    source = tmp_path / "malformed.mp4"
    captions = tmp_path / "captions.vtt"
    output = tmp_path / "output.mp4"
    source.write_bytes(b"not-a-video")
    _vtt(captions)
    output.write_bytes(b"previous-good-result")
    monkeypatch.setenv("NBPPT_FFMPEG", str(FFMPEG_FULL))
    with pytest.raises(SubtitleBurnError, match="媒体检查失败|字幕烧录失败"):
        burn_subtitles(source, captions, output)
    assert output.read_bytes() == b"previous-good-result"
    assert not list(tmp_path.glob(".subtitle-burn-*"))


def test_media_verification_rejects_shortened_render(tmp_path):
    _require_full_ffmpeg()
    source = tmp_path / "source.mp4"
    shortened = tmp_path / "shortened.mp4"
    _video(source, duration=2.0)
    _video(shortened, duration=1.0)
    with pytest.raises(SubtitleBurnError, match="时长不一致"):
        video_subtitles._verify_media_equivalence(FFPROBE_FULL, source, shortened)


def test_long_cue_is_split_into_two_line_timed_segments_without_loss(tmp_path):
    source = tmp_path / "source.vtt"
    prepared = tmp_path / "prepared.vtt"
    text = "完整字幕必须逐字烧录，不调用翻译，也不能因为内容较长而静默截断。" * 3
    source.write_text(f"WEBVTT\n\n00:00:00.000 --> 00:00:12.000\n{text}\n", encoding="utf-8")
    video_subtitles._prepare_burn_vtt(source, prepared, 720, 1280)
    result = prepared.read_text(encoding="utf-8")
    cue_blocks = [block for block in result.split("\n\n") if "-->" in block]
    assert len(cue_blocks) >= 2
    assert all(len(block.splitlines()[1:]) <= 2 for block in cue_blocks)
    reconstructed = "".join("".join(block.splitlines()[1:]) for block in cue_blocks)
    assert reconstructed == text


def test_landscape_caption_does_not_strand_closing_punctuation():
    text='回到开头：找回包裹还不够，让一次判断留下可追溯的依据，才是要解决的事。'
    chunks=video_subtitles._caption_chunks(text,1280,720)
    lines=chunks[0].splitlines()
    assert ''.join(lines)==text
    assert len(lines)==2 and all(2<=len(line)<=34 for line in lines)
    assert all(line[0] not in '，。；：、！？' for line in lines)


def test_landscape_two_line_caption_stays_below_safe_rule(tmp_path, monkeypatch):
    source = tmp_path / "source.mp4"
    captions = tmp_path / "captions.vtt"
    output = tmp_path / "output.mp4"
    frame = tmp_path / "frame.png"
    _video(source, duration=4.0, size="1280x720")
    _vtt(captions, text="横屏字幕安全区" * 5, end=4)
    monkeypatch.setenv("NBPPT_FFMPEG", str(FFMPEG_FULL))
    burn_subtitles(source, captions, output)
    subprocess.run([str(FFMPEG_FULL), "-hide_banner", "-loglevel", "error", "-y",
                    "-ss", "2.5", "-i", str(output), "-frames:v", "1", str(frame)],
                   check=True, timeout=30)
    with Image.open(frame).convert("RGB") as image:
        bright_rows = [y for y in range(image.height) for x in range(20, image.width - 20)
                       if all(channel > 220 for channel in image.getpixel((x, y)))]
        assert bright_rows and min(bright_rows) >= int(image.height * .84)
        assert max(bright_rows) <= image.height - 20
        assert max(bright_rows) - min(bright_rows) >= 35


def test_unreadable_long_cue_fails_instead_of_clipping(tmp_path):
    source = tmp_path / "source.vtt"
    prepared = tmp_path / "prepared.vtt"
    source.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\n" + "内容" * 50 + "\n",
                      encoding="utf-8")
    with pytest.raises(SubtitleBurnError, match="两行可读容量"):
        video_subtitles._prepare_burn_vtt(source, prepared, 720, 1280)
    assert not prepared.exists()


def test_rejects_symlink_destination(tmp_path):
    source = tmp_path / "source.mp4"
    captions = tmp_path / "captions.vtt"
    target = tmp_path / "target.mp4"
    destination = tmp_path / "output.mp4"
    source.write_bytes(b"video")
    _vtt(captions)
    target.write_bytes(b"preserve")
    destination.symlink_to(target)
    with pytest.raises(SubtitleBurnError, match="输出不能"):
        burn_subtitles(source, captions, destination)
    assert target.read_bytes() == b"preserve"


def test_cli_reports_structured_error_and_nonzero_exit(tmp_path):
    captions = tmp_path / "captions.vtt"
    _vtt(captions)
    result = subprocess.run([sys.executable, str(Path(video_subtitles.__file__).resolve()),
                             "--video", str(tmp_path / "missing.mp4"),
                             "--subtitles", str(captions),
                             "--output", str(tmp_path / "output.mp4")],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode != 0
    assert json.loads(result.stdout)["type"] == "error"



@pytest.mark.parametrize("flags", ["..", "...", "T.."])
def test_filter_detection_accepts_platform_flag_columns(monkeypatch, flags):
    monkeypatch.setattr(video_subtitles.subprocess, "run", lambda *a, **k:
                        subprocess.CompletedProcess(a, 0, f" {flags} subtitles V->V Render text subtitles\n"))
    assert video_subtitles._supports_subtitles(Path("/usr/bin/ffmpeg"))


def test_filter_detection_does_not_match_description_only(monkeypatch):
    monkeypatch.setattr(video_subtitles.subprocess, "run", lambda *a, **k:
                        subprocess.CompletedProcess(a, 0, " ... drawtext V->V subtitles V->V\n"))
    assert not video_subtitles._supports_subtitles(Path("/usr/bin/ffmpeg"))
