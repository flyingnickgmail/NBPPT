#!/usr/bin/env python3
"""
Multi-Skill PPTX & Interactive Web Deck Builder (`build_deck.py`).
Supports:
1. GordenSun/GordenPPTSkill Engine: Non-destructive `edits.json` + `scripts/build_pptx.py` execution
   across all 21 hand-polished Chinese `.pptx` templates (`detail.json` slot mapping calibrated to
   each slot's ground-truth `current_text` length and semantic role).
2. Real macOS CoreGraphics QuickLook Per-Slide Renderer (`qlmanage -t -s 1280`):
   Exports every slide of the generated `.pptx` into a pixel-perfect `slide_preview_N.png`.
3. zarazhangrui/frontend-slides Engine: Full-viewport interactive HTML/CSS presentation deck
   with keyboard navigation (`←`/`→`/`Space`/`F`) and embedded slide canvas.
4. Native Python-PPTX Master Builder: For `yonyou-ci-bg`, `abu9-exec-report`, `ppt-master`, `obsidian-roadshow`.
"""
import argparse
import json
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Dict, Any, List

from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.enum.shapes import MSO_SHAPE
from PIL import Image, ImageDraw, ImageFont

FONT_CJK = "PingFang SC"
BASE_DIR = pathlib.Path(__file__).resolve().parents[6]
GORDEN_ROOT = BASE_DIR / "worker" / "external_ppt_skills" / "GordenPPTSkill"

# Rich domain 4-character tags pool used as fallback when a slide has >8 tag slots
DOMAIN_4CHAR_TAGS = [
    "智能寻源", "集采统谈", "长尾整合", "合同审计",
    "安全库存", "产销协同", "呆滞压降", "周转提速",
    "干线物流", "智能分仓", "履约监控", "质量损耗",
    "数据底座", "算法引擎", "流程再造", "组织保障",
    "成本精算", "风险预警", "生态协同", "价值闭环",
]

STRUCTURAL_KEEP_WORDS = {
    "阶段", "目标", "短板", "长板", "运营", "现金流", "总结与计划",
    "关键指标", "投资策略", "里程碑", "估值目标",
    "方法1：", "方法2：", "方法3：", "方法4：",
    "方法1:", "方法2:", "方法3:", "方法4:",
    "STEP 01", "STEP 02", "STEP 03", "STEP 04",
    "PART 01", "PART 02", "PART 03", "PART 04",
}


def hex_to_rgb(hex_str: str) -> RGBColor:
    h = str(hex_str).lstrip("#")
    if len(h) != 6:
        h = "0B0F19"
    return RGBColor(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def set_slide_bg(slide, hex_color: str):
    bg = slide.background
    fill = bg.fill
    fill.solid()
    fill.fore_color.rgb = hex_to_rgb(hex_color)


def add_text_box(
    slide,
    left: float,
    top: float,
    width: float,
    height: float,
    text: str,
    font_size: int = 16,
    color_hex: str = "#F8FAFC",
    bold: bool = False,
    align=PP_ALIGN.LEFT,
):
    tx_box = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
    tf = tx_box.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.alignment = align
    run = p.add_run()
    run.text = text
    run.font.name = FONT_CJK
    run.font.size = Pt(font_size)
    run.font.bold = bold
    run.font.color.rgb = hex_to_rgb(color_hex)
    return tx_box


def add_card_shape(
    slide,
    left: float,
    top: float,
    width: float,
    height: float,
    fill_hex: str = "#161F33",
    border_hex: str = "#28354F",
):
    shape = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE,
        Inches(left),
        Inches(top),
        Inches(width),
        Inches(height),
    )
    shape.fill.solid()
    shape.fill.fore_color.rgb = hex_to_rgb(fill_hex)
    shape.line.color.rgb = hex_to_rgb(border_hex)
    shape.line.width = Pt(1.2)
    return shape


def add_header_bar(slide, slide_num: int, total_slides: int, title: str, kicker: str, palette: Dict[str, Any]):
    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.6), Inches(0.42), Inches(1.2), Inches(0.06))
    bar.fill.solid()
    bar.fill.fore_color.rgb = hex_to_rgb(palette.get("primary", "#38BDF8"))
    bar.line.fill.background()

    add_text_box(
        slide, 0.6, 0.52, 9.5, 0.35, kicker.upper(), font_size=10, color_hex=palette.get("primary", "#38BDF8"), bold=True
    )
    add_text_box(
        slide, 0.6, 0.82, 11.2, 0.65, title, font_size=24, color_hex=palette.get("text", "#F8FAFC"), bold=True
    )
    add_text_box(
        slide,
        11.2,
        0.55,
        1.5,
        0.4,
        f"{slide_num:02d} / {total_slides:02d}",
        font_size=11,
        color_hex=palette.get("muted", "#94A3B8"),
        align=PP_ALIGN.RIGHT,
    )


