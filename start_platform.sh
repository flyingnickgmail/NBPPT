#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

VENV_DIR="$PROJECT_DIR/.venv"
if [ ! -d "$VENV_DIR" ]; then
  echo "=== [1/3] 正在创建 Python 虚拟环境 (.venv) 并安装依赖 ==="
  python3 -m venv "$VENV_DIR"
  "$VENV_DIR/bin/pip" install --upgrade pip
  "$VENV_DIR/bin/pip" install -r requirements.txt
fi

if [ ! -f "$PROJECT_DIR/.env" ]; then
  cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"
fi

mkdir -p "$PROJECT_DIR/workspace/logs"

echo "=== [2/3] 启动海外/本地算力底座守护进程 (Worker API :8001) ==="
pkill -f "uvicorn worker.worker_api:app" || true
nohup "$VENV_DIR/bin/uvicorn" worker.worker_api:app --host 127.0.0.1 --port 8001 > "$PROJECT_DIR/workspace/logs/worker.log" 2>&1 &

echo "=== [3/3] 启动国内门面与商业化 MCP 网关 (Gateway & Web Studio :8000) ==="
pkill -f "uvicorn gateway.main:app" || true
nohup "$VENV_DIR/bin/uvicorn" gateway.main:app --host 127.0.0.1 --port 8000 > "$PROJECT_DIR/workspace/logs/gateway.log" 2>&1 &

sleep 2
echo ""
echo "✅ Personal Agent ProMedia Platform 已成功启动！"
echo "👉 Web Studio 创作工作台与计费后台: http://127.0.0.1:8000"
echo "👉 标准 MCP Server 端点 (Cursor/Claude): http://127.0.0.1:8000/mcp"
echo "👉 算力底座健康检查 (Worker): http://127.0.0.1:8001/health"
