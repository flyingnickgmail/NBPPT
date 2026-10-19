"""
Stage 1 — Master Agent Content Planner & Prompt Engineer (`gateway/deepseek_compiler.py`).

Workflow:
1. Uses Claude (`GLM-5` / Anthropic API) or Codex (`gpt-6-astra`) to write the detailed
   slide-by-slide PPT content (`slide_outline` + `markdown_slide_script`).
2. Crafts high-precision execution prompts (`codex_direct_prompt` & `claude_direct_prompt`)
   following the user's `~/.codex/skills/client-ci-ppt-image-deck` and `image_gen` conventions,
   so Stage 2 can send the prompt directly to `codex exec` or `claude -p` to generate pure-image PPTs
   or skill-native decks without brittle template text replacement.
"""
import asyncio
import json
import os
import pathlib
import re
import sys
from typing import Dict, Any, Optional, List
import httpx

from gateway.config import get_runtime_settings
from gateway.template_registry import match_template_for_prompt
from gateway.ppt_contract import resolve_ppt_engine

VISUAL_PALETTES = {
    "yonyou-ci-bg": {
        "name": "用友高端 BG 红白灰视觉体系 (-yonyou)",
        "primary": "#C8102E",
        "secondary": "#0052D9",
        "bg": "#FFFFFF",
        "surface": "#F6F7F9",
        "text": "#18233A",
        "muted": "#526174",
        "border": "#D9DDE1",
        "brand_lockup": "用友 yonyou",
        "ci_style_prompt": (
            "Pure white #FFFFFF background, charcoal #18233A titles, cool gray #526174 secondary labels, "
            "thin #D9DDE1 dividers, restrained Yonyou red #C8102E for key KPI emphasis and top card bars only. "
            "Swiss consulting editorial grid, 5% outer margin, understated '用友 yonyou' text lockup top right."
        ),
    },
    "abu9-exec-report": {
        "name": "ABU9 友车科技经营汇报视觉体系 ($artifact-template-abu9)",
        "primary": "#E60012",
        "secondary": "#1E293B",
        "bg": "#FFFFFF",
        "surface": "#FFF5F5",
        "text": "#111827",
        "muted": "#4B5563",
        "border": "#F3D6D8",
        "brand_lockup": "友车科技 ABU9",
        "ci_style_prompt": (
            "Pure white #FFFFFF background, executive red #E60012 header bar and metric highlights, "
            "deep ink #111827 titles, light warm gray/red-tinted structured tables and KPI cards, "
            "understated '友车科技 ABU9' text lockup top right, bottom red page number badge."
        ),
    },
    "gorden:mckinsey-style": {
        "name": "麦肯锡咨询风白底红灰网格 (McKinsey Editorial)",
        "primary": "#B91C1C",
        "secondary": "#1E293B",
        "bg": "#FFFFFF",
        "surface": "#F8FAFC",
        "text": "#0F172A",
        "muted": "#475569",
        "border": "#CBD5E1",
        "brand_lockup": "EXECUTIVE BRIEFING",
        "ci_style_prompt": (
            "Pure white #FFFFFF background, charcoal #0F172A action titles at top-left, "
            "dark slate #1E293B and restrained crimson #B91C1C analytical highlights, "
            "McKinsey boardroom consulting grid with clean multi-column cards, flat data tables, and process arrows."
        ),
    },
    "gorden:architecture-deck": {
        "name": "企业级技术架构蓝图风格 (Architecture Blueprint)",
        "primary": "#1D4ED8",
        "secondary": "#0F172A",
        "bg": "#FFFFFF",
        "surface": "#F1F5F9",
        "text": "#0F172A",
        "muted": "#475569",
        "border": "#CBD5E1",
        "brand_lockup": "ARCHITECTURE BLUEPRINT",
        "ci_style_prompt": (
            "Pure white #FFFFFF background, deep navy #0F172A titles, royal blue #1D4ED8 and slate #334155 "
            "layered system architecture boxes, clear boundary labels, directional data-flow arrows, and module matrices."
        ),
    },
    "guizang-swiss-html": {
        "name": "归藏 Swiss 国际主义网格 ($guizang-ppt-skill)",
        "primary": "#002FA7",
        "secondary": "#D9381E",
        "bg": "#F7F6F2",
        "surface": "#FFFFFF",
        "text": "#141413",
        "muted": "#57534E",
        "border": "#E5E0D8",
        "brand_lockup": "SWISS EDITORIAL",
        "ci_style_prompt": (
            "Warm paper white #F7F6F2 background, stark black #141413 typography, International Klein Blue #002FA7 "
            "and safety orange #D9381E accents, Massimo Vignelli Swiss grid with oversized KPI numerals and hairline rules."
        ),
    },
    "obsidian-roadshow": {
        "name": "深邃黑金/青蓝科技路演风格",
        "primary": "#38BDF8",
        "secondary": "#6366F1",
        "bg": "#0B0F19",
        "surface": "#161F33",
        "text": "#F8FAFC",
        "muted": "#94A3B8",
        "border": "#28354F",
        "brand_lockup": "TECH KEYNOTE",
        "ci_style_prompt": (
            "Clean executive white #FFFFFF or high-contrast boardroom layout, charcoal #18233A titles, "
            "cobalt blue #005BAC and crimson #C7352B accents, structured consulting cards and flow arrows."
        ),
    },
}

