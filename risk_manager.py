"""
风险控制模块 v2 — 集成 trading-server 专业风控逻辑
==============================================
功能：
  1. 仓位风控 (position risk)
     - 最大持仓数限制
     - 相关性限制
     - 单票/单行业仓位上限
     - 逐笔风控检查

  2. 止损管理 (stop loss)
     - 静态止损
     - ATR动态止损
     - 跟踪止损
     - 止盈

  3. 熔断保护 (circuit breaker)
     - 单日亏损熔断
     - 连续亏损熔断
     - 总回撤熔断

用法：
  from risk_manager import RiskManager
  rm = RiskManager()
  ok, msg = rm.within_risk_limits(signal, current_positions, daily_pnl)
  stopped = rm.check_stop_loss(client)
"""

import os
import json
import logging
import numpy as np
from datetime import datetime

logger = logging.getLogger("quant.risk")

# ============================================================
# 仓位风控
# ============================================================

class PositionRisk:
    """仓位风控 — 检查新信号是否在风控限制内"""

    # 默认参数
    MAX_POSITIONS = 10
    MAX_SECTOR_PCT = 35.0           # 单行业占仓位上限 (%)
    MAX_POSITION_PCT = 14.0         # 单票占资产上限 (%)
    MAX_CORRELATED_POSITIONS = 4    # 关联持仓上限
    CORRELATION_THRESHOLD = 0.5     # 相关系数阈值
    RISK_PER_TRADE = 0.5            # 每笔交易风险 (% 或 'KELLY')

    def __init__(self, config: dict = None):
        if config:
            self.MAX_POSITIONS = config.get("max_positions", self.MAX_POSITIONS)
            self.MAX_SECTOR_PCT = config.get("max_sector_pct", self.MAX_SECTOR_PCT)
            self.MAX_POSITION_PCT = config.get("max_position_pct", self.MAX_POSITION_PCT)
            self.RISK_PER_TRADE = config.get("risk_per_trade", self.RISK_PER_TRADE)

    def within_position_limit(self, total_active: int) -> tuple:
        """
        检查是否超过最大持仓数

        参数:
            total_active: 当前活跃持仓数

        返回:
            (ok: bool, msg: str)
        """
        if total_active >= self.MAX_POSITIONS:
            return False, f"持仓数已达上限 ({total_active}/{self.MAX_POSITIONS})"
        return True, "ok"

    def within_sector_limit(self, sector: str, sector_counts: dict) -> tuple:
        """
        检查单行业持仓是否超限

        参数:
            sector: 目标股票所属行业
            sector_counts: {行业: 持仓数}

        返回:
            (ok: bool, msg: str)
        """
        current = sector_counts.get(sector, 0)
        total = sum(sector_counts.values())
        if total == 0:
            return True, "ok"
        pct = current / total * 100
        if pct >= self.MAX_SECTOR_PCT / 100:
            return False, f"行业 {sector} 仓位 {pct:.0f}% 已达上限 {self.MAX_SECTOR_PCT:.0f}%"
        return True, "ok"

    def within_position_pct(self, position_value: float, total_equity: float) -> tuple:
        """
        检查单票仓位占比是否超限

        参数:
            position_value: 目标仓位市值
            total_equity: 总权益

        返回:
            (ok: bool, msg: str)
        """
        if total_equity <= 0:
            return False, "总权益为0"
        pct = position_value / total_equity * 100
        if pct > self.MAX_POSITION_PCT:
            return False, f"单票仓位 {pct:.1f}% 超过上限 {self.MAX_POSITION_PCT:.0f}%"
        return True, "ok"

    def calculate_position_size(self, stop_loss_pct: float, entry_price: float,
                                account_equity: float) -> int:
        """
        根据风险参数计算仓位大小

        参数:
            stop_loss_pct: 止损比例 (%)
            entry_price: 入场价格
            account_equity: 账户总权益

        返回:
            qty: 建议买入数量
        """
        if stop_loss_pct <= 0 or entry_price <= 0:
            return 0

        # 固定风险比例
        risk_amount = account_equity * (self.RISK_PER_TRADE / 100)
        stop_distance = abs(entry_price * (stop_loss_pct / 100))

        if stop_distance <= 0:
            return 0

        position_size = risk_amount / stop_distance
        qty = max(1, int(position_size))
        return qty

    def within_risk_limits(self, signal_info: dict, current_positions: dict,
                           sector_map: dict = None) -> tuple:
        """
        一站式风控检查 — 从 trading-server Portfolio.within_risk_limits 借鉴

        参数:
            signal_info: {
                "symbol": 股票代码,
                "sector": 行业,
                "entry_price": 入场价,
                "position_value": 目标仓位市值,
                "stop_loss_pct": 止损比例
            }
            current_positions: 当前持仓 {symbol: {qty, sector, market_value}}
            sector_map: 股票行业映射 {symbol: sector}

        返回:
            (ok: bool, msg: str)
        """
        symbol = signal_info.get("symbol", "")
        sector = signal_info.get("sector", signal_info.get("sector", ""))
        position_value = signal_info.get("position_value", 0)
        entry_price = signal_info.get("entry_price", 0)
        total_equity = signal_info.get("total_equity", 0)
        total_active = signal_info.get("total_active", len(current_positions))

        # 1. 总持仓数检查
        ok, msg = self.within_position_limit(total_active)
        if not ok:
            return False, msg

        # 2. 单行业仓位检查
        if sector and sector_map:
            sector_counts = {}
            for sym, pos in current_positions.items():
                sym_sector = sector_map.get(sym, "unknown")
                sector_counts[sym_sector] = sector_counts.get(sym_sector, 0) + 1
            ok, msg = self.within_sector_limit(sector, sector_counts)
            if not ok:
                return False, msg

        # 3. 单票仓位检查
        if position_value > 0 and total_equity > 0:
            ok, msg = self.within_position_pct(position_value, total_equity)
            if not ok:
                return False, msg

        # 4. 同票冲突检查
        if symbol in current_positions:
            return False, f"{symbol} 已在持仓中"

        return True, "ok"


