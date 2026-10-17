import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest
from PIL import Image

from worker import video_generation as video
from worker.video_renderer import render_video


SOURCE = "客户需要把事实讲清楚。先解释现状，再对比方案，最后给出实施流程。项目分为3步，但收益仍需验证。"


def spec(duration=6, ratio="16:9"):
    return {"generation_contract": "skill-video-v1", "original_prompt_cn": SOURCE,
            "video_duration_sec": duration, "video_aspect_ratio": ratio,
            "matched_template": {"id": "yonyou-ci-bg"}, "planner_provider": "codex_cli",
            "video_narration": False}


def plan():
    return {"task_summary_cn": "把事实讲清楚", "scenes": [
        {"scene_num": 1, "duration_sec": 3, "title": "先解释现状",
         "body": "客户需要把事实讲清楚。", "narration": "讲清客户事实",
         "source_quotes": ["客户需要把事实讲清楚。"],
         "layout": "title", "items": ["事实", "边界"]},
        {"scene_num": 2, "duration_sec": 3, "title": "再给出实施流程",
         "body": "收益仍需验证。", "narration": "收益仍需验证",
         "source_quotes": ["最后给出实施流程。", "收益仍需验证。"],
         "layout": "process", "items": ["现状", "方案", "流程"]},
    ]}


def actual_plan(ratio="16:9"):
    source_spec = spec(ratio=ratio)
    scenes = video.validate_video_plan(plan(), source_spec)
    width, height = ((1280, 720) if ratio == "16:9" else (720, 1280))
    return {**source_spec, "task_summary_cn": "把事实讲清楚", "video_scenes": scenes,
            "video_width": width, "video_height": height, "fps": 24, "video_audio": False}


def test_prompt_limits_agent_to_source_plan_only():
    prompt = video.build_video_prompt(spec())
    assert "source.md IN FULL" in prompt
    assert "Write ONLY video_plan.json" in prompt
    assert "Do not create scripts, images, audio, subtitles or video" in prompt
    assert "Exactly 6" not in prompt  # no fabricated slide/page request
    assert "12-18%" not in prompt and "ROI" in prompt  # prohibition, not default copy


@pytest.mark.parametrize("mutation", [
    "made_up_quote", "duplicate", "too_long", "bad_duration", "path_field",
    "made_up_number", "bad_layout", "too_short_scene", "subtitle_injection", "control_character",
    "duplicate_narration",
])
def test_invalid_plans_are_rejected(mutation):
    value = plan()
    scenes = value["scenes"]
    if mutation == "made_up_quote":
        scenes[0]["source_quotes"] = ["不存在的证据"]
    elif mutation == "duplicate":
        scenes[1]["title"] = scenes[0]["title"]
    elif mutation == "too_long":
        scenes[0]["body"] = "内容" * 81
    elif mutation == "bad_duration":
        scenes[1]["duration_sec"] = 4
    elif mutation == "path_field":
        scenes[0]["background_path"] = "/etc/passwd"
    elif mutation == "made_up_number":
        scenes[0]["body"] = "收益提升50%"
    elif mutation == "bad_layout":
        scenes[0]["layout"] = "custom-html"
    elif mutation == "too_short_scene":
        scenes[0]["duration_sec"], scenes[1]["duration_sec"] = 2, 4
    elif mutation == "subtitle_injection":
        scenes[0]["narration"] = "<b>伪造字幕</b>"
    elif mutation == "control_character":
        scenes[0]["title"] = "伪造\n新提示"
    elif mutation == "duplicate_narration":
        scenes[1]["narration"] = scenes[0]["narration"]
    with pytest.raises((ValueError, RuntimeError)):
        video.validate_video_plan(value, spec())


def test_spec_rejects_unverified_claude_without_fallback():
    value = spec()
    value["planner_provider"] = "claude_cli"
    with pytest.raises(RuntimeError, match="不会回退"):
        video.validate_video_spec(value)


