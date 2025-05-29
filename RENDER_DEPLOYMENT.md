# BGG 報表系統 Render 部署完整指南

## 🚀 快速部署步驟

### 1. 準備 Git 倉庫

首先確保您的程式碼已推送到 GitHub：

```bash
# 如果還沒有 Git 倉庫
git init
git add .
git commit -m "Initial commit: BGG Report System"

# 推送到 GitHub
git remote add origin https://github.com/YOUR_USERNAME/bgg-report-system.git
git push -u origin main
```

### 2. 在 Render 創建服務

1. **登入 Render**
   - 前往 [render.com](https://render.com)
   - 使用 GitHub 帳號登入

2. **創建 Blueprint**
   - 點擊 "New" → "Blueprint"
   - 選擇您的 GitHub 倉庫
   - Render 會自動讀取 `render.yaml` 配置

3. **確認服務配置**
   - Web Service: `bgg-report-web`
   - Background Worker: `bgg-report-scheduler`

### 3. 設定環境變數

在 Render Dashboard 中設定以下環境變數：

#### 必要變數
- `OPENAI_API_KEY`: 您的 OpenAI API 金鑰
- `ADMIN_USERNAME`: 登入帳號（建議：admin）
- `ADMIN_PASSWORD`: 登入密碼（建議設定強密碼）
- `SECRET_KEY`: Flask 密鑰（會自動產生）

#### 可選變數
- `BGG_USERNAME`: 您的 BGG 使用者名稱
- `TZ`: 時區設定（建議：Asia/Taipei）

### 4. 部署確認

部署完成後，您會得到：
- Web 服務 URL：`https://your-app-name.onrender.com`
- 兩個服務都應該顯示為 "Live" 狀態

## ⏰ 排程設定詳解

### 時區配置

我們的排程器設定為每天早上 9:00 執行，但需要確保時區正確：

```python
# scheduler.py 中的設定
scheduler.add_job(
    fetch_and_generate_report,
    CronTrigger(hour=9, minute=0),  # 每天 9:00
    id='daily_report',
    name='每日 BGG 報表產生',
    replace_existing=True
)
```

### 確保排程正常運作

1. **檢查 Worker 狀態**
   - 在 Render Dashboard 中確認 `bgg-report-scheduler` 服務狀態為 "Live"
   - 查看 Logs 確認排程器已啟動

2. **查看日誌**
   - 應該看到：`排程器已設定：每天早上 9:00 執行報表產生`

3. **測試手動執行**
   - 登入您的應用程式
   - 點擊「🔄 重新產生報表」按鈕測試功能

## 🔧 進階配置

### 自訂時區

如果需要調整時區，更新 `render.yaml`：

```yaml
services:
  - type: worker
    name: bgg-report-scheduler
    runtime: python
    buildCommand: pip install -r requirements.txt
    startCommand: python scheduler.py
    envVars:
      - key: TZ
        value: Asia/Taipei  # 台北時區
```

### 調整排程時間

修改 `scheduler.py` 中的時間設定：

```python
# 例如：改為每天下午 2:30
scheduler.add_job(
    fetch_and_generate_report,
    CronTrigger(hour=14, minute=30),
    id='daily_report',
    name='每日 BGG 報表產生',
    replace_existing=True
)
```

## 📊 監控和維護

### 查看執行狀態

1. **Web 介面監控**
   - 訪問您的應用程式 URL
   - 登入後查看最新報表時間

2. **Render Dashboard**
   - 查看兩個服務的運行狀態
   - 監控 CPU 和記憶體使用量

3. **日誌監控**
   - Web Service 日誌：用戶訪問和錯誤
   - Worker 日誌：排程執行和報表產生

### 常見問題排除

1. **排程器無法啟動**
   ```
   解決方案：
   - 檢查 Worker 服務狀態
   - 確認環境變數設定正確
   - 查看錯誤日誌
   ```

2. **報表產生失敗**
   ```
   解決方案：
   - 檢查 OPENAI_API_KEY 是否正確
   - 確認 API 配額是否足夠
   - 查看詳細錯誤訊息
   ```

3. **時區問題**
   ```
   解決方案：
   - 設定 TZ 環境變數
   - 重新部署服務
   ```

## 💰 成本說明

### Render 定價
- **Web Service**: $7/月（Starter 方案）
- **Background Worker**: $7/月（Starter 方案）
- **總計**: $14/月

### 免費方案限制
- Web Service 有 750 小時/月免費額度
- Background Worker 需要付費方案
- 免費方案會在無活動時休眠

## 🔒 安全建議

1. **強密碼設定**
   - 使用複雜的 `ADMIN_PASSWORD`
   - 定期更換密碼

2. **API 金鑰保護**
   - 不要在程式碼中硬編碼 API 金鑰
   - 使用環境變數管理敏感資訊

3. **定期更新**
   - 定期更新依賴套件
   - 監控安全漏洞

## 📝 部署檢查清單

- [ ] GitHub 倉庫已創建並推送程式碼
- [ ] Render 帳號已創建
- [ ] Blueprint 已部署
- [ ] 環境變數已設定
- [ ] Web Service 狀態為 "Live"
- [ ] Worker Service 狀態為 "Live"
- [ ] 可以成功登入應用程式
- [ ] 手動產生報表功能正常
- [ ] 排程器日誌顯示正常啟動

## 🎯 下一步

部署完成後：

1. **測試功能**
   - 登入應用程式
   - 測試報表顯示
   - 測試手動產生報表

2. **等待自動執行**
   - 隔天早上 9:00 檢查是否自動產生新報表
   - 查看 Worker 日誌確認執行狀況

3. **監控和優化**
   - 定期檢查服務狀態
   - 根據使用情況調整配置

恭喜！您的 BGG 報表系統現在已經在雲端運行，並會每天自動產生最新的熱門遊戲報表！ 🎉