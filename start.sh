#!/bin/bash
# 启动脚本 - 启动前后端服务

echo "🚀 启动 YuQuant 服务..."

# 检查是否已在运行（仅检查 LISTEN 状态，忽略 TIME_WAIT）
BACKEND_PID=$(lsof -ti:8000 -sTCP:LISTEN 2>/dev/null || true)
if [ -n "$BACKEND_PID" ]; then
    echo "⚠️  后端服务已在运行 (port 8000, PID: $BACKEND_PID)"
else
    echo "📦 启动后端服务..."
    cd "$(dirname "$0")"
    source venv/bin/activate
    nohup python -m uvicorn app.server.main:app --host 0.0.0.0 --port 8000 --reload > logs/backend.log 2>&1 &
    sleep 4
    if lsof -ti:8000 > /dev/null 2>&1; then
        echo "✅ 后端服务启动成功 (http://localhost:8000)"
    else
        echo "❌ 后端服务启动失败，请检查 backend.log"
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
    sleep 3
    if lsof -ti:3000 > /dev/null 2>&1; then
        echo "✅ 前端服务启动成功 (http://localhost:3000)"
    else
        echo "❌ 前端服务启动失败，请检查 frontend.log"
        exit 1
    fi
fi

echo ""
echo "🎉 服务启动完成！"
echo "   后端: http://localhost:8000"
echo "   前端: http://localhost:3000"
