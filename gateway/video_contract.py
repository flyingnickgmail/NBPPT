"""Pure-data contract validation shared by the gateway and video worker."""
from __future__ import annotations

import re
import unicodedata


LAYOUTS = {"title", "comparison", "process"}
STORY_CONTRACT = "story-video-v2"
STORY_SHOTS = {"focus", "scatter", "gather", "inspect", "decision", "journey", "feedback", "resolve"}
STORY_ROLES = {"hook", "friction", "mechanism", "choice", "resolution"}
VIDEO_VOICES = {"melo", "kokoro_female", "kokoro_male", "microsoft_yunxi", "microsoft_xiaoxiao"}


def voice_provider(voice: str) -> str:
    if voice.startswith("microsoft_"):
        return "microsoft_edge"
    return "melo_tts" if voice == "melo" else "kokoro"


def narration_density(spec: dict) -> tuple[float, int]:
    # Microsoft auditions speak faster than the offline renderer. This is a
    # planning budget only; actual audio must still fit its scene after synthesis.
    return (3.5, 4) if spec.get("video_voice", "").startswith("microsoft_") else (2.5, 3)


PLAN_FIELDS = {"task_summary_cn", "scenes"}
SCENE_FIELDS = {"scene_num", "duration_sec", "title", "body", "narration",
                "source_quotes", "layout", "items"}
NUMBER_PATTERN = re.compile(r"(?<![\d.])[-+]?(?:\d+(?:\.\d+)?|\.\d+)%?(?![\d.])")


def source_boundaries(source: str) -> list[str]:
    """Retain explicit automation/claim exclusions; not a semantic fact checker."""
    return list(dict.fromkeys(re.findall(r"(?:不能自动|不得自动|不承诺|不代表)[^，。；！？\n]{1,45}", source)))


def footage_people_preference(source: str) -> str:
    """Explicit casting request, never a visual ethnicity classifier."""
    if re.search(r"中国(?:人(?:物)?|演员|场景)|Chinese (?:people|cast|setting)", source, re.I):
        return "china"
    if re.search(r"亚洲(?:人(?:物)?|演员|面孔)|Asian (?:people|cast)", source, re.I):
        return "asian"
    return "any"


def validate_footage_review(clip: dict, spec: dict) -> None:
    from gateway.footage_contract import description, casting_pattern, casting_required
    review = clip.get("review")
    if not isinstance(review, dict) or set(review) - {'sampled_ranges','frame_layout'} != {"method", "reason", "query", "source_quote",
            "sample_interval_sec", "sampled_seconds", "people_preference", "people_visible",
            "casting_evidence", "provider_description", "crop_verified", "crop_reason"}:
        raise ValueError("自动实景素材缺少完整审核证据")
    if (review["method"] != "model_sampled_frames_and_crop" or review["sample_interval_sec"] != 1
            or review["crop_verified"] != spec["video_aspect_ratio"]
            or type(review["sampled_seconds"]) is not int or not 2 <= review["sampled_seconds"] <= (32 if clip.get('provider')=='commons' else 24)
            or type(review["people_visible"]) is not bool):
        raise ValueError("素材审核未覆盖交付镜头或实际画幅")
    if review.get('frame_layout','crop') not in {'crop','contain'} or review.get('frame_layout','crop') != clip.get('frame_layout','crop'):
        raise ValueError('素材实际布局与审核布局不一致')
    ranges = review.get('sampled_ranges', [[0,review['sampled_seconds']]])
    if (not isinstance(ranges,list) or not 1 <= len(ranges) <= 4
            or any(not isinstance(r,list) or len(r)!=2 or any(type(x) is not int for x in r)
                   or not 0 <= r[0] < r[1] <= 600 for r in ranges)
            or sum(b-a for a,b in ranges) != review['sampled_seconds']
            or any(a[1] > b[0] for a,b in zip(ranges,ranges[1:]))
            or not any(a <= clip['start'] < clip['start']+clip['duration_sec'] <= b for a,b in ranges)):
        raise ValueError('素材镜头位于未审核的时间段')
    for name in ("reason", "query", "source_quote", "crop_reason"):
        _plain_text(review[name], name, 300)
    _plain_text(review['provider_description'], 'provider_description', 2300)
    if review["source_quote"] not in spec["original_prompt_cn"]:
        raise ValueError("素材审核引用与原文不一致")
    preference = footage_people_preference(spec["original_prompt_cn"])
    if review["people_preference"] != preference:
        raise ValueError("素材人物要求与原文不一致")
    evidence = review["casting_evidence"]
    if not isinstance(evidence, str) or len(evidence) > 200:
        raise ValueError("人物来源证据无效")
    original_description = description(clip)
    if review["provider_description"] != original_description:
        raise ValueError("人物来源描述与素材页不一致")
    if preference != "any" and review["people_visible"] and (casting_required(spec['original_prompt_cn']) or evidence):
        pattern = casting_pattern(preference)
        if (not evidence or evidence not in original_description or not re.search(pattern, evidence, re.I)
                or not re.search(pattern, original_description, re.I)):
            raise ValueError("人物偏好缺少来源证据")




