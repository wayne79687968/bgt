#!/bin/bash

# 停止本地開發環境

echo "🛑 停止本地開發環境..."

# 停止 Docker 容器
docker-compose down

echo "✅ 本地環境已停止"
echo "💡 如需完全清理資料，執行: docker-compose down -v"