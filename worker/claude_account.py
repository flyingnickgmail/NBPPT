"""One canonical login, a process-shared lease and a durable provider circuit.

The lease coordinates managed callers on this host, not other devices or an
unwrapped Claude CLI. No token is copied to the job or written to circuit state.
"""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import sys
import tempfile
import time
from gateway.ppt_contract import ProviderUnavailable


@dataclass(frozen=True)
class ClaudeProfile:
    home: Path
    account_id: str

    @property
    def credentials(self):
        return self.home / ".claude/.credentials.json"

    @classmethod
    def configured(cls):
        configured_home = os.getenv("NBPPT_CLAUDE_HOME", "").strip()
        if not configured_home:
            raise ValueError("必须显式配置唯一 NBPPT_CLAUDE_HOME，禁止自动使用另一份个人登录")
        home = Path(configured_home).expanduser()
        if not home.is_absolute() or home.is_symlink():
            raise ValueError("Claude 登录目录必须是绝对路径，不能使用符号链接")
        config = home / ".claude.json"
        if config.is_symlink() or not config.is_file():
            raise ValueError("Claude 缺少单一登录目录中的账号元信息，请用官方客户端登录")
        account = json.loads(config.read_text()).get("oauthAccount", {}).get("accountUuid")
        if not isinstance(account, str) or not account.strip():
            raise ValueError("Claude 缺少稳定账号标识，不能按任务创建临时登录身份")
        auth = home / ".claude/.credentials.json"
        store = auth.parent
        if store.is_symlink() or not store.is_dir() or store.stat().st_mode & 0o077:
            raise ValueError("Claude 唯一登录存储必须是0700的普通目录")
        if auth.exists() or auth.is_symlink():
            info = auth.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_nlink != 1:
                raise ValueError("Claude 凭据必须为权限0600的独立普通文件")
        elif sys.platform != "darwin":
            raise ValueError("Claude 登录凭据不存在，请在唯一登录目录中重新授权")
        # macOS can use the official client's Keychain login without exporting it.
        return cls(home, "claude-" + hashlib.sha256(account.encode()).hexdigest()[:24])


async def verify_login(binary, profile):
    """Read-only official auth check with the SAME settings boundary as generation."""
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "LANG", "TMPDIR")}
    env["HOME"] = str(profile.home)
    proc = await asyncio.create_subprocess_exec(binary, "--safe-mode", "--restricted",
        "--setting-sources", "", "auth", "status", env=env,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, start_new_session=True)
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), 10)
        value = json.loads(stdout)
        if proc.returncode or value.get("loggedIn") is not True or value.get("apiProvider") != "firstParty" or value.get("authMethod") not in ("claude.ai", "oauth_token"):
            raise ValueError("No canonical first-party login")
    except (ValueError, asyncio.TimeoutError):
        raise ProviderUnavailable("unavailable", "受限模式下未检测到有效官方 Claude 登录，请检查唯一登录目录；不会读取转发配置") from None
    finally:
        if proc.returncode is None:
            proc.kill()
        await proc.wait()


