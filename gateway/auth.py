"""Opaque, revocable browser sessions and header-only API authentication."""
import hashlib
import os
import secrets
import time

import aiosqlite
from fastapi import HTTPException, Request

from gateway.config import DEFAULT_DEMO_API_KEY

COOKIE = "nbppt_session"


def secure_cookie() -> bool:
    return os.getenv("NBPPT_COOKIE_SECURE", "true").lower() != "false"


def check_origin(request: Request, required: bool = True):
    origin = request.headers.get("origin")
    expected = os.getenv("NBPPT_PUBLIC_ORIGIN", str(request.base_url).rstrip("/"))
    if (required and not origin) or (origin and origin != expected):
        raise HTTPException(403, "Cross-origin request rejected")


async def authenticate_key(billing, key: str) -> dict:
    if not key or key == DEFAULT_DEMO_API_KEY:
        raise HTTPException(401, "Authentication required")
    await billing.initialize()
    async with aiosqlite.connect(billing.db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT k.api_key, u.id AS user_id, u.tier FROM mcp_api_keys k JOIN users u ON u.id=k.user_id WHERE k.api_key=? AND k.is_active=1", (key,)
        ) as cur:
            row = await cur.fetchone()
    if not row:
        raise HTTPException(401, "Invalid or revoked credential")
    return dict(row)


async def authenticate_request(billing, request: Request) -> dict:
    header = request.headers.get("authorization")
    if header is not None:
        scheme, _, key = header.partition(" ")
        if scheme.lower() != "bearer":
            raise HTTPException(401, "Bearer credential required")
        return await authenticate_key(billing, key)
    token = request.cookies.get(COOKIE, "")
    if not token:
        raise HTTPException(401, "Authentication required")
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        check_origin(request)
    await billing.initialize()
    async with aiosqlite.connect(billing.db_path) as db:
        async with db.execute("SELECT api_key FROM web_sessions WHERE token_hash=? AND expires_at>?", (hashlib.sha256(token.encode()).hexdigest(), time.time())) as cur:
            row = await cur.fetchone()
    if not row:
        raise HTTPException(401, "Session expired")
    return await authenticate_key(billing, row[0])


async def create_session(billing, key: str) -> str:
    await authenticate_key(billing, key)
    token = secrets.token_urlsafe(32)
    async with aiosqlite.connect(billing.db_path) as db:
        await db.execute("DELETE FROM web_sessions WHERE expires_at <= ?", (time.time(),))
        await db.execute("INSERT INTO web_sessions VALUES (?,?,?)", (hashlib.sha256(token.encode()).hexdigest(), key, time.time() + 8 * 3600))
        await db.commit()
    return token


async def delete_session(billing, token: str):
    async with aiosqlite.connect(billing.db_path) as db:
        await db.execute("DELETE FROM web_sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))
        await db.commit()