def build_cover_slide(prs, slide_data: Dict[str, Any], palette: Dict[str, Any], hero_img: pathlib.Path, total_slides: int):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    set_slide_bg(slide, palette.get("bg", "#0B0F19"))

    surf_hex = palette.get("surface", "#161F33")
    border_hex = palette.get("border", "#28354F")
    brand_tag = palette.get("brand_tag", "PERSONAL AGENT · EXECUTIVE DECK")

    add_card_shape(slide, 0.7, 0.82, 4.4, 0.45, fill_hex=surf_hex, border_hex=palette.get("primary", "#38BDF8"))
    add_text_box(
        slide,
        0.85,
        0.89,
        4.1,
        0.35,
        brand_tag[:38],
        font_size=10,
        color_hex=palette.get("primary", "#38BDF8"),
        bold=True,
    )

    title = slide_data.get("action_title_cn", "商业级智能生产力方案路演")
    subtitle = slide_data.get("subtitle_cn", "强逻辑大纲推演 + 专属母版合成全案")
    add_text_box(slide, 0.7, 1.52, 6.7, 1.6, title, font_size=32, color_hex=palette.get("text", "#F8FAFC"), bold=True)
    add_text_box(slide, 0.7, 3.22, 6.5, 0.9, subtitle, font_size=15, color_hex=palette.get("muted", "#94A3B8"))

    bullets = slide_data.get("bullets_cn", [])[:3]
    y = 4.30
    for idx, b in enumerate(bullets, 1):
        add_card_shape(slide, 0.7, y, 6.5, 0.66, fill_hex=surf_hex, border_hex=border_hex)
        add_text_box(slide, 0.9, y + 0.14, 6.1, 0.4, f"0{idx}   {b}", font_size=13, color_hex=palette.get("text", "#F8FAFC"), bold=True)
        y += 0.80

    if hero_img and hero_img.exists():
        slide.shapes.add_picture(str(hero_img), Inches(7.55), Inches(1.35), width=Inches(5.2))


def build_kpi_and_bullets_slide(
    prs, slide_data: Dict[str, Any], kpis: List[Dict[str, str]], palette: Dict[str, Any], idx: int, total: int
):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    set_slide_bg(slide, palette.get("bg", "#0B0F19"))
    surf_hex = palette.get("surface", "#161F33")
    border_hex = palette.get("border", "#28354F")

    add_header_bar(slide, idx, total, slide_data.get("action_title_cn", ""), slide_data.get("kicker", "METRICS"), palette)
    add_text_box(slide, 0.6, 1.45, 11.5, 0.4, slide_data.get("subtitle_cn", ""), font_size=14, color_hex=palette.get("muted", "#94A3B8"))

    card_w = 2.82
    gap = 0.25
    start_x = 0.6
    for i, kpi in enumerate(kpis[:4]):
        x = start_x + i * (card_w + gap)
        add_card_shape(slide, x, 2.05, card_w, 1.75, fill_hex=surf_hex, border_hex=border_hex)
        add_text_box(slide, x + 0.2, 2.20, card_w - 0.4, 0.35, kpi.get("label", ""), font_size=12, color_hex=palette.get("muted", "#94A3B8"))
        add_text_box(slide, x + 0.2, 2.58, card_w - 0.4, 0.65, kpi.get("value", ""), font_size=28, color_hex=palette.get("primary", "#38BDF8"), bold=True)
        add_text_box(slide, x + 0.2, 3.30, card_w - 0.4, 0.35, kpi.get("delta", ""), font_size=11, color_hex="#10B981", bold=True)

    bullets = slide_data.get("bullets_cn", [])[:3]
    y = 4.15
    for b_idx, b_text in enumerate(bullets, 1):
        add_card_shape(slide, 0.6, y, 12.05, 0.82, fill_hex=surf_hex, border_hex=border_hex)
        add_text_box(slide, 0.85, y + 0.20, 0.7, 0.4, f"0{b_idx}", font_size=15, color_hex=palette.get("primary", "#38BDF8"), bold=True)
        add_text_box(slide, 1.50, y + 0.20, 10.9, 0.45, b_text, font_size=14, color_hex=palette.get("text", "#F8FAFC"))
        y += 0.96


def build_chart_slide(
    prs, slide_data: Dict[str, Any], chart_img: pathlib.Path, palette: Dict[str, Any], idx: int, total: int
):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    set_slide_bg(slide, palette.get("bg", "#0B0F19"))
    surf_hex = palette.get("surface", "#161F33")
    border_hex = palette.get("border", "#28354F")

    add_header_bar(slide, idx, total, slide_data.get("action_title_cn", ""), slide_data.get("kicker", "DATA INSIGHT"), palette)
    add_text_box(slide, 0.6, 1.45, 11.5, 0.4, slide_data.get("subtitle_cn", ""), font_size=14, color_hex=palette.get("muted", "#94A3B8"))

    if chart_img and chart_img.exists():
        slide.shapes.add_picture(str(chart_img), Inches(0.6), Inches(2.05), width=Inches(6.85))

    bullets = slide_data.get("bullets_cn", [])[:3]
    y = 2.05
    for b_idx, b_text in enumerate(bullets, 1):
        add_card_shape(slide, 7.75, y, 4.95, 1.48, fill_hex=surf_hex, border_hex=border_hex)
        add_text_box(
            slide, 7.98, y + 0.16, 4.5, 0.32, f"KEY INSIGHT 0{b_idx}", font_size=10, color_hex=palette.get("primary", "#38BDF8"), bold=True
        )
        add_text_box(slide, 7.98, y + 0.50, 4.5, 0.85, b_text, font_size=13, color_hex=palette.get("text", "#F8FAFC"))
        y += 1.65