@pytest.mark.parametrize(("source_number", "invented_number"), [("150%", "50%"), ("2026", "20"), ("-20", "20")])
def test_numeric_evidence_requires_exact_tokens_not_substrings(source_number, invented_number):
    value = plan()
    value["scenes"][0]["body"] = f"指标是{invented_number}"
    source_spec = spec()
    source_spec["original_prompt_cn"] += f" 原文数字是{source_number}。"
    with pytest.raises(ValueError, match="原文没有的数字"):
        video.validate_video_plan(value, source_spec)


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg required")
@pytest.mark.parametrize(("ratio", "expected_size"), [("16:9", (1280, 720)), ("9:16", (720, 1280))])
def test_trusted_renderer_produces_decodable_h264_video_poster_and_exact_subtitles(tmp_path, ratio, expected_size):
    job_id = "video_0000000001"
    job_dir = tmp_path / job_id
    (job_dir / "staging/assets").mkdir(parents=True)
    artifacts = render_video(job_dir, job_id, actual_plan(ratio))
    assert artifacts["poster"].is_file() and artifacts["subtitles"].is_file()
    subtitles = artifacts["subtitles"].read_text(encoding="utf-8")
    assert "00:00:00.000 --> 00:00:03.000" in subtitles
    assert "00:00:03.000 --> 00:00:06.000" in subtitles
    assert "先解释现状" in subtitles and "收益仍需验证" in subtitles

    probe = subprocess.run([shutil.which("ffprobe"), "-v", "error", "-show_streams",
                            "-show_format", "-of", "json", str(artifacts["video"])],
                           capture_output=True, text=True, check=True, timeout=30)
    info = json.loads(probe.stdout)
    streams = info["streams"]
    picture = next(item for item in streams if item["codec_type"] == "video")
    assert picture["codec_name"] == "h264"
    assert (picture["width"], picture["height"]) == expected_size
    assert picture["pix_fmt"] == "yuv420p" and picture["avg_frame_rate"] == "24/1"
    assert not [item for item in streams if item["codec_type"] == "audio"]
    assert abs(float(info["format"]["duration"]) - 6) <= .1
    subprocess.run([shutil.which("ffmpeg"), "-v", "error", "-i", str(artifacts["video"]),
                    "-f", "null", "-"], capture_output=True, check=True, timeout=60)
    assert not (job_dir / "staging/.video-frames").exists()


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg required")
def test_renderer_uses_trusted_template_palette_and_portrait_vertical_process(tmp_path):
    job_id = "video_0000000006"
    job_dir = tmp_path / job_id
    (job_dir / "staging/assets").mkdir(parents=True)
    value = actual_plan("9:16")
    value["matched_template"] = {"template": {"id": "customer",
        "palette": {"bg": "#112233", "surface": "#EDEDED", "border": "#778899",
                    "primary": "#336699", "accent": "#CC6633", "text": "#101820",
                    "muted": "#556677", "is_light": False}}, "match_mode": "selected"}
    value["video_scenes"][1]["items"] = ["确认现状", "比较方案", "明确责任", "推进实施", "复盘结果"]
    artifacts = render_video(job_dir, job_id, value)
    with Image.open(artifacts["poster"]) as poster:
        assert poster.getpixel((10, 100)) == (17, 34, 51)
    value["video_scenes"][1]["layout"] = "comparison"
    value["video_scenes"][1]["items"] = ["当前方案需要验证", "备选方案保留边界"]
    render_video(job_dir, job_id, value)


def test_renderer_rejects_non_hex_template_palette(tmp_path):
    job_id = "video_0000000007"
    job_dir = tmp_path / job_id
    (job_dir / "staging/assets").mkdir(parents=True)
    value = actual_plan()
    value["matched_template"] = {"template": {"palette": {"bg": "url(file:///etc/passwd)"}}}
    with pytest.raises(Exception, match="#RRGGBB"):
        render_video(job_dir, job_id, value)


