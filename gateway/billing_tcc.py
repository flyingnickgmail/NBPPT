"""
TCC (Try-Confirm-Cancel) 3-Phase Credit Billing Manager.
Uses async SQLite out-of-the-box so the entire billing lifecycle works locally with zero external dependencies,
while matching the exact schema of sql/init_postgres_schema.sql.
"""
import json
import asyncio
import hashlib
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
        self.jobs_root = pathlib.Path(jobs_root or os.getenv('NBPPT_JOBS_ROOT') or pathlib.Path(__file__).resolve().parent.parent / "workspace/jobs")
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
                CREATE TABLE IF NOT EXISTS admin_actions (
                    request_id TEXT PRIMARY KEY,
                    actor_user_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            async with db.execute("PRAGMA table_info(media_jobs)") as cur:
                columns = {row[1] for row in await cur.fetchall()}
            if "request_hash" not in columns:
                await db.execute("ALTER TABLE media_jobs ADD COLUMN request_hash TEXT")
            async with db.execute("PRAGMA table_info(mcp_api_keys)") as cur:
                key_columns = {row[1] for row in await cur.fetchall()}
            if 'scope' not in key_columns:
                await db.execute("ALTER TABLE mcp_api_keys ADD COLUMN scope TEXT NOT NULL DEFAULT 'generate'")
            if 'allow_claude' not in key_columns:
                await db.execute("ALTER TABLE mcp_api_keys ADD COLUMN allow_claude INTEGER NOT NULL DEFAULT 0 CHECK (allow_claude IN (0,1))")
                # Preserve only the already-authorized holder's existing keys, once.
                owner = os.getenv('NBPPT_CLAUDE_OWNER_USER_ID', '').strip()
                if owner:
                    await db.execute("UPDATE mcp_api_keys SET allow_claude=1 WHERE user_id=?", (owner,))
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
            if bootstrap_key:
                await db.execute("UPDATE mcp_api_keys SET scope='admin' WHERE api_key=?", (bootstrap_key,))
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
                "SELECT api_key, name, scope, allow_claude, daily_credit_limit, is_active, created_at FROM mcp_api_keys WHERE user_id = ? ORDER BY created_at DESC",
                (user_id,),
            ) as cur:
                keys = [dict(r) for r in await cur.fetchall()]
                for key in keys:
                    key["key_id"] = hashlib.sha256(key["api_key"].encode()).hexdigest()
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

    @staticmethod
    async def _require_key_admin(db, current_api_key):
        async with db.execute(
            "SELECT k.user_id FROM mcp_api_keys k JOIN users u ON k.user_id=u.id WHERE k.api_key=? AND k.is_active=1 AND k.scope='admin' AND u.tier='admin'", (current_api_key,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            raise PermissionError('Administrator required')
        return row[0]

    async def create_new_api_key(self, current_api_key: str, key_name: str, *, allow_claude=False, daily_credit_limit=240,
                                 initial_credits=0, scope='generate', request_id=None) -> Dict[str, Any]:
        """Issue a separate tenant, never an alias of the administrator's account."""
        if type(allow_claude) is not bool or type(daily_credit_limit) is not int or not 1 <= daily_credit_limit <= 5000:
            raise ValueError('Invalid key permissions or daily limit')
        if not isinstance(key_name, str) or not 1 <= len(key_name.strip()) <= 80:
            raise ValueError('密钥名称须为1–80字')
        if type(initial_credits) is not int or not 0 <= initial_credits <= 1000000 or scope not in ('generate','read'):
            raise ValueError('Invalid initial credits or scope')
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('BEGIN IMMEDIATE')
            actor = await self._require_key_admin(db, current_api_key)
            values = {'name':key_name.strip(),'allow_claude':allow_claude,'daily_credit_limit':daily_credit_limit,'initial_credits':initial_credits,'scope':scope}
            request_id, fingerprint, previous = await self._admin_action(db, actor, request_id, 'CREATE_KEY', '', values)
            if previous:
                async with db.execute('SELECT api_key,is_active FROM mcp_api_keys WHERE user_id=?', (previous['user_id'],)) as cur:
                    key = next((r for r in await cur.fetchall() if hashlib.sha256(r[0].encode()).hexdigest()==previous['key_id']), None)
                if not key or not key[1]:
                    raise ValueError('原请求的密钥已停用，不会重新创建')
                return {**previous, 'api_key':key[0]}
            # A permission flag cannot authorize another tenant to borrow personal OAuth.
            if allow_claude:
                raise PermissionError('独立账户尚无适用的 Claude 授权，不能借用个人持有人的登录')
            new_key = f"sk-mcp-{secrets.token_urlsafe(32)}"
            user_id = str(uuid.uuid4())
            ts = now_iso()
            await db.execute("INSERT INTO users (id,phone_or_email,tier,credits_available,credits_frozen,created_at) VALUES (?,?,'studio',?,0,?)",
                             (user_id, f'account-{user_id}@local.invalid', initial_credits, ts))
            await db.execute(
                "INSERT INTO mcp_api_keys (api_key,user_id,name,daily_credit_limit,is_active,created_at,scope,allow_claude) VALUES (?,?,?,?,1,?,?,0)",
                (new_key, user_id, key_name.strip(), daily_credit_limit, ts, scope),
            )
            if initial_credits:
                await db.execute("INSERT INTO credit_ledger(user_id,job_id,action,amount,balance_after,note,created_at) VALUES (?,?,'ADMIN_ADJUST',?,?,?,?)",
                                 (user_id,'admin_'+request_id,initial_credits,initial_credits,f'管理员 {actor} 创建账户时分配',ts))
            result = {'key_id': hashlib.sha256(new_key.encode()).hexdigest(), 'user_id': user_id,
                      'name': key_name.strip(), 'scope': scope, 'allow_claude': False,
                      'daily_credit_limit': daily_credit_limit, 'credits_available': initial_credits, 'created_at': ts}
            await self._save_admin_action(db, actor, request_id, 'CREATE_KEY', user_id, fingerprint, result)
            await db.commit()
            return {**result, 'api_key':new_key}

    @staticmethod
    async def _admin_action(db, actor, request_id, action, target, values):
        import re
        request_id = request_id or str(uuid.uuid4())
        if not isinstance(request_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,80}',request_id):
            raise ValueError('Invalid request_id')
        fingerprint = hashlib.sha256(json.dumps([action,target,values],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        async with db.execute('SELECT actor_user_id,fingerprint,result_json FROM admin_actions WHERE request_id=?',(request_id,)) as cur:
            row=await cur.fetchone()
        if row:
            if row[0]!=actor or row[1]!=fingerprint:
                raise ValueError('操作编号已用于其他请求；未执行本次修改')
            return request_id,fingerprint,json.loads(row[2])
        return request_id,fingerprint,None

    @staticmethod
    async def _save_admin_action(db, actor, request_id, action, target, fingerprint, result):
        await db.execute('INSERT INTO admin_actions VALUES (?,?,?,?,?,?,?)',
                         (request_id,actor,action,target,fingerprint,json.dumps(result,ensure_ascii=False),now_iso()))

    @staticmethod
    async def _managed_key(db, key_id):
        async with db.execute('SELECT api_key,user_id,scope,is_active FROM mcp_api_keys') as cur:
            row=next((r for r in await cur.fetchall() if hashlib.sha256(r[0].encode()).hexdigest()==key_id),None)
        if not row:
            raise LookupError('Key not found')
        return row

    async def list_managed_keys(self, current_api_key):
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            await self._require_key_admin(db, current_api_key)
            db.row_factory = aiosqlite.Row
            async with db.execute('''SELECT k.api_key,k.user_id,k.name,k.scope,k.allow_claude,k.daily_credit_limit,k.is_active,k.created_at,
                u.credits_available,u.credits_frozen,coalesce(s.spent,0) AS daily_spent,
                (SELECT count(*) FROM mcp_api_keys a WHERE a.user_id=k.user_id) AS account_key_count
                FROM mcp_api_keys k JOIN users u ON u.id=k.user_id
                LEFT JOIN (SELECT user_id,sum(-amount) AS spent FROM credit_ledger WHERE action='FREEZE' AND substr(created_at,1,10)=? GROUP BY user_id) s ON s.user_id=k.user_id
                ORDER BY k.created_at DESC,k.rowid DESC''',(now_iso()[:10],)) as cur:
                rows = [dict(row) for row in await cur.fetchall()]
        for row in rows:
            raw = row.pop('api_key')
            row.update(key_id=hashlib.sha256(raw.encode()).hexdigest(), api_key='***'+raw[-4:], allow_claude=bool(row['allow_claude']))
            row['is_current'] = secrets.compare_digest(raw,current_api_key)
            row['effective_daily_limit'] = min(row['daily_credit_limit'],int(os.getenv('NBPPT_DAILY_CREDITS','1200')))
            row['claude_eligible'] = os.getenv('NBPPT_CLAUDE_ENABLED','false').lower()=='true' and row['user_id']==os.getenv('NBPPT_CLAUDE_OWNER_USER_ID','').strip()
        return rows

    async def update_managed_key(self, current_api_key, key_id, values, request_id=None):
        if not values or set(values)-{'name','scope','daily_credit_limit','allow_claude'}:
            raise ValueError('Invalid key settings')
        if 'name' in values and (not isinstance(values['name'],str) or not 1<=len(values['name'].strip())<=80):
            raise ValueError('密钥名称须为1–80字')
        if 'daily_credit_limit' in values and (type(values['daily_credit_limit']) is not int or not 1<=values['daily_credit_limit']<=5000):
            raise ValueError('每日上限须为1–5000整数')
        if 'allow_claude' in values and type(values['allow_claude']) is not bool:
            raise ValueError('allow_claude must be a boolean')
        if 'scope' in values and values['scope'] not in ('generate','read'):
            raise ValueError('只能设置生成或只读权限')
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('BEGIN IMMEDIATE')
            actor=await self._require_key_admin(db,current_api_key)
            request_id,fingerprint,previous=await self._admin_action(db,actor,request_id,'UPDATE_KEY',key_id,values)
            if previous:return previous
            raw,user,scope,active=await self._managed_key(db,key_id)
            if not active:raise ValueError('Key is revoked')
            if scope=='admin' and 'scope' in values:
                raise PermissionError('管理员密钥的管理权限不能在此降级')
            if values.get('allow_claude'):
                from gateway.ppt_contract import require_claude_owner
                require_claude_owner(user)
            for column,value in values.items():
                await db.execute(f'UPDATE mcp_api_keys SET {column}=? WHERE api_key=?',(value.strip() if column=='name' else value,raw))
            result={'key_id':key_id,'user_id':user,**values}
            await self._save_admin_action(db,actor,request_id,'UPDATE_KEY',key_id,fingerprint,result)
            await db.commit()
        return result

    async def adjust_managed_credits(self, current_api_key, key_id, delta, note, request_id):
        if type(delta) is not int or not -1000000<=delta<=1000000 or delta==0:
            raise ValueError('调整点数须为非零整数，绝对值不超过100万')
        if not isinstance(note,str) or not 1<=len(note.strip())<=200:
            raise ValueError('请填写1–200字的调整原因')
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('BEGIN IMMEDIATE')
            actor=await self._require_key_admin(db,current_api_key)
            values={'delta':delta,'note':note.strip()}
            request_id,fingerprint,previous=await self._admin_action(db,actor,request_id,'ADJUST_CREDITS',key_id,values)
            if previous:return previous
            _,user,_,_=await self._managed_key(db,key_id)
            async with db.execute('SELECT credits_available,credits_frozen FROM users WHERE id=?',(user,)) as cur:
                available,frozen=await cur.fetchone()
            if available+delta<0:raise ValueError('减额超过可用余额，冻结点数不参与调整')
            balance=available+delta
            await db.execute('UPDATE users SET credits_available=? WHERE id=?',(balance,user))
            await db.execute("INSERT INTO credit_ledger(user_id,job_id,action,amount,balance_after,note,created_at) VALUES (?,?,'ADMIN_ADJUST',?,?,?,?)",
                             (user,'admin_'+request_id,delta,balance,f'管理员 {actor}：{note.strip()}',now_iso()))
            result={'user_id':user,'delta':delta,'note':note.strip(),'credits_available':balance,'credits_frozen':frozen}
            await self._save_admin_action(db,actor,request_id,'ADJUST_CREDITS',key_id,fingerprint,result)
            await db.commit()
        return result

    async def list_admin_actions(self,current_api_key,limit=30):
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            await self._require_key_admin(db,current_api_key)
            db.row_factory=aiosqlite.Row
            async with db.execute('SELECT request_id,actor_user_id,action,target_id,result_json,created_at FROM admin_actions ORDER BY rowid DESC LIMIT ?', (max(1,min(limit,100)),)) as cur:
                return [{**dict(r),'result':json.loads(r['result_json'])} for r in await cur.fetchall()]

    async def set_key_claude_permission(self, current_api_key, key_id, allow_claude):
        return await self.update_managed_key(current_api_key,key_id,{'allow_claude':allow_claude})

    async def revoke_api_key(self, principal, key_id, request_id=None):
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('BEGIN IMMEDIATE')
            actor=await self._require_key_admin(db, principal['api_key'])
            request_id,fingerprint,previous=await self._admin_action(db,actor,request_id,'REVOKE_KEY',key_id,{})
            if previous:return previous
            key,_,_,_=await self._managed_key(db,key_id)
            if key == principal['api_key']:
                raise ValueError('Cannot revoke the current administrator credential')
            await db.execute('UPDATE mcp_api_keys SET is_active=0 WHERE api_key=?', (key,))
            await db.execute('DELETE FROM web_sessions WHERE api_key=?', (key,))
            result={'revoked':True,'key_id':key_id}
            await self._save_admin_action(db,actor,request_id,'REVOKE_KEY',key_id,fingerprint,result)
            await db.commit()
        return result

    async def try_freeze_credits(
        self, api_key: str, job_id: str, task_type: str, cn_prompt: str, freeze_amount: int, request_hash: str | None = None,
        *, require_claude=False
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
                SELECT u.id as user_id, u.credits_available, u.credits_frozen, u.tier, k.daily_credit_limit, k.scope, k.allow_claude
                FROM mcp_api_keys k
                JOIN users u ON k.user_id = u.id
                WHERE k.api_key = ? AND k.is_active = 1
                """,
                (api_key,),
            ) as cur:
                row = await cur.fetchone()
            if not row:
                raise PermissionError("无效或已停用的 MCP API Key")
            if row['scope'] not in ('admin', 'generate'):
                raise PermissionError('Credential scope does not allow generation')
            if require_claude:
                from gateway.ppt_contract import require_claude_owner
                require_claude_owner(row['user_id'])
                if not row['allow_claude']:
                    raise PermissionError('当前密钥未获准使用 Claude')
            async with db.execute("SELECT count(*), sum(user_id=?) FROM media_jobs WHERE status='RUNNING'", (row['user_id'],)) as cur:
                total, owned = await cur.fetchone()
            if total >= int(os.getenv('NBPPT_MAX_RUNNING', '8')) or (owned or 0) >= int(os.getenv('NBPPT_MAX_USER_RUNNING', '2')):
                raise ValueError('生成队列已满，请等待现有任务完成')
            daily_limit = min(row['daily_credit_limit'], int(os.getenv('NBPPT_DAILY_CREDITS', '1200')))
            async with db.execute("SELECT coalesce(sum(-amount),0) FROM credit_ledger WHERE user_id=? AND action='FREEZE' AND substr(created_at,1,10)=?", (row['user_id'], now_iso()[:10])) as cur:
                spent = (await cur.fetchone())[0]
            if spent + freeze_amount > daily_limit:
                raise ValueError('今日生成额度已用完；失败请求也计入尝试额度')
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
        # Validate large files off the event loop and before taking the write lock.
        async with aiosqlite.connect(self.db_path) as preflight:
            preflight.row_factory = aiosqlite.Row
            async with preflight.execute("SELECT * FROM media_jobs WHERE job_id=?", (job_id,)) as cur:
                checked = await cur.fetchone()
        if checked and checked["status"] == "RUNNING":
            manifest = await asyncio.to_thread(verify_published, job_id, checked["task_type"],
                json.loads(checked["en_compiled_spec"] or "{}"), self.jobs_root / job_id / "output")
            if cdn_urls != delivery_urls(job_id, manifest):
                raise ValueError("Delivery URLs do not match verified files")
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
            if not checked or checked["status"] != "RUNNING" or checked["en_compiled_spec"] != job["en_compiled_spec"]:
                raise ValueError("Job changed during delivery verification")

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