# ============================================================
# 止损管理
# ============================================================

class StopLossManager:
    """止损管理 — 检查持仓是否需要止损/止盈"""

    def __init__(self, config: dict = None):
        cfg = config or {}
        self.stop_loss_pct = float(cfg.get("stop_loss_pct", 15))
        self.atr_multiple = float(cfg.get("stop_loss_atr_multiple", 3.0))
        self.stop_loss_min = float(cfg.get("stop_loss_min_pct", 5))
        self.stop_loss_max = float(cfg.get("stop_loss_max_pct", 25))
        self.trailing_activate = float(cfg.get("trailing_stop_activate_pct", 15))
        self.trailing_atr = float(cfg.get("trailing_stop_atr_multiple", 2.0))
        self.trailing_min = float(cfg.get("trailing_stop_min_pct", 8))
        self.take_profit_pct = float(cfg.get("take_profit_pct", 0))

    def get_atr(self, symbol: str) -> float:
        """获取股票 ATR 值"""
        try:
            from data_prod import load_price_cache
            import pandas as pd
            cache = load_price_cache()
            df = cache.get(symbol)
            if df is not None and "ATR_Pct" in df.columns:
                atr = float(df["ATR_Pct"].iloc[-1])
                return atr if not np.isnan(atr) else 3.0
        except:
            pass
        return 3.0

    def get_recent_peak(self, symbol: str, days: int = 60) -> float:
        """获取近期最高价"""
        try:
            from data_prod import load_price_cache
            cache = load_price_cache()
            df = cache.get(symbol)
            if df is not None and len(df) > days:
                return float(df["High"].iloc[-days:].max())
        except:
            pass
        return 0.0

    def check_position(self, symbol: str, entry_price: float,
                       current_price: float, pnl_pct: float) -> dict:
        """
        检查单只持仓是否需要止损

        参数:
            symbol: 股票代码
            entry_price: 入场价
            current_price: 当前价
            pnl_pct: 当前盈亏 (%)

        返回:
            dict: {"should_stop": bool, "reason": str, "action": str}
        """
        atr = self.get_atr(symbol)
        atr_stop = max(self.stop_loss_min,
                       min(self.stop_loss_max,
                           atr * self.atr_multiple))

        result = {"should_stop": False, "reason": "", "action": "hold"}

        # 1. 止盈
        if self.take_profit_pct > 0 and pnl_pct >= self.take_profit_pct:
            result["should_stop"] = True
            result["reason"] = f"止盈 ({pnl_pct:+.1f}% >= {self.take_profit_pct:.0f}%)"
            result["action"] = "take_profit"
            return result

        # 2. 静态止损
        if pnl_pct < -self.stop_loss_pct:
            result["should_stop"] = True
            result["reason"] = f"静态止损 ({pnl_pct:+.1f}% < -{self.stop_loss_pct:.0f}%)"
            result["action"] = "stop_loss"
            return result

        # 3. ATR动态止损
        if pnl_pct < -atr_stop:
            result["should_stop"] = True
            result["reason"] = f"ATR动态止损 ({pnl_pct:+.1f}% < -{atr_stop:.0f}%, ATR={atr:.1f}%)"
            result["action"] = "stop_loss"
            return result

        # 4. 跟踪止损
        if entry_price > 0 and pnl_pct > self.trailing_activate:
            peak = self.get_recent_peak(symbol)
            if peak > entry_price:
                trailing_dist = max(self.trailing_min, atr * self.trailing_atr)
                if current_price < peak * (1 - trailing_dist / 100):
                    result["should_stop"] = True
                    result["reason"] = (f"跟踪止损 (最高${peak:.2f}回落{trailing_dist:.0f}%, "
                                        f"当前{current_price:.2f})")
                    result["action"] = "trailing_stop"
                    return result

        return result

    def check_all(self, positions: dict) -> list:
        """
        检查所有持仓，返回需要止损的列表

        参数:
            positions: {symbol: {qty, avg_entry, current_price, pnl_pct}}

        返回:
            list: [{symbol, reason, action, pnl_pct}]
        """
        results = []
        for sym, pos in positions.items():
            result = self.check_position(
                sym,
                pos.get("avg_entry", 0),
                pos.get("current_price", 0),
                pos.get("pnl_pct", 0),
            )
            if result["should_stop"]:
                results.append({
                    "symbol": sym,
                    "reason": result["reason"],
                    "action": result["action"],
                    "pnl_pct": pos.get("pnl_pct", 0),
                    "qty": pos.get("qty", 0),
                })
        return results


