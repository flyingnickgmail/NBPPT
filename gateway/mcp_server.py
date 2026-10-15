"""
Standard Commercial MCP Server Definition & JSON-RPC 2.0 Streamable HTTP Handler.
Exposes:
  1. `create_pro_presentation` (60 credits pre-freeze)
  2. `create_jimeng_marketing_video` (80 credits pre-freeze)
  3. `create_composite_campaign` (120 credits pre-freeze)
Can be mounted directly at `/mcp` in FastAPI or launched standalone via FastMCP.
"""
import json
import uuid
from typing import Dict, Any, Optional
import httpx

from gateway.config import (
    OVERSEAS_WORKER_URL,
    OVERSEAS_WORKER_SECRET,
    DEFAULT_DEMO_API_KEY,
    TASK_FREEZE_CREDITS,
)
from gateway.billing_tcc import BillingManager
from gateway.deepseek_compiler import compile_cn_request_to_english_spec, validate_direct_completion

MCP_TOOLS_MANIFEST = [
    {
        "name": "create_pro_presentation",
        "description": "[商业级PPT生成与美化] 已集成 GitHub 知名 PPT Skills (GordenSun/GordenPPTSkill 21套真实母版、zarazhangrui/frontend-slides、hugohe3/ppt-master、用友高端BG、ABU9)。输入中文主题或大纲，自动匹配母版并生成非破坏性插槽克隆 .pptx 与交互式网页演示 .html（预冻结 60 算力点）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "topic_and_requirements": {"type": "string", "description": "中文 PPT 主题、受众与核心内容要求"},
                "template_id": {
                    "type": "string",
                    "default": "auto",
                    "description": "可选母版ID：auto、gorden:mckinsey-style、gorden:architecture-deck、gorden:premium-corp、gorden:minimal-business-summary、gorden:data-viz-deck、frontend-slides、ppt-master、yonyou-ci-bg、abu9-exec-report 等",
                },
                "slide_count": {"type": "integer", "default": 6, "description": "幻灯片页数 (4-15)"},
                "visual_style": {
                    "type": "string",
                    "default": "executive-dark",
                },
            },
            "required": ["topic_and_requirements"],
        },
    },
    {
        "name": "create_jimeng_marketing_video",
        "description": "[即梦AI高清营销视频生成] 输入中文视频创意或产品描述，自动拆解分镜并合成带动态运镜、中文字幕与音轨的 1080P .mp4 视频（预冻结 80 算力点）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "video_description_cn": {"type": "string", "description": "中文视频创意、产品卖点或分镜描述"},
                "duration_seconds": {"type": "integer", "default": 10, "description": "视频时长秒数 (6-30)"},
                "aspect_ratio": {"type": "string", "default": "16:9", "enum": ["16:9", "9:16"]},
            },
            "required": ["video_description_cn"],
        },
    },
    {
        "name": "create_composite_campaign",
        "description": "[PPT + 营销视频全案一键生成] 同时生成商业级 .pptx 路演文稿、300DPI 数据图表与 1080P 宣传短视频（预冻结 120 算力点）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "campaign_prompt_cn": {"type": "string", "description": "中文全案主题与具体需求描述"},
                "template_id": {"type": "string", "default": "auto"},
                "slide_count": {"type": "integer", "default": 6},
                "duration_seconds": {"type": "integer", "default": 10},
                "visual_style": {"type": "string", "default": "executive-dark"},
            },
            "required": ["campaign_prompt_cn"],
        },
    },
]


async def execute_mcp_tool_call(
    billing: BillingManager,
    api_key: str,
    tool_name: str,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """Execute an MCP tool call end-to-end with TCC credit freeze, compilation, worker dispatch, and settlement."""
    key = api_key or DEFAULT_DEMO_API_KEY
    if tool_name == "create_pro_presentation":
        task_type = "ppt"
        cn_prompt = arguments.get("topic_and_requirements", "新一代 AI 产品商业路演")
        extra_params = {
            "template_id": arguments.get("template_id", "auto"),
            "slide_count": int(arguments.get("slide_count", 6)),
            "visual_style": arguments.get("visual_style", "executive-dark"),
        }
    elif tool_name == "create_jimeng_marketing_video":
        task_type = "video"
        cn_prompt = arguments.get("video_description_cn", "科技感新品发布宣传片")
        extra_params = {
            "duration_seconds": int(arguments.get("duration_seconds", 10)),
            "aspect_ratio": arguments.get("aspect_ratio", "16:9"),
        }
    elif tool_name == "create_composite_campaign":
        task_type = "composite"
        cn_prompt = arguments.get("campaign_prompt_cn", "智能硬件全球众筹路演全案")
        extra_params = {
            "slide_count": int(arguments.get("slide_count", 6)),
            "duration_seconds": int(arguments.get("duration_seconds", 10)),
            "visual_style": arguments.get("visual_style", "executive-dark"),
        }
    else:
        raise ValueError(f"Unknown MCP tool: {tool_name}")

    freeze_amount = TASK_FREEZE_CREDITS[task_type]
    job_id = f"{task_type}_{uuid.uuid4().hex[:10]}"

    # 1. TCC Try
    await billing.try_freeze_credits(key, job_id, task_type, cn_prompt, freeze_amount)

    try:
        # 2. Bilingual Task Spec Compilation
        en_spec = await compile_cn_request_to_english_spec(cn_prompt, task_type, extra_params)
        await billing.save_compiled_spec(job_id, en_spec)

        # 3. Call Overseas / Local Worker Stream
        final_payload: Optional[Dict[str, Any]] = None
        async with httpx.AsyncClient(timeout=600.0, trust_env=False) as client:
            async with client.stream(
                "POST",
                f"{OVERSEAS_WORKER_URL}/internal/execute-stream",
                headers={"X-Worker-Secret": OVERSEAS_WORKER_SECRET},
                json={
                    "job_id": job_id,
                    "task_type": task_type,
                    "max_budget_usd": 0.85,
                    "execution_mode": "auto",
                    "english_spec": en_spec,
                },
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    evt = json.loads(line[6:])
                    if evt.get("type") == "completed":
                        final_payload = evt
                    elif evt.get("type") == "error":
                        raise RuntimeError(evt.get("message", "Worker error"))

        if not final_payload:
            raise RuntimeError("海外/本地算力底座未返回完成结果")

        if en_spec.get("generation_contract") == "skill-direct-v1":
            en_spec = validate_direct_completion(final_payload)
            await billing.save_compiled_spec(job_id, en_spec)

        # 4. TCC Confirm
        settle_info = await billing.confirm_settle(
            job_id, float(final_payload.get("total_cost_usd", 0.12)), final_payload.get("cdn_urls", {})
        )

        return {
            "job_id": job_id,
            "task_type": task_type,
            "status": "completed",
            "summary_cn": en_spec.get("task_summary_cn"),
            "deliverables": final_payload.get("cdn_urls", {}),
            "billing_settlement": settle_info,
        }
    except Exception as exc:
        await billing.cancel_refund(job_id, str(exc))
        raise RuntimeError(f"任务中断，预冻结的 {freeze_amount} 算力点已全额退回。原因: {exc}")
