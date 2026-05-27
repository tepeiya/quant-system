"""
持仓导出工具
=========
导出持仓和交易记录为 CSV 格式，方便报税或导入 Excel
"""

import os
import csv
import json
import logging
from datetime import datetime

logger = logging.getLogger("quant.export")

EXPORT_DIR = "signals/exports"
os.makedirs(EXPORT_DIR, exist_ok=True)


def export_positions():
    """导出当前持仓为CSV"""
    pf_file = "signals/portfolio.json"
    if not os.path.exists(pf_file):
        return {"error": "无持仓数据"}

    with open(pf_file) as f:
        pf = json.load(f)

    positions = pf.get("positions", {})
    if not positions:
        return {"error": "空仓"}

    now = datetime.now().strftime("%Y%m%d_%H%M")
    path = f"{EXPORT_DIR}/positions_{now}.csv"

    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["股票", "数量", "均价", "现价", "成本", "市值", "PnL", "PnL%", "占比%"])
        equity = pf.get("equity", 1)
        for sym, p in sorted(positions.items()):
            cost = p.get("cost_basis", 0)
            mv = p.get("market_value", 0)
            pnl = p.get("pnl_amount", 0)
            pnl_pct = p.get("pnl_pct", 0)
            pct = (mv / max(equity, 1) * 100) if equity > 0 else 0
            w.writerow([
                sym, p.get("qty", 0),
                f"{p.get('avg_entry_price', 0):.2f}",
                f"{p.get('current_price', 0):.2f}",
                f"{cost:.2f}", f"{mv:.2f}",
                f"{pnl:.2f}", f"{pnl_pct:.2f}",
                f"{pct:.1f}"
            ])

    logger.info(f"持仓已导出: {path}")
    return {"path": path, "count": len(positions)}


def export_trades():
    """导出交易记录为CSV"""
    trade_file = "signals/trade_log.json"
    if not os.path.exists(trade_file):
        return {"error": "无交易记录"}

    with open(trade_file) as f:
        trades = json.load(f)

    if not trades:
        return {"error": "无交易记录"}

    now = datetime.now().strftime("%Y%m%d_%H%M")
    path = f"{EXPORT_DIR}/trades_{now}.csv"

    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["时间", "操作", "股票", "数量", "价格", "金额"])
        for t in trades:
            w.writerow([
                t.get("time", "")[:19],
                t.get("side", "").upper(),
                t.get("symbol", ""),
                t.get("qty", 0),
                f"{t.get('price', 0):.2f}",
                f"{t.get('value', 0):.2f}",
            ])

    logger.info(f"交易已导出: {path}")
    return {"path": path, "count": len(trades)}


def export_all():
    """导出所有数据"""
    p = export_positions()
    t = export_trades()
    return {"positions": p, "trades": t}


if __name__ == "__main__":
    import sys
    if "--trades" in sys.argv:
        r = export_trades()
    elif "--all" in sys.argv:
        r = export_all()
    else:
        r = export_positions()
    print(r)
