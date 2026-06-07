FROM python:3.12-slim

RUN useradd -m -u 1000 user && mkdir -p /app
WORKDIR /app

# 先创建目录并给权限
RUN mkdir -p logs signals config data_cache && chmod 777 logs signals config data_cache

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir --default-timeout=300 -r requirements.txt

# 复制全部代码 + entrypoint（还在 root 身份）
COPY . .
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

# 清理调试文件
RUN rm -f debug_ic.py debug_signal.py quick_signal.py test_full.py fix_stability.py || true

# 切换到普通用户
USER user
ENV HOME=/home/user PATH=/home/user/.local/bin:$PATH

EXPOSE 8765

CMD ["/app/docker-entrypoint.sh"]
