FROM python:3.12-slim

# 创建用户（HF Spaces 要求）
RUN useradd -m -u 1000 user && mkdir -p /app && chown -R user:user /app
USER user
ENV HOME=/home/user PATH=/home/user/.local/bin:$PATH
WORKDIR /app

# 安装依赖
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir --default-timeout=300 \
    flask gunicorn pandas numpy alpaca-py yfinance requests passlib

# 复制代码
COPY --chown=user . .

# 清理
RUN rm -f debug_ic.py debug_signal.py quick_signal.py test_full.py fix_stability.py || true
RUN mkdir -p logs signals config data_cache

# Hugging Face Spaces 默认端口 7860
EXPOSE 7860

# 启动
CMD gunicorn web_app:app --bind 0.0.0.0:7860 --workers 2 --timeout 120 --log-level info
