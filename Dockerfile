FROM python:3.12-slim

WORKDIR /app

# 系统依赖（numpy/pandas编译需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc build-essential curl && \
    rm -rf /var/lib/apt/lists/*

# 复制代码
COPY . .

# 安装Python依赖
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir \
    flask pandas numpy matplotlib \
    alpaca-py yfinance requests \
    passlib \
    wheel

# 清理调试文件
RUN rm -f debug_ic.py debug_signal.py quick_signal.py test_full.py fix_stability.py

# 创建必要目录
RUN mkdir -p logs signals config data_cache

EXPOSE 8765

# Railway动态端口支持
ENV PORT 8765

# 启动Web服务
CMD ["sh", "-c", "cd /app && python3 -c \"
import os
# Railway用 \$PORT，本地用8765
port = int(os.environ.get('PORT', 8765))
from web_app import app, register_blueprints
register_blueprints()
print(f'🚀 启动在 0.0.0.0:{port}')
app.run(host='0.0.0.0', port=port, debug=False)
\""]
