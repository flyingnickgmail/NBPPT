"""
Configuration, Local CLI Account Discovery & Runtime Model Settings Manager.
Automatically discovers logged-in personal Codex CLI (`~/.codex/auth.json`),
Claude CLI (`~/.claude/.credentials.json`), and `~/.cc-switch/cc-switch.db` providers,
while supporting Overseas Personal Account Anti-Ban Protection (`account_safe_mode`).
"""
import json
import os
import pathlib
import sqlite3
from typing import Dict, Any
from dotenv import load_dotenv

BASE_DIR = pathlib.Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"
load_dotenv(ENV_FILE)

GATEWAY_HOST = os.getenv("GATEWAY_HOST", "127.0.0.1")
GATEWAY_PORT = int(os.getenv("GATEWAY_PORT", "8000"))

DATA_DIR = BASE_DIR / "workspace" / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DATABASE_PATH = os.getenv("DATABASE_PATH") or str(DATA_DIR / "platform.db")
RUNTIME_SETTINGS_FILE = DATA_DIR / "runtime_settings.json"

DEFAULT_DEMO_API_KEY = "sk-mcp-demo-pro-8899"

TASK_FREEZE_CREDITS = {
    "ppt": 60,
    "video": 80,
    "composite": 120,
}

import shutil

CODEX_BIN_CANDIDATES = [
    os.getenv("CODEX_BIN", ""),
    shutil.which("codex") or "",
    "/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex",
    "/usr/local/bin/codex",
    "/usr/bin/codex",
    "/opt/homebrew/bin/codex",
]
CLAUDE_BIN_CANDIDATES = [
    os.getenv("CLAUDE_BIN", ""),
    shutil.which("claude") or "",
    str(pathlib.Path.home() / ".local" / "bin" / "claude"),
    "/usr/local/bin/claude",
    "/usr/bin/claude",
    "/opt/homebrew/bin/claude",
]


def detect_local_cli_accounts() -> Dict[str, Any]:
    """Detect real logged-in Codex CLI, Claude CLI, and cc-switch providers on this machine."""
    codex_bin = next((p for p in CODEX_BIN_CANDIDATES if p and pathlib.Path(p).exists()), "")
    claude_bin = next((p for p in CLAUDE_BIN_CANDIDATES if p and pathlib.Path(p).exists()), "")

    codex_auth_file = pathlib.Path.home() / ".codex" / "auth.json"
    codex_config_file = pathlib.Path.home() / ".codex" / "config.toml"
    codex_logged_in = False
    codex_model = "gpt-6-astra"
    if codex_bin and codex_auth_file.exists():
        try:
            auth_data = json.loads(codex_auth_file.read_text(encoding="utf-8"))
            codex_logged_in = bool(auth_data.get("tokens") or auth_data.get("OPENAI_API_KEY"))
        except Exception:
            pass
    if codex_config_file.exists():
        try:
            for line in codex_config_file.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith("model ="):
                    codex_model = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
        except Exception:
            pass

    # Check cc-switch SQLite database for active Anthropic-compatible providers (e.g., Zhipu GLM-5, MiniMax)
    cc_switch_db = pathlib.Path.home() / ".cc-switch" / "cc-switch.db"
    cc_providers = {}
    if cc_switch_db.exists():
        try:
            conn = sqlite3.connect(str(cc_switch_db))
            for name, cfg_str in conn.execute("SELECT name, settings_config FROM providers").fetchall():
                cfg = json.loads(cfg_str)
                env = cfg.get("env", {})
                token = env.get("ANTHROPIC_AUTH_TOKEN") or env.get("ANTHROPIC_API_KEY")
                base_url = env.get("ANTHROPIC_BASE_URL")
                model = env.get("ANTHROPIC_MODEL")
                if token and base_url and name in ("Zhipu GLM", "MiniMax"):
                    cc_providers[name] = {
                        "name": name,
                        "api_key": token,
                        "base_url": base_url.rstrip("/"),
                        "model": model or "glm-5",
                    }
            conn.close()
        except Exception:
            pass

    return {
        "codex_bin": codex_bin,
        "codex_logged_in": codex_logged_in,
        "codex_model": codex_model,
        "claude_bin": claude_bin,
        "claude_installed": bool(claude_bin),
        "cc_switch_providers": cc_providers,
    }


