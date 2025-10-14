# 使用官方 Python 3.7 精簡鏡像 (turicreate 相容性)
FROM python:3.7-slim

# 設置工作目錄
WORKDIR /app

# 設置環境變數
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# 安裝系統依賴
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    libgomp1 \
    postgresql-client \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# 複製應用代碼 (需要 board-game-recommender 目錄)
COPY . .

# 安裝 Python 依賴
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 創建必要目錄（卷掛載會覆蓋這些目錄）
RUN mkdir -p /app/data /app/frontend/public/outputs

# 暴露端口（動態）
EXPOSE $PORT

# 啟動命令 - 使用完整的主應用
CMD gunicorn --bind 0.0.0.0:$PORT --timeout 120 --workers 1 --access-logfile - --error-logfile - start_simple:app