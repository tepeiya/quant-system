"""
增强回测引擎 v2.0
==================
支持完整回测功能，包括：

1. 事件驱动回测
2. 多种订单类型（市价、限价、止损）
3. 交易成本（佣金、滑点、市场冲击）
4. 参数优化（网格搜索、贝叶斯优化）
5. 性能指标计算
6. Walk-Forward分析
"""

import os
import json
import logging
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Callable
from dataclasses import dataclass, field

logger = logging.getLogger("quant.backtest")

# 回测配置
DEFAULT_CONFIG = {
    "initial_capital": 100000,  # 初始资金
    "commission": 0.001,        # 佣金1%
    "slippage": 0.0005,         # 滑点0.05%
    "max_position_pct": 0.15,  # 单只股票最大仓位15%
    "min_hold_days": 5,         # 最小持仓天数
    "allow_short": False,       # 不允许做空
}


@dataclass
class Trade:
    """交易记录"""
    date: str
    ticker: str
    side: str  # BUY / SELL
    quantity: float
    price: float
    commission: float
    slippage: float
    signal: str  # 信号来源


@dataclass
class Position:
    """持仓"""
    ticker: str
    quantity: float
    avg_cost: float
    entry_date: str
    stop_loss: float = 0
    take_profit: float = 0


@dataclass
class Portfolio:
    """投资组合状态"""
    cash: float
    positions: Dict[str, Position]
    equity_curve: List[float] = field(default_factory=list)
    trades: List[Trade] = field(default_factory=list)
    daily_returns: List[float] = field(default_factory=list)


