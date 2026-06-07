FROM python:3.12-slim

# 创建用户（HF Spaces兼容）
RUN useradd -m -u 1000 user && mkdir -p /app && chown -R user:user /app
USER user
ENV HOME=/home/user PATH=/home/user/.local/bin:$PATH
WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir --default-timeout=300 -r requirements.txt

# 复制代码
COPY --chown=user . .

# 清理调试文件
RUN rm -f debug_ic.py debug_signal.py quick_signal.py test_full.py fix_stability.py || true
RUN mkdir -p logs signals config data_cache

# 端口
EXPOSE 8765

# 启动脚本：同时运行 Web 和 Daemon
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh
CMD ["/app/docker-entrypoint.sh"]