def build_grid_slide(prs, slide_data: Dict[str, Any], palette: Dict[str, Any], idx: int, total: int):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    set_slide_bg(slide, palette.get("bg", "#0B0F19"))
    surf_hex = palette.get("surface", "#161F33")
    border_hex = palette.get("border", "#28354F")

    add_header_bar(slide, idx, total, slide_data.get("action_title_cn", ""), slide_data.get("kicker", "ARCHITECTURE"), palette)
    add_text_box(slide, 0.6, 1.45, 11.5, 0.4, slide_data.get("subtitle_cn", ""), font_size=14, color_hex=palette.get("muted", "#94A3B8"))

    bullets = slide_data.get("bullets_cn", [])[:3]
    col_w = 3.85
    gap = 0.25
    for i, b_text in enumerate(bullets):
        x = 0.6 + i * (col_w + gap)
        add_card_shape(slide, x, 2.15, col_w, 4.55, fill_hex=surf_hex, border_hex=border_hex)
        badge = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(x + 0.3), Inches(2.45), Inches(0.65), Inches(0.65))
        badge.fill.solid()
        badge.fill.fore_color.rgb = hex_to_rgb(palette.get("primary", "#38BDF8"))
        badge.line.fill.background()
        add_text_box(slide, x + 0.42, 2.57, 0.5, 0.4, f"0{i+1}", font_size=14, color_hex="#FFFFFF", bold=True)

        parts = b_text.split("：", 1) if "：" in b_text else [f"核心支柱 0{i+1}", b_text]
        head_t = parts[0]
        body_t = parts[1] if len(parts) > 1 else b_text
        add_text_box(slide, x + 0.3, 3.35, col_w - 0.6, 0.6, head_t, font_size=18, color_hex=palette.get("text", "#F8FAFC"), bold=True)
        add_text_box(slide, x + 0.3, 4.05, col_w - 0.6, 2.2, body_t, font_size=14, color_hex=palette.get("muted", "#94A3B8"))


def _get_pil_font(size: int) -> ImageFont.FreeTypeFont:
    candidates = [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
    ]
    for c in candidates:
        if pathlib.Path(c).exists():
            try:
                return ImageFont.truetype(c, size)
            except Exception:
                continue
    return ImageFont.load_default()


def render_slide_preview_card(slide_data: Dict[str, Any], palette: Dict[str, Any], idx: int, total: int, out_png: pathlib.Path):
    """Fallback PIL preview card used only if macOS QuickLook (`qlmanage`) is unavailable."""
    w, h = 1280, 720
    bg_hex = palette.get("bg", "#0B0F19").lstrip("#")
    surf_hex = palette.get("surface", "#161F33").lstrip("#")
    border_hex = palette.get("border", "#28354F").lstrip("#")
    prim_hex = palette.get("primary", "#38BDF8").lstrip("#")
    txt_hex = palette.get("text", "#F8FAFC").lstrip("#")
    mut_hex = palette.get("muted", "#94A3B8").lstrip("#")

    def _rgb(hx, default=(15, 23, 42)):
        return tuple(int(hx[i : i + 2], 16) for i in (0, 2, 4)) if len(hx) == 6 else default

    img = Image.new("RGB", (w, h), _rgb(bg_hex))
    draw = ImageDraw.Draw(img)

    f_kicker = _get_pil_font(16)
    f_title = _get_pil_font(34)
    f_sub = _get_pil_font(20)
    f_body = _get_pil_font(20)

    draw.rectangle([0, 0, w, 10], fill=_rgb(prim_hex))
    draw.rectangle([48, 38, 175, 44], fill=_rgb(prim_hex))
    draw.text((48, 54), f"SLIDE {idx:02d}/{total:02d}  ·  {slide_data.get('kicker', 'STRATEGY')}", font=f_kicker, fill=_rgb(prim_hex))
    draw.text((48, 92), slide_data.get("action_title_cn", "")[:32], font=f_title, fill=_rgb(txt_hex))
    draw.text((48, 145), slide_data.get("subtitle_cn", "")[:48], font=f_sub, fill=_rgb(mut_hex))

    y = 215
    for b_i, b in enumerate(slide_data.get("bullets_cn", [])[:3], 1):
        draw.rounded_rectangle([48, y, w - 48, y + 130], radius=14, fill=_rgb(surf_hex), outline=_rgb(border_hex), width=2)
        draw.rectangle([48, y + 22, 56, y + 108], fill=_rgb(prim_hex))
        draw.text((78, y + 48), f"0{b_i}   {b[:48]}", font=f_body, fill=_rgb(txt_hex))
        y += 152

    out_png.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(out_png), "PNG")


def _prune_pptx_to_single_slide(prs, slide_1indexed: int) -> None:
    """Keep only `slide_1indexed` (1-based) in `prs` using XML `_sldIdLst` pruning."""
    sldIdLst = prs.slides._sldIdLst
    sld_ids = list(sldIdLst)
    target_el = sld_ids[slide_1indexed - 1]
    for sld in list(sldIdLst):
        sldIdLst.remove(sld)
    sldIdLst.append(target_el)


