import json
from pathlib import Path
import shutil
import subprocess

import pytest
from PIL import Image

from worker.video_renderer import DEFAULT_PALETTE, _render_scene, render_video


def _scene(layout: str) -> dict:
    common = {"scene_num": 1, "title": "把复杂业务讲清楚，并让每一步都能执行",
              "body": "面向汇报和产品讲解场景，画面需要保留完整事实、关键边界与执行说明。" * 3,
              "layout": layout}
    if layout == "title":
        common["items"] = ["事实完整呈现", "选择有明确依据", "下一步可以直接执行"]
    elif layout == "comparison":
        common["items"] = ["当前方案：信息分散，决策者需要来回查找证据" * 2,
                           "优化方案：结论、依据和动作在同一画面完成闭环" * 2]
    else:
        common["items"] = ["确认现状和目标", "比较方案与边界", "明确责任人", "执行并复盘结果", "沉淀后续动作"]
    return common


@pytest.mark.parametrize("layout", ["title", "comparison", "process"])
def test_portrait_layouts_preserve_long_text_and_caption_safe_zone(tmp_path, layout):
    destination = tmp_path / f"{layout}.png"
    _render_scene(_scene(layout), 720, 1280, destination, DEFAULT_PALETTE)
    with Image.open(destination).convert("RGB") as image:
        assert image.size == (720, 1280)
        # A native portrait frame fills both side edges; it is not a scaled
        # landscape image with black bars.
        assert image.getpixel((1, 640)) == (245, 247, 248)
        assert image.getpixel((718, 640)) == (245, 247, 248)
        # Below the divider is a clean, deterministic subtitle band.
        color_counts = image.crop((0, 1085, 720, 1279)).getcolors(maxcolors=720 * 1280)
        colors = {color for _, color in (color_counts or [])}
        assert colors == {(245, 247, 248)}


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
                    reason="FFmpeg required")
def test_encoded_portrait_is_native_9_by_16_without_letterbox(tmp_path):
    job_id = "video_1111111111"
    job_dir = tmp_path / job_id
    (job_dir / "staging/assets").mkdir(parents=True)
    scene = _scene("process")
    scene["duration_sec"] = 3
    plan = {"video_width": 720, "video_height": 1280, "fps": 24,
            "video_audio": False, "video_scenes": [scene], "matched_template": {}}
    artifacts = render_video(job_dir, job_id, plan)
    probe = subprocess.run([shutil.which("ffprobe"), "-v", "error", "-show_streams",
                            "-of", "json", str(artifacts["video"])],
                           capture_output=True, text=True, check=True, timeout=30)
    stream = next(value for value in json.loads(probe.stdout)["streams"]
                  if value["codec_type"] == "video")
    assert (stream["width"], stream["height"]) == (720, 1280)
    frame = tmp_path / "encoded.png"
    subprocess.run([shutil.which("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
                    "-i", str(artifacts["video"]), "-frames:v", "1", str(frame)],
                   check=True, timeout=30)
    with Image.open(frame).convert("RGB") as image:
        for point in ((1, 640), (718, 640), (1, 1180), (718, 1180)):
            assert max(image.getpixel(point)) > 200