MASTER_AGENT_SYSTEM_PROMPT = """You are the Master Content Planner & Prompt Engineer for a consulting-grade presentation studio.
Your job is to take the user's Chinese request and generate:
1. A deeply reasoned, consulting-grade slide-by-slide PPT content plan (`slide_outline`).
2. For each slide, concrete modules (`cards`) with short, crisp, legible Simplified Chinese titles, metrics, and bullet points suitable for direct rendering by Codex's `image_gen` slide generator or Claude's PPT builder.

Respond with ONLY a valid raw JSON object (no markdown fences) matching this exact schema:
{
  "task_summary_cn": "一句话总结本次汇报的核心战略主张",
  "logical_reasoning_chain_cn": [
    "第一步（核心论点界定）：...",
    "第二步（叙事主线设计）：...",
    "第三步（提示词与视觉映射）：..."
  ],
  "master_outline_cn": {
    "core_thesis": "全案唯一核心结论（Action-oriented elevator thesis）",
    "narrative_arc": "全案叙事弧（例如：现状痛点 -> 核心破局方案 -> 架构/路径拆解 -> 量化收益与验收）",
    "key_pillars": ["支柱一", "支柱二", "支柱三"]
  },
  "kpis": [
    {"label": "4-6字指标名", "value": "带单位数值如 15-25%", "delta": "简短说明"},
    {"label": "4-6字指标名", "value": "带单位数值如 3.2x", "delta": "简短说明"},
    {"label": "4-6字指标名", "value": "带单位数值如 99.2%", "delta": "简短说明"}
  ],
  "slide_outline": [
    {
      "slide_num": 1,
      "page_type": "executive-message | evidence-infographic | architecture-diagram | roadmap",
      "kicker": "01 核心主张",
      "action_title_cn": "12~20字结论先行大标题（直接写结论，不要写空洞名词）",
      "subtitle_cn": "15~28字副标题或核心论据说明",
      "cards": [
        {
          "header_cn": "4~8字模块标题（如：2026 Q1 准备期 / 智能寻源降本）",
          "metric_cn": "醒目核心数字或标签（如：5-10% 或 阶段一）",
          "items_cn": ["6~14字精炼要点一", "6~14字精炼要点二"]
        }
      ],
      "bottom_flow_cn": ["左节点（4~8字）", "中节点（4~8字）", "右节点（4~8字）"],
      "footnote_cn": "底部备注（如：核心指标基于业务基线测算，实际推进以阶段验收为准）",
      "bullets_cn": [
        "模块一完整阐述（含具体数字与业务动作）",
        "模块二完整阐述（含具体数字与业务动作）",
        "模块三完整阐述（含具体数字与业务动作）"
      ]
    }
  ],
  "video_scenes": [
    {
      "scene_id": 1,
      "duration_sec": 3,
      "motion_template": "node_topology | bar_race_chart | radial_kpi_matrix",
      "title_cn": "动效场景主标题",
      "subtitle_cn": "动效副标题",
      "data_nodes_cn": ["节点1", "节点2", "节点3", "节点4"],
      "metric_highlight": "+320%"
    }
  ]
}
Rules:
- If `Slide Count` is a specific number N, generate that exact number of slides. If `Slide Count` is `AUTO (Unlimited / 不限页数)`, freely determine the optimal number of slides based on the topic's logical structure and depth (or honor any page count mentioned inside the user's Chinese command, typically 4 to 8 slides) so every section is thoroughly covered without artificial truncation.
- Every slide MUST have 3 to 5 `cards`, 3 `bottom_flow_cn` items, and 3 `bullets_cn`.
- Keep text inside `cards` concise and sharp so that when Codex `image_gen` renders the slide image, every Chinese character is 100% large, crisp, and legible!"""


