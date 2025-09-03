# BGG 熱門遊戲報表系統

一個簡化的 Flask 應用程式，用於顯示 BoardGameGeek (BGG) 熱門遊戲報表。

## 🎯 功能特色

- 🔐 簡單的登入機制
- 📊 Markdown 報表顯示
- 🔄 手動重新產生報表
- ⏰ 自動排程（每天早上 9:00）
- 🚀 可部署到雲端平台

## 🏗️ 系統架構

```
├── app.py              # Flask 主應用程式
├── scheduler.py        # 自動排程器
├── templates/          # HTML 模板
├── requirements.txt    # Python 依賴
├── Procfile           # 部署配置
├── render.yaml        # Render 部署配置
└── DEPLOYMENT.md      # 詳細部署指南
```

## 🚀 快速開始

### 本地開發

1. **安裝依賴**
```bash
pip install -r requirements.txt
```

2. **設定環境變數**
```bash
export ADMIN_USERNAME=admin
export ADMIN_PASSWORD=your-password
export SECRET_KEY=your-secret-key
export OPENAI_API_KEY=your-openai-key
```

3. **啟動應用程式**
```bash
# 啟動 Web 服務
python app.py

# 啟動排程器（另一個終端）
python scheduler.py
```

4. **訪問應用程式**
   - 開啟瀏覽器：http://localhost:5000
   - 使用設定的帳號密碼登入

## 🌐 部署到雲端

### Render（推薦）

1. 將程式碼推送到 GitHub
2. 在 [Render](https://render.com) 創建新的 Blueprint
3. 連接您的 GitHub 倉庫
4. 設定環境變數：
   - `OPENAI_API_KEY`
   - `ADMIN_USERNAME`
   - `ADMIN_PASSWORD`
   - `SECRET_KEY`

詳細部署指南請參考 [DEPLOYMENT.md](DEPLOYMENT.md)

### 其他平台

- **Heroku**: 支援 Procfile
- **Railway**: 自動檢測 Python 應用程式
- **DigitalOcean App Platform**: 支援 Docker 部署

## 📱 使用說明

### Web 介面

- **首頁**: 顯示最新的 BGG 熱門遊戲報表
- **登入**: 使用環境變數中設定的帳號密碼
- **重新產生**: 手動觸發報表產生
- **登出**: 結束登入狀態

### 自動排程

系統會在每天早上 9:00 自動執行：

1. 抓取 BGG 熱門遊戲榜單
2. 獲取遊戲詳細資訊
3. 抓取討論串並翻譯
4. 產生繁體中文報表

## 🔧 環境變數

| 變數名稱 | 必要 | 說明 |
|---------|------|------|
| `SECRET_KEY` | ✅ | Flask 應用程式密鑰 |
| `ADMIN_USERNAME` | ✅ | 登入帳號 |
| `ADMIN_PASSWORD` | ✅ | 登入密碼 |
| `OPENAI_API_KEY` | ✅ | OpenAI API 金鑰 |
| `PORT` | ❌ | 服務埠號（預設：5000） |

## 📁 檔案結構

```
bgg_rag_daily/
├── app.py                          # Flask 主應用程式
├── scheduler.py                    # 自動排程器
├── templates/                      # HTML 模板
│   ├── base.html                  # 基礎模板
│   ├── login.html                 # 登入頁面
│   ├── report.html                # 報表顯示
│   └── error.html                 # 錯誤頁面
├── data/                          # 資料庫檔案
│   └── cache/                    # 快取目錄
├── frontend/public/outputs/       # 報表輸出目錄
├── requirements.txt               # Python 依賴
├── Procfile                      # 部署配置
├── render.yaml                   # Render 部署配置
└── DEPLOYMENT.md                 # 詳細部署指南
```

## 🛠️ 開發

### 本地測試

```bash
# 測試 Flask 應用程式
python -c "from app import app; print('OK')"

# 測試排程器
python -c "from scheduler import fetch_and_generate_report; print('OK')"
```

### 手動產生報表

```bash
python generate_report.py --lang zh-tw --detail all
```

## 📊 成本估算

- **Render**: 約 $14/月（Web + Worker）
- **Heroku**: 約 $14/月（Web + Worker）
- **Railway**: 約 $5-10/月（使用量計費）

## 🔍 故障排除

### 常見問題

1. **無法登入**: 檢查環境變數設定
2. **報表無法產生**: 檢查 OpenAI API 金鑰
3. **排程器無法啟動**: 檢查 Worker 服務狀態

### 日誌查看

應用程式會輸出詳細的執行日誌，可在雲端平台的 Logs 頁面查看。

## 📄 授權

MIT License

## 🤝 貢獻

歡迎提交 Issue 和 Pull Request！