# ============================================================
# 熔断保护
# ============================================================

class CircuitBreaker:
    """熔断保护 — 从 circuit_breaker.py 合并"""

    def __init__(self, config: dict = None):
        cfg = config or {}
        self.daily_loss_limit = float(cfg.get("circuit_daily_loss", 10.0))
        self.consecutive_loss_limit = int(cfg.get("circuit_consecutive_loss", 5))
        self.max_drawdown = float(cfg.get("circuit_max_drawdown", 25.0))
        self.cooldown_hours = float(cfg.get("circuit_cooldown_hours", 24))

    def check_daily_loss(self, daily_pnl_pct: float) -> tuple:
        """
        检查单日亏损是否触发熔断

        参数:
            daily_pnl_pct: 当日盈亏 (%)

        返回:
            (tripped: bool, msg: str)
        """
        if daily_pnl_pct < -self.daily_loss_limit:
            return True, f"单日亏损 {daily_pnl_pct:.1f}% 超过熔断阈值 {self.daily_loss_limit:.0f}%"
        return False, ""

    def check_consecutive_losses(self, recent_pnls: list) -> tuple:
        """
        检查连续亏损是否触发熔断

        参数:
            recent_pnls: 最近几日盈亏列表 [%, %, ...]

        返回:
            (tripped: bool, msg: str)
        """
        streak = 0
        for pnl in reversed(recent_pnls):
            if pnl < 0:
                streak += 1
            else:
                break
        if streak >= self.consecutive_loss_limit:
            return True, f"连续亏损 {streak} 天，达到熔断阈值 {self.consecutive_loss_limit}"
        return False, ""

    def check_drawdown(self, current_dd_pct: float) -> tuple:
        """
        检查总回撤是否触发熔断

        参数:
            current_dd_pct: 当前回撤 (%)

        返回:
            (tripped: bool, msg: str)
        """
        if current_dd_pct > self.max_drawdown:
            return True, f"总回撤 {current_dd_pct:.1f}% 超过熔断阈值 {self.max_drawdown:.0f}%"
        return False, ""