def _extract_json_dict(raw_text: str) -> Optional[Dict[str, Any]]:
    text = raw_text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except Exception:
            pass
    return None


def _build_slide_image_prompt(
    slide: Dict[str, Any],
    slide_idx: int,
    total_slides: int,
    palette: Dict[str, Any],
) -> str:
    """
    Build the exact `Use case: infographic-diagram` prompt for Codex's built-in `image_gen` tool,
    modeled directly after the user's proven `~/.codex/skills/client-ci-ppt-image-deck` prompts.
    """
    title = slide.get("action_title_cn", f"核心战略模块 0{slide_idx}")
    subtitle = slide.get("subtitle_cn", "")
    page_type = slide.get("page_type", "executive-message")
    kicker = slide.get("kicker", f"0{slide_idx} 核心模块")
    brand = palette.get("brand_lockup", "用友 yonyou")
    ci_style = palette.get("ci_style_prompt", VISUAL_PALETTES["yonyou-ci-bg"]["ci_style_prompt"])
    cards = slide.get("cards") or []
    bullets = slide.get("bullets_cn") or []

    card_lines = []
    if cards:
        for i, c in enumerate(cards[:5], 1):
            hdr = c.get("header_cn", f"核心模块 {i}")
            met = c.get("metric_cn", "")
            items = "；".join(c.get("items_cn", [])[:2])
            card_lines.append(f"Column/Card {i}: header '{hdr}', highlight '{met}', points '{items}'")
    else:
        for i, b in enumerate(bullets[:4], 1):
            parts = b.split("：", 1) if "：" in b else [f"要点 0{i}", b]
            card_lines.append(f"Column/Card {i}: header '{parts[0][:10]}', body '{parts[-1][:24]}'")

    flow_items = slide.get("bottom_flow_cn") or ["数据采集与底座", "AI智能决策引擎", "业务降本增效闭环"]
    flow_str = " -> ".join(flow_items[:4])
    footnote = slide.get("footnote_cn") or "规划指标基于业务基线测算，实际推进以合规口径与阶段验收为准"

    return (
        f"Use case: infographic-diagram\n"
        f"Asset type: one 16:9 Chinese management consulting PowerPoint slide, high resolution 1672x941, landscape. "
        f"Render a complete flat slide edge-to-edge, not a photographed screen.\n"
        f"Consistent design: {ci_style}\n"
        f"Primary request: Generate slide P{slide_idx:02d} of a coherent {total_slides}-slide executive deck ({page_type}).\n"
        f"Top-left title (verbatim Simplified Chinese): \"{title}\"\n"
        f"Subtitle: \"{subtitle}\"\n"
        f"Top-right small text lockup: \"{brand}\"\n"
        f"Main content columns/cards ({len(card_lines)} aligned vertical cards with thin borders and red/blue top header bars):\n"
        + "\n".join(f"  - {cl}" for cl in card_lines)
        + f"\nBottom horizontal process bar with arrows: {flow_str}\n"
        f"Footer left: \"{kicker}\" | Footer note: \"{footnote}\" | Footer right: \"P{slide_idx:02d}\"\n"
        f"Constraints: Flat consulting layout, precise aligned columns, ample whitespace, rigorous hierarchy. "
        f"All Simplified Chinese text must be large, sharp, and verbatim. No 3D, no photos, no cartoon icons, no watermarks."
    )


