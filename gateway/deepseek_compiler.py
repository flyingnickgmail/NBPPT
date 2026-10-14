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
import re
from typing import Dict, Any, Optional, List
import httpx

from gateway.config import get_runtime_settings
from gateway.template_registry import match_template_for_prompt

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
    Instructs Codex to call its built-in `image_gen` tool for each slide, save each PNG to
    `./output/assets/slide_preview_<N>.png`, and assemble `./output/<job_id>_deck.pptx` using
    `~/.codex/skills/client-ci-ppt-image-deck/scripts/images_to_pptx.py`.
    """
    home_dir = str(pathlib.Path.home())
    img2pptx = f"{home_dir}/.codex/skills/client-ci-ppt-image-deck/scripts/images_to_pptx.py"
    slides = spec.get("slide_outline", [])
    total = len(slides)
    per_slide_blocks = []
    for idx, s in enumerate(slides, 1):
        img_p = s.get("image_gen_prompt", "")
        per_slide_blocks.append(
            f"=== SLIDE {idx} OF {total} (save to ./output/assets/slide_preview_{idx}.png) ===\n{img_p}"
        )

    return (
        f"You are executing a non-interactive PPT generation job in the current working directory.\n"
        f"Do NOT ask any clarifying questions. Do NOT scan unrelated directories.\n"
        f"Follow `$client-ci-ppt-image-deck` pure-image PPT workflow:\n"
        f"1. Call your built-in `image_gen` tool once for each of the {total} slides below to generate high-resolution 16:9 consulting slide images.\n"
        f"2. Immediately after generating each slide image, copy the generated PNG file from `~/.codex/generated_images/...` to `./output/assets/slide_preview_<N>.png` (where N is 1..{total}).\n"
        f"3. After all {total} slide images are saved in `./output/assets/`, assemble them into a 16:9 PowerPoint file by running:\n"
        f"   `python3 {img2pptx} --image-dir ./output/assets --out ./output/final_deck.pptx`\n\n"
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
    requested_tpl = extra_params.get("template_id", "auto")
    match_info = match_template_for_prompt(cn_prompt, requested_tpl)
    matched_tpl = match_info["template"]
    tpl_id = matched_tpl["id"]

    palette = VISUAL_PALETTES.get(tpl_id) or VISUAL_PALETTES["yonyou-ci-bg"]
    raw_slide_count = int(extra_params.get("slide_count", 0))
    if raw_slide_count <= 0:
        slide_count_mode = "unlimited"
        m_pages = re.search(r"(\d+)\s*页", cn_prompt)
        slide_count = max(2, min(15, int(m_pages.group(1)))) if m_pages else 4
    else:
        slide_count_mode = "fixed"
        slide_count = max(2, min(15, raw_slide_count))
    duration = int(extra_params.get("duration_seconds", 9))
    aspect_ratio = extra_params.get("aspect_ratio", "16:9")

    # Clean core topic from prompt
    clean_p = re.sub(r"^(帮我|请|使用|用|按照|基于|围绕|把|将)+", "", cn_prompt.strip())
    if "『" in cn_prompt and "』" in cn_prompt:
        topic = cn_prompt.split("『", 1)[1].split("』", 1)[0]
    else:
        topic = clean_p.split("，")[0].split("。")[0][:22] or "企业级AI智能体降本增效方案"

    slide_blueprints = [
        {
            "page_type": "executive-message",
            "kicker": "01 核心主张与目标",
            "action_title_cn": f"{topic}：核心价值主张与量化目标",
            "subtitle_cn": "从传统人工离散作业升级为 AI 数据驱动的端到端闭环体系",
            "cards": [
                {"header_cn": "综合成本压降", "metric_cn": "12-18%", "items_cn": ["智能比价与集采统谈", "消除历史价格信息孤岛"]},
                {"header_cn": "全链路周转提效", "metric_cn": "35-50%", "items_cn": ["需求与订单自动处理", "跨部门审批协同加速"]},
                {"header_cn": "履约与合规风控", "metric_cn": "24/7", "items_cn": ["供应商履约实时预警", "全流程可追溯合规审计"]},
            ],
            "bottom_flow_cn": ["统一数据底座", "AI 智能决策引擎", "可审计业务结果"],
            "bullets_cn": [
                "综合成本压降 12-18%：通过智能比价模型与跨事业部集采统谈，显著压缩溢价空间",
                "全链路周转提效 35-50%：打通需求预测、自动审单与合同合规审查全流程",
                "24/7 实时风控闭环：动态监测供应商交付准时率与质量波动，前置阻断断供风险",
            ],
        },
        {
            "page_type": "architecture-diagram",
            "kicker": "02 总体架构蓝图",
            "action_title_cn": "三层解耦智能体架构支撑全业务场景闭环",
            "subtitle_cn": "数据感知层、智能推理层与业务执行层标准协同",
            "cards": [
                {"header_cn": "统一数据感知层", "metric_cn": "100% 归集", "items_cn": ["ERP/SRM 主数据实时同步", "外部行情与舆情接入"]},
                {"header_cn": "多智能体推理层", "metric_cn": "毫秒级响应", "items_cn": ["寻源议价与库存预测算法", "红线合规规则自动校验"]},
                {"header_cn": "业务协同执行层", "metric_cn": "端到端闭环", "items_cn": ["人机协同确认机制", "异常工单秒级派发与回滚"]},
            ],
            "bottom_flow_cn": ["多源数据治理", "Agent 策略推演", "人工确认与执行"],
            "bullets_cn": [
                "统一数据感知层：归集主数据、历史交易流水与外部行情，消除口径不一致",
                "多智能体推理层：内置寻源比价、动态安全库存与合同风险识别三大专精模型",
                "业务协同执行层：严格保留关键节点人工确认与一键回滚机制，确保生产安全",
            ],
        },
        {
            "page_type": "roadmap",
            "kicker": "03 分阶段推进路线",
            "action_title_cn": "按准备、试点、验证与推广四步稳妥推进",
            "subtitle_cn": "以数据清单、合规口径与阶段验收基线驱动规模化落地",
            "cards": [
                {"header_cn": "阶段一：准备立项", "metric_cn": "M1-M2", "items_cn": ["数据盘点与权限合规", "锁定试点基线指标"]},
                {"header_cn": "阶段二：标杆试点", "metric_cn": "M3-M4", "items_cn": ["核心品类智能寻源上线", "对照组 ROI 实测验证"]},
                {"header_cn": "阶段三：全面推广", "metric_cn": "M5-M6", "items_cn": ["多事业部规模化复制", "考核指标固化与移交"]},
            ],
            "bottom_flow_cn": ["数据采集完整性", "AI 能力采纳率", "经审计业务 ROI"],
            "bullets_cn": [
                "阶段一（M1-M2 准备）：完成数据盘点、合规口径对齐与试点基线锁定",
                "阶段二（M3-M4 试点）：在核心业务单元跑通最小闭环，实测验证降本提效基线",
                "阶段三（M5-M6 推广）：通过效果评审后分区域推广，实现全集团指标固化",
            ],
        },
        {
            "page_type": "evidence-infographic",
            "kicker": "04 收益测算与保障",
            "action_title_cn": "量化投资回报清晰，红线门禁保障交付确定性",
            "subtitle_cn": "建立可量化、可归因、可退出的商业价值兑现机制",
            "cards": [
                {"header_cn": "投资回收周期", "metric_cn": "< 6 个月", "items_cn": ["首期试点即可收回投入", "边际扩展成本极低"]},
                {"header_cn": "数据与合规门禁", "metric_cn": "零越权", "items_cn": ["核心账套只读不写", "关键审批保留人工确认"]},
                {"header_cn": "组织与运维移交", "metric_cn": "100% 赋能", "items_cn": ["提供标准 SOP 与培训", "支持驻场联调与陪跑"]},
            ],
            "bottom_flow_cn": ["基线对赌锁定", "合规门禁守护", "季度价值审计"],
            "bullets_cn": [
                "高确定性 ROI：首期试点预计 6 个月内收回投资，年化净节约显著",
                "严格安全红线：默认只读接入核心业务系统，关键价格与合同审批100%人工确认",
                "长效运维机制：配套标准化操作手册与业务团队赋能，确保系统高采纳率",
            ],
        },
    ]

    slides = []
    for i in range(1, slide_count + 1):
        bp = dict(slide_blueprints[(i - 1) % len(slide_blueprints)])
        bp["slide_num"] = i
        bp["kicker"] = f"0{i} {bp['kicker'].split(' ', 1)[-1]}"
        slides.append(bp)

    spec = {
        "task_type": task_type,
        "original_prompt_cn": cn_prompt,
        "task_summary_cn": f"围绕「{topic}」构建高确定性商业汇报方案",
        "template_id": tpl_id,
        "matched_template": {
            "id": tpl_id,
            "gorden_slug": matched_tpl.get("gorden_slug", ""),
            "skill_engine": matched_tpl.get("skill_engine", ""),
            "name": matched_tpl["name"],
            "badge": matched_tpl["badge"],
            "source_skill": matched_tpl["source_skill"],
            "real_pptx_path": matched_tpl.get("real_pptx_path", ""),
            "preview_url": matched_tpl.get("preview_url", ""),
            "match_mode": match_info["match_mode"],
            "match_reason_cn": match_info["match_reason_cn"],
        },
        "visual_style": tpl_id,
        "slide_count": slide_count,
        "slide_count_mode": slide_count_mode,
        "video_duration_sec": duration,
        "video_aspect_ratio": aspect_ratio,
        "compiler_engine": "local-heuristic-fallback",
        "is_real_llm": False,
        "palette": palette,
        "logical_reasoning_chain_cn": [
            f"1. 详细内容规划：围绕「{topic}」梳理 {slide_count} 页金字塔结构与每页模块卡片。",
            f"2. 视觉体系锁定：{match_info['match_reason_cn']}。",
            f"3. 执行提示词生成：已按 16:9 咨询级纯图片 PPT 规范生成逐页 `image_gen` 提示词与标准 Markdown 脚本。",
        ],
        "master_outline_cn": {
            "core_thesis": f"通过标准化智能架构推进「{topic}」，实现可量化、可审计的降本增效闭环",
            "narrative_arc": "核心主张与目标 → 总体架构蓝图 → 分阶段推进路线 → 收益测算与保障",
            "key_pillars": [s["action_title_cn"] for s in slides[:4]],
        },
        "kpis": [
            {"label": "综合成本优化", "value": "12-18%", "delta": "智能比价与集采"},
            {"label": "流程周转提效", "value": "35-50%", "delta": "端到端自动协同"},
            {"label": "合规风控覆盖", "value": "24/7", "delta": "实时预警与审计"},
            {"label": "投资回收周期", "value": "<6个月", "delta": "试点快速验证"},
        ],
        "slide_outline": slides,
        "video_scenes": [
            {
                "scene_id": 1,
                "duration_sec": max(2, duration // 3),
                "motion_template": "node_topology",
                "title_cn": topic[:18],
                "subtitle_cn": "多智能体协同拓扑与数据底座",
                "data_nodes_cn": ["数据感知", "AI推理", "策略寻源", "风控闭环"],
                "metric_highlight": "8.5x",
            },
            {
                "scene_id": 2,
                "duration_sec": max(2, duration // 3),
                "motion_template": "bar_race_chart",
                "title_cn": "降本增效分阶段兑现曲线",
                "subtitle_cn": "试点期至全面推广期效能跃升",
                "data_nodes_cn": ["准备期", "试点一", "试点二", "全面推广"],
                "metric_highlight": "+320%",
            },
            {
                "scene_id": 3,
                "duration_sec": max(2, duration - 2 * (duration // 3)),
                "motion_template": "radial_kpi_matrix",
                "title_cn": "核心经营指标达成全景",
                "subtitle_cn": "全链路可追溯 ROI 审计闭环",
                "data_nodes_cn": ["成本-15%", "提效+45%", "合规100%"],
                "metric_highlight": "99.2%",
            },
        ],
    }
    return _enrich_spec_with_prompts(spec)


async def _reason_with_codex_cli(codex_bin: str, user_payload: str, proxy_url: str = "") -> Optional[Dict[str, Any]]:
    """Invoke the user's logged-in Codex CLI (`codex exec --ignore-user-config`) for fast outline planning."""
    env = os.environ.copy()
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


async def compile_cn_request_to_english_spec(
    cn_prompt: str, task_type: str, extra_params: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Stage 1: Generate detailed PPT slide content (`slide_outline` + `markdown_slide_script`)
    and build the execution prompts (`codex_direct_prompt` / `claude_direct_prompt`) for Stage 2.
    """
    extra_params = extra_params or {}
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

    if errors:
        base_spec["compiler_engine"] = f"本地规划兜底 ({'; '.join(errors)[:60]})"
    return base_spec
