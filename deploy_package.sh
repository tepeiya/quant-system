#!/bin/bash
# 创建部署包
PACKAGE="quant_system_$(date +%Y%m%d).tar.gz"

# 排除不需要的文件
EXCLUDE="--exclude=*.pyc --exclude=__pycache__ --exclude=*.log --exclude=.git --exclude=venv --exclude=env --exclude=*.db"

echo "正在打包系统..."
tar czf $PACKAGE $EXCLUDE \
    *.py \
    web/ \
    templates/ \
    static/ \
    signals/ \
    config/ \
    data_cache/ \
    requirements.txt \
    2>/dev/null

echo "打包完成: $PACKAGE"
ls -lh $PACKAGE
