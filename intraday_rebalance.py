"""
盘前快速调仓
==========
原理：开盘后15分钟用最新价格重新评分，如果信号有重大变化则调仓
不依赖历史数据缓存，只用当前盘前/开盘价的快照

用法：
  python3 intraday_rebalance.py
"""

import os
import logging
import time
from datetime import datetime

logger = logging.getLogger("quant.intraday")


def fetch_current_prices(tickers: list[str]) -> dict[str, float]:
    """获取当前最新价格（使用Alpaca快照API）"""
    import requests
    KEY = os.environ.get("ALPACA_API_KEY_ID", "")
    SECRET = os.environ.get("ALPACA_SECRET_KEY", "")
    if not KEY or not SECRET:
        logger.warning("Alpaca Key未设置")
        return {}

    base = "https://data.alpaca.markets"
    prices = {}

    # 批量获取（一次最多250只）
    for i in range(0, len(tickers), 200):
        batch = tickers[i:i+200]
        symbols = ",".join(batch)
        try:
            r = requests.get(
                f"{base}/v2/stocks/snapshots?symbols={symbols}",
                auth=(KEY, SECRET), timeout=10
            )
            if r.status_code == 200:
                data = r.json()
                for sym in batch:
                    snap = data.get(sym, {})
                    trade = snap.get("latestTrade", {})
                    if trade and trade.get("p"):
                        prices[sym] = trade["p"]
        except Exception as e:
            logger.warning(f"快照获取失败: {e}")
        time.sleep(0.5)

    return prices


def quick_rebalance():
    """快速重新评分并调仓"""
    import json

    # 读取最新信号
    import glob
    files = sorted(glob.glob("signals/signal_*.json"))
    if not files:
        logger.error("无信号文件")
        return

    with open(files[-1]) as f:
        signal = json.load(f)

    # 读取当前持仓
    positions = {}
    if os.path.exists("signals/portfolio.json"):
        with open("signals/portfolio.json") as f:
            portfolio = json.load(f)
        positions = portfolio.get("positions", {})

    # 获取最新价格
    all_tickers = list(positions.keys())
    for c in signal.get("buy_candidates", []):
        if c["ticker"] not in all_tickers:
            all_tickers.append(c["ticker"])

    prices = fetch_current_prices(all_tickers[:100])  # 最多100只
    print(f"\n当前价格快照: {len(prices)}只")
    for t, p in sorted(prices.items())[:5]:
        pos = positions.get(t, {})
        entry = pos.get("avg_entry_price", 0)
        if entry > 0:
            pnl = (p - entry) / entry * 100
            print(f"  {t}: ${p:.2f} (成本${entry:.2f}, PnL {pnl:+.2f}%)")

    # 建议
    print(f"\n📋 当前持仓: {len(positions)}只")
    print(f"📊 信号候选: {len(signal.get('buy_candidates', []))}只")
    print(f"💡 建议: python3 paper_trader.py --auto")


if __name__ == "__main__":
    quick_rebalance()
