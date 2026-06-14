FROM python:3.12-slim

RUN useradd -m -u 1000 user && mkdir -p /app
WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir --default-timeout=300 -r requirements.txt

# 复制代码（还在 root 身份）
COPY --chown=user:user . .

# 创建可写数据目录（必须放在 COPY 之后，否则会被覆盖）
RUN mkdir -p logs signals config data_cache && chmod 777 logs signals config data_cache

# 清理调试文件
RUN rm -f debug_ic.py debug_signal.py quick_signal.py test_full.py fix_stability.py || true

# 切换到普通用户
USER user
ENV HOME=/home/user PATH=/home/user/.local/bin:$PATH

EXPOSE 8765

CMD gunicorn web_app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120 --log-level info