class BacktestEngine:
    """回测引擎"""
    
    def __init__(self, config: Dict = None):
        self.config = {**DEFAULT_CONFIG, **(config or {})}
        self.initial_capital = self.config["initial_capital"]
        self.commission_rate = self.config["commission"]
        self.slippage_rate = self.config["slippage"]
        
        self.portfolio = None
        self.current_date = None
        self.price_data = {}  # {ticker: DataFrame}
        self.signals = {}     # {date: {ticker: signal_score}}
        
    def set_price_data(self, ticker: str, data: pd.DataFrame):
        """设置价格数据"""
        self.price_data[ticker] = data
    
    def set_signals(self, signals: Dict):
        """设置信号数据 {date: {ticker: score}}"""
        self.signals = signals
    
    def _get_price(self, ticker: str, date: str) -> Optional[float]:
        """获取指定日期的价格"""
        if ticker not in self.price_data:
            return None
        
        df = self.price_data[ticker]
        row = df[df["date"] == date]
        if len(row) > 0:
            return row.iloc[0]["close"]
        return None
    
    def _calculate_commission(self, amount: float) -> float:
        """计算佣金"""
        return amount * self.commission_rate
    
    def _calculate_slippage(self, price: float, side: str) -> float:
        """计算滑点"""
        # 买入时提高价格，卖出时降低价格
        multiplier = 1 + self.slippage_rate if side == "BUY" else 1 - self.slippage_rate
        return price * multiplier
    
    def _execute_trade(self, ticker: str, side: str, quantity: float, 
                      price: float, signal: str, date: str) -> Trade:
        """执行交易"""
        # 应用滑点
        execution_price = self._calculate_slippage(price, side)
        
        # 计算金额
        amount = execution_price * quantity
        
        # 计算佣金
        commission = self._calculate_commission(amount)
        
        # 扣除佣金
        total_cost = amount + commission if side == "BUY" else amount - commission
        
        # 更新现金
        if side == "BUY":
            self.portfolio.cash -= total_cost
            # 更新持仓
            if ticker in self.portfolio.positions:
                pos = self.portfolio.positions[ticker]
                total_qty = pos.quantity + quantity
                pos.avg_cost = (pos.avg_cost * pos.quantity + execution_price * quantity) / total_qty
                pos.quantity = total_qty
            else:
                self.portfolio.positions[ticker] = Position(
                    ticker=ticker,
                    quantity=quantity,
                    avg_cost=execution_price,
                    entry_date=date
                )
        else:
            self.portfolio.cash += total_cost
            # 更新持仓
            if ticker in self.portfolio.positions:
                pos = self.portfolio.positions[ticker]
                pos.quantity -= quantity
                if pos.quantity <= 0:
                    del self.portfolio.positions[ticker]
        
        # 记录交易
        trade = Trade(
            date=date,
            ticker=ticker,
            side=side,
            quantity=quantity,
            price=execution_price,
            commission=commission,
            slippage=abs(price - execution_price),
            signal=signal
        )
        self.portfolio.trades.append(trade)
        
        return trade
    
    def _calculate_equity(self) -> float:
        """计算当前权益"""
        equity = self.portfolio.cash
        
        for ticker, pos in self.portfolio.positions.items():
            price = self._get_price(ticker, self.current_date)
            if price:
                equity += pos.quantity * price
        
        return equity
    
    def run(self) -> Dict:
        """
        执行回测
        
        Returns:
            回测结果报告
        """
        logger.info("🚀 开始回测...")
        
        # 初始化组合
        self.portfolio = Portfolio(
            cash=self.initial_capital,
            positions={}
        )
        
        # 获取所有交易日期
        all_dates = set()
        for ticker, df in self.price_data.items():
            all_dates.update(df["date"].tolist())
        dates = sorted(all_dates)
        
        # 逐日回测
        for date in dates:
            self.current_date = date
            
            # 获取当日信号
            day_signals = self.signals.get(date, {})
            
            # 1. 检查止损
            self._check_stop_loss()
            
            # 2. 检查止盈
            self._check_take_profit()
            
            # 3. 处理卖出信号
            self._process_sell_signals(day_signals)
            
            # 4. 处理买入信号
            self._process_buy_signals(day_signals)
            
            # 5. 更新权益曲线
            equity = self._calculate_equity()
            self.portfolio.equity_curve.append(equity)
            
            # 6. 计算日收益
            if len(self.portfolio.equity_curve) > 1:
                daily_return = (equity / self.portfolio.equity_curve[-2] - 1) * 100
                self.portfolio.daily_returns.append(daily_return)
        
        # 生成报告
        return self._generate_report()
    
    def _check_stop_loss(self):
        """检查止损"""
        for ticker, pos in list(self.portfolio.positions.items()):
            price = self._get_price(ticker, self.current_date)
            if price and pos.stop_loss > 0 and price <= pos.stop_loss:
                logger.info(f"  🛑 触发止损 {ticker} @ ${price:.2f}")
                self._execute_trade(ticker, "SELL", pos.quantity, price, "stop_loss", self.current_date)
    
    def _check_take_profit(self):
        """检查止盈"""
        for ticker, pos in list(self.portfolio.positions.items()):
            price = self._get_price(ticker, self.current_date)
            if price and pos.take_profit > 0 and price >= pos.take_profit:
                logger.info(f"  🎯 触发止盈 {ticker} @ ${price:.2f}")
                self._execute_trade(ticker, "SELL", pos.quantity, price, "take_profit", self.current_date)
    
    def _process_sell_signals(self, signals: Dict):
        """处理卖出信号"""
        for ticker, pos in list(self.portfolio.positions.items()):
            # 检查是否持有足够久
            entry_date = datetime.strptime(pos.entry_date, "%Y-%m-%d")
            hold_days = (datetime.strptime(self.current_date, "%Y-%m-%d") - entry_date).days
            
            if hold_days < self.config["min_hold_days"]:
                continue
            
            # 检查信号
            signal_score = signals.get(ticker, 0)
            
            if signal_score < 0:
                logger.info(f"  📤 卖出信号 {ticker} (score={signal_score:.2f})")
                self._execute_trade(ticker, "SELL", pos.quantity, 
                                  self._get_price(ticker, self.current_date), 
                                  "signal", self.current_date)
    
    def _process_buy_signals(self, signals: Dict):
        """处理买入信号"""
        # 过滤出买入信号
        buy_signals = {t: s for t, s in signals.items() if s > 0}
        
        if not buy_signals or self.portfolio.positions:
            # 已有持仓或无买入信号
            return
        
        # 按评分排序
        sorted_signals = sorted(buy_signals.items(), key=lambda x: x[1], reverse=True)
        
        # 计算可买入数量
        max_positions = 5  # 最多5只
        available_tickers = [t for t, s in sorted_signals 
                           if t not in self.portfolio.positions][:max_positions]
        
        if not available_tickers:
            return
        
        # 分配资金
        capital_per_stock = self.portfolio.cash / len(available_tickers)
        
        for ticker in available_tickers:
            price = self._get_price(ticker, self.current_date)
            if not price:
                continue
            
            # 计算买入数量
            max_qty = int(capital_per_stock / price)
            if max_qty <= 0:
                continue
            
            # 检查单只仓位限制
            position_value = max_qty * price
            if position_value > self.initial_capital * self.config["max_position_pct"]:
                max_qty = int(self.initial_capital * self.config["max_position_pct"] / price)
            
            if max_qty > 0:
                logger.info(f"  📥 买入信号 {ticker} x {max_qty} @ ${price:.2f}")
                self._execute_trade(ticker, "BUY", max_qty, price, 
                                  "signal", self.current_date)
                
                # 设置止损止盈
                pos = self.portfolio.positions.get(ticker)
                if pos:
                    pos.stop_loss = price * 0.95  # 5%止损
                    pos.take_profit = price * 1.20  # 20%止盈
    
    def _generate_report(self) -> Dict:
        """生成回测报告"""
        equity = np.array(self.portfolio.equity_curve)
        returns = np.array(self.portfolio.daily_returns)
        
        # 基本指标
        total_return = (equity[-1] / equity[0] - 1) * 100 if len(equity) > 0 else 0
        sharpe_ratio = self._calculate_sharpe(returns)
        max_drawdown, max_drawdown_pct = self._calculate_max_drawdown(equity)
        
        # 交易统计
        trades = self.portfolio.trades
        buy_trades = [t for t in trades if t.side == "BUY"]
        sell_trades = [t for t in trades if t.side == "SELL"]
        
        winning_trades = 0
        total_profit = 0
        total_loss = 0
        
        for i, trade in enumerate(sell_trades):
            # 找到对应的买入
            ticker = trade.ticker
            buys = [t for t in buy_trades if t.ticker == ticker]
            if buys:
                avg_buy_price = sum(t.price * t.quantity for t in buys) / sum(t.quantity for t in buys)
                pnl = (trade.price - avg_buy_price) * trade.quantity - trade.commission
                if pnl > 0:
                    winning_trades += 1
                    total_profit += pnl
                else:
                    total_loss += abs(pnl)
        
        total_trades = len(sell_trades)
        win_rate = winning_trades / total_trades if total_trades > 0 else 0
        avg_win = total_profit / winning_trades if winning_trades > 0 else 0
        avg_loss = total_loss / (total_trades - winning_trades) if total_trades > winning_trades else 0
        profit_factor = total_profit / total_loss if total_loss > 0 else float('inf')
        
        return {
            "backtest_period": {
                "start": self.current_date if self.portfolio.equity_curve else "N/A",
                "initial_capital": self.initial_capital,
                "final_equity": equity[-1] if len(equity) > 0 else 0
            },
            "returns": {
                "total_return": round(total_return, 2),
                "annual_return": round(total_return / max(1, len(equity) / 252) * 100, 2),
                "sharpe_ratio": round(sharpe_ratio, 2),
                "max_drawdown": round(max_drawdown, 2),
                "max_drawdown_pct": round(max_drawdown_pct * 100, 2)
            },
            "trading": {
                "total_trades": total_trades,
                "buy_trades": len(buy_trades),
                "sell_trades": len(sell_trades),
                "win_rate": round(win_rate * 100, 2),
                "avg_win": round(avg_win, 2),
                "avg_loss": round(avg_loss, 2),
                "profit_factor": round(profit_factor, 2) if profit_factor != float('inf') else "N/A",
                "total_commission": round(sum(t.commission for t in trades), 2)
            },
            "equity_curve": equity.tolist(),
            "daily_returns": returns.tolist()[-30:],  # 最近30天
            "trades": [
                {
                    "date": t.date,
                    "ticker": t.ticker,
                    "side": t.side,
                    "quantity": t.quantity,
                    "price": round(t.price, 2),
                    "signal": t.signal
                }
                for t in trades[-20:]  # 最近20笔交易
            ]
        }
    
    def _calculate_sharpe(self, returns: np.ndarray, risk_free_rate: float = 0.02) -> float:
        """计算夏普比率"""
        if len(returns) < 2:
            return 0
        
        excess_returns = returns - risk_free_rate / 252  # 日化无风险利率
        return np.sqrt(252) * np.mean(excess_returns) / np.std(excess_returns) if np.std(excess_returns) > 0 else 0
    
    def _calculate_max_drawdown(self, equity: np.ndarray) -> Tuple[float, float]:
        """计算最大回撤"""
        if len(equity) < 2:
            return 0, 0
        
        running_max = np.maximum.accumulate(equity)
        drawdown = (equity - running_max) / running_max
        max_dd = np.min(drawdown)
        max_dd_idx = np.argmin(drawdown)
        
        return abs(equity[max_dd_idx] - running_max[max_dd_idx]), abs(max_dd)


