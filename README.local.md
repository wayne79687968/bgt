# BGG RAG 本地開發環境設置

本指南幫助你設置本地 Docker 環境來測試郵件註冊和驗證流程。

## 架構概覽

本地環境包含三個主要服務：
- **PostgreSQL**: 主資料庫
- **MailHog**: 本地 SMTP 測試伺服器 (可視化郵件介面)
- **BGG RAG App**: Flask 應用程式

## 快速開始

### 1. 啟動服務

```bash
# 啟動所有服務
docker-compose -f docker-compose.local.yml up -d

# 查看服務狀態
docker-compose -f docker-compose.local.yml ps

# 查看日誌
docker-compose -f docker-compose.local.yml logs -f app
```

### 2. 訪問服務

- **BGG RAG 應用**: http://localhost:5000
- **MailHog Web UI**: http://localhost:8025 (查看測試郵件)
- **PostgreSQL**: localhost:5432

### 3. 測試郵件註冊流程

1. 打開瀏覽器訪問 http://localhost:5000
2. 點擊註冊頁面
3. 填寫郵件地址和密碼
4. 提交註冊表單
5. 到 http://localhost:8025 查看收到的驗證郵件
6. 完成驗證流程

## 環境配置

### 主要環境變數 (.env.local)

```bash
# 資料庫
DATABASE_URL=postgresql://bgg_user:bgg_password@localhost:5432/bgg_rag

# SMTP (MailHog)
SMTP_SERVER=localhost
SMTP_PORT=1025
FROM_EMAIL=noreply@bgg-rag-local.com

# 管理員
ADMIN_USERNAME=admin
ADMIN_PASSWORD=admin123
```

### MailHog 設定

MailHog 是一個輕量級的 SMTP 測試工具：
- **SMTP Port**: 1025 (應用程式連接)
- **Web UI Port**: 8025 (查看郵件)
- **功能**: 攔截所有發送的郵件，提供 Web 介面查看

## 開發工作流程

### 修改代碼後重新啟動

```bash
# 重新構建並啟動應用程式
docker-compose -f docker-compose.local.yml up --build -d app

# 或者重新啟動所有服務
docker-compose -f docker-compose.local.yml restart
```

### 查看日誌

```bash
# 查看應用程式日誌
docker-compose -f docker-compose.local.yml logs -f app

# 查看資料庫日誌
docker-compose -f docker-compose.local.yml logs -f postgres

# 查看所有服務日誌
docker-compose -f docker-compose.local.yml logs -f
```

### 進入容器調試

```bash
# 進入應用程式容器
docker-compose -f docker-compose.local.yml exec app bash

# 進入資料庫容器
docker-compose -f docker-compose.local.yml exec postgres psql -U bgg_user -d bgg_rag
```

## 測試場景

### 1. 註冊流程測試
- 用戶註冊 → 發送驗證郵件 → 郵件驗證 → 登入成功

### 2. 密碼重設測試
- 忘記密碼 → 發送重設郵件 → 郵件驗證 → 設定新密碼

### 3. 登入驗證測試
- 啟用登入驗證 → 發送登入驗證碼 → 輸入驗證碼 → 登入成功

## 故障排除

### 應用程式無法啟動
```bash
# 檢查日誌
docker-compose -f docker-compose.local.yml logs app

# 檢查資料庫連接
docker-compose -f docker-compose.local.yml exec app python -c "from database import get_db_connection; print('DB OK')"
```

### 無法收到郵件
1. 確認 MailHog 服務正在運行
2. 檢查應用程式是否連接到 localhost:1025
3. 查看 http://localhost:8025 的 MailHog Web UI

### 資料庫連接失敗
```bash
# 檢查 PostgreSQL 服務
docker-compose -f docker-compose.local.yml exec postgres pg_isready -U bgg_user

# 重新初始化資料庫
docker-compose -f docker-compose.local.yml exec app python database.py
```

## 清理環境

```bash
# 停止所有服務
docker-compose -f docker-compose.local.yml down

# 刪除所有資料 (包含資料庫)
docker-compose -f docker-compose.local.yml down -v

# 清理 Docker 資源
docker system prune -f
```

## 生產環境差異

本地環境與生產環境的主要差異：
- 使用 MailHog 替代真實 SMTP 服務
- 資料庫密碼和密鑰為測試用途
- 啟用 Flask 除錯模式
- 較短的啟動等待時間