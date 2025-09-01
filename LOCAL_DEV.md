# 本地開發環境設置

## 快速開始

### 1. 依賴準備

確保已安裝：
- Docker Desktop
- Python 3.12+
- pip

### 2. 環境配置

1. 複製環境配置文件：
```bash
cp .env.local.example .env.local
```

2. 編輯 `.env.local`，配置你的 SMTP 和其他設置

### 3. 啟動開發環境

```bash
# 一鍵啟動 (推薦)
./start_local.sh

# 或手動啟動
docker-compose up -d postgres
python3 app.py
```

### 4. 停止開發環境

```bash
# 停止服務
./stop_local.sh

# 或手動停止
docker-compose down

# 完全清理數據
docker-compose down -v
```

## 服務端口

- **Flask 應用**: http://localhost:5000
- **PostgreSQL**: localhost:5432
- **pgAdmin** (可選): http://localhost:8080

## 資料庫管理

### pgAdmin (可選)
```bash
# 啟動 pgAdmin 管理介面
docker-compose --profile admin up -d pgadmin
```

登入信息：
- Email: admin@admin.com  
- Password: admin123

### 手動資料庫操作
```bash
# 進入 PostgreSQL 容器
docker-compose exec postgres psql -U postgres -d bgg_rag

# 重置資料庫
docker-compose exec postgres psql -U postgres -c "DROP DATABASE bgg_rag; CREATE DATABASE bgg_rag;"
```

## 開發流程

1. 修改代碼
2. Flask 自動重載 (開發模式)
3. 如需重置資料庫，停止並重新啟動

## 故障排除

### PostgreSQL 連接失敗
```bash
# 檢查 PostgreSQL 狀態
docker-compose ps postgres

# 查看日誌
docker-compose logs postgres

# 重啟服務
docker-compose restart postgres
```

### 資料庫結構問題
```bash
# 重新初始化資料庫
python3 -c "from database import init_database; init_database()"
```

### 端口衝突
如果 5432 端口被占用，修改 `docker-compose.yml` 中的端口映射：
```yaml
ports:
  - "5433:5432"  # 改為 5433
```

同時更新 `.env.local` 中的 DATABASE_URL。