#!/bin/sh
# 数据恢复脚本
# 容器重建后恢复数据：cp data_backup/* data_cache/
# 用法：sh restore_data.sh

BACKUP_DIR="data_backup"
TARGET_DIR="data_cache"
DATA_DIR="data"

echo "=== 恢复缓存数据 ==="
for f in prices.pkl sp500_tickers.json spy_real.pkl; do
  if [ -f "$BACKUP_DIR/$f" ]; then
    cp "$BACKUP_DIR/$f" "$TARGET_DIR/$f"
    echo "  ✅ 恢复 $f"
  else
    echo "  ⚠️  $BACKUP_DIR/$f 不存在"
  fi
done

echo ""
echo "=== 恢复数据库 ==="
for f in config.db signal_bus.db; do
  if [ -f "$BACKUP_DIR/$f" ]; then
    cp "$BACKUP_DIR/$f" "$DATA_DIR/$f"
    echo "  ✅ 恢复 $f"
  else
    echo "  ⚠️  $BACKUP_DIR/$f 不存在"
  fi
done

echo ""
echo "=== 完成 ==="
ls -lh $TARGET_DIR/prices.pkl 2>/dev/null
