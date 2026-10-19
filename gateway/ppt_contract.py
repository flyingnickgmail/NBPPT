"""Explicit PPT provider selection; Claude is enabled only by the operator."""
import os
import math


class ProviderUnavailable(ValueError):
    def __init__(self, state, message, retry_after=0):
        super().__init__(message)
        self.state = state
        self.retry_after = max(0, math.ceil(retry_after))
        self.status_code = 429 if state == "cooldown" else 503


def claude_runtime_owner():
    """Identify the server's provider login, independently of the paying tenant."""
    owner = os.getenv("NBPPT_CLAUDE_OWNER_USER_ID", "").strip()
    if os.getenv("NBPPT_CLAUDE_ENABLED", "false").lower() != "true" or not owner:
        raise ValueError("服务器尚未配置 Claude 运行账号，入口保持关闭")
    return owner


def require_claude_owner(user_id):
    """Private worker check: the gateway must bind the configured provider login."""
    owner = claude_runtime_owner()
    if not user_id or user_id != owner:
        raise PermissionError("Claude 运行账号绑定无效")


def available_ppt_engines(*, allow_claude=True):
    engines = ["codex_cli"]
    owner = os.getenv("NBPPT_CLAUDE_OWNER_USER_ID", "").strip()
    if allow_claude and os.getenv("NBPPT_CLAUDE_ENABLED", "false").lower() == "true" and owner:
        engines.extend(["claude_cli", "claude_codex"])
    return engines


def resolve_ppt_engine(value="auto"):
    engine = "codex_cli" if value == "auto" else value
    if engine not in ("codex_cli", "claude_cli", "claude_codex"):
        raise ValueError("不支持的 PPT 生成引擎")
    if engine not in available_ppt_engines():
        raise ValueError("服务器尚未启用 Claude PPT 生成")
    return engine
