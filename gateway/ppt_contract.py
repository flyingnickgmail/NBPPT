"""Explicit PPT provider selection; Claude is enabled only by the operator."""
import os


def available_ppt_engines():
    engines = ["codex_cli"]
    if os.getenv("NBPPT_CLAUDE_ENABLED", "false").lower() == "true":
        engines.append("claude_cli")
    return engines


def resolve_ppt_engine(value="auto"):
    engine = "codex_cli" if value == "auto" else value
    if engine not in ("codex_cli", "claude_cli"):
        raise ValueError("不支持的 PPT 生成引擎")
    if engine not in available_ppt_engines():
        raise ValueError("服务器尚未启用 Claude PPT 生成")
    return engine