def validate_video_spec(spec: dict) -> dict:
    if not isinstance(spec, dict) or spec.get("generation_contract") not in ("skill-video-v1", STORY_CONTRACT):
        raise ValueError("视频任务缺少受支持的视频契约")
    source = spec.get("original_prompt_cn")
    if not isinstance(source, str) or not source.strip():
        raise ValueError("视频任务缺少完整中文原文")
    duration = spec.get("video_duration_sec")
    if type(duration) is not int or not 6 <= duration <= (180 if spec.get("planner_provider")=="claude_cli" else 60):
        raise ValueError("视频时长必须是 6 至 180 秒的整数；超过60秒需Claude内容模式")
    ratio = spec.get("video_aspect_ratio")
    if ratio not in ("16:9", "9:16"):
        raise ValueError("视频比例只能是 16:9 或 9:16")
    if not isinstance(spec.get("matched_template", {}), dict):
        raise ValueError("视频模板信息必须是对象")
    if "video_narration" in spec and type(spec["video_narration"]) is not bool:
        raise ValueError("视频配音开关必须是布尔值")
    if spec.get("video_voice", "melo") not in VIDEO_VOICES:
        raise ValueError("不支持的视频音色")
    if "video_subtitles" in spec and type(spec["video_subtitles"]) is not bool:
        raise ValueError("视频字幕开关必须是布尔值")
    provider = spec.get("planner_provider", "codex_cli")
    if provider not in ("codex_cli", "claude_cli"):
        raise ValueError("不支持的视频规划器")
    if provider == "claude_cli" and spec["generation_contract"] != STORY_CONTRACT:
        raise RuntimeError("Claude 需要内容优先的故事契约，不会回退到 Codex")
    if spec["generation_contract"] == STORY_CONTRACT and provider != "claude_cli":
        raise ValueError("内容故事契约必须由 Claude 编写，不会替换成其他引擎")
    if spec.get("video_visual_mode","motion") not in {"motion","live_action"}:
        raise ValueError("不支持的视频画面模式")
    if spec.get("video_visual_mode")=="live_action" and provider!="claude_cli":
        raise ValueError("实景内容模式需Claude编写口播")
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
    live = spec.get("video_visual_mode")=="live_action"
    if live:
        from gateway.live_action_contract import validate_live_plan
        return validate_live_plan(plan,spec)
    story_mode = spec["generation_contract"] == STORY_CONTRACT
    if not isinstance(plan, dict) or set(plan) != (PLAN_FIELDS | {"story"} if story_mode else PLAN_FIELDS):
        raise ValueError("视频计划顶层字段不符合严格契约")
    if story_mode:
        validate_story(plan["story"], spec["original_prompt_cn"])
    _plain_text(plan.get("task_summary_cn"), "task_summary_cn", 80)
    scenes = plan.get("scenes")
    max_scenes = min(30 if spec["video_duration_sec"]>60 else 10, spec["video_duration_sec"] // 3)
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
        if not isinstance(raw, dict) or set(raw) != (SCENE_FIELDS | {"role", "state_before", "state_after"} if story_mode else SCENE_FIELDS):
            raise ValueError(f"第 {index} 场字段不符合严格契约")
        if raw.get("scene_num") != index:
            raise ValueError("视频场景编号必须从 1 连续递增")
        duration = raw.get("duration_sec")
        if type(duration) is not int or duration < 3:
            raise ValueError(f"第 {index} 场时长必须是不少于 3 秒的整数")
        title = _plain_text(raw.get("title"), f"scene[{index}].title", 28)
        body = _plain_text(raw.get("body"), f"scene[{index}].body", 64 if story_mode else 160)
        narration = _plain_text(raw.get("narration"), f"scene[{index}].narration", duration * (narration_density(spec)[1] if story_mode else 4))
        layout = raw.get("layout")
        if layout not in (STORY_SHOTS if story_mode else LAYOUTS):
            raise ValueError(f"第 {index} 场版式不受支持")
        if story_mode and any(word in body and word not in source for word in
                              ('卡片四散','漂移','画面中','放大','亮起','镜头切换','聚拢到')):
            raise ValueError('分镜制作指令不能作为可见正文')
        items = raw.get("items")
        if not isinstance(items, list):
            raise ValueError(f"第 {index} 场可视项目不符合排版容量")
        try:
            items = [_plain_text(item, f"scene[{index}].items", 12 if story_mode else 36) for item in items]
        except ValueError as exc:
            raise ValueError(f"第 {index} 场可视项目不符合排版容量") from exc
        if ((layout == "title" and len(items) > 3)
                or (layout == "comparison" and len(items) != 2)
                or (layout == "process" and not 2 <= len(items) <= 5)):
            raise ValueError(f"第 {index} 场项目数量与版式不匹配")
        extras = {}
        if story_mode:
            if not 2 <= len(items) <= 4 or (layout == "decision" and len(items) != 2):
                raise ValueError("故事镜头需要 2–4 个对象，决策镜头恰好两个选项")
            if raw.get("role") not in STORY_ROLES:
                raise ValueError("故事镜头缺少受支持的叙事作用")
            extras = {"role": raw["role"],
                      "state_before": _plain_text(raw.get("state_before"), "state_before", 16),
                      "state_after": _plain_text(raw.get("state_after"), "state_after", 16)}
            if _normalise(extras["state_before"]) == _normalise(extras["state_after"]):
                raise ValueError("故事镜头必须发生有意义的状态变化")
        quotes = raw.get("source_quotes")
        if (not isinstance(quotes, list) or not quotes
                or any(not isinstance(q, str) or not q.strip() or len(q) > 160 or q not in source for q in quotes)):
            raise ValueError(f"第 {index} 场缺少可追溯的原文引用")
        visible = " ".join([title, body, narration, *items, *extras.values()])
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
                          "layout": layout, "items": items, **extras})
    if total != spec["video_duration_sec"]:
        raise ValueError("视频场景总时长与请求不一致")
    if (len(set(titles)) != len(titles) or len(set(bodies)) != len(bodies)
            or len(set(narrations)) != len(narrations)):
        raise ValueError("视频计划包含重复标题、正文或旁白")
    if len(scenes) >= 3 and len(set(layouts)) < 2:
        raise ValueError("多场景视频需要根据内容使用至少两种版式")
    if story_mode:
        if scenes[0]["role"] != "hook" or scenes[-1]["role"] != "resolution":
            raise ValueError("故事必须从问题切入并回到结果或明确的下一步")
        if spec["video_duration_sec"] >= 12 and (len(scenes) < 3 or len(set(layouts)) < 3
                or not any(s["role"] in {"mechanism", "choice"} for s in scenes[1:-1])):
            raise ValueError("故事缺少中间行动或镜头变化")
        if any(a == b == c for a, b, c in zip(layouts, layouts[1:], layouts[2:])):
            raise ValueError("禁止连续三个相同故事镜头")
        presented = ' '.join(' '.join([s['title'], s['body'], s['narration'], *s['items'],
                                      s['state_before'], s['state_after']]) for s in validated)
        missing = [boundary for boundary in source_boundaries(source) if boundary not in presented]
        if missing:
            raise ValueError("故事遗漏原文的自动化限制或承诺边界：" + '；'.join(missing))
    return validated


def validate_story(story: dict, source: str) -> dict:
    if not isinstance(story, dict) or set(story) != {"subject", "goal", "question", "visual"}:
        raise ValueError("故事主线字段不符合严格契约")
    limits = {"subject": 10, "goal": 24, "question": 24}
    result = {key: _plain_text(story.get(key), key, limit) for key, limit in limits.items()}
    if story.get("visual") not in {"person", "parcel", "book", "document", "device"}:
        raise ValueError("故事主体图形不受支持")
    if any(n not in set(NUMBER_PATTERN.findall(source)) for n in NUMBER_PATTERN.findall(" ".join(result.values()))):
        raise ValueError("故事主线包含原文没有的数字")
    return {**result, "visual": story["visual"]}
