FROM python:3.12-slim

# 使用 root 完成所有初始化，最后再切用户
WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir --default-timeout=300 -r requirements.txt

# 复制代码
COPY . .

# 创建所有运行时目录并设为 777（user 和 volume 挂载都能写）
RUN mkdir -p /app/logs /app/signals /app/config /app/data_cache && \
    chmod -R 777 /app/logs /app/signals /app/config /app/data_cache

# 创建非 root 用户
RUN useradd -m -u 1000 user && chown -R user:user /app

# 切换到普通用户
USER user
ENV HOME=/home/user PATH=/home/user/.local/bin:$PATH

EXPOSE 8765

CMD gunicorn web_app:app --bind 0.0.0.0:${PORT:-8765} --workers 2 --timeout 120 --log-level info