def _build_markdown_slide_script(spec: Dict[str, Any]) -> str:
    """
    Build a standard Markdown slide script compatible with
    `~/.codex/skills/client-ci-ppt-image-deck/scripts/markdown_script_to_ci_pptx.mjs`
    and human review.
    """
    lines = [
        f"# {spec.get('task_summary_cn', '商业决策汇报方案')}",
        "",
        f"- **核心主旨 (Core Thesis)**: {spec.get('master_outline_cn', {}).get('core_thesis', '')}",
        f"- **叙事主线 (Narrative Arc)**: {spec.get('master_outline_cn', {}).get('narrative_arc', '')}",
        f"- **视觉母版 (Visual CI)**: {spec.get('matched_template', {}).get('name', '')}",
        "",
        "---",
        "",
    ]
    for s in spec.get("slide_outline", []):
        s_num = s.get("slide_num", 1)
        title = s.get("action_title_cn", "")
        sub = s.get("subtitle_cn", "")
        page_type = s.get("page_type", "executive-message")
        bullets = s.get("bullets_cn", [])
        flow = " -> ".join(s.get("bottom_flow_cn") or ["基础底座", "AI赋能", "业务结果"])
        lines.extend(
            [
                f"## SLIDE {s_num} | {title}",
                "",
                "### 视觉建议",
                f"- 版式类型：{page_type}（16:9 咨询级宽屏网格，顶部左对齐大标题，中部并列模块卡片，底部流程闭环条）",
                f"- 副标题：{sub}",
                "",
                "### 页面文字",
                "```text",
                f"【主标题】{title}",
                f"【副标题】{sub}",
                *[f"• {b}" for b in bullets],
                f"【底部闭环】{flow}",
                "```",
                "",
                "### 演讲话术",
                f"本页聚焦「{title}」，核心结论是：{sub}。",
                "",
                "### 数据与证据",
                *[f"- {b}" for b in bullets[:2]],
                "",
                "---",
                "",
            ]
        )
    return "\n".join(lines)


def _build_codex_direct_prompt(spec: Dict[str, Any]) -> str:
    """
    Build the exact prompt sent to `codex exec` when the user chooses Codex to generate the PPT directly.
    Instructs Codex to call its built-in `image_gen` tool for each slide in order, while Stage 3
    automatically collects the generated 1672x941 PNGs and packages them into `<job_id>_deck.pptx`
    via `images_to_pptx.py`.
    """
    slides = spec.get("slide_outline", [])
    total = len(slides)
    per_slide_blocks = []
    for idx, s in enumerate(slides, 1):
        img_p = s.get("image_gen_prompt", "")
        per_slide_blocks.append(
            f"=== SLIDE {idx} OF {total} ===\n{img_p}"
        )

    return (
        f"You are executing a non-interactive pure-image PPT generation job.\n"
        f"Do NOT ask any clarifying questions. Use shell commands only to copy the images generated for THIS job.\n"
        f"Your ONLY task is to call your built-in `image_gen` tool once for each of the {total} slides below (in order from SLIDE 1 to SLIDE {total}) to render high-resolution 16:9 consulting slide images.\n"
        f"Copy each generated image to ./staging/assets/slide_preview_N.png (N starts at 1). Never collect images from other jobs. After all copies are complete, reply with `CODEX_IMAGES_DONE`.\n\n"
        + "\n\n".join(per_slide_blocks)
    )


def _build_claude_direct_prompt(spec: Dict[str, Any]) -> str:
    """
    Build the exact prompt sent to `claude -p` when the user chooses Claude Code CLI to generate the PPT directly.
    """
    home_dir = str(pathlib.Path.home())
    base_dir = str(pathlib.Path(__file__).resolve().parent.parent)
    tpl_id = spec.get("matched_template", {}).get("id", "yonyou-ci-bg")
    return (
        f"You are executing a non-interactive PPT generation job in the current working directory.\n"
        f"Read `./slide_script.md` and `./task_spec.json`.\n"
        f"Matched Template / Skill: {tpl_id}\n"
        f"Execute the following steps immediately without asking questions:\n"
        f"1. Run `node {home_dir}/.codex/skills/client-ci-ppt-image-deck/scripts/markdown_script_to_ci_pptx.mjs --source ./slide_script.md --out ./output/final_deck.pptx` "
        f"(or if `{tpl_id}` is a `gorden:*` template, run `{base_dir}/.venv/bin/python {base_dir}/worker/agent_skills/.claude/skills/pptx-pro/scripts/build_deck.py --spec ./task_spec.json --assets ./output/assets --out ./output/final_deck.pptx`).\n"
        f"2. Verify that `./output/final_deck.pptx` exists and is non-empty, then reply with `CLAUDE_PPT_DONE`."
    )