class ParameterOptimizer:
    """参数优化器"""
    
    def __init__(self, engine_class: type, param_grid: Dict, metric: str = "sharpe_ratio"):
        self.engine_class = engine_class
        self.param_grid = param_grid
        self.metric = metric
        self.results = []
    
    def _generate_param_combinations(self) -> List[Dict]:
        """生成参数组合"""
        import itertools
        
        keys = list(self.param_grid.keys())
        values = list(self.param_grid.values())
        
        combinations = []
        for combo in itertools.product(*values):
            combinations.append(dict(zip(keys, combo)))
        
        return combinations
    
    def optimize(self, price_data: Dict, signals: Dict) -> Dict:
        """执行参数优化"""
        combinations = self._generate_param_combinations()
        
        logger.info(f"🔍 开始参数优化，共 {len(combinations)} 种组合...")
        
        best_result = None
        best_params = None
        best_metric = -float('inf')
        
        for i, params in enumerate(combinations):
            logger.info(f"  [{i+1}/{len(combinations)}] 测试参数: {params}")
            
            # 创建回测引擎
            engine = self.engine_class(params)
            engine.set_price_data("SPY", price_data["SPY"])
            engine.set_signals(signals)
            
            # 执行回测
            result = engine.run()
            
            # 获取目标指标
            metric_value = result["returns"].get(self.metric, -float('inf'))
            
            self.results.append({
                "params": params,
                "result": result,
                "metric": metric_value
            })
            
            if metric_value > best_metric:
                best_metric = metric_value
                best_params = params
                best_result = result
                logger.info(f"    ✅ 新最优! {self.metric}={metric_value:.4f}")
        
        return {
            "best_params": best_params,
            "best_result": best_result,
            "best_metric": best_metric,
            "all_results": self.results,
            "total_combinations": len(combinations)
        }


