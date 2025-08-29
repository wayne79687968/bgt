# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**重要原則:**
1. 務必測試功能
2. 搭配 git 做版本控制
3. 所有功能必須在 Zeabur 雲端環境運行

## 系統概述

這是一個 BGG (BoardGameGeek) 綜合分析平台，包含：

1. **熱門遊戲報表系統**: 每日抓取 BGG 熱門遊戲並生成中文分析報告
2. **設計師/繪師追蹤系統**: 搜尋並追蹤遊戲設計師/繪師，獲得新作品通知
3. **遊戲推薦系統**: 基於用戶收藏的個人化推薦
4. **Web 管理介面**: 用戶登入、設定管理、報告檢視

## 核心功能模組

### 1. 報表生成系統
- **scheduler.py**: APScheduler 排程器 (UTC+8 09:00 自動執行)
- **generate_report.py**: 主報告生成邏輯，支援多語言 i18n
- **fetch_hotgames.py**: BGG 熱門遊戲列表抓取
- **fetch_details.py**: 遊戲詳細資訊抓取
- **fetch_bgg_forum_threads.py**: 論壇討論串抓取
- **comment_summarize_llm.py**: OpenAI LLM 評論分析

### 2. 設計師追蹤系統  
- **creator_tracker.py**: BGG XML API 設計師/繪師搜尋與資料抓取
- **update_creators.py**: 定期更新追蹤設計師作品 (GitHub Actions)
- **email_service.py**: SMTP 新作品通知服務
- **templates/creator_tracker.html**: 搜尋與追蹤介面

### 3. 推薦系統
- **advanced_recommender.py**: 基於機器學習的遊戲推薦
- **collection_sync.py**: BGG 用戶收藏同步

### 4. Web 應用程式
- **app.py**: Flask 主應用程式，包含所有 API 端點
- **start_simple.py**: Zeabur 優化的啟動腳本
- **database.py**: 資料庫管理 (SQLite 本地 / PostgreSQL 生產)

## Zeabur 部署配置

### 環境變數 (必須設定)
```bash
# 基本配置
SECRET_KEY=your-secret-key-here
ADMIN_USERNAME=admin
ADMIN_PASSWORD=your-secure-password-here
TZ=Asia/Taipei

# 資料庫 (Zeabur 自動提供)
DATABASE_URL=${POSTGRES_CONNECTION_STRING}

# 外部服務
OPENAI_API_KEY=your-openai-api-key-here
CRON_SECRET_TOKEN=your-cron-secret-token-here

# Email 通知 (可選)
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=your-email@gmail.com
SMTP_PASSWORD=your-app-password
FROM_EMAIL=your-email@gmail.com
FROM_NAME=BGG 設計師追蹤
```

### 服務架構
```yaml
# zeabur.yml
services:
  postgresql: PostgreSQL 資料庫
  app: Python Flask 應用程式 (gunicorn + start_simple.py)
```

### 關鍵端點
- `/`: 首頁登入
- `/dashboard`: 主控台
- `/reports`: 報告檢視
- `/creator-tracker`: 設計師追蹤
- `/settings`: 設定頁面
- `/health`: 健康檢查
- `/api/trigger-report`: 手動觸發報告生成 (需 CRON_SECRET_TOKEN)

## 資料庫結構

### 核心資料表
```sql
- hot_games: 熱門遊戲歷史快照
- game_detail: 遊戲詳細資訊
- game_comments: 遊戲評論快取
- forum_threads: 論壇討論串
- creators: 設計師/繪師基本資料
- creator_games: 設計師作品列表
- user_follows: 用戶追蹤關係
- game_notifications: 新作品通知記錄
- reports: 生成的報告內容
```

## 自動化流程

### 每日報告 (09:00 UTC+8)
1. 抓取 BGG 熱門遊戲 → 獲取遊戲詳情
2. 抓取論壇討論 → LLM 分析評論
3. 生成中文報告 → 儲存到資料庫和檔案

### 設計師更新 (GitHub Actions 每日)
1. 檢查所有被追蹤的設計師/繪師
2. 抓取新作品資訊
3. 發送 Email 通知給追蹤用戶

## 開發指令 (Zeabur 環境)

### 基本測試
```bash
# 測試資料庫初始化
python database.py

# 測試 Flask 應用程式
python app.py

# 手動生成報告
python generate_report.py --lang zh-tw --detail all

# 測試設計師追蹤
python creator_tracker.py

# 測試 Email 服務
python email_service.py
```

### API 測試
```bash
# 健康檢查
curl https://your-app.zeabur.app/health

# 手動觸發報告 (需要 CRON_SECRET_TOKEN)
curl -X POST "https://your-app.zeabur.app/api/trigger-report?token=YOUR_TOKEN"
```

## 重要技術細節

### 時區處理
- 全系統使用 `Asia/Taipei` 時區
- 所有 datetime 操作使用 `pytz` 確保一致性

### BGG API 整合
- XML API 2.0 用於搜尋和基本資料
- 網頁抓取用於詳細論壇內容

### LLM 處理
- OpenAI GPT 用於評論摘要和情感分析
- 錯誤處理和重試機制

### 部署優化
- 使用 `start_simple.py` 避免複雜初始化問題
- Gunicorn 配置適合 Zeabur 環境
- 健康檢查支援長時間初始化

## 故障排除

### 常見問題
1. **502 Bad Gateway**: 檢查 `start_simple.py` 是否正常啟動
2. **資料庫連接失敗**: 確認 `DATABASE_URL` 環境變數
3. **報告生成失敗**: 檢查 OpenAI API 金鑰和額度
4. **Email 通知不工作**: 檢查 SMTP 設定和應用程式密碼

### 日誌監控
Zeabur 平台提供即時日誌，關注：
- 資料庫初始化狀態
- BGG API 請求狀態  
- OpenAI API 回應
- Email 發送結果