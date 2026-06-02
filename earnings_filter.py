"""
财报日历过滤模块
=============
原理：持仓股未来7天内发财报 → 减仓一半，避免财报黑天鹅
      财报后2天再加入买入候选（等市场消化波动）

数据源：财报日期通过两种方式获取
  1. 优先：yfinance（电脑上不限频）
  2. 备选：行业估算（不依赖API，误差1-2天）

用法：
  from earnings_filter import EarningsFilter
  ef = EarningsFilter()
  near = ef.get_upcoming_earnings(["AAPL","JPM"], days_ahead=7)
  print(near)
"""

import logging
from datetime import datetime, timedelta
import os
import requests

logger = logging.getLogger("quant.earnings")

from system_config import get as get_cfg


# 行业财报窗口（季度末后第几周）
_EARNINGS_WINDOW = {
    "bank": 2,      # JPM, BAC, GS...
    "tech_large": 3,  # AAPL, MSFT, NVDA...
    "retail": 4,      # WMT, COST, TGT...
    "energy": 4,      # XOM, CVX...
    "default": 3,
}

_BANKS = {"JPM","BAC","C","GS","MS","WFC","BK","AXP","SCHW","PNC","USB","TFC","KEY","MTB","FITB","HBAN","RF","CFG"}
_TECH = {"AAPL","MSFT","NVDA","AMD","INTC","QCOM","TXN","AVGO","MU","CRM","ORCL","ADBE","NOW","PANW","CRWD","CSCO","AMAT","KLAC","LRCX","ASML"}
_RETAIL = {"WMT","COST","TGT","HD","LOW","MCD","SBUX","NKE","TJX","DG","DLTR","ROST"}                                    


class EarningsFilter:
    """财报日历过滤"""

    def __init__(self):
        self.days_avoid = get_cfg("earnings_avoid_days", 7)
        self.days_cooldown = get_cfg("earnings_cooldown_days", 2)
        self.reduce_ratio = get_cfg("earnings_reduce_ratio", 0.5)

    def estimate_earnings(self, ticker: str, year: int = None, quarter: int = None) -> list[str]:
        """
        估算指定季度的财报日期。
        不依赖实时API，基于行业规律。
        """
        if year is None:
            year = datetime.now().year
        if quarter is None:
            now = datetime.now()
            quarter = (now.month - 1) // 3 + 1

        # 行业窗口
        if ticker in _BANKS:
            weeks = _EARNINGS_WINDOW["bank"]
        elif ticker in _TECH:
            weeks = _EARNINGS_WINDOW["tech_large"]
        elif ticker in _RETAIL:
            weeks = _EARNINGS_WINDOW["retail"]
        else:
            weeks = _EARNINGS_WINDOW["default"]

        q_end = {1: f"{year}-03-31", 2: f"{year}-06-30",
                 3: f"{year}-09-30", 4: f"{year}-12-31"}

        end = datetime.strptime(q_end[quarter], "%Y-%m-%d")
        est = end + timedelta(weeks=weeks)

        # 同季度后3天也给一个保守估计
        est2 = end + timedelta(weeks=weeks + 1)

        return [est.strftime("%Y-%m-%d"), est2.strftime("%Y-%m-%d")]

    def _get_finnhub_earnings(self, ticker: str, days_ahead: int = 30) -> list[str]:
        """从 Finnhub 获取未来财报日期"""
        api_key = os.environ.get("FINNHUB_API_KEY", "")
        if not api_key:
            return []
        now = datetime.now().date()
        end = now + timedelta(days=days_ahead)
        try:
            url = "https://finnhub.io/api/v1/calendar/earnings"
            params = {"symbol": ticker, "from": str(now), "to": str(end), "token": api_key}
            r = requests.get(url, params=params, timeout=10)
            if r.status_code != 200:
                return []
            data = r.json()
            rows = data.get("earningsCalendar") or []
            out = []
            for row in rows:
                d = row.get("date")
                if d:
                    out.append(d)
            return out
        except Exception:
            return []

    def get_upcoming_earnings(self, tickers: list[str],
                              days_ahead: int = 7) -> list[dict]:
        """
        检查哪些股票在未来 days_ahead 天内发财报。
        优先 Finnhub，失败回退到估算。
        返回：受影响的股票列表
        """
        now = datetime.now()
        affected = []

        for t in tickers:
            finnhub_dates = self._get_finnhub_earnings(t, days_ahead=days_ahead + 7)
            dates = finnhub_dates if finnhub_dates else self.estimate_earnings(t)
            for d in dates:
                report_date = datetime.strptime(d, "%Y-%m-%d")
                if now <= report_date <= now + timedelta(days=days_ahead):
                    days_to = (report_date - now).days
                    affected.append({
                        "ticker": t,
                        "report_date": d,
                        "days_to_report": days_to,
                        "suggested_action": f"减仓{int(self.reduce_ratio*100)}%",
                        "source": "finnhub" if finnhub_dates else "estimate",
                    })
                    break

        return affected

    def filter_buys(self, candidates: list[dict]) -> list[dict]:
        """
        过滤买入候选：财报后2天内不买入
        """
        now = datetime.now()
        filtered = []

        for c in candidates:
            t = c["ticker"]
            dates = self.estimate_earnings(t)
            skip = False
            for d in dates:
                report_date = datetime.strptime(d, "%Y-%m-%d")
                # 如果财报刚过2天内，也不买入（等波动消化）
                if report_date <= now <= report_date + timedelta(days=self.days_cooldown):
                    skip = True
                    logger.info(f"  ⏳ {t} 财报刚过，冷却中（{d}）")
                    break
            if not skip:
                filtered.append(c)

        return filtered

    def adjust_positions_for_earnings(self, positions: dict) -> dict:
        """
        调整持仓：未来7天发财报的减仓一半
        返回：需要减仓的指令
        """
        affected = self.get_upcoming_earnings(list(positions.keys()), self.days_avoid)
        reductions = {}

        for a in affected:
            t = a["ticker"]
            pos = positions.get(t)
            if pos:
                qty = pos.get("qty", 0)
                reduce_qty = max(1, int(qty * self.reduce_ratio))
                reductions[t] = {
                    "qty": reduce_qty,
                    "reason": f"财报避险 ({a['report_date']})",
                }
                logger.info(f"  ⚠️ {t}: {reduce_qty}股减仓（财报{a['report_date']}）")

        return reductions


if __name__ == "__main__":
    ef = EarningsFilter()

    # 测试：当前持仓的财报风险
    test_positions = {"AAPL": {"qty": 10}, "JPM": {"qty": 5}, "NVDA": {"qty": 8}}

    print("📅 财报风险评估:")
    affected = ef.get_upcoming_earnings(list(test_positions.keys()), days_ahead=30)
    if affected:
        for a in affected:
            print(f"  ⚠️ {a['ticker']}: {a['days_to_report']}天后财报 ({a['report_date']})")
    else:
        print(f"  ✅ 30天内无财报风险")

    print("\n🟢 买入过滤测试:")
    cands = [{"ticker": "AAPL", "score": 80}, {"ticker": "JPM", "score": 75}]
    filtered = ef.filter_buys(cands)
    print(f"  过滤前: {len(cands)}, 过滤后: {len(filtered)}")
