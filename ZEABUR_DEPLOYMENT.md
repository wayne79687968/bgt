# BGG RAG Daily - Zeabur 部署指南

## 🚀 部署步驟

### 1. 準備 Zeabur 帳號
- 前往 [Zeabur](https://zeabur.com) 註冊帳號
- 連接你的 GitHub 帳號

### 2. 建立新專案
- 在 Zeabur 控制台點擊「Create Project」
- 選擇此 GitHub 儲存庫

### 3. 配置服務
Zeabur 會自動讀取 `zeabur.yml` 配置檔案，並建立兩個服務：

#### 主應用程式 (app)
- **類型**: Python 應用
- **啟動命令**: `python start.py`
- **埠號**: 5000
- **健康檢查**: `/health` 端點

#### 排程服務 (scheduler)
- **類型**: Python 背景服務
- **啟動命令**: `python scheduler.py`
- **功能**: 每天早上 8:00 自動執行報表產生

### 4. 設定環境變數
在 Zeabur 控制台設定以下環境變數：

```bash
# 必要設定
ADMIN_USERNAME=你的管理員帳號
ADMIN_PASSWORD=你的安全密碼
SECRET_KEY=你的安全金鑰

# 可選設定
TZ=Asia/Taipei
PORT=5000
FLASK_ENV=production
```

### 5. 部署
- 推送代碼到 GitHub
- Zeabur 會自動觸發部署
- 等待部署完成

## 🔧 功能特色

### ✅ 已實現功能
1. **Zeabur 雲端部署支援**
   - 自動化部署配置
   - 雙服務架構（主應用 + 排程服務）
   - 健康檢查機制

2. **排程系統更新**
   - 改為每天早上 8:00 自動執行
   - 台北時區設定

3. **設定管理頁面**
   - 手動執行完整排程任務
   - 系統狀態監控
   - 快速操作區

4. **首頁 Markdown 顯示**
   - 自動顯示當日報表
   - 如無當日報表則顯示最新報表

5. **日期選擇器**
   - 下拉選單選擇歷史報表
   - 自動載入指定日期報表

### 🎯 使用方式

#### 訪問應用
- 主頁：`https://your-app.zeabur.app/`
- 設定頁：`https://your-app.zeabur.app/settings`

#### 登入帳號
- 使用環境變數中設定的 `ADMIN_USERNAME` 和 `ADMIN_PASSWORD`

#### 手動執行排程
1. 登入後進入設定頁面
2. 點擊「立即執行完整排程」按鈕
3. 系統會自動執行：
   - 抓取 BGG 熱門遊戲榜單
   - 獲取遊戲詳細資訊
   - 抓取討論串並翻譯
   - 產生報表

#### 查看歷史報表
1. 在首頁使用日期選擇器
2. 選擇想查看的日期
3. 系統會自動載入該日期的報表

## 📋 目錄結構

```
bgg_rag_daily/
├── zeabur.yml          # Zeabur 部署配置
├── start.py            # 應用啟動腳本
├── app.py              # 主要 Flask 應用
├── scheduler.py        # 排程服務
├── templates/          # HTML 模板
│   ├── base.html       # 基底模板
│   ├── report.html     # 報表顯示頁面
│   ├── settings.html   # 設定管理頁面
│   └── login.html      # 登入頁面
└── requirements.txt    # Python 依賴套件
```

## 🔍 監控與維護

### 健康檢查
- 應用提供 `/health` 端點進行健康檢查
- Zeabur 會每 30 秒檢查一次應用狀態

### 日誌查看
- 在 Zeabur 控制台可以查看應用日誌
- 排程執行狀況和錯誤訊息都會記錄

### 手動重啟
- 如需重啟服務，可在 Zeabur 控制台手動重啟
- 或推送新代碼觸發自動重新部署

## 🛠️ 疑難排解

### 常見問題

1. **排程沒有執行**
   - 檢查 scheduler 服務是否正常運行
   - 確認時區設定正確 (`TZ=Asia/Taipei`)

2. **找不到報表**
   - 檢查 `frontend/public/outputs/` 目錄是否存在
   - 確認資料庫連接正常

3. **登入失敗**
   - 檢查環境變數 `ADMIN_USERNAME` 和 `ADMIN_PASSWORD` 設定
   - 確認 `SECRET_KEY` 已設定

### 支援與協助
如有問題，請檢查：
1. Zeabur 控制台的服務狀態
2. 應用日誌中的錯誤訊息
3. 環境變數是否正確設定

---

**部署完成後，你的 BGG 熱門遊戲報表系統就可以每天自動運行了！** 🎉