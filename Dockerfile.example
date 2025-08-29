# 多階段構建 Dockerfile，優化構建速度和層級緩存
FROM python:3.13-slim as base

# 設定工作目錄
WORKDIR /app

# 安裝系統依賴（這層會被緩存，除非系統依賴改變）
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# ===========================
# 依賴安裝階段（分層緩存優化）
# ===========================
FROM base as deps

# 只複製 requirements.txt，這樣只有依賴改變時才重新安裝
COPY requirements.txt .

# 安裝 Python 依賴（這是最耗時的步驟，會被緩存）
# 分離基礎依賴和重型依賴來提高緩存效率
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir gunicorn

# 先安裝不常變動的重型依賴（scikit-learn, numpy, pandas 等）
# 這些會被強烈緩存，除非版本改變
RUN pip install --no-cache-dir \
    numpy==2.3.2 \
    scipy==1.16.1 \
    scikit-learn==1.4.0 \
    pandas==2.3.2

# 安裝其餘依賴
RUN sed '/-e/d; /numpy/d; /scipy/d; /scikit-learn/d; /pandas/d' requirements.txt | \
    pip install --no-cache-dir -r /dev/stdin

# ===========================
# 應用程式階段
# ===========================
FROM deps as app

# 創建必要目錄
RUN mkdir -p /app/data /app/frontend/public/outputs /app/static/images

# 複製應用程式代碼（這層在代碼改變時才會重建）
COPY . .

# 設定環境變數
ENV PYTHONPATH=/app
ENV PORT=5000
ENV FLASK_ENV=production

# 暴露端口
EXPOSE 5000

# 健康檢查
HEALTHCHECK --interval=30s --timeout=30s --start-period=60s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:5000/health')" || exit 1

# 啟動命令
CMD ["python", "start_simple.py"]