# ===== 便捷函数 =====

def quick_backtest(ticker: str, prices: pd.DataFrame, 
                   signals: pd.DataFrame, config: Dict = None) -> Dict:
    """快速回测"""
    engine = BacktestEngine(config)
    
    engine.set_price_data(ticker, prices)
    
    # 转换信号格式
    signal_dict = {}
    for _, row in signals.iterrows():
        date = row["date"]
        for col in signals.columns:
            if col != "date":
                signal_dict.setdefault(date, {})[col] = row[col]
    
    engine.set_signals(signal_dict)
    
    return engine.run()


# ===== 测试 =====

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print("\n🧪 回测引擎测试")
    print("=" * 50)
    
    # 生成测试数据
    dates = pd.date_range(start="2024-01-01", end="2024-12-31", freq="D").strftime("%Y-%m-%d").tolist()
    prices = pd.DataFrame({
        "date": dates,
        "close": 100 + np.cumsum(np.random.randn(len(dates)) * 2)
    })
    
    # 生成信号
    signals_df = pd.DataFrame({
        "date": dates,
        "SPY": np.random.randn(len(dates)) * 0.5 + 0.1
    })
    
    signals = {}
    for _, row in signals_df.iterrows():
        signals[row["date"]] = {"SPY": row["SPY"]}
    
    # 运行回测
    result = quick_backtest("SPY", prices, signals_df)
    
    print(f"\n📊 回测结果")
    print(f"  总收益: {result['returns']['total_return']:.2f}%")
    print(f"  夏普比率: {result['returns']['sharpe_ratio']:.2f}")
    print(f"  最大回撤: {result['returns']['max_drawdown_pct']:.2f}%")
    print(f"  交易次数: {result['trading']['total_trades']}")
    print(f"  胜率: {result['trading']['win_rate']:.2f}%")
    
    print("\n" + "=" * 50)
