#!/bin/bash

# 本地開發環境啟動腳本

echo "🚀 啟動本地 BGG RAG Daily 開發環境..."

# 檢查 Docker 是否運行
if ! docker info >/dev/null 2>&1; then
    echo "❌ Docker 未運行，請先啟動 Docker"
    exit 1
fi

# 載入本地環境變數
if [ -f .env.local ]; then
    export $(cat .env.local | grep -v '^#' | xargs)
    echo "✅ 已載入 .env.local 環境變數"
else
    echo "⚠️  未找到 .env.local 文件，使用預設配置"
fi

# 啟動 PostgreSQL
echo "🐘 啟動 PostgreSQL 資料庫..."
docker-compose up -d postgres

# 等待 PostgreSQL 啟動
echo "⏳ 等待 PostgreSQL 啟動..."
sleep 5

# 檢查 PostgreSQL 是否就緒
max_attempts=30
attempt=1
while [ $attempt -le $max_attempts ]; do
    if docker-compose exec postgres pg_isready -U postgres >/dev/null 2>&1; then
        echo "✅ PostgreSQL 已就緒"
        break
    fi
    echo "⏳ PostgreSQL 啟動中... ($attempt/$max_attempts)"
    sleep 2
    ((attempt++))
done

if [ $attempt -gt $max_attempts ]; then
    echo "❌ PostgreSQL 啟動超時"
    exit 1
fi

# 初始化資料庫
echo "🗃️ 初始化資料庫結構..."
python3 -c "from database import init_database; init_database()"

if [ $? -eq 0 ]; then
    echo "✅ 資料庫初始化完成"
else
    echo "❌ 資料庫初始化失敗"
    exit 1
fi

# 啟動 Flask 應用
echo "🌐 啟動 Flask 應用 (http://localhost:5000)..."
python3 app.py