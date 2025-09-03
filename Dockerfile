# 使用官方 Python 3.11 精簡鏡像
FROM python:3.11-slim

# 設置工作目錄
WORKDIR /app

# 設置環境變數
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# 安裝系統依賴
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# 複製依賴文件
COPY requirements.core.txt .
COPY requirements.ml.txt .

# 安裝 Python 依賴 - 分層安裝以優化緩存
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.core.txt && \
    pip install --no-cache-dir -r requirements.ml.txt

# 複製應用代碼
COPY . .

# 創建必要目錄
RUN mkdir -p data frontend/public/outputs

# 暴露端口（動態）
EXPOSE $PORT

# 啟動命令 - 使用完整的主應用
CMD gunicorn --bind 0.0.0.0:$PORT --timeout 120 --workers 1 --access-logfile - --error-logfile - start_simple:app