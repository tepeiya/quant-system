"""
每日报告推送
==========
功能：每天跑完信号后自动生成一份日报，推送到手机。

推送方式（按优先级）：
1. Bark App（iOS免费，最方便）— https://bark.day.app
2. 直接写文件（供系统通知读取）

用法：
  python3 daily_report.py              # 生成日报
  python3 daily_report.py --push       # 生成日报+推送通知
"""

import os
import json
import logging
from datetime import datetime

logger = logging.getLogger("quant.report")

REPORT_DIR = "signals/reports"
os.makedirs(REPORT_DIR, exist_ok=True)


def load_signal() -> dict | None:
    """读取最新信号"""
    import glob
    files = sorted(glob.glob("signals/signal_*.json"))
    if not files:
        return None
    with open(files[-1]) as f:
        return json.load(f)


def load_portfolio():
    """读取持仓"""
    if os.path.exists("signals/portfolio.json"):
        with open("signals/portfolio.json") as f:
            return json.load(f)
    return None


def load_trade_log(limit=5):
    """读取最近交易"""
    if os.path.exists("signals/trade_log.json"):
        with open("signals/trade_log.json") as f:
            logs = json.load(f)
            return logs[-limit:]
    return []


def generate_report() -> dict:
    """生成日报"""
    signal = load_signal()
    portfolio = load_portfolio()
    trades = load_trade_log(5)

    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    # 大盘状态
    if signal:
        market = signal.get("market", {})
        top_scores = signal.get("top_scores", [])
        buy_candidates = signal.get("buy_candidates", [])
    else:
        market = {"trend": "无数据", "action": "无"}
        top_scores = []
        buy_candidates = []

    # 持仓
    positions = portfolio.get("positions", {}) if portfolio else {}
    equity = portfolio.get("equity", 0) if portfolio else 0
    cash = portfolio.get("cash", 0) if portfolio else 0

    total_pnl = sum(p.get("pnl_amount", 0) for p in positions.values())
    total_cost = sum(p.get("cost_basis", 0) for p in positions.values())
    total_pnl_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0

    # 构建日报文本
    lines = []
    lines.append(f"📊 量化日报 | {now[:10]}")
    lines.append("")
    lines.append(f"大盘: {market.get('trend', '?')}")
    lines.append(f"建议: {market.get('action', '?')}")

    if positions:
        lines.append(f"")
        lines.append(f"📋 持仓 ({len(positions)}只)")
        total_pnl_display = 0
        for sym, p in sorted(positions.items()):
            pnl = p.get("pnl_amount", 0)
            pnl_str = f"${pnl:+.2f}" if abs(pnl) >= 0.01 else "$0.00"
            lines.append(f"{sym}: {p['qty']}股 | {pnl_str} ({p.get('pnl_pct',0):+.2f}%)")
            total_pnl_display += pnl
        lines.append(f"合计: ${total_pnl_display:+.2f} ({total_pnl_pct:+.2f}%)")
        lines.append(f"权益: ${equity:,.2f}")
    else:
        lines.append(f"持仓: 空仓")
        lines.append(f"现金: ${equity:,.2f}")

    if buy_candidates:
        lines.append(f"")
        lines.append(f"🟢 买入候选:")
        for c in buy_candidates[:3]:
            lines.append(f"  {c['ticker']} 评分{c['score']}")

    if trades:
        lines.append(f"")
        lines.append(f"📝 最近交易:")
        for t in trades:
            lines.append(f"  {t.get('time','')[:10]} {t['side']} {t['symbol']} x{t['qty']} @ ${t['price']}")

    report_text = "\n".join(lines)

    # 保存日报
    report_path = f"{REPORT_DIR}/report_{now[:10]}.txt"
    with open(report_path, "w") as f:
        f.write(report_text)

    # 同时保存最新版（覆盖）
    latest_path = f"{REPORT_DIR}/latest_report.txt"
    with open(latest_path, "w") as f:
        f.write(report_text)

    report_data = {
        "date": now[:10],
        "time": now,
        "market_trend": market.get("trend", "?"),
        "market_action": market.get("action", "?"),
        "equity": round(equity, 2),
        "cash": round(cash, 2),
        "position_count": len(positions),
        "total_pnl": round(total_pnl, 2),
        "total_pnl_pct": round(total_pnl_pct, 2),
        "report_text": report_text,
    }

    return report_data


def push_notification(report: dict):
    """推送通知到手机"""
    text = report["report_text"]

    # 告警检查
    try:
        from risk_alerts import check_alerts, push_alerts
        alerts = check_alerts()
        if alerts:
            push_alerts(alerts)
            text += "\n\n⚠️ 告警:\n" + "\n".join(a["message"] for a in alerts)
    except:
        pass

    # 方式1: Android系统通知（Minis环境）
    import subprocess, json
    try:
        result = subprocess.run(
            ["android-notification", "send",
             "--title", f"📊 量化日报 {report['date']}",
             "--body", text[:500]],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            logger.info("📱 通知已推送到手机")
            return
    except:
        pass

    # 方式2: PushPlus微信
    pushplus = os.environ.get("PUSHPLUS_TOKEN", "")
    if pushplus:
        try:
            import requests
            r = requests.post("https://www.pushplus.plus/send", json={
                "token": pushplus, "title": f"量化日报 {report['date']}",
                "content": text.replace("\n", "<br>"), "template": "html",
            }, timeout=5)
            if r.status_code == 200:
                logger.info("微信推送成功")
                return
        except:
            pass

    # 方式3: 写文件
    with open("signals/latest_notification.txt", "w") as f:
        f.write(text)
    logger.info(f"通知已保存到文件")


def run():
    """生成日报并推送"""
    report = generate_report()
    print(report["report_text"])

    if "--push" in __import__("sys").argv:
        push_notification(report)

    return report


if __name__ == "__main__":
    run()
