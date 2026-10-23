import json
import os
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import numpy as np
import pytest

from worker.video_renderer import render_video
from worker.video_speech import SpeechError, synthesize_narration


def plan():
    scenes = [
        {"scene_num": 1, "duration_sec": 3, "title": "现状", "body": "先讲事实",
         "narration": "讲清客户事实", "source_quotes": ["讲清客户事实"],
         "layout": "title", "items": []},
        {"scene_num": 2, "duration_sec": 3, "title": "流程", "body": "再讲行动",
         "narration": "收益仍需验证", "source_quotes": ["收益仍需验证"],
         "layout": "process", "items": ["现状", "行动"]},
    ]
    return {"generation_contract": "skill-video-v1", "original_prompt_cn": "讲清客户事实，收益仍需验证",
            "video_duration_sec": 6, "video_aspect_ratio": "16:9", "video_scenes": scenes,
            "video_width": 1280, "video_height": 720, "fps": 24, "video_audio": False}


class FakeEngine:
    def __init__(self, first_duration=3.0):
        self.first_duration = first_duration
        self.speeds = []

    def generate(self, text, sid, speed):
        self.speeds.append(speed)
        base = self.first_duration if text == "讲清客户事实" else 1.1
        rate = 8000
        return SimpleNamespace(samples=np.zeros(int(base / speed * rate), dtype=np.float32),
                               sample_rate=rate)


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg required")
def test_speech_retries_with_bounded_speed_pads_silence_and_muxes_aac(tmp_path):
    job_id = "video_0000000010"
    job_dir = tmp_path / job_id
    (job_dir / "staging/assets").mkdir(parents=True)
    source_plan = plan()
    render_video(job_dir, job_id, source_plan)
    engine = FakeEngine()
    result = synthesize_narration(job_dir, job_id, source_plan, engine=engine)

    assert 1 < result["scenes"][0]["speed"] <= 1.2
    assert result["scenes"][0]["speech_duration_sec"] < 3
    assert result["total_duration_sec"] == 6
    assert engine.speeds[0] == 1.0 and engine.speeds[1] > 1.0
    captions = (job_dir / "staging/subtitles.vtt").read_text(encoding="utf-8")
    assert "讲清客户事实" in captions and "收益仍需验证" in captions
    assert "00:00:00.000 --> 00:00:03.000" in captions
    assert result["scenes"][0]["caption_duration_sec"] == 3
    assert not (job_dir / "staging/.speech-work").exists()

    probe = subprocess.run([shutil.which("ffprobe"), "-v", "error", "-show_streams",
                            "-show_format", "-of", "json",
                            str(job_dir / f"staging/{job_id}_video.mp4")],
                           capture_output=True, text=True, check=True, timeout=30)
    info = json.loads(probe.stdout)
    assert next(s for s in info["streams"] if s["codec_type"] == "video")["codec_name"] == "h264"
    assert next(s for s in info["streams"] if s["codec_type"] == "audio")["codec_name"] == "aac"
    assert abs(float(info["format"]["duration"]) - 6) <= .05


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg required")
def test_speech_that_does_not_fit_at_1_2_speed_is_rejected_without_truncation(tmp_path):
    job_id = "video_0000000011"
    job_dir = tmp_path / job_id
    (job_dir / "staging/assets").mkdir(parents=True)
    source_plan = plan()
    render_video(job_dir, job_id, source_plan)
    with pytest.raises(SpeechError, match="拒绝截断"):
        synthesize_narration(job_dir, job_id, source_plan, engine=FakeEngine(first_duration=4.0))
    assert not (job_dir / "staging/.speech-work").exists()


@pytest.mark.skipif(not (os.environ.get("NBPPT_TTS_PYTHON") and os.environ.get("NBPPT_TTS_MODEL_DIR")),
                    reason="trusted MeloTTS runtime not configured")
def test_real_melo_runtime_generates_chinese_audio(tmp_path):
    job_id = "video_0000000012"
    job_dir = tmp_path / job_id
    (job_dir / "staging/assets").mkdir(parents=True)
    source_plan = plan()
    # Keep the real smoke text comfortably within each three-second scene.
    source_plan["video_scenes"][0]["narration"] = "讲清事实"
    source_plan["video_scenes"][1]["narration"] = "谨慎验证"
    render_video(job_dir, job_id, source_plan)
    (job_dir / "validated_video_plan.json").write_text(json.dumps(source_plan, ensure_ascii=False), encoding="utf-8")
    env = {"PATH": os.environ.get("PATH", ""), "LANG": "C.UTF-8", "PYTHONUNBUFFERED": "1",
           "NBPPT_TTS_MODEL_DIR": os.environ["NBPPT_TTS_MODEL_DIR"]}
    speech_script = Path(__file__).resolve().parents[1] / "worker/video_speech.py"
    result = subprocess.run([os.environ["NBPPT_TTS_PYTHON"], str(speech_script),
                             "--job-dir", str(job_dir), "--job-id", job_id],
                            env=env, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    metadata = json.loads((job_dir / "speech_result.json").read_text(encoding="utf-8"))
    assert metadata["provider"] == "melo_tts" and len(metadata["scenes"]) == 2
    probe = subprocess.run([shutil.which("ffprobe"), "-v", "error", "-select_streams", "a",
                            "-show_entries", "stream=codec_name", "-of", "json",
                            str(job_dir / f"staging/{job_id}_video.mp4")],
                           capture_output=True, text=True, check=True, timeout=30)
    assert json.loads(probe.stdout)["streams"][0]["codec_name"] == "aac"