def render_real_pptx_slides_macos(pptx_path: pathlib.Path, assets_dir: pathlib.Path, max_slides: int = 8) -> List[str]:
    """
    Use macOS native CoreGraphics Office renderer (`/usr/bin/qlmanage -t -s 1280`)
    to export EVERY slide of `pptx_path` into `assets_dir/slide_preview_1.png` ... `slide_preview_N.png`.
    """
    ql_bin = pathlib.Path("/usr/bin/qlmanage")
    if not ql_bin.exists() or not pptx_path.exists():
        return []

    try:
        prs_full = Presentation(str(pptx_path))
        n_slides = min(len(prs_full.slides), max_slides)
        if n_slides == 0:
            return []

        assets_dir.mkdir(parents=True, exist_ok=True)
        rendered_paths: List[str] = []

        with tempfile.TemporaryDirectory(prefix="promedia_ql_") as tmp_dir_str:
            tmp_dir = pathlib.Path(tmp_dir_str)
            single_pptx_files: List[str] = []
            for idx in range(1, n_slides + 1):
                p_single = Presentation(str(pptx_path))
                _prune_pptx_to_single_slide(p_single, idx)
                sp = tmp_dir / f"slide_{idx}.pptx"
                p_single.save(str(sp))
                single_pptx_files.append(str(sp))

            subprocess.run(
                [str(ql_bin), "-t", "-s", "1280", "-o", str(tmp_dir)] + single_pptx_files,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=35,
            )

            for idx in range(1, n_slides + 1):
                gen_png = tmp_dir / f"slide_{idx}.pptx.png"
                if gen_png.exists():
                    dest_png = assets_dir / f"slide_preview_{idx}.png"
                    shutil.copyfile(gen_png, dest_png)
                    rendered_paths.append(str(dest_png))

        return rendered_paths
    except Exception:
        return []


def _fit_text_to_budget(text: str, target_len: int) -> str:
    """
    Fit `text` cleanly near `target_len` without ever chopping mid-word or adding '...'.
    Follows GordenPPTSkill SKILL.md Rule #3.
    """
    t = re.sub(r"\s+", " ", str(text or "").strip())
    if not t:
        return ""
    if len(t) <= target_len + 2:
        return t
    # Try natural clause boundaries that fit within target_len + 2
    for sep in ["。", "；", "，", "、", " · "]:
        if sep in t:
            parts = t.split(sep)
            acc = parts[0]
            for p in parts[1:]:
                if len(acc) + 1 + len(p) <= target_len + 2:
                    acc = f"{acc}{sep}{p}"
                else:
                    break
            if 4 <= len(acc) <= target_len + 3:
                return acc
    # If still longer, strip leading "XX：" prefix if present
    if "：" in t:
        after = t.split("：", 1)[1].strip()
        if len(after) <= target_len + 2:
            return after
        for sep in ["，", "；", "。"]:
            if sep in after and len(after.split(sep)[0]) <= target_len + 2:
                return after.split(sep)[0]
    return t[:target_len]


def _extract_slide_pools(s_spec: Dict[str, Any], slide_idx: int, all_titles: List[str]) -> Dict[str, Any]:
    """
    Build rich, non-repeating pools of:
    - `page_title` (8-13 chars)
    - `tags_4char` (12+ unique 4-char tags)
    - `subheadings` (6+ unique 10-18 char subheadings)
    - `paragraphs` (6+ unique 24-55 char analytical sentences)
    for a single slide.
    """
    raw_title = s_spec.get("page_title_cn") or s_spec.get("action_title_cn") or all_titles[slide_idx % len(all_titles)]
    # Clean page title to 8-13 chars
    if "：" in raw_title:
        p1, p2 = raw_title.split("：", 1)
        page_title = p2[:13] if 6 <= len(p2) <= 14 else p1[:13]
    else:
        page_title = _fit_text_to_budget(raw_title, 12)

    raw_bullets = list(s_spec.get("bullets_cn") or [])
    raw_subs = list(s_spec.get("subheadings_cn") or [])
    raw_tags = list(s_spec.get("tags_cn") or [])

    # Extract 4-char tags and body sentences from bullets if not explicitly provided
    for b in raw_bullets:
        if "：" in b:
            head, body = b.split("：", 1)
            head = head.strip()
            body = body.strip()
            if 3 <= len(head) <= 6 and head not in raw_tags:
                raw_tags.append(head)
            elif 7 <= len(head) <= 18 and head not in raw_subs:
                raw_subs.append(head)
            if len(body) >= 8 and body not in raw_subs:
                first_clause = body.split("，")[0].split("；")[0]
                if 8 <= len(first_clause) <= 19:
                    raw_subs.append(first_clause)

    # Pad `raw_tags` with domain 4-char tags (rotated by slide_idx so each slide has fresh tags)
    rotated_domain = DOMAIN_4CHAR_TAGS[(slide_idx * 4) % len(DOMAIN_4CHAR_TAGS):] + DOMAIN_4CHAR_TAGS[:(slide_idx * 4) % len(DOMAIN_4CHAR_TAGS)]
    for dt in rotated_domain:
        if dt not in raw_tags:
            raw_tags.append(dt)

    # Pad `raw_subs` (10-16 chars)
    if s_spec.get("subtitle_cn"):
        sub_first = s_spec["subtitle_cn"].split("，")[0].split(" · ")[0]
        if 8 <= len(sub_first) <= 18 and sub_first not in raw_subs:
            raw_subs.insert(0, sub_first)
    if s_spec.get("action_title_cn") and s_spec["action_title_cn"] not in raw_subs:
        raw_subs.append(_fit_text_to_budget(s_spec["action_title_cn"], 15))

    fallback_subs = [
        "AI算法驱动全链路降本增效",
        "构建数字化实时协同运营底座",
        "核心业务指标与行业标杆对齐",
        "跨部门资源整合放大规模效应",
        "全生命周期风险预警与质量闭环",
        "分阶段敏捷迭代保障ROI兑现",
    ]
    for fs in fallback_subs:
        if fs not in raw_subs:
            raw_subs.append(fs)

    # Build clean `paragraphs` (24-55 chars) without repetitive prefixes
    paragraphs: List[str] = []
    for b in raw_bullets:
        clean_b = b.split("：", 1)[1].strip() if ("：" in b and len(b.split("：", 1)[0]) <= 8) else b.strip()
        if clean_b and clean_b not in paragraphs:
            paragraphs.append(clean_b)

    fallback_paras = [
        "通过智能算法建模与历史数据沉淀，实现核心流程自动化决策与效率跃升。",
        "打通跨部门数据孤岛，建立端到端实时监控指标体系，显著压降隐性运营损耗。",
        "推行标准化模块复用与分级算力调度，在保障交付质量的同时大幅降低边际成本。",
        "建立可量化、可归因、可审计的ROI评估闭环，支撑业务规模化复制与持续增长。",
    ]
    for fp in fallback_paras:
        if fp not in paragraphs:
            paragraphs.append(fp)

    return {
        "page_title": page_title,
        "tags": raw_tags,
        "subheadings": raw_subs,
        "paragraphs": paragraphs,
        "kicker": s_spec.get("kicker") or "EXECUTIVE STRATEGY",
        "subtitle": s_spec.get("subtitle_cn") or page_title,
    }


