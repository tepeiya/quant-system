"""
持仓盈亏警报
==========
每次跑 daily_signal.py 或 止损监控 时，
如果总账户亏损超10%或单票亏损超15%，自动推通知
"""

import os
import json
import logging
from datetime import datetime

logger = logging.getLogger("quant.alerts")

TOTAL_DRAWDOWN_ALERT = 10  # 总账户亏损10%告警
SINGLE_LOSS_ALERT = 15     # 单票亏损15%告警


def check_alerts():
    """检查是否需要告警"""
    alerts = []

    # 读取持仓
    portfolio_file = "signals/portfolio.json"
    if not os.path.exists(portfolio_file):
        return alerts

    try:
        with open(portfolio_file) as f:
            portfolio = json.load(f)
    except:
        return alerts

    equity = portfolio.get("equity", 0)
    positions = portfolio.get("positions", {})

    # 初始资金估算（从日报读取最早的equity）
    initial_equity = 1000
    import glob
    report_files = sorted(glob.glob("signals/reports/report_*.txt"))
    if report_files:
        try:
            with open(report_files[0]) as f:
                content = f.read()
        except:
            content = ""
        for line in content.split("\n"):
            if "权益:" in line:
                try:
                    initial_equity = float(line.split("$")[1].replace(",", ""))
                    break
                except:
                    pass

    # 总账户回撤
    total_drawdown = (equity - initial_equity) / initial_equity * 100
    if total_drawdown < -TOTAL_DRAWDOWN_ALERT:
        alerts.append({
            "type": "total_drawdown",
            "severity": "high",
            "message": f"⚠️ 总账户亏损{abs(total_drawdown):.1f}%，当前${equity:.0f}，初始${initial_equity:.0f}",
            "data": {"drawdown_pct": round(total_drawdown, 1)}
        })

    # 单票亏损
    for sym, p in positions.items():
        pnl_pct = p.get("pnl_pct", 0)
        if pnl_pct < -SINGLE_LOSS_ALERT:
            alerts.append({
                "type": "single_loss",
                "severity": "high",
                "message": f"⚠️ {sym} 亏损{abs(pnl_pct):.1f}%，成本${p.get('cost_basis',0):.0f}，现市值${p.get('market_value',0):.0f}",
                "data": {"symbol": sym, "pnl_pct": round(pnl_pct, 1)}
            })

    return alerts


def push_alerts(alerts: list):
    """推送告警"""
    if not alerts:
        return

    for alert in alerts:
        logger.warning(alert["message"])

    # Android通知
    try:
        import subprocess
        for alert in alerts:
            subprocess.run([
                "android-notification", "send",
                "--title", f"量化告警: {alert['type']}",
                "--body", alert["message"]
            ], capture_output=True, timeout=5)
    except:
        pass

    # 写入文件
    alert_file = "signals/alerts.txt"
    with open(alert_file, "a") as f:
        for alert in alerts:
            f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M')} [{alert['type']}] {alert['message']}\n")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    alerts = check_alerts()
    if alerts:
        print(f"⚠️ 告警 {len(alerts)} 条:")
        for a in alerts:
            print(f"  {a['message']}")
        push_alerts(alerts)
    else:
        print("✅ 所有指标正常")
