"""Worker-owned footage catalog. Planner selects IDs, never files or network URLs."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def probe(path: Path) -> dict:
    result = subprocess.run(["ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe", "-show_streams", "-show_format",
                             "-of", "json", str(path)], capture_output=True, timeout=30, check=True)
    return json.loads(result.stdout)


def safe_file(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not re.fullmatch(r"[A-Za-z0-9_-]+\.(?:mp4|webm|ogv)", relative):
        raise ValueError("素材文件名不安全")
    path = root / relative
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root):
        raise ValueError("实景素材文件缺失或不安全")
    return path


def load_catalog(source: str, configured: str | None = None) -> dict:
    configured = os.getenv("NBPPT_SCENE_CATALOG", "") if configured is None else configured
    path = Path(configured)
    if not configured or not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise RuntimeError("未配置实景素材库，不能用静态画面代替")
    if path.stat().st_size > 1024 * 1024:
        raise ValueError("实景素材库元数据过大")
    root = path.parent.resolve()
    raw = json.loads(path.read_text())
    if raw.get("version") != 1 or not isinstance(raw.get("clips"), list) or len(raw["clips"]) > 500:
        raise ValueError("素材库格式无效")
    clips = [c for c in raw["clips"] if any(t in source for t in c.get("topics", []))]
    if not clips:
        raise ValueError("素材库没有与原文主题匹配的实景，请补充授权素材后重试")
    ids, checked = set(), {}
    for clip in clips:
        if not re.fullmatch(r"[a-z0-9_-]{1,64}", clip.get("id", "")) or clip["id"] in ids:
            raise ValueError("素材编号重复或无效")
        ids.add(clip["id"])
        if clip.get("reviewed") is not True or clip.get("usage") != "illustration_only":
            raise ValueError("实景素材尚未审核或缺少情境演绎边界")
        if not all(isinstance(clip.get(k), str) and clip[k].strip() for k in ("description", "author", "source_url", "license_url", "sha256", "shot_size")):
            raise ValueError("实景素材缺少来源、作者、许可或取景说明")
        from gateway.footage_contract import validate_source
        validate_source(clip)
        media = safe_file(root, clip["file"])
        if media.name not in checked:
            if media.stat().st_size > 500 * 1024 * 1024:
                raise ValueError("实景素材过大")
            digest, info = sha256(media), probe(media)
            checked[media.name] = digest, info
        digest, info = checked[media.name]
        if digest != clip["sha256"]:
            raise ValueError("实景素材摘要不匹配，请重新验收素材库")
        start, end = clip.get("start"), clip.get("end")
        if any(type(n) not in (int, float) or not math.isfinite(n) for n in (start, end)) or not 0 <= start < end <= float(info["format"]["duration"]) - .02:
            raise ValueError("素材可用时间窗超出真实视频")
        if not any(s.get("codec_type") == "video" and s.get("width", 0) > 0 for s in info["streams"]):
            raise ValueError("素材没有视频画面")
        for ratio in ("9:16", "16:9"):
            crop = clip.get("crops", {}).get(ratio, {})
            from worker.scene_framing import validate_crop
            validate_crop(crop)
    return {"version": 1, "root": str(root), "clips": clips}


def planner_catalog(catalog: dict, ratio: str) -> dict:
    return {"clips": [{"id": c["id"], "description": c["description"],
                        "shot_size": c["shot_size"], "seconds_available": int(c["end"] - c["start"]),
                        "continuity": c.get("continuity", "independent illustrative insert"),
                        **({"people_visible": c["review"]["people_visible"]} if "review" in c else {})}
                       for c in catalog["clips"]],
            "aspect_ratio": ratio, "usage": "illustration_only",
            "people_preference": next((c["review"]["people_preference"] for c in catalog["clips"] if "review" in c), "any")}


def select_shots(scenes: list[dict], catalog: dict) -> list[dict]:
    by_id = {c["id"]: c for c in catalog["clips"]}
    selected, intervals = [], {}
    for scene in scenes:
        for shot in scene["shots"]:
            if shot["clip_id"]=="animation": continue
            if shot["clip_id"] not in by_id:
                raise ValueError("规划器选择了未授权或不匹配原文的素材")
            clip = by_id[shot["clip_id"]]
            end = clip["start"] + shot["duration_sec"]
            if end > clip["end"] + 1e-6:
                raise ValueError("镜头超过审核时间窗，禁止冻结、拉伸或循环补帧")
            for start, stop in intervals.get(clip["file"], []):
                if max(start, clip["start"]) < min(stop, end):
                    raise ValueError("视频重复使用了同一段实拍画面")
            intervals.setdefault(clip["file"], []).append((clip["start"], end))
            selected.append({**clip, "scene_num": scene["scene_num"], "duration_sec": shot["duration_sec"],
                             "reason": shot["reason"], "source_quote": shot.get("source_quote",scene["source_quotes"][0])})
    if len(selected) >= 4 and len({s["shot_size"] for s in selected}) < 2:
        raise ValueError("实景剪辑至少需要两种景别")
    if len(selected) >= 6 and any(a["sha256"] == b["sha256"] == c["sha256"]
                                 for a, b, c in zip(selected, selected[1:], selected[2:])):
        raise ValueError("实景视频连续使用同机位素材过多，请重新规划镜头")
    return selected


def prepare_assets(job: Path, scenes: list[dict], catalog: dict, ratio: str) -> None:
    selected = select_shots(scenes, catalog)
    target = job / "footage"
    target.mkdir(exist_ok=False)
    for filename in dict.fromkeys(c["file"] for c in selected):
        source = safe_file(Path(catalog["root"]), filename)
        destination = target / filename
        shutil.copyfile(source, destination)
        expected = next(c["sha256"] for c in selected if c["file"] == filename)
        if sha256(destination) != expected:
            raise ValueError("复制素材时摘要变化")
    (job / "selected_footage.json").write_text(json.dumps({"version": 1, "aspect_ratio": ratio,
        "clips": selected}, ensure_ascii=False, indent=2))