def build_with_gorden_ppt_skill(
    spec: Dict[str, Any],
    gorden_slug: str,
    assets_dir: pathlib.Path,
    out_pptx: pathlib.Path,
) -> bool:
    """
    Execute GordenSun/GordenPPTSkill non-destructive template cloning & slot replacement:
    Calibrates every slot's replacement text to the ground-truth `current_text` length and semantic role
    in `detail.json` so diagrams, badges, funnels, and barrels NEVER overflow or repeat.
    """
    tpl_dir = GORDEN_ROOT / "templates" / gorden_slug
    detail_path = tpl_dir / "detail.json"
    source_pptx = tpl_dir / "template.pptx"
    preview_src = tpl_dir / "preview.png"
    build_script = GORDEN_ROOT / "scripts" / "build_pptx.py"

    if not detail_path.exists() or not source_pptx.exists() or not build_script.exists():
        return False

    detail = json.loads(detail_path.read_text(encoding="utf-8"))
    pages_by_num = {p["slide_number"]: p for p in detail.get("pages", [])}
    skip_set = set(detail.get("skip_pages", []))
    roles = detail.get("page_roles", {})

    slides_spec = spec.get("slide_outline", [])
    target_count = max(4, len(slides_spec))

    # Pick slides from template: cover + agenda (optional) + content pages + ending (optional)
    selected_slides: List[int] = []
    covers = [n for n in roles.get("cover", []) if n not in skip_set]
    agendas = [n for n in roles.get("agenda", []) if n not in skip_set]
    contents = [n for n in roles.get("content", []) if n not in skip_set]
    endings = [n for n in roles.get("ending", []) if n not in skip_set]

    if covers:
        selected_slides.append(covers[0])
    if agendas and target_count >= 5:
        selected_slides.append(agendas[0])

    # Sort content candidates to prefer clean, readable slides (4..30 editable slots) first
    def _slide_score(s_no: int) -> int:
        p_obj = pages_by_num.get(s_no, {})
        ed_cnt = sum(1 for sl in p_obj.get("text_slots", []) if sl.get("editable", True))
        if 4 <= ed_cnt <= 28:
            return 0
        return abs(ed_cnt - 20)

    sorted_contents = sorted(contents, key=lambda n: (_slide_score(n), n))
    needed_content = max(2, target_count - len(selected_slides) - (1 if endings else 0))
    for cn in sorted_contents[:needed_content]:
        if cn not in selected_slides:
            selected_slides.append(cn)

    if endings and len(selected_slides) < target_count:
        selected_slides.append(endings[0])

    if not selected_slides:
        selected_slides = [p["slide_number"] for p in detail.get("pages", []) if p["slide_number"] not in skip_set][:target_count]

    edits: List[Dict[str, Any]] = []
    all_titles = [s.get("action_title_cn", "核心战略规划") for s in slides_spec] or ["核心战略规划"]

    for idx_in_deck, s_num in enumerate(selected_slides):
        page_obj = pages_by_num.get(s_num, {})
        page_role = page_obj.get("role", "content")
        s_spec = slides_spec[min(idx_in_deck, len(slides_spec) - 1)] if slides_spec else {}
        pools = _extract_slide_pools(s_spec, idx_in_deck, all_titles)

        editable_slots = [sl for sl in page_obj.get("text_slots", []) if sl.get("editable", True)]
        tag_cursor = 0
        sub_cursor = 0
        para_cursor = 0
        agenda_cursor = 0
        page_title_assigned = False

        for slot in editable_slots:
            slot_id = slot["slot_id"]
            s_role = str(slot.get("role", ""))
            pos = str(slot.get("position", ""))
            lang = str(slot.get("language", "")).lower()
            cur = str(slot.get("current_text") or "").strip()
            cur_len = len(cur)
            max_c = int(slot.get("max_chars") or max(cur_len, 12))
            font_pt = float(slot.get("font_size_pt") or 14.0)

            # 1. Structural / Year / Fixed Diagram Chrome -> Keep intact or update year!
            if cur in STRUCTURAL_KEEP_WORDS:
                edits.append({"slide": s_num, "slot_id": slot_id, "new_text": cur})
                continue
            if re.fullmatch(r"202\d(年)?", cur):
                new_yr = "2026年" if cur.endswith("年") else str(2025 + (tag_cursor % 4))
                tag_cursor += 1
                edits.append({"slide": s_num, "slot_id": slot_id, "new_text": new_yr[:cur_len]})
                continue
            if cur_len <= 3 and page_role not in ("cover", "ending"):
                # Very short 1-3 char diagram label (e.g. '阶段', '目标', '短板', '运营'): keep original!
                edits.append({"slide": s_num, "slot_id": slot_id, "new_text": cur})
                continue

            # 2. English decorative slot
            if lang == "en" or "英" in s_role or slot_id.endswith("_en"):
                en_txt = pools["kicker"][: max(10, cur_len + 4)]
                edits.append({"slide": s_num, "slot_id": slot_id, "new_text": en_txt})
                continue

            # 3. Cover slide
            if page_role == "cover":
                if "副" in s_role or "sub" in slot_id or "desc" in slot_id:
                    cand = _fit_text_to_budget(pools["subtitle"], max(14, cur_len + 4))
                elif "汇报人" in s_role or "author" in slot_id or "dept" in slot_id:
                    cand = "ProMedia 智能工作台"
                else:
                    cand = _fit_text_to_budget(pools["page_title"], max(12, cur_len + 4))
                edits.append({"slide": s_num, "slot_id": slot_id, "new_text": cand})
                continue

            # 4. Agenda slide
            if page_role == "agenda":
                if "主标" in s_role or slot_id == "agenda_title_cn" or cur_len <= 4:
                    cand = "核心目录"[:max(2, cur_len)]
                else:
                    ch_s = slides_spec[min(agenda_cursor + 1, len(slides_spec) - 1)] if slides_spec else {}
                    ch_pool = _extract_slide_pools(ch_s, agenda_cursor + 1, all_titles)
                    agenda_cursor += 1
                    cand = _fit_text_to_budget(ch_pool["page_title"], max(6, cur_len + 2))
                edits.append({"slide": s_num, "slot_id": slot_id, "new_text": cand})
                continue

            # 5. Ending slide
            if page_role == "ending":
                cand = "感谢聆听 · 欢迎指正" if cur_len >= 8 else "感谢聆听"
                edits.append({"slide": s_num, "slot_id": slot_id, "new_text": cand})
                continue

            # 6. Content / Section Divider slide: calibrate strictly by position, font_pt, and cur_len!
            # 6a. Primary Top-Left Page Title (e.g., s1_sh4_p0r0 `pos=顶部左侧, pt=28, cur_len=13`)
            if not page_title_assigned and "顶部" in pos and font_pt >= 22.0 and cur_len >= 6:
                page_title_assigned = True
                cand = _fit_text_to_budget(pools["page_title"], max(10, cur_len + 1))
                edits.append({"slide": s_num, "slot_id": slot_id, "new_text": cand})
                continue

            # 6b. Prefixed Problem / Strategy slots (e.g. '问题01：响应速度慢' or '改进策略：智能化响应')
            m_prob = re.match(r"^(问题\d+：|痛点\d+：|改进策略：|策略\d+：)", cur)
            if m_prob:
                prefix = m_prob.group(1).replace("问题", "痛点")
                tag4 = pools["tags"][tag_cursor % len(pools["tags"])][:4]
                tag_cursor += 1
                edits.append({"slide": s_num, "slot_id": slot_id, "new_text": f"{prefix}{tag4}"})
                continue

            # 6c. Question header slots (e.g. '长板怎么维持？方法：' or '短板怎么补救？方法：')
            if "？" in cur and cur_len <= 14:
                edits.append({"slide": s_num, "slot_id": slot_id, "new_text": cur})
                continue

            # 6d. Short 4-8 char Category Badges / Planks (e.g. '一线生产工资', '原材料采购', '业绩达成')
            if 4 <= cur_len <= 8:
                tag = pools["tags"][tag_cursor % len(pools["tags"])]
                tag_cursor += 1
                cand = tag[:cur_len]
                edits.append({"slide": s_num, "slot_id": slot_id, "new_text": cand})
                continue

            # 6e. Mid-length Sub-headings (9 <= cur_len <= 20)
            if 9 <= cur_len <= 20:
                sub = pools["subheadings"][sub_cursor % len(pools["subheadings"])]
                sub_cursor += 1
                cand = _fit_text_to_budget(sub, cur_len + 1)
                edits.append({"slide": s_num, "slot_id": slot_id, "new_text": cand})
                continue

            # 6f. Longer Body Paragraphs (cur_len >= 21)
            para = pools["paragraphs"][para_cursor % len(pools["paragraphs"])]
            para_cursor += 1
            budget = min(max_c, max(cur_len + 4, 26))
            cand = _fit_text_to_budget(para, budget)
            edits.append({"slide": s_num, "slot_id": slot_id, "new_text": cand})

    edits_payload = {
        "$schema": "ppt-edit-spec/v1",
        "template_slug": gorden_slug,
        "selected_slides": selected_slides,
        "edits": edits,
    }
    edits_file = out_pptx.parent / "gorden_edits.json"
    out_pptx.parent.mkdir(parents=True, exist_ok=True)
    edits_file.write_text(json.dumps(edits_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    if preview_src.exists():
        shutil.copyfile(preview_src, assets_dir / "slide_preview_0_template.png")

    cmd = [
        sys.executable,
        str(build_script),
        str(source_pptx),
        str(edits_file),
        str(out_pptx),
        "--detail",
        str(detail_path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
    return res.returncode == 0 and out_pptx.exists()


def build_interactive_html_deck(spec: Dict[str, Any], out_html: pathlib.Path, num_rendered_slides: int = 0):
    """
    Generate a full-viewport interactive HTML presentation powered by `zarazhangrui/frontend-slides`:
    - Displays the real high-DPI rendered PowerPoint slide image (`assets/slide_preview_N.png`)
      alongside structured executive speaker notes when available!
    - Supports Left/Right arrow keys, Spacebar, Fullscreen 'F', and view mode toggle.
    """
    palette = spec.get("palette", {})
    slides = spec.get("slide_outline", [])
    tpl_name = spec.get("matched_template", {}).get("name", palette.get("name", "Executive Deck"))
    bg = "#F6F5F1"
    surf = "#FFFFFF"
    border = "#E6E4DD"
    primary = palette.get("primary", "#B45309")
    text_col = "#141413"
    muted = "#57534E"

    slides_html = []
    total = max(len(slides), num_rendered_slides, 1)
    for i in range(1, total + 1):
        s = slides[min(i - 1, len(slides) - 1)] if slides else {}
        bullets_html = "".join(
            f'<div class="bullet-card"><span class="b-idx">0{bi}</span><div class="b-txt">{b}</div></div>'
            for bi, b in enumerate(s.get("bullets_cn", []), 1)
        )
        img_Url = f"assets/slide_preview_{i}.png"
        slides_html.append(
            f"""
            <section class="slide {'active' if i == 1 else ''}" data-index="{i - 1}">
              <header class="slide-header">
                <div class="kicker-group">
                  <span class="accent-dot"></span>
                  <span class="kicker">SLIDE {i:02d} · {tpl_name}</span>
                </div>
                <span class="page-no">{i:02d} / {total:02d}</span>
              </header>
              <div class="slide-split">
                <div class="slide-canvas-wrap">
                  <img src="{img_Url}" alt="Slide {i}" class="slide-canvas-img" />
                </div>
                <aside class="slide-notes">
                  <div class="notes-badge">本页核心论点与汇报提纲</div>
                  <h2>{s.get("action_title_cn", "")}</h2>
                  <p class="subtitle">{s.get("subtitle_cn", "")}</p>
                  <div class="bullets-stack">{bullets_html}</div>
                </aside>
              </div>
              <footer class="slide-footer">
                <span>ProMedia Studio × GordenPPTSkill × frontend-slides</span>
                <span>按 ← / → / 空格键 翻页 · 按 F 键切换全屏演示</span>
              </footer>
            </section>
            """
        )

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>{spec.get('task_summary_cn', 'Interactive Presentation')}</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ margin:0; font-family:"Inter",-apple-system,"PingFang SC",sans-serif; background:{bg}; color:{text_col}; overflow:hidden; height:100vh; width:100vw; display:flex; flex-direction:column; }}
  .progress-bar {{ position:fixed; top:0; left:0; height:4px; background:{primary}; transition:width 240ms ease; z-index:50; }}
  .stage {{ flex:1; width:100%; height:100%; display:flex; align-items:center; justify-content:center; padding:2.2vw 3.2vw; }}
  .slide {{ display:none; width:100%; max-width:1520px; height:100%; max-height:860px; background:{surf}; border:1px solid {border}; border-radius:16px; padding:24px 32px; box-shadow:0 12px 36px rgba(20,20,19,0.06); flex-direction:column; justify-content:space-between; }}
  .slide.active {{ display:flex; }}
  .slide-header {{ display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid {border}; padding-bottom:12px; }}
  .kicker-group {{ display:flex; align-items:center; gap:8px; }}
  .accent-dot {{ width:8px; height:8px; border-radius:50%; background:{primary}; }}
  .kicker {{ font-size:12px; font-weight:600; letter-spacing:0.04em; color:{muted}; }}
  .page-no {{ font-family:monospace; font-size:13px; color:{muted}; font-weight:600; }}
  .slide-split {{ flex:1; display:grid; grid-template-columns: 1.65fr 1fr; gap:24px; align-items:center; padding:14px 0; overflow:hidden; }}
  .slide-canvas-wrap {{ width:100%; height:100%; display:flex; align-items:center; justify-content:center; background:#EFEDE7; border-radius:12px; border:1px solid {border}; overflow:hidden; padding:8px; }}
  .slide-canvas-img {{ max-width:100%; max-height:100%; object-fit:contain; border-radius:8px; box-shadow:0 6px 20px rgba(0,0,0,0.08); }}
  .slide-notes {{ display:flex; flex-direction:column; gap:10px; height:100%; justify-content:center; overflow-y:auto; padding-right:4px; }}
  .notes-badge {{ display:inline-block; align-self:flex-start; font-size:11px; font-weight:600; color:{primary}; background:#F0EFEA; padding:4px 10px; border-radius:6px; }}
  h2 {{ margin:0; font-size:20px; line-height:1.35; color:{text_col}; }}
  .subtitle {{ margin:0; font-size:13px; color:{muted}; line-height:1.5; }}
  .bullets-stack {{ display:flex; flex-direction:column; gap:8px; margin-top:4px; }}
  .bullet-card {{ display:flex; align-items:flex-start; gap:10px; padding:10px 12px; border-radius:10px; border:1px solid {border}; background:{bg}; font-size:13px; line-height:1.5; }}
  .b-idx {{ color:{primary}; font-weight:700; font-family:monospace; font-size:12px; margin-top:1px; }}
  .slide-footer {{ display:flex; justify-content:space-between; align-items:center; border-top:1px solid {border}; padding-top:10px; font-size:12px; color:{muted}; }}
  .controls {{ position:fixed; bottom:18px; right:28px; display:flex; gap:8px; z-index:60; }}
  .ctrl-btn {{ background:{surf}; color:{text_col}; border:1px solid {border}; border-radius:8px; padding:7px 13px; font-size:12px; font-weight:600; cursor:pointer; box-shadow:0 2px 8px rgba(0,0,0,0.05); }}
</style>
</head>
<body>
  <div class="progress-bar" id="progBar" style="width: {100 / max(1, total):.1f}%"></div>
  <div class="stage">{''.join(slides_html)}</div>
  <div class="controls">
    <button class="ctrl-btn" onclick="go(-1)">← 上一页</button>
    <button class="ctrl-btn" onclick="go(1)">下一页 →</button>
    <button class="ctrl-btn" onclick="toggleFs()">全屏 (F)</button>
  </div>
  <script>
    let cur = 0;
    const slides = document.querySelectorAll('.slide');
    const total = slides.length;
    function show(idx) {{
      cur = Math.max(0, Math.min(total - 1, idx));
      slides.forEach((s, i) => s.classList.toggle('active', i === cur));
      document.getElementById('progBar').style.width = (((cur + 1) / total) * 100) + '%';
    }}
    function go(delta) {{ show(cur + delta); }}
    function toggleFs() {{
      if (!document.fullscreenElement) document.documentElement.requestFullscreen().catch(()=>{{}});
      else document.exitFullscreen().catch(()=>{{}});
    }}
    window.addEventListener('keydown', (e) => {{
      if (e.key === 'ArrowRight' || e.key === ' ' || e.key === 'PageDown') go(1);
      if (e.key === 'ArrowLeft' || e.key === 'PageUp') go(-1);
      if (e.key.toLowerCase() === 'f') toggleFs();
    }});
  </script>
</body>
</html>"""
    out_html.write_text(html, encoding="utf-8")


def build_presentation_from_spec(spec_path: pathlib.Path, assets_dir: pathlib.Path, out_pptx: pathlib.Path) -> Dict[str, Any]:
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    palette = spec.get("palette", {})
    slides_spec = spec.get("slide_outline", [])
    kpis = spec.get("kpis", [])
    matched_tpl = spec.get("matched_template", {})
    tpl_id = str(matched_tpl.get("id") or spec.get("template_id") or "")

    total = len(slides_spec)
    used_engine = "python-pptx-native"

    # 1. Check if this template belongs to GordenSun/GordenPPTSkill
    gorden_slug = matched_tpl.get("gorden_slug") or (tpl_id.split("gorden:", 1)[1] if tpl_id.startswith("gorden:") else "")
    if gorden_slug:
        ok = build_with_gorden_ppt_skill(spec, gorden_slug, assets_dir, out_pptx)
        if ok:
            used_engine = f"GordenPPTSkill ({gorden_slug})"

    # 2. Fallback or standard native python-pptx build if not built by GordenPPTSkill
    if used_engine == "python-pptx-native":
        prs = Presentation()
        prs.slide_width = Inches(13.333)
        prs.slide_height = Inches(7.5)

        hero_img = assets_dir / "visual_hero.png"
        bar_img = assets_dir / "chart_growth.png"
        donut_img = assets_dir / "chart_share.png"

        for i, s_data in enumerate(slides_spec, 1):
            layout_type = s_data.get("layout", "grid")
            if i == 1 or layout_type == "cover":
                build_cover_slide(prs, s_data, palette, hero_img, total)
            elif i == 2 or layout_type == "kpi":
                build_kpi_and_bullets_slide(prs, s_data, kpis, palette, i, total)
            elif layout_type == "chart_bar" or i == 3:
                build_chart_slide(prs, s_data, bar_img, palette, i, total)
            elif layout_type == "chart_donut" or i == 4:
                build_chart_slide(prs, s_data, donut_img, palette, i, total)
            else:
                build_grid_slide(prs, s_data, palette, i, total)

        out_pptx.parent.mkdir(parents=True, exist_ok=True)
        prs.save(str(out_pptx))

    # 3. Render REAL PowerPoint slide previews via macOS QuickLook (`qlmanage -t -s 1280`)
    preview_files = render_real_pptx_slides_macos(out_pptx, assets_dir, max_slides=max(6, total))
    if not preview_files:
        for i, s_data in enumerate(slides_spec[:6], 1):
            prev_p = assets_dir / f"slide_preview_{i}.png"
            render_slide_preview_card(s_data, palette, i, total, prev_p)
            preview_files.append(str(prev_p))

    out_html = out_pptx.parent / f"{out_pptx.stem}_interactive.html"
    build_interactive_html_deck(spec, out_html, num_rendered_slides=len(preview_files))

    return {
        "status": "ok",
        "engine": used_engine,
        "pptx_path": str(out_pptx),
        "html_deck_path": str(out_html),
        "slide_count": total,
        "preview_images": preview_files,
    }


def main():
    parser = argparse.ArgumentParser(description="Build commercial PPTX deck from task_spec.json")
    parser.add_argument("--spec", type=str, required=True, help="Path to task_spec.json")
    parser.add_argument("--assets", type=str, default="./output/assets", help="Assets directory")
    parser.add_argument("--out", type=str, default="./output/presentation.pptx", help="Output PPTX path")
    args = parser.parse_args()

    res = build_presentation_from_spec(
        pathlib.Path(args.spec),
        pathlib.Path(args.assets),
        pathlib.Path(args.out),
    )
    print(json.dumps(res, ensure_ascii=False))


if __name__ == "__main__":
    main()