def _enrich_spec_with_prompts(spec: Dict[str, Any]) -> Dict[str, Any]:
    palette = spec.get("palette") or VISUAL_PALETTES["yonyou-ci-bg"]
    slides = spec.get("slide_outline", [])
    total = len(slides)
    for idx, s in enumerate(slides, 1):
        s["slide_num"] = idx
        s["image_gen_prompt"] = _build_slide_image_prompt(s, idx, total, palette)

    spec["markdown_slide_script"] = _build_markdown_slide_script(spec)
    spec["codex_direct_prompt"] = _build_codex_direct_prompt(spec)
    spec["claude_direct_prompt"] = _build_claude_direct_prompt(spec)
    return spec


def _build_local_structured_spec(cn_prompt: str, task_type: str, extra_params: Dict[str, Any]) -> Dict[str, Any]:
    """Prepare source/configuration only; content must come from a real planner."""
    match = match_template_for_prompt(cn_prompt, extra_params.get("template_id", "auto"))
    template = match["template"]
    count = int(extra_params.get("slide_count", 0))
    if not cn_prompt.strip() or not 0 <= count <= 60:
        raise ValueError("请输入原文，页数须为 0（自动）或 1–60")
    return {
        "task_type": task_type,
        "original_prompt_cn": cn_prompt,
        "task_summary_cn": cn_prompt.strip().splitlines()[0][:100],
        "template_id": template["id"], "matched_template": template,
        "visual_style": template["id"],
        "palette": VISUAL_PALETTES.get(template["id"], template.get("palette", {})),
        "slide_count": count, "slide_count_mode": "fixed" if count else "auto",
        "video_duration_sec": int(extra_params.get("duration_seconds", 9)),
        "video_aspect_ratio": extra_params.get("aspect_ratio", "16:9"),
        "compiler_engine": "awaiting-planner", "is_real_llm": False,
        "slide_outline": [], "video_scenes": [], "kpis": [],
        "master_outline_cn": {}, "logical_reasoning_chain_cn": [],
    }


async def _reason_with_codex_cli(codex_bin: str, user_payload: str, proxy_url: str = "") -> Optional[Dict[str, Any]]:
    """Invoke the user's logged-in Codex CLI (`codex exec --ignore-user-config`) for fast outline planning."""
    env = os.environ.copy()
    for private_name in ("NBPPT_ADMIN_API_KEY", "OVERSEAS_WORKER_SECRET"):
        env.pop(private_name, None)
    if proxy_url:
        env["HTTP_PROXY"] = proxy_url
        env["HTTPS_PROXY"] = proxy_url
        env["ALL_PROXY"] = proxy_url

    prompt = (
        f"{MASTER_AGENT_SYSTEM_PROMPT}\n"
        f"IMPORTANT: Do NOT run any shell commands or tools. Respond immediately with the raw JSON object only.\n\n{user_payload}"
    )
    proc = await asyncio.create_subprocess_exec(
        codex_bin,
        "exec",
        "--ignore-user-config",
        "-m",
        "gpt-6-astra",
        "-c",
        'model_reasoning_effort="low"',
        "--skip-git-repo-check",
        prompt,
        cwd="/tmp",
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=55.0)
    if proc.returncode != 0:
        return None
    return _extract_json_dict(stdout.decode("utf-8", errors="ignore"))