def get_runtime_settings() -> Dict[str, Any]:
    """Load current model, account-login & anti-ban settings."""
    local_info = detect_local_cli_accounts()
    glm_prov = local_info["cc_switch_providers"].get("Zhipu GLM", {})

    defaults = {
        "master_reasoning_engine": "auto",  # "auto", "codex_login", "claude_login", "deepseek_api"
        "deepseek_api_key": (os.getenv("DEEPSEEK_API_KEY") or "").strip(),
        "deepseek_base_url": (os.getenv("DEEPSEEK_BASE_URL") or "https://api.deepseek.com").rstrip("/"),
        "deepseek_model": (os.getenv("DEEPSEEK_MODEL") or "deepseek-chat").strip(),
        "anthropic_api_key": (os.getenv("ANTHROPIC_API_KEY") or glm_prov.get("api_key", "")).strip(),
        "anthropic_base_url": (os.getenv("ANTHROPIC_BASE_URL") or glm_prov.get("base_url", "https://api.anthropic.com")).rstrip("/"),
        "claude_model": (os.getenv("CLAUDE_MODEL") or glm_prov.get("model", "glm-5")).strip(),
        "openai_api_key": os.getenv("OPENAI_API_KEY", "").strip(),
        "jimeng_api_key": os.getenv("JIMENG_API_KEY", "").strip(),
        "overseas_worker_url": os.getenv("OVERSEAS_WORKER_URL", "http://127.0.0.1:8001").rstrip("/"),
        "overseas_worker_secret": os.getenv("OVERSEAS_WORKER_SECRET", ""),
        "account_safe_mode": True,
        "account_safe_proxy": os.getenv("ACCOUNT_SAFE_PROXY", "").strip(),
        "allow_sandbox_fallback": True,
        "local_cli_status": {
            "codex_bin": local_info["codex_bin"],
            "codex_logged_in": local_info["codex_logged_in"],
            "codex_model": local_info["codex_model"],
            "claude_bin": local_info["claude_bin"],
            "claude_installed": local_info["claude_installed"],
            "cc_switch_available": list(local_info["cc_switch_providers"].keys()),
        },
    }
    if RUNTIME_SETTINGS_FILE.exists():
        try:
            saved = json.loads(RUNTIME_SETTINGS_FILE.read_text(encoding="utf-8"))
            for k, v in saved.items():
                if v is not None and k in defaults and k not in ("local_cli_status", "overseas_worker_secret"):
                    # Keep auto-discovered cc-switch key if saved key was empty
                    if k in ("anthropic_api_key", "anthropic_base_url", "claude_model") and not v and defaults.get(k):
                        continue
                    defaults[k] = v
        except Exception:
            pass
    return defaults


def save_runtime_settings(updates: Dict[str, Any]) -> Dict[str, Any]:
    """Persist updated model API keys, account mode & anti-ban settings."""
    current = get_runtime_settings()
    for k, v in updates.items():
        if k in current and k != "local_cli_status" and v is not None:
            if isinstance(v, str):
                v = v.strip()
                if "***" in v:
                    continue
            current[k] = v
    to_save = {k: v for k, v in current.items() if k != "local_cli_status"}
    RUNTIME_SETTINGS_FILE.write_text(json.dumps(to_save, ensure_ascii=False, indent=2), encoding="utf-8")
    return get_runtime_settings()


def mask_key(val: str) -> str:
    if not val:
        return ""
    if len(val) <= 8:
        return "***"
    return f"{val[:6]}***{val[-4:]}"


OVERSEAS_WORKER_URL = get_runtime_settings()["overseas_worker_url"]
OVERSEAS_WORKER_SECRET = get_runtime_settings()["overseas_worker_secret"]