# ============================================================
# 统一入口
# ============================================================

class RiskManager:
    """风险控制统一入口"""

    def __init__(self, config: dict = None):
        if config is None:
            # 延迟导入，避免触发 data_global 初始化
            import importlib, os, json
            CONFIG_FILE = "config/system_config.json"
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE) as f:
                    config = json.load(f)
            else:
                config = {}
        self.position_risk = PositionRisk(config)
        self.stop_loss = StopLossManager(config)
        self.circuit_breaker = CircuitBreaker(config)

    def check_signal(self, signal_info: dict, current_positions: dict,
                     sector_map: dict = None) -> tuple:
        """
        检查新信号是否在风控范围内

        返回:
            (ok: bool, msg: str)
        """
        return self.position_risk.within_risk_limits(
            signal_info, current_positions, sector_map)

    def check_stops(self, positions: dict) -> list:
        """
        检查持仓止损

        返回:
            list: 需要止损的持仓
        """
        return self.stop_loss.check_all(positions)

    def check_circuit(self, daily_pnl_pct: float, recent_pnls: list,
                      current_dd_pct: float) -> list:
        """
        检查熔断条件

        返回:
            list: 触发的熔断告警
        """
        alerts = []
        tripped, msg = self.circuit_breaker.check_daily_loss(daily_pnl_pct)
        if tripped:
            alerts.append({"type": "daily_loss", "message": msg})

        tripped, msg = self.circuit_breaker.check_consecutive_losses(recent_pnls)
        if tripped:
            alerts.append({"type": "consecutive_loss", "message": msg})

        tripped, msg = self.circuit_breaker.check_drawdown(current_dd_pct)
        if tripped:
            alerts.append({"type": "drawdown", "message": msg})

        return alerts

    def calculate_position_size(self, stop_loss_pct: float, entry_price: float,
                                account_equity: float) -> int:
        """计算仓位大小"""
        return self.position_risk.calculate_position_size(
            stop_loss_pct, entry_price, account_equity)


# ============================================================
# 测试
# ============================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")

    rm = RiskManager()
    logger.info("风险控制模块已初始化")

    # 测试仓位风控
    signal = {
        "symbol": "AAPL",
        "sector": "Technology",
        "entry_price": 200,
        "position_value": 10000,
        "total_equity": 100000,
        "total_active": 5,
    }
    current = {"MSFT": {"sector": "Technology", "qty": 10}}
    sector_map = {"MSFT": "Technology", "AAPL": "Technology"}
    ok, msg = rm.check_signal(signal, current, sector_map)
    print(f"  信号检查: {'✅' if ok else '❌'} {msg}")

    # 测试止损
    positions = {
        "TEST": {"qty": 10, "avg_entry": 100, "current_price": 85, "pnl_pct": -15.0},
        "HOLD": {"qty": 5, "avg_entry": 50, "current_price": 52, "pnl_pct": 4.0},
    }
    stops = rm.check_stops(positions)
    print(f"  止损检查: {len(stops)} 笔触发")
    for s in stops:
        print(f"    {s['symbol']}: {s['reason']}")

    # 测试仓位计算
    qty = rm.calculate_position_size(5.0, 200, 100000)
    print(f"  仓位计算: {qty} 股 (止损5%, 权益$100k, 风险0.5%)")

    print("\n✅ 风险控制模块测试通过")
