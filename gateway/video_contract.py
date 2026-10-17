"""Pure-data contract validation shared by the gateway and video worker."""
from __future__ import annotations

import re
import unicodedata


LAYOUTS = {"title", "comparison", "process"}
PLAN_FIELDS = {"task_summary_cn", "scenes"}
SCENE_FIELDS = {"scene_num", "duration_sec", "title", "body", "narration",
                "source_quotes", "layout", "items"}
NUMBER_PATTERN = re.compile(r"(?<![\d.])[-+]?(?:\d+(?:\.\d+)?|\.\d+)%?(?![\d.])")


def validate_video_spec(spec: dict) -> dict:
    if not isinstance(spec, dict) or spec.get("generation_contract") != "skill-video-v1":
        raise ValueError("视频任务缺少 skill-video-v1 契约")
    source = spec.get("original_prompt_cn")
    if not isinstance(source, str) or not source.strip():
        raise ValueError("视频任务缺少完整中文原文")
    duration = spec.get("video_duration_sec")
    if type(duration) is not int or not 6 <= duration <= 60:
        raise ValueError("视频时长必须是 6 至 60 秒的整数")
    ratio = spec.get("video_aspect_ratio")
    if ratio not in ("16:9", "9:16"):
        raise ValueError("视频比例只能是 16:9 或 9:16")
    if not isinstance(spec.get("matched_template", {}), dict):
        raise ValueError("视频模板信息必须是对象")
    if "video_narration" in spec and type(spec["video_narration"]) is not bool:
        raise ValueError("视频配音开关必须是布尔值")
    provider = spec.get("planner_provider", "codex_cli")
    if provider not in ("codex_cli", "claude_cli"):
        raise ValueError("不支持的视频规划器")
    if provider == "claude_cli":
        raise RuntimeError("Claude 视频规划接口已保留，但尚未配置并验证隔离执行，任务已拒绝且不会回退到 Codex")
    return spec


def _plain_text(value, field: str, maximum: int) -> str:
    if (not isinstance(value, str) or not value.strip() or len(value) > maximum
            or any(unicodedata.category(char).startswith("C") for char in value)
            or "<" in value or ">" in value or "-->" in value):
        raise ValueError(f"视频计划字段 {field} 缺失或超过排版容量")
    return value.strip()


def _normalise(value: str) -> str:
    return re.sub(r"[\W\d_]+", "", value).casefold()


def validate_video_plan(plan: dict, spec: dict) -> list[dict]:
    validate_video_spec(spec)
    if not isinstance(plan, dict) or set(plan) != PLAN_FIELDS:
        raise ValueError("视频计划顶层字段不符合严格契约")
    _plain_text(plan.get("task_summary_cn"), "task_summary_cn", 80)
    scenes = plan.get("scenes")
    max_scenes = min(10, spec["video_duration_sec"] // 3)
    if not isinstance(scenes, list) or not 1 <= len(scenes) <= max_scenes:
        raise ValueError("视频场景数量不合法")
    source = spec["original_prompt_cn"]
    source_numbers = set(NUMBER_PATTERN.findall(source))
    validated: list[dict] = []
    titles: list[str] = []
    bodies: list[str] = []
    narrations: list[str] = []
    layouts: list[str] = []
    total = 0
    for index, raw in enumerate(scenes, 1):
        if not isinstance(raw, dict) or set(raw) != SCENE_FIELDS:
            raise ValueError(f"第 {index} 场字段不符合严格契约")
        if raw.get("scene_num") != index:
            raise ValueError("视频场景编号必须从 1 连续递增")
        duration = raw.get("duration_sec")
        if type(duration) is not int or duration < 3:
            raise ValueError(f"第 {index} 场时长必须是不少于 3 秒的整数")
        title = _plain_text(raw.get("title"), f"scene[{index}].title", 28)
        body = _plain_text(raw.get("body"), f"scene[{index}].body", 160)
        narration = _plain_text(raw.get("narration"), f"scene[{index}].narration", duration * 4)
        layout = raw.get("layout")
        if layout not in LAYOUTS:
            raise ValueError(f"第 {index} 场版式不受支持")
        items = raw.get("items")
        if not isinstance(items, list):
            raise ValueError(f"第 {index} 场可视项目不符合排版容量")
        try:
            items = [_plain_text(item, f"scene[{index}].items", 36) for item in items]
        except ValueError as exc:
            raise ValueError(f"第 {index} 场可视项目不符合排版容量") from exc
        if ((layout == "title" and len(items) > 3)
                or (layout == "comparison" and len(items) != 2)
                or (layout == "process" and not 2 <= len(items) <= 5)):
            raise ValueError(f"第 {index} 场项目数量与版式不匹配")
        quotes = raw.get("source_quotes")
        if (not isinstance(quotes, list) or not quotes
                or any(not isinstance(q, str) or not q.strip() or len(q) > 160 or q not in source for q in quotes)):
            raise ValueError(f"第 {index} 场缺少可追溯的原文引用")
        visible = " ".join([title, body, narration, *items])
        for number in NUMBER_PATTERN.findall(visible):
            if number not in source_numbers:
                raise ValueError(f"第 {index} 场包含原文没有的数字：{number}")
        titles.append(_normalise(title))
        bodies.append(_normalise(body))
        narrations.append(_normalise(narration))
        layouts.append(layout)
        total += duration
        validated.append({"scene_num": index, "duration_sec": duration, "title": title,
                          "body": body, "narration": narration,
                          "source_quotes": [q.strip() for q in quotes],
                          "layout": layout, "items": items})
    if total != spec["video_duration_sec"]:
        raise ValueError("视频场景总时长与请求不一致")
    if (len(set(titles)) != len(titles) or len(set(bodies)) != len(bodies)
            or len(set(narrations)) != len(narrations)):
        raise ValueError("视频计划包含重复标题、正文或旁白")
    if len(scenes) >= 3 and len(set(layouts)) < 2:
        raise ValueError("多场景视频需要根据内容使用至少两种版式")
    return validated
