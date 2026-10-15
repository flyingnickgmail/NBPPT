"""Deterministic delivery gate shared by the worker and settlement boundary.

This checks files, not the truth of slide content. Published output is immutable.
"""
import hashlib
import json
import pathlib
import re
import subprocess
import zipfile
import base64
from html.parser import HTMLParser

from PIL import Image
from pptx import Presentation


class DeliveryError(ValueError):
    pass


def safe_job_id(job_id: str) -> str:
    if not re.fullmatch(r"(?:ppt|video|composite)_[a-f0-9]{10}", job_id):
        raise DeliveryError("Invalid job identifier")
    return job_id


def contained_file(root: pathlib.Path, relative: str) -> pathlib.Path:
    root = root.resolve()
    path = root / relative
    if path.is_symlink() or not path.resolve().is_relative_to(root) or not path.is_file():
        raise DeliveryError("Missing or unsafe artifact")
    if path.stat().st_size == 0:
        raise DeliveryError("Empty artifact")
    return path


class ImageReferences(HTMLParser):
    def __init__(self):
        super().__init__()
        self.sources = []

    def handle_starttag(self, tag, attrs):
        if tag == "img":
            self.sources.append(dict(attrs).get("src", ""))


def inspect_delivery(job_id: str, task_type: str, spec: dict, root: pathlib.Path) -> dict:
    root = root.resolve()
    safe_job_id(job_id)
    if task_type not in ("ppt", "video", "composite"):
        raise DeliveryError("Unsupported task type")
    files = []
    count = 0
    if task_type in ("ppt", "composite"):
        count = len(spec.get("slide_outline", []))
        if count < 1 or spec.get("slide_count") != count:
            raise DeliveryError("Invalid planned slide count")
        requested = spec.get("requested_slide_count", 0)
        if requested > 0 and requested != count:
            raise DeliveryError("Fixed slide count was not satisfied")
        deck = contained_file(root, f"{job_id}_deck.pptx")
        try:
            with zipfile.ZipFile(deck) as archive:
                if archive.testzip() is not None:
                    raise DeliveryError("PPTX archive integrity failure")
            prs = Presentation(deck)
            if len(prs.slides) != count:
                raise DeliveryError("PPTX page count mismatch")
            if abs(prs.slide_width / prs.slide_height - 16 / 9) > 0.01:
                raise DeliveryError("PPTX must be widescreen")
        except Exception as exc:
            raise DeliveryError("Invalid PPTX or page count/aspect ratio") from exc
        expected = [f"assets/slide_preview_{i}.png" for i in range(1, count + 1)]
        found = {p.relative_to(root).as_posix() for p in (root / "assets").glob("slide_preview_*.png")}
        if found != set(expected):
            raise DeliveryError("Preview page count or numbering mismatch")
        for name in expected:
            path = contained_file(root, name)
            try:
                with Image.open(path) as im:
                    im.load()
                    if im.format != "PNG" or im.size != (1672, 941):
                        raise DeliveryError("Preview must be a 1672x941 PNG")
            except Exception as exc:
                raise DeliveryError("Invalid preview image or resolution") from exc
            files.append(path)
        html = contained_file(root, f"{job_id}_deck_interactive.html")
        refs = ImageReferences()
        refs.feed(html.read_text(encoding="utf-8"))
        embedded = ["data:image/png;base64," + base64.b64encode((root / name).read_bytes()).decode("ascii") for name in expected]
        if refs.sources != expected and refs.sources != embedded:
            raise DeliveryError("HTML must reference every preview in page order")
        files.extend([deck, html])
    if task_type in ("video", "composite"):
        video = contained_file(root, f"{job_id}_video.mp4")
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(video)],
                capture_output=True, timeout=30, check=True,
            )
            info = json.loads(result.stdout)
            duration = float(info["format"]["duration"])
            streams = [s for s in info["streams"] if s.get("codec_type") == "video" and s.get("width", 0) > 0 and s.get("height", 0) > 0]
            if duration <= 0 or not streams:
                raise ValueError("No video stream")
            expected_duration = spec.get("video_duration_sec")
            if expected_duration and abs(duration - float(expected_duration)) > 0.5:
                raise ValueError("Video duration mismatch")
            ratio = spec.get("video_aspect_ratio")
            if ratio in ("16:9", "9:16"):
                width, height = map(int, ratio.split(":"))
                if abs(streams[0]["width"] / streams[0]["height"] - width / height) > 0.02:
                    raise ValueError("Video aspect ratio mismatch")
        except Exception as exc:
            raise DeliveryError("Video cannot be validated; ffprobe and valid media are required") from exc
        files.append(video)
    return {
        "version": 1, "job_id": job_id, "task_type": task_type,
        "planned_slides": count, "file_status": "PASSED", "content_status": "NOT_REVIEWED",
        "files": [
            {"path": p.relative_to(root).as_posix(), "size": p.stat().st_size,
             "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
            for p in sorted(files)
        ],
    }


def verify_published(job_id: str, task_type: str, spec: dict, root: pathlib.Path) -> dict:
    manifest = json.loads(contained_file(root, "delivery.json").read_text())
    actual = inspect_delivery(job_id, task_type, spec, root)
    if manifest != actual:
        raise DeliveryError("Published delivery differs from verified manifest")
    return actual


def delivery_urls(job_id: str, manifest: dict) -> dict:
    base = f"/artifacts/{job_id}/"
    paths = [f["path"] for f in manifest["files"]]
    return {
        "pptx_url": next((base + p for p in paths if p.endswith(".pptx")), None),
        "html_deck_url": next((base + p for p in paths if p.endswith(".html")), None),
        "mp4_url": next((base + p for p in paths if p.endswith(".mp4")), None),
        "slide_preview_urls": [base + f"assets/slide_preview_{i}.png" for i in range(1, manifest["planned_slides"] + 1)],
        "chart_urls": [], "keyframe_urls": [],
    }