async def _reason_with_anthropic_messages(
    api_key: str, base_url: str, model_name: str, user_payload: str
) -> Optional[Dict[str, Any]]:
    """Invoke Anthropic-compatible `/v1/messages` (cc-switch GLM-5 or Claude) with `trust_env=False` and `max_tokens=8192`."""
    url = f"{base_url.rstrip('/')}/v1/messages"
    async with httpx.AsyncClient(timeout=75.0, trust_env=False) as client:
        resp = await client.post(
            url,
            headers={
                "x-api-key": api_key,
                "Authorization": f"Bearer {api_key}",
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model_name,
                "max_tokens": 8192,
                "system": MASTER_AGENT_SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": user_payload}],
                "temperature": 0.3,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        text_blocks = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
        return _extract_json_dict("\n".join(text_blocks))


async def _reason_with_openai_compatible(
    api_key: str, base_url: str, model_name: str, user_payload: str
) -> Optional[Dict[str, Any]]:
    """Invoke OpenAI-compatible `/v1/chat/completions` (DeepSeek) with `trust_env=False`."""
    url = f"{base_url.rstrip('/')}/v1/chat/completions"
    if base_url.rstrip("/").endswith("/v1"):
        url = f"{base_url.rstrip('/')}/chat/completions"

    async with httpx.AsyncClient(timeout=65.0, trust_env=False) as client:
        resp = await client.post(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model_name,
                "messages": [
                    {"role": "system", "content": MASTER_AGENT_SYSTEM_PROMPT},
                    {"role": "user", "content": user_payload},
                ],
                "temperature": 0.3,
                "max_tokens": 8192,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        return _extract_json_dict(content)


def _merge_llm_spec(base_spec: Dict[str, Any], llm_spec: Dict[str, Any], engine_label: str) -> Dict[str, Any]:
    required = ["video_scenes"] if base_spec["task_type"] == "video" else ["slide_outline"]
    if base_spec["task_type"] == "composite":
        required.append("video_scenes")
    for key in required:
        if not isinstance(llm_spec.get(key), list) or not llm_spec[key]:
            raise ValueError(f"规划缺少 {key}，不能补入示例内容")
    merged = dict(base_spec)
    for k in (
        "task_summary_cn",
        "logical_reasoning_chain_cn",
        "master_outline_cn",
        "kpis",
        "slide_outline",
        "video_scenes",
    ):
        if llm_spec.get(k):
            merged[k] = llm_spec[k]
    merged["slide_count"] = len(merged.get("slide_outline", [])) or base_spec["slide_count"]
    merged["compiler_engine"] = engine_label
    merged["is_real_llm"] = True
    return _enrich_spec_with_prompts(merged)


def validate_direct_completion(event: Dict[str, Any], expected_spec=None) -> Dict[str, Any]:
    """Validate the direct worker's delivery contract before saving or settling it."""
    spec = event.get("compiled_spec") or {}
    qa = event.get("qa_report") or {}
    urls = event.get("cdn_urls") or {}
    count = len(spec.get("slide_outline") or [])
    if (not count or qa.get("status") != "PASSED"
            or any(qa.get(key) != count for key in ("planned_slides", "delivered_slides", "pptx_slides_count"))
            or not urls.get("pptx_url") or not urls.get("html_deck_url")
            or len(urls.get("slide_preview_urls") or []) != count):
        raise RuntimeError("直接生成未通过完整交付检查")
    if expected_spec is not None:
        for key in ("generation_contract", "original_prompt_cn", "matched_template"):
            if spec.get(key) != expected_spec.get(key):
                raise RuntimeError("PPT 交付与原始请求不一致")
        if (spec.get("generator_engine", "codex_cli") != expected_spec.get("generator_engine", "codex_cli")
                or (expected_spec.get("slide_count") and count != expected_spec["slide_count"])):
            raise RuntimeError("PPT 交付引擎或页数与请求不一致")
    return spec


async def compile_cn_request_to_english_spec(
    cn_prompt: str, task_type: str, extra_params: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Stage 1: Generate detailed PPT slide content (`slide_outline` + `markdown_slide_script`)
    and build the execution prompts (`codex_direct_prompt` / `claude_direct_prompt`) for Stage 2.
    """
    extra_params = extra_params or {}
    # Let the generating agent read the source and use skills in one context.
    # A local four-slide sample is never an acceptable replacement for user content.
    if task_type == "ppt":
        engine = resolve_ppt_engine(extra_params.get("execution_mode", "auto"))
        match = match_template_for_prompt(cn_prompt, extra_params.get("template_id", "auto"))
        count = int(extra_params.get("slide_count", 0))
        if not cn_prompt.strip() or not 0 <= count <= 60:
            raise ValueError("请输入原文，页数须为 0（自动）或 1–60")
        return {
            "generation_contract": "skill-direct-v1",
            "generator_engine": engine,
            "task_type": "ppt", "original_prompt_cn": cn_prompt,
            "task_summary_cn": cn_prompt.strip().splitlines()[0][:100],
            "template_id": match["template"]["id"], "matched_template": match["template"],
            "template_match_reason_cn": match["match_reason_cn"],
            "slide_count": count, "slide_count_mode": "fixed" if count else "auto",
            "slide_outline": [], "compiler_engine": f"{'Claude' if engine == 'claude_cli' else 'Codex'} 技能直出（等待实际规划）",
            "is_real_llm": False,
        }
    base_spec = _build_local_structured_spec(cn_prompt, task_type, extra_params)
    settings = get_runtime_settings()

    engine_pref = extra_params.get("master_reasoning_engine") or settings.get("master_reasoning_engine", "auto")
    local_cli = settings.get("local_cli_status", {})
    codex_bin = local_cli.get("codex_bin", "")
    codex_logged_in = local_cli.get("codex_logged_in", False)
    codex_model = local_cli.get("codex_model", "gpt-6-astra")

    ds_key = settings.get("deepseek_api_key", "").strip()
    ds_url = settings.get("deepseek_base_url", "https://api.deepseek.com").rstrip("/")
    ds_model = settings.get("deepseek_model", "deepseek-chat")

    anth_key = settings.get("anthropic_api_key", "").strip()
    anth_url = settings.get("anthropic_base_url", "https://api.anthropic.com").rstrip("/")
    anth_model = settings.get("claude_model", "glm-5")
    proxy_url = settings.get("account_safe_proxy", "").strip()

    raw_slide_count = int(extra_params.get("slide_count", 0))
    slide_count_instruction = (
        "AUTO (Unlimited / 不限页数 — freely determine the optimal number of slides based on the content depth and any page count mentioned in User Command)"
        if raw_slide_count <= 0
        else str(base_spec["slide_count"])
    )

    user_payload = (
        f"Task Type: {task_type}\n"
        f"Visual CI Template: {base_spec['matched_template']['name']} ({base_spec['template_id']})\n"
        f"Slide Count: {slide_count_instruction}\n"
        f"Video Duration: {extra_params.get('duration_seconds', 9)}s\n"
        f"User Command (Chinese): {cn_prompt}"
    )

    errors: List[str] = []

    # 1. If user explicitly asked for Codex as planner
    if engine_pref == "codex_login" and codex_bin and codex_logged_in:
        try:
            llm_spec = await _reason_with_codex_cli(codex_bin, user_payload, proxy_url=proxy_url)
            if llm_spec:
                return _merge_llm_spec(
                    base_spec,
                    llm_spec,
                    f"Real Codex Planner ({codex_model})",
                )
        except Exception as e:
            errors.append(f"Codex: {type(e).__name__}")

    # 2. Claude / GLM-5 Planner (Default in 'auto' or 'claude_login' mode, and automatic fallback if Codex planner timed out)
    if anth_key:
        try:
            llm_spec = await _reason_with_anthropic_messages(anth_key, anth_url, anth_model, user_payload)
            if llm_spec:
                return _merge_llm_spec(
                    base_spec,
                    llm_spec,
                    f"Claude 内容规划引擎 ({anth_model})",
                )
        except Exception as e:
            errors.append(f"Claude/GLM: {type(e).__name__}")

    # 3. Fallback to Codex CLI in 'auto' mode
    if engine_pref != "codex_login" and codex_bin and codex_logged_in:
        try:
            llm_spec = await _reason_with_codex_cli(codex_bin, user_payload, proxy_url=proxy_url)
            if llm_spec:
                return _merge_llm_spec(
                    base_spec,
                    llm_spec,
                    f"Real Codex Planner ({codex_model})",
                )
        except Exception as e:
            errors.append(f"Codex: {type(e).__name__}")

    # 4. DeepSeek API
    if ds_key:
        try:
            llm_spec = await _reason_with_openai_compatible(ds_key, ds_url, ds_model, user_payload)
            if llm_spec:
                return _merge_llm_spec(
                    base_spec,
                    llm_spec,
                    f"Real DeepSeek Planner ({ds_model})",
                )
        except Exception as e:
            errors.append(f"DeepSeek: {type(e).__name__}")

    raise RuntimeError("内容规划失败，未生成替代内容：" + "; ".join(errors or ["无可用规划模型"]))