def test_package_preserves_source_and_reserves_narration_metadata(tmp_path):
    job_id = "video_0000000002"
    job_dir = tmp_path / job_id
    job_dir.mkdir()
    (job_dir / "video_plan.json").write_text(json.dumps(plan(), ensure_ascii=False), encoding="utf-8")
    value = spec()
    value["video_narration"] = True
    compiled, qa = video.package_video(job_id, job_dir, value)
    assert compiled["original_prompt_cn"] == SOURCE
    assert compiled["video_audio"] is False
    assert compiled["narration"] == {"requested": True, "status": "pending",
                                      "provider": "melo_tts", "script_source": "video_scenes",
                                      "audio_track": None}
    assert qa["status"] == "PLAN_VALIDATED"


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg required")
def test_stream_runs_planner_renderer_delivery_gate_and_atomic_publish(tmp_path):
    planner = tmp_path / "planner.py"
    planner.write_text("""#!/usr/bin/env python3
import json
from pathlib import Path
plan = {\"task_summary_cn\":\"把事实讲清楚\",\"scenes\":[
{\"scene_num\":1,\"duration_sec\":3,\"title\":\"先解释现状\",\"body\":\"客户需要把事实讲清楚。\",\"narration\":\"讲清客户事实\",\"source_quotes\":[\"客户需要把事实讲清楚。\"],\"layout\":\"title\",\"items\":[\"事实\"]},
{\"scene_num\":2,\"duration_sec\":3,\"title\":\"再给出实施流程\",\"body\":\"收益仍需验证。\",\"narration\":\"收益仍需验证\",\"source_quotes\":[\"收益仍需验证。\"],\"layout\":\"process\",\"items\":[\"现状\",\"流程\"]}]}
Path('video_plan.json').write_text(json.dumps(plan, ensure_ascii=False))
""", encoding="utf-8")
    planner.chmod(0o755)

    async def scenario():
        req = SimpleNamespace(job_id="video_0000000004", english_spec=spec(), runtime_keys={})
        semaphore = asyncio.Semaphore(1)
        events = []
        locked_after_planning = False
        async for value in video.generate_video_stream(req, tmp_path, str(planner), semaphore):
            parsed = json.loads(value[6:])
            events.append(parsed)
            if parsed["type"] in {"completed", "error"}:
                assert not semaphore.locked()
            if parsed.get("pct") == 50:
                locked_after_planning = semaphore.locked()
        return events, locked_after_planning, semaphore.locked()

    events, locked_after_planning, locked_after_finish = asyncio.run(scenario())
    assert events[-1]["type"] == "completed"
    assert any(item["type"] == "progress" and item["pct"] == 92 for item in events)
    assert events[-1]["compiled_spec"]["video_audio"] is False
    assert locked_after_planning is True and locked_after_finish is False
    assert events[-1]["cdn_urls"]["mp4_url"].endswith("video_0000000004_video.mp4")
    output = tmp_path / "video_0000000004/output"
    assert (output / "video_0000000004_video.mp4").is_file()
    assert (output / "assets/video_poster.png").is_file()
    assert (output / "subtitles.vtt").is_file()
    assert not (tmp_path / "video_0000000004/staging").exists()


@pytest.mark.skipif(not (os.environ.get("NBPPT_TTS_PYTHON") and os.environ.get("NBPPT_TTS_MODEL_DIR")),
                    reason="trusted MeloTTS runtime not configured")
def test_stream_with_real_melo_tts_passes_delivery_gate(tmp_path):
    planner = tmp_path / "planner.py"
    planner.write_text("""#!/usr/bin/env python3
import json
from pathlib import Path
plan = {\"task_summary_cn\":\"把事实讲清楚\",\"scenes\":[
{\"scene_num\":1,\"duration_sec\":3,\"title\":\"先解释现状\",\"body\":\"客户需要把事实讲清楚。\",\"narration\":\"讲清事实\",\"source_quotes\":[\"客户需要把事实讲清楚。\"],\"layout\":\"title\",\"items\":[\"事实\"]},
{\"scene_num\":2,\"duration_sec\":3,\"title\":\"再给出实施流程\",\"body\":\"收益仍需验证。\",\"narration\":\"谨慎验证\",\"source_quotes\":[\"收益仍需验证。\"],\"layout\":\"process\",\"items\":[\"现状\",\"流程\"]}]}
Path('video_plan.json').write_text(json.dumps(plan, ensure_ascii=False))
""", encoding="utf-8")
    planner.chmod(0o755)

    async def scenario():
        request_spec = spec()
        request_spec["video_narration"] = True
        req = SimpleNamespace(job_id="video_0000000005", english_spec=request_spec, runtime_keys={})
        return [json.loads(value[6:]) async for value in
                video.generate_video_stream(req, tmp_path, str(planner), asyncio.Semaphore(1))]

    events = asyncio.run(scenario())
    assert events[-1]["type"] == "completed", events[-1]
    assert events[-1]["compiled_spec"]["video_audio"] is True
    assert events[-1]["compiled_spec"]["narration"]["provider"] == "melo_tts"
    assert events[-1]["cdn_urls"]["video_poster_url"]
    assert events[-1]["cdn_urls"]["subtitles_url"]


