"""Validated Claude-to-Codex content handoff and reproducible text deliverable."""
import json
import re

CONTENT_FIELDS = ("slide_num", "action_title_cn", "key_message_cn", "visible_text_cn",
                  "source_quotes", "evidence_status", "argument_cn", "speaker_notes_cn", "transition_cn")


def validate_plan(plan, spec):
    slides = plan.get("slide_outline")
    if not isinstance(slides, list) or not 1 <= len(slides) <= 60:
        raise ValueError("规划缺失或页数不合法")
    if spec["slide_count"] and len(slides) != spec["slide_count"]:
        raise ValueError("规划页数与请求不符")
    source = spec["original_prompt_cn"]
    titles, messages, layouts = [], [], []
    for i, slide in enumerate(slides, 1):
        if slide.get("slide_num") != i:
            raise ValueError("规划页码不连续")
        for field in ("action_title_cn", "key_message_cn", "page_type", "visible_text_cn", "layout_description", "evidence_status"):
            if not isinstance(slide.get(field), str) or not slide[field].strip():
                raise ValueError(f"第 {i} 页缺少 {field}")
        quotes = slide.get("source_quotes")
        if not isinstance(quotes, list) or not quotes or any(not isinstance(q, str) or not q.strip() or q not in source for q in quotes):
            raise ValueError(f"第 {i} 页缺少可追溯的原文依据")
        # Ignore punctuation/numbering to catch the old four-page cyclic filler.
        norm = lambda value: re.sub(r"[\W\d_]+", "", value).casefold()
        titles.append(norm(slide["action_title_cn"]))
        messages.append(norm(slide["key_message_cn"]))
        layouts.append(slide["page_type"].strip().lower())
    if len(set(titles)) != len(titles) or len(set(messages)) != len(messages):
        raise ValueError("规划包含重复标题或循环论点")
    if len(slides) >= 5 and (len(set(layouts)) < 3 or any(len(set(layouts[i:i+3])) == 1 for i in range(len(layouts)-2))):
        raise ValueError("逐页版式缺少变化")
    return slides


def validate_content_plan(plan, spec):
    if not isinstance(plan, dict):
        raise ValueError("Claude 内容策划必须是对象")
    if len(json.dumps(plan, ensure_ascii=False).encode()) > 2 * 1024 * 1024:
        raise ValueError("Claude 内容策划过大")
    for key in ("task_summary_cn", "audience_cn", "central_thesis_cn", "narrative_arc_cn", "evidence_boundary_cn"):
        if not isinstance(plan.get(key), str) or not plan[key].strip():
            raise ValueError(f"Claude 内容策划缺少 {key}")
    slides = validate_plan(plan, spec)
    for slide in slides:
        for key in ("argument_cn", "speaker_notes_cn", "transition_cn"):
            if not isinstance(slide.get(key), str) or not slide[key].strip():
                raise ValueError(f"Claude 第 {slide['slide_num']} 页缺少 {key}")
        if slide["evidence_status"] not in ("fact", "direction", "hypothesis", "mixed"):
            raise ValueError("Claude 证据性质不合法")
    return plan


def validate_content_handoff(slides, plan):
    planned = plan["slide_outline"]
    if len(slides) != len(planned) or any(
            any(actual.get(k) != source.get(k) for k in CONTENT_FIELDS)
            for actual, source in zip(slides, planned)):
        raise ValueError("Codex 改写或遗漏了 Claude 的内容策划")


def outline_markdown(plan):
    lines = ["# " + plan["task_summary_cn"], "", "## 受众", plan["audience_cn"],
             "", "## 核心主张", plan["central_thesis_cn"], "", "## 全篇逻辑", plan["narrative_arc_cn"],
             "", "## 证据与推演边界", plan["evidence_boundary_cn"]]
    for page in plan["slide_outline"]:
        lines += ["", f"## 第 {page['slide_num']} 页 · {page['action_title_cn']}", "",
                  "**本页结论**\n" + page["key_message_cn"], "",
                  "**论证**\n" + page["argument_cn"], "",
                  "**画面文字**\n" + page["visible_text_cn"], "",
                  "**讲稿**\n" + page["speaker_notes_cn"], "",
                  "**衔接**\n" + page["transition_cn"], "",
                  "**画面建议**\n" + page["layout_description"], "",
                  "**证据性质** " + page["evidence_status"], "",
                  "**原文依据**\n" + "\n".join("> " + q.replace("\n", "\n> ") for q in page["source_quotes"])]
    return "\n".join(lines) + "\n"


def read_plan(path, root=None):
    if root is not None and not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Claude 内容策划不能位于任务外")
    if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1 or not 0 < path.stat().st_size <= 2 * 1024 * 1024:
        raise ValueError("Claude 内容策划缺失或文件不安全")
    return json.loads(path.read_text(encoding="utf-8"))
