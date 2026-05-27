"""
日志归档工具
=========
功能：每日信号运行日志自动按月归档，保留最近12个月
"""

import os
import shutil
import glob
import logging
from datetime import datetime

logger = logging.getLogger("quant.logs")


def archive():
    """归档日志文件到按月目录"""
    now = datetime.now()
    month_dir = now.strftime("%Y_%m")
    archive_base = "signals/logs"
    target = f"{archive_base}/{month_dir}"
    os.makedirs(target, exist_ok=True)

    # 信号文件
    for f in glob.glob("signals/signal_*.json"):
        date = os.path.basename(f).replace("signal_", "").replace(".json", "")
        file_month = date[:7].replace("-", "_")
        if file_month < month_dir:
            dest = f"{archive_base}/{file_month}/"
            os.makedirs(dest, exist_ok=True)
            shutil.move(f, dest)

    # 交易日志
    for f in glob.glob("signals/trade_log*.json"):
        shutil.copy(f, target)

    # 日报
    for f in glob.glob("signals/reports/report_*.txt"):
        date = os.path.basename(f).replace("report_", "").replace(".txt", "")
        file_month = date[:7].replace("-", "_")
        if file_month < month_dir:
            dest = f"{archive_base}/{file_month}/"
            os.makedirs(dest, exist_ok=True)
            shutil.move(f, dest)

    # 清理过旧日志（保留12个月）
    for d in sorted(os.listdir(archive_base)):
        if d.count("_") == 1 and d < (now - __import__("dateutil.relativedelta").relativedelta(months=12)).strftime("%Y_%m"):
            shutil.rmtree(f"{archive_base}/{d}", ignore_errors=True)

    count = len(glob.glob(f"{target}/*"))
    logger.info(f"日志已归档到 {target}: {count}个文件")
    return count


def status():
    """查看归档状态"""
    archive_base = "signals/logs"
    if not os.path.exists(archive_base):
        return {"months": 0, "total_files": 0}
    months = sorted(os.listdir(archive_base))
    total = sum(len(glob.glob(f"{archive_base}/{m}/*")) for m in months)
    return {"months": len(months), "total_files": total, "month_list": months}


if __name__ == "__main__":
    import sys
    if "--status" in sys.argv:
        s = status()
        print(f"归档月份: {s['months']}个")
        print(f"总文件数: {s['total_files']}")
        for m in s.get("month_list", []):
            files = len(glob.glob(f"signals/logs/{m}/*"))
            print(f"  {m}: {files}个文件")
    else:
        archive()
