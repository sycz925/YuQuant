#!/bin/bash
# 停止脚本 - 停止前后端服务

echo "🛑 停止 YuQuant 服务..."

# 停止后端服务
if lsof -ti:8000 > /dev/null 2>&1; then
    echo "📦 停止后端服务..."
    lsof -ti:8000 | xargs kill -9 2>/dev/null
    sleep 2
    echo "✅ 后端服务已停止"
else
    echo "ℹ️  后端服务未运行"
fi

# 停止前端服务
if lsof -ti:3000 > /dev/null 2>&1; then
    echo "🎨 停止前端服务..."
    lsof -ti:3000 | xargs kill -9 2>/dev/null
    sleep 2
    echo "✅ 前端服务已停止"
else
    echo "ℹ️  前端服务未运行"
fi

echo ""
echo "🎉 服务已全部停止"
