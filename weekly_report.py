"""
周报生成器
=========
每周五收盘后自动生成本周交易报告。

内容：
  - 周收益（本周 vs 上周）
  - 本周交易记录
  - 当前持仓
  - 大盘回顾
  - 因子表现

用法：
  python3 weekly_report.py
"""

import os
import json
import logging
from datetime import datetime, timedelta

logger = logging.getLogger("quant.weekly")


def load_equity_history(days=90):
    """从日报文件读取权益历史"""
    history = []
    reports_dir = "signals/reports"
    if not os.path.exists(reports_dir):
        return history
    for f in sorted(os.listdir(reports_dir)):
        if not f.startswith("report_") or not f.endswith(".txt"):
            continue
        date = f.replace("report_", "").replace(".txt", "")
        content = open(f"{reports_dir}/{f}").read()
        for line in content.split("\n"):
            if "权益:" in line:
                try:
                    eq = float(line.split("$")[1].replace(",", ""))
                    history.append({"date": date, "equity": eq})
                except:
                    pass
                break
    return history[-days:]


def generate():
    """生成本周报告"""
    now = datetime.now()
    week_num = now.isocalendar()[1]

    # 权益历史
    history = load_equity_history(90)
    if len(history) < 2:
        return {"error": "数据不足，至少需要2天的日报"}

    # 本周收益
    this_week_start = now - timedelta(days=now.weekday())
    week_equities = [h for h in history if h["date"] >= this_week_start.strftime("%Y-%m-%d")]
    last_equity = history[-1]["equity"] if history else 0
    first_equity = history[0]["equity"] if history else 0

    if len(week_equities) >= 2:
        week_start_val = week_equities[0]["equity"]
        week_end_val = week_equities[-1]["equity"]
        week_return = (week_end_val - week_start_val) / week_start_val * 100
    else:
        week_return = 0

    total_return = (last_equity - first_equity) / first_equity * 100 if first_equity > 0 else 0

    # 本周交易
    trades = []
    trade_log_file = "signals/trade_log.json"
    if os.path.exists(trade_log_file):
        with open(trade_log_file) as f:
            all_trades = json.load(f)
        week_start = (now - timedelta(days=7)).strftime("%Y-%m-%d")
        trades = [t for t in all_trades if t.get("time", "").startswith(week_start[:10])]

    # 当前持仓
    positions = {}
    pf_file = "signals/portfolio.json"
    if os.path.exists(pf_file):
        with open(pf_file) as f:
            pf = json.load(f)
        positions = pf.get("positions", {})
        last_equity = pf.get("equity", last_equity)

    # 大盘(从信号文件读)
    market_trend = "?"
    import glob
    signals = sorted(glob.glob("signals/signal_*.json"))
    if signals:
        with open(signals[-1]) as f:
            sig = json.load(f)
        market_trend = sig.get("market", {}).get("trend", "?")

    # 构建报告
    total_pnl = sum(p.get("pnl_amount", 0) for p in positions.values())

    lines = []
    lines.append(f"{'='*55}")
    lines.append(f"  📊 M+ 周报 · 2026年第{week_num}周")
    lines.append(f"  {now.strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"{'='*55}")
    lines.append(f"")
    lines.append(f"📈 大盘趋势: {market_trend}")
    lines.append(f"")
    lines.append(f"💰 账户表现")
    lines.append(f"  总权益: ${last_equity:>8,.2f}")
    lines.append(f"  本周收益: {week_return:>+7.2f}%")
    lines.append(f"  累计收益: {total_return:>+7.2f}%")
    lines.append(f"")
    lines.append(f"📋 当前持仓 ({len(positions)}只) 总PnL: ${total_pnl:+.2f}")

    if positions:
        for sym, p in sorted(positions.items()):
            pnl = p.get("pnl_amount", 0)
            emoji = "🟢" if pnl >= 0 else "🔴"
            lines.append(f"  {emoji} {sym:>6} {p['qty']:>2}股 ${p.get('current_price',0):>7.2f} {pnl:>+8.2f}")

    if trades:
        lines.append(f"")
        lines.append(f"📝 本周交易 ({len(trades)}笔)")
        for t in trades[-10:]:
            lines.append(f"  {t.get('time','')[:10]} {t['side']:>4} {t['symbol']:>6} x{t['qty']:>3} @ ${t.get('price',0):.2f}")

    lines.append(f"")
    lines.append(f"{'='*55}")
    lines.append(f"  下周一自动调仓，祝好！M+ 🤝")
    lines.append(f"{'='*55}")

    report_text = "\n".join(lines)

    # 保存周报
    report_path = f"signals/reports/weekly_{now.strftime('%Y%m%d')}.txt"
    with open(report_path, "w") as f:
        f.write(report_text)

    # 推送
    try:
        import subprocess
        subprocess.run([
            "android-notification", "send",
            "--title", f"📊 M+ 周报 · 第{week_num}周",
            "--body", f"权益${last_equity:.0f} | 本周{week_return:+.2f}% | 累计{total_return:+.2f}% | 持仓{len(positions)}只 | 总PnL ${total_pnl:+.2f}",
        ], capture_output=True, timeout=5)
    except:
        pass

    print(report_text)
    return report_text


if __name__ == "__main__":
    generate()
