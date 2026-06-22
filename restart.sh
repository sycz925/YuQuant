#!/bin/bash
# 重启脚本 - 重启前后端服务

echo "🔄 重启 YuQuant 服务..."

SCRIPT_DIR="$(dirname "$0")"

# 先停止
bash "$SCRIPT_DIR/stop.sh"

# 再启动
bash "$SCRIPT_DIR/start.sh"
