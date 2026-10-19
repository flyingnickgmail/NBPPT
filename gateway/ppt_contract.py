"""Explicit PPT provider selection; Claude is enabled only by the operator."""
import os
import math


class ProviderUnavailable(ValueError):
    def __init__(self, state, message, retry_after=0):
        super().__init__(message)
        self.state = state
        self.retry_after = max(0, math.ceil(retry_after))
        self.status_code = 429 if state == "cooldown" else 503


def require_claude_owner(user_id):
    owner = os.getenv("NBPPT_CLAUDE_OWNER_USER_ID", "").strip()
    if os.getenv("NBPPT_CLAUDE_ENABLED", "false").lower() != "true" or not owner:
        raise ValueError("Claude 尚未配置个人持有人绑定，入口保持关闭")
    if not user_id or user_id != owner:
        raise PermissionError("这份 Claude 个人登录只允许持有人使用")


def available_ppt_engines(user_id=None, *, allow_claude=True):
    engines = ["codex_cli"]
    owner = os.getenv("NBPPT_CLAUDE_OWNER_USER_ID", "").strip()
    if allow_claude and os.getenv("NBPPT_CLAUDE_ENABLED", "false").lower() == "true" and owner and (user_id is None or user_id == owner):
        engines.extend(["claude_cli", "claude_codex"])
    return engines


def resolve_ppt_engine(value="auto"):
    engine = "codex_cli" if value == "auto" else value
    if engine not in ("codex_cli", "claude_cli", "claude_codex"):
        raise ValueError("不支持的 PPT 生成引擎")
    if engine not in available_ppt_engines():
        raise ValueError("服务器尚未启用 Claude PPT 生成")
    return engine
