FROM python:3.12-slim

WORKDIR /app

# 系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 复制代码
COPY . .

# 安装Python依赖
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir --default-timeout=300 \
    flask gunicorn \
    pandas numpy \
    alpaca-py yfinance \
    requests passlib

# 清理
RUN rm -f debug_ic.py debug_signal.py quick_signal.py test_full.py fix_stability.py
RUN mkdir -p logs signals config data_cache

EXPOSE 8765

# 启动 - 用gunicorn生产级服务器
CMD gunicorn web_app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120 --log-level info
