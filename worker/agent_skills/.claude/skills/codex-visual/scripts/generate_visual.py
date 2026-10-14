#!/usr/bin/env python3
"""
High-DPI Commercial Data Visualization & Hero Graphic Generator (codex-visual skill)
Supports both Dark Tech Palettes (Obsidian) and Enterprise Light Templates (Yonyou BG, ABU9, Swiss).
"""
import argparse
import json
import pathlib
from typing import Dict, Any, List

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import numpy as np
from PIL import Image, ImageDraw, ImageFont


def configure_cjk_font() -> str:
    candidates = [
        "PingFang SC",
        "Heiti TC",
        "STHeiti",
        "Hiragino Sans GB",
        "Arial Unicode MS",
        "Noto Sans CJK SC",
        "Source Han Sans SC",
        "Microsoft YaHei",
        "SimHei",
    ]
    available = {f.name for f in fm.fontManager.ttflist}
    chosen = "sans-serif"
    for c in candidates:
        if c in available:
            chosen = c
            break
    plt.rcParams["font.sans-serif"] = [chosen, "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    return chosen


def get_pil_font(size: int) -> ImageFont.FreeTypeFont:
    font_paths = [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    ]
    for fp in font_paths:
        if pathlib.Path(fp).exists():
            try:
                return ImageFont.truetype(fp, size)
            except Exception:
                continue
    return ImageFont.load_default()


def render_bar_growth_chart(
    title: str,
    categories: List[str],
    series_a: List[float],
    series_b: List[float],
    palette: Dict[str, Any],
    out_path: pathlib.Path,
    label_a: str = "核心业务规模",
    label_b: str = "行业基准均值",
):
    configure_cjk_font()
    fig, ax = plt.subplots(figsize=(8.2, 4.6), dpi=240)
    bg_color = palette.get("surface", "#161F33")
    border_col = palette.get("border", "#334155")
    fig.patch.set_facecolor(bg_color)
    ax.set_facecolor(bg_color)

    n = min(len(categories), len(series_a), len(series_b))
    if n == 0:
        categories, series_a, series_b = ["Q1", "Q2", "Q3", "Q4"], [120, 260, 520, 960], [100, 140, 190, 250]
        n = 4
    categories, series_a, series_b = categories[:n], series_a[:n], series_b[:n]

    x = np.arange(n)
    width = 0.34

    c_primary = palette.get("primary", "#38BDF8")
    c_accent = palette.get("accent", "#6366F1")
    c_text = palette.get("text", "#F8FAFC")
    c_muted = palette.get("muted", "#94A3B8")

    rects1 = ax.bar(x - width / 2, series_a, width, label=label_a, color=c_primary, edgecolor="none", zorder=3)
    rects2 = ax.bar(x + width / 2, series_b, width, label=label_b, color=c_accent, alpha=0.82, edgecolor="none", zorder=3)

    ax.set_title(title, color=c_text, fontsize=13.5, fontweight="bold", pad=16)
    ax.set_xticks(x)
    ax.set_xticklabels(categories, color=c_text, fontsize=10.5)
    ax.tick_params(axis="y", colors=c_muted, labelsize=9.5)
    ax.grid(axis="y", linestyle="--", alpha=0.25, color=c_muted, zorder=0)

    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)
    for spine in ["left", "bottom"]:
        ax.spines[spine].set_color(border_col)

    for r in rects1:
        h = r.get_height()
        ax.annotate(
            f"{h:g}",
            xy=(r.get_x() + r.get_width() / 2, h),
            xytext=(0, 4),
            textcoords="offset points",
            ha="center",
            va="bottom",
            color=c_primary,
            fontsize=9.5,
            fontweight="bold",
        )

    legend = ax.legend(frameon=True, facecolor=bg_color, edgecolor=border_col, fontsize=9.5)
    for text in legend.get_texts():
        text.set_color(c_text)

    plt.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=240, facecolor=fig.get_facecolor(), edgecolor="none")
    plt.close(fig)


def render_donut_chart(
    title: str,
    labels: List[str],
    sizes: List[float],
    palette: Dict[str, Any],
    out_path: pathlib.Path,
):
    configure_cjk_font()
    fig, ax = plt.subplots(figsize=(8.0, 4.6), dpi=240)
    bg_color = palette.get("surface", "#161F33")
    fig.patch.set_facecolor(bg_color)
    ax.set_facecolor(bg_color)

    n = min(len(labels), len(sizes))
    if n == 0:
        labels, sizes = ["核心模块", "自动化工具", "生态接口", "增值服务"], [42.0, 28.5, 19.5, 10.0]
    else:
        labels, sizes = labels[:n], [max(1.0, float(s)) for s in sizes[:n]]

    colors = [
        palette.get("primary", "#38BDF8"),
        palette.get("accent", "#6366F1"),
        palette.get("emerald", "#10B981"),
        "#F59E0B",
        "#EC4899",
    ][: len(labels)]

    wedges, texts, autotexts = ax.pie(
        sizes,
        labels=labels,
        autopct="%1.1f%%",
        startangle=140,
        colors=colors,
        pctdistance=0.76,
        wedgeprops=dict(width=0.42, edgecolor=bg_color, linewidth=2.5),
    )

    c_text = palette.get("text", "#F8FAFC")
    for t in texts:
        t.set_color(c_text)
        t.set_fontsize(10.5)
    for at in autotexts:
        at.set_color("#FFFFFF")
        at.set_fontsize(9.5)
        at.set_fontweight("bold")

    ax.set_title(title, color=c_text, fontsize=13.5, fontweight="bold", pad=14)
    plt.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=240, facecolor=fig.get_facecolor(), edgecolor="none")
    plt.close(fig)


