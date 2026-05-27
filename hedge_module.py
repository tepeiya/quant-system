"""
ETF对冲模块
===========
原理：当大盘下跌信号触发时，买入反向ETF对冲持仓风险。
反向ETF（不需要做空权限，Alpaca可买）：
  - SH（做空标普500）
  - PSQ（做空纳斯达克100）
  - DOG（做空道指）

策略：
  当 SPY < SMA200 → 买入 SH 对冲 50% 持仓市值
  当 VIX > 30 → 加仓至 75% 对冲
  当大盘恢复多头 → 卖出平仓

独立运行，不影响主策略的选股和调仓。
"""

import os
import logging
from datetime import datetime

logger = logging.getLogger("quant.hedge")

from system_config import get as get_cfg
from data_prod import compute_indicators
from broker_manager import BrokerManager
import numpy as np
import pandas as pd


# 反向ETF列表
INVERSE_ETFS = {
    "SH": {"name": "做空标普500", "target": "SPY", "ratio": -1.0},
    "PSQ": {"name": "做空纳斯达克100", "target": "QQQ", "ratio": -1.0},
    "DOG": {"name": "做空道指", "target": "DIA", "ratio": -1.0},
}

HEDGE_FILE = "config/hedge_positions.json"


class HedgeManager:
    """对冲管理器"""

    def __init__(self):
        self.spy_ma200_trigger = get_cfg("hedge_spy_ma200", True)
        self.vix_trigger = get_cfg("hedge_vix_trigger", 30)
        self.hedge_ratio_base = get_cfg("hedge_ratio_base", 0.5)
        self.hedge_ratio_max = get_cfg("hedge_ratio_max", 0.75)
        self.signal_timeout_days = get_cfg("hedge_signal_timeout", 3)

    def check_signal(self, spy: pd.DataFrame, vix: float = None) -> dict:
        """
        判断是否需要启动对冲。
        返回：{"hedge": bool, "reason": str, "ratio": float}
        """
        if spy is None or len(spy) < 200:
            return {"hedge": False, "reason": "数据不足", "ratio": 0}

        close = spy["Close"].values
        sma200 = spy["SMA200"].values if "SMA200" in spy.columns else None

        reason_parts = []
        ratio = 0.0

        # 条件1：SPY跌破200MA
        if sma200 is not None and not np.isnan(sma200[-1]):
            if close[-1] < sma200[-1]:
                severity = (sma200[-1] - close[-1]) / sma200[-1]
                ratio = min(self.hedge_ratio_max, severity * 3)  # 跌破越深对冲越多
                reason_parts.append(f"SPY跌破200MA ({severity*100:.1f}%)")
            elif close[-1] < sma200[-1] * 1.02:
                # 接近200MA，预警级别
                if len(reason_parts) == 0:
                    reason_parts.append("SPY接近200MA，预警")

        # 条件2：VIX过高
        if vix is not None and vix > self.vix_trigger:
            vix_ratio = min(0.5, (vix - self.vix_trigger) / 20)
            ratio = max(ratio, vix_ratio)
            reason_parts.append(f"VIX={vix:.0f}（>{self.vix_trigger}）")

        # 限制最大对冲比例
        ratio = min(ratio, self.hedge_ratio_max)

        if ratio > 0:
            hedge = True
            reason = " + ".join(reason_parts) if reason_parts else "未知触发"
        else:
            hedge = False
            reason = "无需对冲"
            ratio = 0

        return {"hedge": hedge, "reason": reason, "ratio": round(ratio, 2)}

    def execute_hedge(self, signal: dict, broker=None):
        """
        执行对冲买卖。
        根据信号买入或卖出反向ETF。
        """
        if broker is None:
            bm = BrokerManager()
            try:
                broker = bm.get_current()
            except:
                logger.error("无法获取券商连接")
                return {"error": "无券商连接"}

        # 获取当前持仓市值
        portfolio = self._get_portfolio(broker)
        portfolio_value = portfolio.get("equity", 0)
        positions = portfolio.get("positions", {})

        # 当前已有对冲持仓
        current_hedge_value = 0
        for sym in INVERSE_ETFS:
            if sym in positions:
                current_hedge_value += positions[sym].get("market_value", 0)

        target_value = portfolio_value * signal["ratio"]
        target_etf = "SH"  # 默认用SH（做空标普500）

        # 计算需要买卖的量
        diff = target_value - current_hedge_value

        orders = []
        if abs(diff) < portfolio_value * 0.02:
            # 变化太小，不操作
            return {"action": "skip", "reason": f"变化太小({diff:.0f})", "orders": []}

        if diff > 0:
            # 需要买入更多对冲
            price = self._get_price(broker, target_etf)
            if price and price > 0:
                qty = max(1, int(diff / max(price, 1)))
                try:
                    result = broker.submit_order(target_etf, qty, "BUY")
                    orders.append({"symbol": target_etf, "qty": qty, "side": "BUY", "result": result})
                    logger.info(f"🛡️ 对冲买入 {target_etf} x{qty} @ ${price:.2f}")
                except Exception as e:
                    logger.error(f"对冲买入失败: {e}")

        elif diff < 0:
            # 需要卖出部分对冲
            qty = min(int(abs(diff) / max(price, 1)), int(current_hedge_value / max(price, 1))) if price and price > 0 else 0
            if qty > 0 and target_etf in positions:
                qty = min(qty, int(positions[target_etf].get("qty", 0)))
                if qty > 0:
                    try:
                        result = broker.submit_order(target_etf, qty, "SELL")
                        orders.append({"symbol": target_etf, "qty": qty, "side": "SELL", "result": result})
                        logger.info(f"🛡️ 对冲卖出 {target_etf} x{qty}")
                    except Exception as e:
                        logger.error(f"对冲卖出失败: {e}")

        # 保存对冲状态
        self._save_hedge_state(signal, target_value)

        return {"action": "executed", "orders": orders}

    def _get_portfolio(self, broker) -> dict:
        """获取组合信息"""
        try:
            acct = broker.get_account()
            equity = float(acct.get("equity", 0))
        except:
            equity = 0

        positions = {}
        try:
            for p in broker.get_positions():
                positions[p["symbol"]] = p
        except:
            pass

        return {"equity": equity, "positions": positions}

    def _get_price(self, broker, symbol: str) -> float:
        """获取实时价格"""
        try:
            import requests, os
            KEY = os.environ.get("ALPACA_API_KEY_ID", "")
            SECRET = os.environ.get("ALPACA_SECRET_KEY", "")
            if KEY and SECRET:
                r = requests.get(
                    f"https://data.alpaca.markets/v2/stocks/{symbol}/trades/latest",
                    auth=(KEY, SECRET), timeout=5
                )
                if r.status_code == 200:
                    return r.json().get("trade", {}).get("p", 0)
        except:
            pass
        return 0

    def _save_hedge_state(self, signal: dict, value: float):
        """保存对冲状态"""
        state = {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "hedge_active": signal["hedge"],
            "reason": signal["reason"],
            "target_value": round(value, 2),
            "ratio": signal["ratio"],
        }
        os.makedirs("config", exist_ok=True)
        import json
        with open(HEDGE_FILE, "w") as f:
            json.dump(state, f, indent=2)

    def get_hedge_status(self) -> dict:
        """查看对冲状态"""
        import json
        if os.path.exists(HEDGE_FILE):
            with open(HEDGE_FILE) as f:
                return json.load(f)
        return {"hedge_active": False, "reason": "未启动", "ratio": 0}


if __name__ == "__main__":
    hm = HedgeManager()

    # 测试：模拟大盘数据
    import yfinance as yf
    spy = yf.download("SPY", period="1y", progress=False, auto_adjust=True)
    if isinstance(spy.columns, pd.MultiIndex):
        spy.columns = spy.columns.get_level_values(0)
    spy = compute_indicators(spy)

    signal = hm.check_signal(spy, vix=25)
    print(f"对冲信号: {'🛡️' if signal['hedge'] else '✅'} {signal['reason']} 比例:{signal['ratio']:.0%}")