def test_cancelled_stream_kills_trusted_renderer_process_group(tmp_path, monkeypatch):
    planner = tmp_path / "planner.py"
    planner.write_text("""#!/usr/bin/env python3
import json
from pathlib import Path
plan = {\"task_summary_cn\":\"把事实讲清楚\",\"scenes\":[
{\"scene_num\":1,\"duration_sec\":3,\"title\":\"先解释现状\",\"body\":\"客户需要把事实讲清楚。\",\"narration\":\"讲清客户事实\",\"source_quotes\":[\"客户需要把事实讲清楚。\"],\"layout\":\"title\",\"items\":[]},
{\"scene_num\":2,\"duration_sec\":3,\"title\":\"再给出实施流程\",\"body\":\"收益仍需验证。\",\"narration\":\"收益仍需验证\",\"source_quotes\":[\"收益仍需验证。\"],\"layout\":\"process\",\"items\":[\"现状\",\"流程\"]}]}
Path('video_plan.json').write_text(json.dumps(plan, ensure_ascii=False))
""", encoding="utf-8")
    planner.chmod(0o755)
    fake_renderer = tmp_path / "renderer.py"
    fake_renderer.write_text("""import os, pathlib, sys, time
pathlib.Path(sys.argv[2], 'renderer.pid').write_text(str(os.getpid()))
time.sleep(120)
""", encoding="utf-8")
    monkeypatch.setattr(video, "RENDERER", fake_renderer)

    async def scenario():
        req = SimpleNamespace(job_id="video_0000000003", english_spec=spec(), runtime_keys={})
        stream = video.generate_video_stream(req, tmp_path, str(planner), asyncio.Semaphore(1))
        while True:
            event = json.loads((await stream.__anext__())[6:])
            if event.get("pct") == 50:
                break
        pending = asyncio.create_task(stream.__anext__())
        pid_file = tmp_path / req.job_id / "renderer.pid"
        for _ in range(100):
            if pid_file.exists():
                break
            await asyncio.sleep(.02)
        assert pid_file.exists()
        pid = int(pid_file.read_text())
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        await stream.aclose()
        for _ in range(100):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            await asyncio.sleep(.02)
        pytest.fail("renderer process survived cancellation")

    asyncio.run(scenario())


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg required")
def test_ten_scene_encoding_with_bounded_threads(tmp_path):
    """Exercise the maximum input count under the Linux encoder process limit."""
    from worker.video_renderer import _encode
    frame = tmp_path / "frame.png"
    Image.new("RGB", (1280, 720), "white").save(frame)
    output = tmp_path / "ten-scenes.mp4"
    _encode([frame] * 10, [{"duration_sec": 3}] * 10, output, 1280, 720)
    probe = subprocess.run([shutil.which("ffprobe"), "-v", "error", "-show_entries",
        "format=duration", "-of", "default=nw=1:nk=1", str(output)],
        check=True, capture_output=True, text=True, timeout=30)
    assert abs(float(probe.stdout) - 30) < .05


def test_failure_releases_queue_before_terminal_event(tmp_path, monkeypatch):
    monkeypatch.setattr(video, "_planner_command", lambda *args: ["/bin/false"])
    async def scenario():
        semaphore = asyncio.Semaphore(1)
        req = SimpleNamespace(job_id="video_0000000099", english_spec=spec(), runtime_keys={})
        stream = video.generate_video_stream(req, tmp_path, "/bin/false", semaphore)
        async for value in stream:
            if json.loads(value[6:])["type"] == "error":
                assert not semaphore.locked()
                await asyncio.wait_for(semaphore.acquire(), .1)
                semaphore.release()
                break
        await stream.aclose()
    asyncio.run(scenario())


def test_portrait_title_uses_width_and_preserves_long_text(tmp_path):
    from worker.video_renderer import _render_scene, DEFAULT_PALETTE
    scene = {"scene_num": 1, "title": "失败可重试，已经完成的成果继续保留并供下载", "body": "成果继续保留。",
             "layout": "comparison", "items": ["生成失败：单独重试", "已完成：继续保留"]}
    destination = tmp_path / "portrait.png"
    _render_scene(scene, 720, 1280, destination, DEFAULT_PALETTE)
    assert Image.open(destination).size == (720, 1280)


def test_portrait_title_chips_stack_three_items_without_clipping(tmp_path):
    from worker.video_renderer import _render_scene, DEFAULT_PALETTE
    scene = {"scene_num": 2, "title": "查看进度，预览下载", "body": "查看生成进度，预览并下载成果。",
             "layout": "title", "items": ["查看进度", "预览", "下载"]}
    destination = tmp_path / "portrait-chips.png"
    _render_scene(scene, 720, 1280, destination, DEFAULT_PALETTE)
    assert Image.open(destination).size == (720, 1280)
