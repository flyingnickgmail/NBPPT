"""
TCC (Try-Confirm-Cancel) 3-Phase Credit Billing Manager.
Uses async SQLite out-of-the-box so the entire billing lifecycle works locally with zero external dependencies,
while matching the exact schema of sql/init_postgres_schema.sql.
"""
import json
import secrets
import uuid
import os
import math
import pathlib
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

import aiosqlite
from gateway.config import DATABASE_PATH, DEFAULT_DEMO_API_KEY
from gateway.delivery import verify_published, delivery_urls


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


class BillingManager:
    def __init__(self, db_path: str = DATABASE_PATH, jobs_root=None):
        self.db_path = db_path
        self.jobs_root = pathlib.Path(jobs_root or pathlib.Path(__file__).resolve().parent.parent / "workspace/jobs")
        self._initialized = False

    async def initialize(self):
        if self._initialized:
            return
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    phone_or_email TEXT UNIQUE NOT NULL,
                    tier TEXT DEFAULT 'studio',
                    credits_available INTEGER NOT NULL DEFAULT 2000,
                    credits_frozen INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS mcp_api_keys (
                    api_key TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    name TEXT DEFAULT 'Default Studio Key',
                    daily_credit_limit INTEGER DEFAULT 5000,
                    is_active INTEGER DEFAULT 1,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                );

                CREATE TABLE IF NOT EXISTS media_jobs (
                    job_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'PENDING',
                    cn_user_prompt TEXT NOT NULL,
                    en_compiled_spec TEXT,
                    credits_frozen INTEGER NOT NULL,
                    credits_charged INTEGER DEFAULT 0,
                    overseas_cost_usd REAL DEFAULT 0.0,
                    result_cdn_urls TEXT,
                    error_msg TEXT,
                    created_at TEXT NOT NULL,
                    completed_at TEXT
                );

                CREATE TABLE IF NOT EXISTS credit_ledger (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    job_id TEXT,
                    action TEXT NOT NULL,
                    amount INTEGER NOT NULL,
                    balance_after INTEGER NOT NULL,
                    note TEXT,
                    created_at TEXT NOT NULL
                );
                """
            )
            async with db.execute("PRAGMA table_info(media_jobs)") as cur:
                columns = {row[1] for row in await cur.fetchall()}
            if "request_hash" not in columns:
                await db.execute("ALTER TABLE media_jobs ADD COLUMN request_hash TEXT")
            await db.execute("CREATE TABLE IF NOT EXISTS web_sessions (token_hash TEXT PRIMARY KEY, api_key TEXT NOT NULL, expires_at REAL NOT NULL)")
            # Never re-enable the historically public demo credential.
            await db.execute("UPDATE mcp_api_keys SET is_active = 0 WHERE api_key = ?", (DEFAULT_DEMO_API_KEY,))
            bootstrap_key = os.getenv("NBPPT_ADMIN_API_KEY", "")
            if bootstrap_key and (len(bootstrap_key) < 32 or bootstrap_key == DEFAULT_DEMO_API_KEY):
                raise ValueError("NBPPT_ADMIN_API_KEY must contain at least 32 characters")
            async with db.execute("SELECT id FROM users WHERE phone_or_email = ?", ("founder@personal-agent.cn",)) as cur:
                row = await cur.fetchone()
            if not row and bootstrap_key:
                user_id = str(uuid.uuid4())
                ts = now_iso()
                await db.execute(
                    "INSERT INTO users (id, phone_or_email, tier, credits_available, credits_frozen, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (user_id, "founder@personal-agent.cn", "admin", 2000, 0, ts),
                )
                await db.execute(
                    "INSERT INTO mcp_api_keys (api_key, user_id, name, daily_credit_limit, is_active, created_at) VALUES (?, ?, ?, ?, 1, ?)",
                    (bootstrap_key, user_id, "管理员初始密钥", 5000, ts),
                )
                await db.execute(
                    "INSERT INTO credit_ledger (user_id, job_id, action, amount, balance_after, note, created_at) VALUES (?, ?, 'TOPUP', 2000, 2000, '系统初始化赠送算力点', ?)",
                    (user_id, "init_grant", ts),
                )
            elif row and bootstrap_key:
                await db.execute("UPDATE users SET tier = 'admin' WHERE id = ?", (row[0],))
                await db.execute("INSERT OR IGNORE INTO mcp_api_keys (api_key,user_id,name,created_at) VALUES (?,?,?,?)", (bootstrap_key,row[0],"管理员初始密钥",now_iso()))
            await db.commit()
        self._initialized = True

    async def get_wallet_overview(self, api_key: str) -> Dict[str, Any]:
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT u.id as user_id, u.phone_or_email, u.tier, u.credits_available, u.credits_frozen,
                       k.api_key, k.name as key_name, k.daily_credit_limit
                FROM mcp_api_keys k
                JOIN users u ON k.user_id = u.id
                WHERE k.api_key = ? AND k.is_active = 1
                """,
                (api_key,),
            ) as cur:
                user_row = await cur.fetchone()

            if not user_row:
                raise PermissionError("无效或已停用的密钥")

            user_id = user_row["user_id"]
            async with db.execute(
                "SELECT api_key, name, daily_credit_limit, is_active, created_at FROM mcp_api_keys WHERE user_id = ? ORDER BY created_at DESC",
                (user_id,),
            ) as cur:
                keys = [dict(r) for r in await cur.fetchall()]
                for key in keys:
                    key["api_key"] = "***" + key["api_key"][-4:]

            async with db.execute(
                "SELECT id, job_id, action, amount, balance_after, note, created_at FROM credit_ledger WHERE user_id = ? ORDER BY id DESC LIMIT 20",
                (user_id,),
            ) as cur:
                ledger = [dict(r) for r in await cur.fetchall()]

            user = dict(user_row)
            user.pop("api_key", None)
            return {
                "user": user,
                "api_keys": keys,
                "recent_ledger": ledger,
            }

    async def topup_credits(self, api_key: str, amount: int, channel: str = "微信支付 Native") -> Dict[str, Any]:
        await self.initialize()
        if amount <= 0:
            raise ValueError("充值算力点必须大于 0")
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT u.id as user_id, u.credits_available FROM mcp_api_keys k JOIN users u ON k.user_id = u.id WHERE k.api_key = ? AND k.is_active = 1",
                (api_key,),
            ) as cur:
                row = await cur.fetchone()
            if not row:
                raise PermissionError("无效的 API Key")

            new_bal = row["credits_available"] + amount
            ts = now_iso()
            await db.execute("UPDATE users SET credits_available = ? WHERE id = ?", (new_bal, row["user_id"]))
            await db.execute(
                "INSERT INTO credit_ledger (user_id, job_id, action, amount, balance_after, note, created_at) VALUES (?, ?, 'TOPUP', ?, ?, ?, ?)",
                (row["user_id"], f"topup_{secrets.token_hex(4)}", amount, new_bal, f"{channel} 充值 +{amount} 算力点", ts),
            )
            await db.commit()
            return {"credits_available": new_bal, "added": amount}

    async def create_new_api_key(self, current_api_key: str, key_name: str) -> Dict[str, Any]:
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT user_id FROM mcp_api_keys WHERE api_key = ? AND is_active = 1", (current_api_key,)
            ) as cur:
                row = await cur.fetchone()
            if not row:
                raise PermissionError("无效的当前 API Key")
            new_key = f"sk-mcp-{secrets.token_urlsafe(32)}"
            ts = now_iso()
            await db.execute(
                "INSERT INTO mcp_api_keys (api_key, user_id, name, daily_credit_limit, is_active, created_at) VALUES (?, ?, ?, 5000, 1, ?)",
                (new_key, row["user_id"], key_name or "External MCP Client Key", ts),
            )
            await db.commit()
            return {"api_key": new_key, "name": key_name, "created_at": ts}

    async def try_freeze_credits(
        self, api_key: str, job_id: str, task_type: str, cn_prompt: str, freeze_amount: int, request_hash: str | None = None
    ) -> Dict[str, Any]:
        """Phase 1 (Try): Atomically validate API key and freeze user credits before invoking overseas worker."""
        await self.initialize()
        if freeze_amount <= 0:
            raise ValueError("Freeze amount must be positive")
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT u.id as user_id, u.credits_available, u.credits_frozen, u.tier
                FROM mcp_api_keys k
                JOIN users u ON k.user_id = u.id
                WHERE k.api_key = ? AND k.is_active = 1
                """,
                (api_key,),
            ) as cur:
                row = await cur.fetchone()
            if not row:
                raise PermissionError("无效或已停用的 MCP API Key")
            if row["credits_available"] < freeze_amount:
                raise ValueError(
                    f"账户可用算力点不足（当前可用: {row['credits_available']} 点，本次任务需预冻结: {freeze_amount} 点），请先点击右上角充值。"
                )

            new_avail = row["credits_available"] - freeze_amount
            new_frozen = row["credits_frozen"] + freeze_amount
            ts = now_iso()

            await db.execute(
                "UPDATE users SET credits_available = ?, credits_frozen = ? WHERE id = ?",
                (new_avail, new_frozen, row["user_id"]),
            )
            await db.execute(
                """
                INSERT INTO media_jobs (job_id, user_id, task_type, status, cn_user_prompt, credits_frozen, created_at, request_hash)
                VALUES (?, ?, ?, 'RUNNING', ?, ?, ?, ?)
                """,
                (job_id, row["user_id"], task_type, cn_prompt, freeze_amount, ts, request_hash),
            )
            await db.execute(
                """
                INSERT INTO credit_ledger (user_id, job_id, action, amount, balance_after, note, created_at)
                VALUES (?, ?, 'FREEZE', ?, ?, ?, ?)
                """,
                (row["user_id"], job_id, -freeze_amount, new_avail, f"TCC Try: 预冻结 {freeze_amount} 点 ({task_type})", ts),
            )
            await db.commit()
            return {
                "user_id": row["user_id"],
                "tier": row["tier"],
                "frozen_credits": freeze_amount,
                "balance_after_freeze": new_avail,
            }

    async def save_compiled_spec(self, job_id: str, en_spec: Dict[str, Any]):
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE media_jobs SET en_compiled_spec = ? WHERE job_id = ?",
                (json.dumps(en_spec, ensure_ascii=False), job_id),
            )
            await db.commit()

    async def confirm_settle(self, job_id: str, actual_cost_usd: float, cdn_urls: Dict[str, Any]) -> Dict[str, Any]:
        """Phase 2 (Confirm): Dynamically settle credits based on actual_cost_usd and refund unused frozen difference."""
        await self.initialize()
        if not math.isfinite(actual_cost_usd) or actual_cost_usd < 0:
            raise ValueError("Invalid cost")
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM media_jobs WHERE job_id = ?", (job_id,)) as cur:
                job = await cur.fetchone()
            if not job:
                raise ValueError(f"Job {job_id} not found")
            if job["status"] == "COMPLETED":
                async with db.execute("SELECT credits_available FROM users WHERE id=?", (job["user_id"],)) as cur:
                    current_balance = (await cur.fetchone())[0]
                return {"already_settled": True, "charged_credits": job["credits_charged"],
                        "remaining_credits": current_balance,
                        "refunded_diff_credits": job["credits_frozen"] - job["credits_charged"],
                        "overseas_cost_usd": job["overseas_cost_usd"]}
            if job["status"] != "RUNNING":
                raise ValueError("Job is not eligible for settlement")
            manifest = verify_published(job_id, job["task_type"], json.loads(job["en_compiled_spec"] or "{}"), self.jobs_root / job_id / "output")
            if cdn_urls != delivery_urls(job_id, manifest):
                raise ValueError("Delivery URLs do not match verified files")

            frozen = int(job["credits_frozen"])
            # Dynamic formula: min(frozen, max(int(frozen * 0.7), int(actual_cost_usd * 300)))
            dynamic_credits = min(frozen, max(int(frozen * 0.7), int(round(actual_cost_usd * 300))))
            refund_diff = frozen - dynamic_credits

            async with db.execute("SELECT credits_available, credits_frozen FROM users WHERE id = ?", (job["user_id"],)) as cur:
                u_row = await cur.fetchone()

            new_avail = u_row["credits_available"] + refund_diff
            new_frozen = max(0, u_row["credits_frozen"] - frozen)
            ts = now_iso()

            await db.execute(
                "UPDATE users SET credits_available = ?, credits_frozen = ? WHERE id = ?",
                (new_avail, new_frozen, job["user_id"]),
            )
            await db.execute(
                """
                UPDATE media_jobs
                SET status = 'COMPLETED', credits_charged = ?, overseas_cost_usd = ?, result_cdn_urls = ?, completed_at = ?
                WHERE job_id = ?
                """,
                (dynamic_credits, actual_cost_usd, json.dumps(cdn_urls, ensure_ascii=False), ts, job_id),
            )
            await db.execute(
                """
                INSERT INTO credit_ledger (user_id, job_id, action, amount, balance_after, note, created_at)
                VALUES (?, ?, 'SETTLE', ?, ?, ?, ?)
                """,
                (
                    job["user_id"],
                    job_id,
                    refund_diff,
                    new_avail,
                    f"TCC Confirm: 实扣 {dynamic_credits} 点 (估算成本 ${actual_cost_usd:.4f})，退回差额 +{refund_diff} 点",
                    ts,
                ),
            )
            await db.commit()
            return {
                "frozen_credits": frozen,
                "charged_credits": dynamic_credits,
                "refunded_diff_credits": refund_diff,
                "overseas_cost_usd": actual_cost_usd,
                "remaining_credits": new_avail,
            }

    async def cancel_refund(self, job_id: str, error_msg: str) -> Dict[str, Any]:
        """Phase 3 (Cancel): Full refund of frozen credits if overseas worker fails or times out."""
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM media_jobs WHERE job_id = ?", (job_id,)) as cur:
                job = await cur.fetchone()
            if not job or job["status"] != "RUNNING":
                return {"refunded": 0}

            frozen = int(job["credits_frozen"])
            async with db.execute("SELECT credits_available, credits_frozen FROM users WHERE id = ?", (job["user_id"],)) as cur:
                u_row = await cur.fetchone()

            new_avail = u_row["credits_available"] + frozen
            new_frozen = max(0, u_row["credits_frozen"] - frozen)
            ts = now_iso()

            await db.execute(
                "UPDATE users SET credits_available = ?, credits_frozen = ? WHERE id = ?",
                (new_avail, new_frozen, job["user_id"]),
            )
            await db.execute(
                "UPDATE media_jobs SET status = 'FAILED', error_msg = ?, completed_at = ? WHERE job_id = ?",
                (error_msg[:500], ts, job_id),
            )
            await db.execute(
                """
                INSERT INTO credit_ledger (user_id, job_id, action, amount, balance_after, note, created_at)
                VALUES (?, ?, 'REFUND', ?, ?, ?, ?)
                """,
                (job["user_id"], job_id, frozen, new_avail, f"TCC Cancel: 异常中断全额退还 +{frozen} 点", ts),
            )
            await db.commit()
            return {"refunded": frozen, "remaining_credits": new_avail}

    async def list_jobs(self, user_id: str, limit: int = 15) -> List[Dict[str, Any]]:
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM media_jobs WHERE user_id = ? ORDER BY created_at DESC LIMIT ?", (user_id, max(1, min(limit, 100)))
            ) as cur:
                rows = await cur.fetchall()
            result = []
            for r in rows:
                d = dict(r)
                d["en_compiled_spec"] = json.loads(d["en_compiled_spec"]) if d.get("en_compiled_spec") else None
                d["result_cdn_urls"] = json.loads(d["result_cdn_urls"]) if d.get("result_cdn_urls") else None
                result.append(d)
            return result

    async def get_job(self, job_id: str, user_id: str) -> Optional[dict]:
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM media_jobs WHERE job_id = ? AND user_id = ?", (job_id, user_id)) as cur:
                row = await cur.fetchone()
                return dict(row) if row else None

    async def recover_interrupted(self):
        """Single-gateway startup: previous streaming jobs cannot resume safely."""
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT job_id FROM media_jobs WHERE status='RUNNING'") as cur:
                jobs = await cur.fetchall()
        for (job_id,) in jobs:
            await self.cancel_refund(job_id, "Gateway restarted before verified settlement")
