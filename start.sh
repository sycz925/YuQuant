#!/bin/bash
# 启动脚本 - 启动前后端服务

echo "🚀 启动 A股量化系统 服务..."

# 等待端口监听（最多等待秒）
wait_port() {
    local port=$1
    local max_wait=${2:-30}
    for _ in $(seq 1 "$max_wait"); do
        if lsof -ti:"$port" -sTCP:LISTEN > /dev/null 2>&1; then
            return 0
        fi
        sleep 1
    done
    return 1
}

# 检查是否已在运行（仅检查 LISTEN 状态，忽略 TIME_WAIT）
BACKEND_PID=$(lsof -ti:8000 -sTCP:LISTEN 2>/dev/null || true)
if [ -n "$BACKEND_PID" ]; then
    echo "⚠️  后端服务已在运行 (port 8000, PID: $BACKEND_PID)"
else
    echo "📦 启动后端服务..."
    cd "$(dirname "$0")"
    source venv/bin/activate
    nohup python -m uvicorn app.server.main:app --host 0.0.0.0 --port 8000 --timeout-keep-alive 30 > logs/backend.log 2>&1 &
    if wait_port 8000 60; then
        echo "✅ 后端服务启动成功 (http://localhost:8000)"
    else
        echo "❌ 后端服务启动失败，请检查 backend.log"
        tail -20 logs/backend.log
        exit 1
    fi
fi

FRONTEND_PID=$(lsof -ti:3000 -sTCP:LISTEN 2>/dev/null || true)
if [ -n "$FRONTEND_PID" ]; then
    echo "⚠️  前端服务已在运行 (port 3000, PID: $FRONTEND_PID)"
else
    echo "🎨 启动前端服务..."
    cd "$(dirname "$0")/app/client"
    nohup npm run dev > frontend.log 2>&1 &
    if wait_port 3000 60; then
        echo "✅ 前端服务启动成功 (http://localhost:3000)"
    else
        echo "❌ 前端服务启动失败，请检查 frontend.log"
        tail -20 frontend.log
        exit 1
    fi
fi

echo ""
echo "🎉 服务启动完成！"
echo "   后端: http://localhost:8000"
echo "   前端: http://localhost:3000"
