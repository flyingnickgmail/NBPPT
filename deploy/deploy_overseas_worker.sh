#!/usr/bin/env bash
# ==============================================================================
# Personal Agent ProMedia Studio — Overseas Worker & Anti-Ban Account Sandbox
# Target OS: Ubuntu 22.04 / 24.04 LTS or Debian 12 (Overseas VPS: Tokyo/Silicon Valley)
# Supports:
#   1. Personal Account Login (`codex login` / `claude login`) via SSH Tunnel
#   2. 4-Layer Anti-Ban Security Shield (Static Residential Proxy + Serial Semaphore(1)
#      + Human Jitter + Persistent Non-Root User Device Fingerprint)
# ==============================================================================
set -euo pipefail

APP_DIR="/opt/personal-agent-worker"
WORKER_PORT="${WORKER_PORT:-8001}"
WORKER_SECRET="${OVERSEAS_WORKER_SECRET:?Set a random secret of at least 32 characters}"
ACCOUNT_SAFE_PROXY="${ACCOUNT_SAFE_PROXY:-}"

echo "[1/6] Installing system dependencies (Python3, Node.js 20, FFmpeg, CJK Fonts)..."
sudo apt-get update -y
sudo apt-get install -y python3 python3-venv python3-pip ffmpeg fonts-noto-cjk curl git ca-certificates

if ! command -v node >/dev/null 2>&1; then
  curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
  sudo apt-get install -y nodejs
fi

echo "[2/6] Installing Claude Code CLI & OpenAI Codex CLI globally..."
sudo npm install -g @anthropic-ai/claude-code @openai/codex || true

echo "[3/6] Creating dedicated non-root user 'agentuser' for persistent device fingerprint..."
if ! id -u agentuser >/dev/null 2>&1; then
  sudo useradd -m -s /bin/bash agentuser
fi
sudo mkdir -p "${APP_DIR}"
sudo cp -r ./worker "${APP_DIR}/"
sudo cp ./requirements.txt "${APP_DIR}/"
sudo chown -R agentuser:agentuser "${APP_DIR}"

echo "[4/6] Setting up Python virtualenv and rendering libraries..."
sudo -u agentuser bash -c "
  cd '${APP_DIR}'
  python3 -m venv .venv
  ./.venv/bin/pip install --upgrade pip
  ./.venv/bin/pip install -r requirements.txt
"

echo "[5/6] Creating systemd service (personal-agent-worker.service) with Anti-Ban Serial Shield..."
sudo tee /etc/systemd/system/personal-agent-worker.service > /dev/null <<EOF
[Unit]
Description=Personal Agent Overseas Worker (Anti-Ban Personal Account Sandbox)
After=network.target

[Service]
Type=simple
User=agentuser
WorkingDirectory=${APP_DIR}
Environment="HOME=/home/agentuser"
Environment="OVERSEAS_WORKER_SECRET=${WORKER_SECRET}"
Environment="CLAUDE_BIN=/usr/bin/claude"
Environment="CODEX_BIN=/usr/bin/codex"
Environment="FFMPEG_BIN=/usr/bin/ffmpeg"
Environment="ACCOUNT_SAFE_PROXY=${ACCOUNT_SAFE_PROXY}"
ExecStart=${APP_DIR}/.venv/bin/uvicorn worker.worker_api:app --host 127.0.0.1 --port ${WORKER_PORT} --workers 1
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

echo "[6/6] Starting and enabling personal-agent-worker..."
sudo systemctl daemon-reload
sudo systemctl enable personal-agent-worker
sudo systemctl restart personal-agent-worker

echo "=============================================================================="
echo "✅ Overseas Worker Engine is LIVE on port ${WORKER_PORT}!"
echo ""
echo "🔐 【如何在海外服务器上安全登录您的个人 Claude / Codex 账号且防封号】："
echo "1. 绑定海外静态住宅 IP (防止机房 ASN 被封):"
echo "   在 Web Studio 顶部「账号防封与模型设置」填入海外静态住宅 SOCKS5/HTTP 代理，"
echo "   或设置环境变量 ACCOUNT_SAFE_PROXY=socks5://user:pass@us-residential-ip:port"
echo ""
echo "2. 通过 SSH 本地端口转发登录个人账号 (一次性持久化保存凭证):"
echo "   在您的 Mac 终端执行:"
echo "   ssh -L 1455:127.0.0.1:1455 -L 54545:127.0.0.1:54545 root@您的海外服务器IP"
echo "   登录服务器后切换至固定指纹用户:"
echo "   su - agentuser"
echo "   export HTTPS_PROXY=${ACCOUNT_SAFE_PROXY:-直连或您的住宅代理}"
echo "   codex login    # 在本地浏览器完成 ChatGPT Plus/Pro 授权，持久化至 ~/.codex/auth.json"
echo "   claude login   # 在本地浏览器完成 Claude Pro/Max 授权，持久化至 ~/.claude/.credentials.json"
echo "=============================================================================="
