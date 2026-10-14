---
name: codex-visual
description: Generate high-resolution commercial charts, data visualizations, and hero illustrations with CJK font support and transparent dark/light backgrounds.
---

# Codex Visual & Data Chart Generation Skill

When invoked by Claude Code or the Worker Pipeline, use this skill to produce 300-DPI visual assets for slides and video scenes:

## 1. Command-Line Usage

```bash
python3 /Users/flyignick/Code/person-work/worker/agent_skills/.claude/skills/codex-visual/scripts/generate_visual.py \
  --spec ./task_spec.json \
  --outdir ./output/assets
```

Or generate a single chart/illustration:
```bash
python3 /Users/flyignick/Code/person-work/worker/agent_skills/.claude/skills/codex-visual/scripts/generate_visual.py \
  --chart-type "bar_growth" \
  --title "全球智能硬件市场增长预测 (2024-2028)" \
  --out ./output/assets/chart_1.png
```

## 2. Capabilities
- Automatically detects installed CJK fonts on macOS (`PingFang SC`, `Heiti TC`, `Arial Unicode MS`) and Linux (`Noto Sans CJK SC`).
- Supports `bar_growth`, `market_donut`, `radar_benchmark`, and `hero_architecture` visual types.
- If `OPENAI_API_KEY` is configured and `--use-openai-image` is passed, invokes OpenAI image generation API for photorealistic hero visuals.
