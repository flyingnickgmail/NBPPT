-- ============================================================================
-- Production PostgreSQL Schema for Personal Agent ProMedia Platform
-- Implements TCC (Try-Confirm-Cancel) Credit Billing & MCP API Key Management
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    phone_or_email VARCHAR(128) UNIQUE NOT NULL,
    tier VARCHAR(32) DEFAULT 'pro',                 -- 'starter', 'pro', 'studio'
    credits_available INT NOT NULL DEFAULT 0,       -- Available compute credits (1 RMB ≈ 15 credits)
    credits_frozen INT NOT NULL DEFAULT 0,          -- Pre-frozen credits during task execution
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS mcp_api_keys (
    api_key VARCHAR(128) PRIMARY KEY,               -- Format: sk-mcp-xxxxxxxxxxxx
    user_id UUID NOT NULL REFERENCES users(id),
    name VARCHAR(64) DEFAULT 'Default MCP Key',
    daily_credit_limit INT DEFAULT 2000,
    is_active BOOLEAN DEFAULT TRUE,
    scope VARCHAR(16) NOT NULL DEFAULT 'generate',
    allow_claude BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS media_jobs (
    job_id VARCHAR(64) PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id),
    task_type VARCHAR(32) NOT NULL,                 -- 'ppt', 'video', 'composite'
    status VARCHAR(32) NOT NULL DEFAULT 'PENDING',  -- 'PENDING','RUNNING','COMPLETED','FAILED'
    cn_user_prompt TEXT NOT NULL,
    en_compiled_spec JSONB,
    credits_frozen INT NOT NULL,
    credits_charged INT DEFAULT 0,
    overseas_cost_usd NUMERIC(10, 5) DEFAULT 0.0,   -- Actual total_cost_usd reported by worker
    result_cdn_urls JSONB,                          -- {"pptx_url": "...", "mp4_url": "...", "visual_urls": [...]}
    error_msg TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS credit_ledger (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id),
    job_id VARCHAR(64),
    action VARCHAR(32) NOT NULL,                    -- 'TOPUP', 'FREEZE', 'SETTLE', 'REFUND'
    amount INT NOT NULL,
    balance_after INT NOT NULL,
    note TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS admin_actions (
    request_id VARCHAR(80) PRIMARY KEY,
    actor_user_id UUID NOT NULL REFERENCES users(id),
    action VARCHAR(32) NOT NULL,
    target_id TEXT NOT NULL,
    fingerprint VARCHAR(64) NOT NULL,
    result_json TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
