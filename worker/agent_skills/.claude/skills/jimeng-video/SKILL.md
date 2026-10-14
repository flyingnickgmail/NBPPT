---
name: jimeng-video
description: Generate 1080p marketing videos via Jimeng AI CLI/API or Playwright logged-in browser, and synthesize multi-scene dynamic MP4 videos with CJK subtitles and audio using FFmpeg.
---

# Jimeng AI (即梦) Video Production & FFmpeg Synthesis Skill (`jimeng-video`)

Follow this dual-mode execution strategy to generate commercial videos from `./task_spec.json`:

## 1. Execution Command
```bash
python3 /Users/flyignick/Code/person-work/worker/agent_skills/.claude/skills/jimeng-video/scripts/jimeng_pipeline.py \
  --spec ./task_spec.json \
  --out ./output/marketing_video.mp4
```

## 2. Dual-Mode Channels
1. **Primary Channel (Jimeng AI CLI / Volcengine Seedance API)**:
   If `JIMENG_API_KEY` or `jimeng` CLI is present, submits scene prompts (`jimeng_prompt_cn`) for cloud video generation.
2. **Browser / Local FFmpeg Motion Synthesis Channel**:
   Renders 1080p keyframe storyboards with CJK typography and uses `ffmpeg` (`zoompan` camera motion + H.264 `yuv420p` + ambient audio synthesis) to produce a broadcast-ready `.mp4` deliverable.
