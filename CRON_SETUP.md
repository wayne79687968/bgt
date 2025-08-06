# BGG 報表排程設定指南

由於 Zeabur 平台對長時間運行的排程服務支援有限，我們提供了多種替代的排程解決方案：

## 方案 1：GitHub Actions 排程（推薦）

### 設定步驟：

1. **在 GitHub Repository 中設定 Secrets：**
   - 前往 `Settings` > `Secrets and variables` > `Actions`
   - 新增以下 Secrets：
     ```
     ZEABUR_APP_URL=https://your-app.zeabur.app
     CRON_SECRET_TOKEN=your-secure-random-token
     ```

2. **調整執行時間：**
   - 編輯 `.github/workflows/schedule.yml`
   - 修改 cron 表達式，例如：
     ```yaml
     schedule:
       # 每日台北時間 17:00 執行 (UTC 09:00)
       - cron: '0 9 * * *'
     ```

3. **手動觸發測試：**
   - 前往 `Actions` 頁面
   - 選擇 `Daily BGG Report Generation`
   - 點擊 `Run workflow` 進行測試

## 方案 2：外部 Cron 服務

### 使用 cron-job.org：

1. 註冊 [cron-job.org](https://cron-job.org)
2. 建立新的 Cron Job：
   ```
   URL: https://your-app.zeabur.app/api/cron-trigger
   Method: POST
   Headers: Authorization: Bearer your-cron-secret-token
   ```
3. 設定執行時間和頻率

### 使用其他服務：
- [EasyCron](https://www.easycron.com/)
- [SetCronJob](https://www.setcronjob.com/)

## 環境變數設定

在 Zeabur 中需要設定：
```
CRON_SECRET_TOKEN=your-secure-random-token
```

## API 端點說明

### `/api/cron-trigger` (POST)
- **用途**：外部 Cron 服務呼叫此端點觸發報表產生
- **驗證**：需要 Bearer Token
- **Headers**：
  ```
  Authorization: Bearer your-cron-secret-token
  Content-Type: application/json
  ```

### 安全性
- 使用隨機生成的 Token 進行驗證
- 記錄所有觸發請求的來源 IP
- 無需登入即可觸發（適合自動化）

## 時間設定說明

Web 介面中的時間設定現在主要用於：
- 顯示預期的執行時間
- 記錄使用者偏好
- 作為設定外部排程服務的參考

實際的執行時間需要在選擇的排程服務中進行配置。

## 故障排除

1. **GitHub Actions 失敗**：
   - 檢查 Secrets 是否正確設定
   - 確認 Zeabur 應用程式正在運行
   - 查看 Actions 執行日誌

2. **外部 Cron 失敗**：
   - 驗證 URL 和 Token 是否正確
   - 檢查 Zeabur 應用程式的日誌
   - 確認服務沒有休眠

3. **報表未生成**：
   - 查看應用程式日誌中的錯誤訊息
   - 檢查資料庫連接狀態
   - 驗證 OpenAI API Key 是否有效