class AccountGate:
    @classmethod
    def configured(cls, profile):
        raw = os.getenv('NBPPT_ACCOUNT_STATE_DIR', '').strip()
        if not raw:
            raise ValueError('必须显式配置所有受控进程共享的 NBPPT_ACCOUNT_STATE_DIR')
        root = Path(raw).expanduser()
        owner = profile.home.stat().st_uid
        if not root.exists() and os.geteuid() != owner:
            raise ValueError('请先为唯一登录所属用户创建0700的共享状态目录')
        gate = cls(profile.account_id, root)
        if root.stat().st_uid != owner:
            raise ValueError('共享状态目录必须归唯一登录所属用户，不能由其他账号另建状态')
        return gate

    def __init__(self, account_id, state_dir=None):
        if not account_id.startswith("claude-") or not account_id[7:].isalnum():
            raise ValueError("Invalid account identity")
        root = Path(state_dir or os.getenv("NBPPT_ACCOUNT_STATE_DIR") or Path.home() / ".local/state/nbppt/accounts").expanduser()
        if not root.is_absolute() or root.is_symlink():
            raise ValueError("账号状态目录须为绝对路径，不能是符号链接")
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if root.stat().st_mode & 0o077:
            raise ValueError("账号状态目录必须为0700")
        self.root = root
        self.lock_path = root / (account_id + ".lock")
        self.state_path = root / (account_id + ".json")

    def _open_lock(self):
        fd = os.open(self.lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_mode & 0o077:
            os.close(fd)
            raise ValueError("不安全的账号锁文件")
        if os.geteuid() == 0:
            owner = self.root.stat()
            try:
                os.fchown(fd, owner.st_uid, owner.st_gid)
            except BaseException:
                os.close(fd)
                raise
        return fd

    def _read(self):
        if self.state_path.is_symlink():
            raise ValueError("账号熔断状态不能是符号链接")
        if not self.state_path.exists():
            return {}
        info = self.state_path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_mode & 0o077 or info.st_size > 8192:
            raise ValueError("账号熔断状态损坏，停止调用")
        value = json.loads(self.state_path.read_text())
        if not isinstance(value, dict) or value.get("state", "ready") not in ("ready", "cooldown", "blocked"):
            raise ValueError("账号熔断状态损坏，停止调用")
        until = value.get("until", 0)
        if type(until) not in (int, float) or not math.isfinite(until) or until < 0:
            raise ValueError("账号冷却时间损坏，停止调用")
        if type(value.get("strikes", 0)) is not int or not 0 <= value.get("strikes", 0) <= 8:
            raise ValueError("账号限流计数损坏，停止调用")
        return value

    def _write(self, value):
        with tempfile.NamedTemporaryFile(dir=self.root, delete=False) as stream:
            temp = Path(stream.name)
            try:
                if os.geteuid() == 0:
                    owner = self.root.stat()
                    os.fchown(stream.fileno(), owner.st_uid, owner.st_gid)
                stream.write(json.dumps(value).encode())
                stream.flush()
                os.fsync(stream.fileno())
                os.replace(temp, self.state_path)
                fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
            finally:
                temp.unlink(missing_ok=True)

    def status(self):
        value = self._read()
        state = value.get("state", "ready")
        remaining = max(0, value.get("until", 0) - time.time())
        if state == "cooldown" and not remaining:
            state = "ready"
        messages = {"ready": "Claude 可以接受任务", "cooldown": "Claude 已限流，冷却期间不接受新生成或重试", "blocked": "Claude 账号已暂停调用，需要持有人检查授权、订阅或额度后手动恢复"}
        return {"state": state, "retry_after_seconds": math.ceil(remaining), "message": messages[state]}

    def check(self):
        status = self.status()
        if status["state"] != "ready":
            raise ProviderUnavailable(status["state"], status["message"], status["retry_after_seconds"])

    @asynccontextmanager
    async def lease(self, timeout=600):
        self.check()
        fd = self._open_lock()
        started = time.monotonic()
        try:
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    self.check()
                    if time.monotonic() - started >= timeout:
                        raise ProviderUnavailable("busy", "Claude 账号正在执行其他任务，请稍后重试")
                    await asyncio.sleep(.1)
            self.check()  # A prior process may have opened the circuit while we waited.
            yield self
        finally:
            # Closing releases the kernel lock even on cancellation/process death.
            os.close(fd)

    def record_event(self, event):
        """Called by the lease holder before the CLI can retry a rejected request."""
        if not isinstance(event, dict):
            return
        error, status, until, delay = "", None, None, 0
        if event.get("type") == "system" and event.get("subtype") == "api_retry":
            error, status = event.get("error", ""), event.get("error_status")
            delay = event.get("retry_delay_ms", 0)
            delay = delay / 1000 if type(delay) in (int, float) and math.isfinite(delay) else 0
        elif event.get("type") == "rate_limit_event":
            info = event.get("rate_limit_info") or {}
            if not isinstance(info, dict) or info.get("status") != "rejected":
                return
            error, status, until = "rate_limit", 429, info.get("resetsAt")
        elif event.get("type") == "assistant" and event.get("error"):
            error = event["error"]
        elif event.get("type") == "result" and (event.get("is_error") or event.get("subtype") != "success"):
            # Retain only a classification, never raw provider errors or tokens.
            text = (str(event.get("result", "")) + str(event.get("errors", ""))).lower()
            if any(x in text for x in ("authentication", "not logged in", "invalid api key", "account_on_hold", "account has been", "forbidden", "401", "403")):
                error = "authentication_failed"
            elif any(x in text for x in ("hit your limit", "usage limit", "weekly limit", "quota", "credit balance", "billing_error")):
                error = "quota_unknown_reset"
            elif "rate limit" in text or "429" in text:
                error, status = "rate_limit", 429
        if status in (401, 403) or error in ("authentication_failed", "oauth_org_not_allowed", "account_on_hold", "billing_error", "quota_unknown_reset"):
            reason = error if error in ("authentication_failed", "oauth_org_not_allowed", "account_on_hold", "billing_error", "quota_unknown_reset") else "authentication_failed"
            self._write({"state": "blocked", "reason": reason, "until": 0})
            self.check()
        if status == 429 or error == "rate_limit":
            previous = self._read()
            strikes = min(int(previous.get("strikes", 0)) + 1, 8)
            if until is not None and (type(until) not in (int, float) or not math.isfinite(until)):
                until = None
            # No known quota reset means human confirmation, not guessed retries.
            if event.get("type") == "rate_limit_event" and (not until or until <= time.time()):
                self._write({"state": "blocked", "reason": "quota_unknown_reset", "until": 0})
            else:
                self._write({"state": "cooldown", "strikes": strikes,
                             "until": max(until or 0, time.time() + max(delay, min(60 * 2 ** (strikes - 1), 3600)))})
            self.check()

    async def reset(self):
        """Explicit operator action; does not log in, recharge or retry requests."""
        fd = self._open_lock()
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError("不能在 Claude 正在执行时恢复账号入口")
            self._write({"state": "ready", "until": 0})
        finally:
            os.close(fd)