def render_hero_architecture_card(
    title: str,
    subtitle: str,
    pillars: List[str],
    palette: Dict[str, Any],
    out_path: pathlib.Path,
):
    """Render a sleek 16:9 visual illustration adapted to light or dark template palettes."""
    w, h = 1280, 720
    is_light = bool(palette.get("is_light", False))
    bg_col = palette.get("bg", "#0B0F19")
    surf_col = palette.get("surface", "#161F33")
    border_col = palette.get("border", "#28354F")
    primary_col = palette.get("primary", "#38BDF8")
    accent_col = palette.get("accent", "#6366F1")
    text_col = palette.get("text", "#F8FAFC")
    muted_col = palette.get("muted", "#94A3B8")
    brand_tag = palette.get("brand_tag", "AI PERSONAL AGENT · VISUAL ENGINE")

    img = Image.new("RGB", (w, h), bg_col)
    draw = ImageDraw.Draw(img)

    grid_col = "#E2E8F0" if is_light else "#131C31"
    for gx in range(0, w, 64):
        draw.line([(gx, 0), (gx, h)], fill=grid_col, width=1)
    for gy in range(0, h, 64):
        draw.line([(0, gy), (w, gy)], fill=grid_col, width=1)

    cx, cy = int(w * 0.76), int(h * 0.5)
    for r, col in [(250, border_col), (185, accent_col), (120, primary_col), (65, primary_col)]:
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=col, width=3)

    draw.rounded_rectangle([64, 72, 830, 648], radius=20, fill=surf_col, outline=primary_col, width=2)

    f_kicker = get_pil_font(19)
    f_title = get_pil_font(36)
    f_sub = get_pil_font(21)
    f_item = get_pil_font(20)

    draw.text((100, 108), brand_tag, fill=primary_col, font=f_kicker)
    draw.text((100, 155), title[:26], fill=text_col, font=f_title)
    if len(title) > 26:
        draw.text((100, 204), title[26:52], fill=text_col, font=f_title)
    draw.text((100, 265), subtitle[:42], fill=muted_col, font=f_sub)

    y_offset = 335
    item_bg = "#F1F5F9" if is_light else "#111827"
    for idx, p in enumerate(pillars[:4], 1):
        draw.rounded_rectangle([100, y_offset, 790, y_offset + 58], radius=10, fill=item_bg, outline=border_col, width=1)
        draw.text((122, y_offset + 16), f"0{idx}  {p[:33]}", fill=text_col, font=f_item)
        y_offset += 72

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "PNG")


def generate_all_from_spec(spec_path: pathlib.Path, outdir: pathlib.Path) -> List[str]:
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    palette = spec.get("palette", {})
    outdir.mkdir(parents=True, exist_ok=True)
    generated_files: List[str] = []

    hero_path = outdir / "visual_hero.png"
    slides = spec.get("slide_outline", [])
    first_title = slides[0].get("action_title_cn", spec.get("task_summary_cn", "核心战略全案")) if slides else "核心战略全案"
    first_sub = slides[0].get("subtitle_cn", "数据驱动 · 智能生成 · 商业级视觉交付") if slides else ""
    first_bullets = slides[0].get("bullets_cn", ["强逻辑大纲推演", "专属母版自动匹配", "高分辨率图表合成"]) if slides else []
    render_hero_architecture_card(first_title, first_sub, first_bullets, palette, hero_path)
    generated_files.append(str(hero_path))

    bar_path = outdir / "chart_growth.png"
    chart_cfg = spec.get("chart_config", {})
    render_bar_growth_chart(
        title=chart_cfg.get("bar_title", "核心业务规模与增长预测"),
        categories=chart_cfg.get("categories", ["阶段一", "阶段二", "阶段三", "阶段四", "阶段五"]),
        series_a=chart_cfg.get("series_a", [160, 350, 720, 1320, 2240]),
        series_b=chart_cfg.get("series_b", [120, 175, 240, 310, 390]),
        palette=palette,
        out_path=bar_path,
        label_a=chart_cfg.get("label_a", "本方案目标表现"),
        label_b=chart_cfg.get("label_b", "传统基线水平"),
    )
    generated_files.append(str(bar_path))

    donut_path = outdir / "chart_share.png"
    render_donut_chart(
        title=chart_cfg.get("donut_title", "核心价值构成与资源投入占比"),
        labels=chart_cfg.get("donut_labels", ["核心业务场景", "自动化工具链", "生态协同拓展", "创新增值服务"]),
        sizes=chart_cfg.get("donut_sizes", [42.0, 28.5, 19.5, 10.0]),
        palette=palette,
        out_path=donut_path,
    )
    generated_files.append(str(donut_path))

    return generated_files


def main():
    parser = argparse.ArgumentParser(description="Generate commercial charts and visuals")
    parser.add_argument("--spec", type=str, help="Path to task_spec.json")
    parser.add_argument("--outdir", type=str, default="./output/assets", help="Output directory")
    parser.add_argument("--chart-type", type=str, default="bar_growth")
    parser.add_argument("--title", type=str, default="核心增长指标趋势分析")
    parser.add_argument("--out", type=str, default="./output/assets/single_chart.png")
    args = parser.parse_args()

    if args.spec and pathlib.Path(args.spec).exists():
        files = generate_all_from_spec(pathlib.Path(args.spec), pathlib.Path(args.outdir))
        print(json.dumps({"status": "ok", "generated_visuals": files}, ensure_ascii=False))
    else:
        out_p = pathlib.Path(args.out)
        render_bar_growth_chart(
            title=args.title,
            categories=["Q1", "Q2", "Q3", "Q4"],
            series_a=[180, 320, 510, 790],
            series_b=[120, 170, 230, 290],
            palette={},
            out_path=out_p,
        )
        print(json.dumps({"status": "ok", "generated_visuals": [str(out_p)]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
