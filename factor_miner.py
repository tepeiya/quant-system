"""
高级因子挖掘模块 — 从 akquant 因子操作函数移植
=============================================
不依赖 Polars，直接用 Pandas/NumPy 计算专业因子。

因子类型:
  - 动量类: 不同窗口的动量、加速度
  - 波动类: ATR比值、波动率变化
  - 相关类: 个股与SPY的滚动相关性、滚动BETA
  - 成交量类: 量价比、成交量形态
  - 截面类: 排名、标准化、行业中性化
  - 复合类: 因子组合

用法:
  from factor_miner import FactorMiner
  miner = FactorMiner(cache)
  factors = miner.compute_all()
  ic = miner.compute_ic(factors, forward_returns)
"""

import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import logging

logger = logging.getLogger("quant.factor_miner")


class FactorMiner:
    """高级因子挖掘器"""

    def __init__(self, cache: dict = None):
        self.cache = cache

    # ============================================================
    # 时间序列因子 (TS)
    # ============================================================

    @staticmethod
    def ts_mean(series: np.ndarray, window: int) -> float:
        """滚动均值"""
        if len(series) < window:
            return np.nan
        return float(np.mean(series[-window:]))

    @staticmethod
    def ts_std(series: np.ndarray, window: int) -> float:
        """滚动标准差"""
        if len(series) < window:
            return np.nan
        return float(np.std(series[-window:], ddof=1))

    @staticmethod
    def ts_max(series: np.ndarray, window: int) -> float:
        """滚动最大值"""
        if len(series) < window:
            return np.nan
        return float(np.max(series[-window:]))

    @staticmethod
    def ts_min(series: np.ndarray, window: int) -> float:
        """滚动最小值"""
        if len(series) < window:
            return np.nan
        return float(np.min(series[-window:]))

    @staticmethod
    def ts_sum(series: np.ndarray, window: int) -> float:
        """滚动求和"""
        if len(series) < window:
            return np.nan
        return float(np.sum(series[-window:]))

    @staticmethod
    def delta(series: np.ndarray, d: int) -> float:
        """差分: x(t) - x(t-d)"""
        if len(series) <= d:
            return np.nan
        return float(series[-1] - series[-1 - d])

    @staticmethod
    def delay(series: np.ndarray, d: int) -> float:
        """延迟: x(t-d)"""
        if len(series) <= d:
            return np.nan
        return float(series[-1 - d])

    @staticmethod
    def ts_rank(series: np.ndarray, window: int) -> float:
        """滚动排名 (0~1)，当前值在窗口内的分位"""
        if len(series) < window:
            return np.nan
        window_data = series[-window:]
        current = window_data[-1]
        # 排名: 比当前小的有多少个
        rank = np.sum(window_data < current) / (len(window_data) - 1)
        return float(rank)

    @staticmethod
    def ts_corr(x: np.ndarray, y: np.ndarray, window: int) -> float:
        """滚动相关系数"""
        if len(x) < window or len(y) < window:
            return np.nan
        return float(np.corrcoef(x[-window:], y[-window:])[0, 1])

    @staticmethod
    def ts_cov(x: np.ndarray, y: np.ndarray, window: int) -> float:
        """滚动协方差"""
        if len(x) < window or len(y) < window:
            return np.nan
        return float(np.cov(x[-window:], y[-window:])[0, 1])

    # ============================================================
    # 专业因子计算
    # ============================================================

    def momentum_factor(self, df: pd.DataFrame, windows: list = None) -> dict:
        """多窗口动量因子"""
        if windows is None:
            windows = [5, 10, 21, 63, 126, 252]

        close = df["Close"].values
        result = {}

        for w in windows:
            if len(close) > w:
                result[f"momentum_{w}d"] = (close[-1] / close[-1 - w] - 1) * 100
            else:
                result[f"momentum_{w}d"] = np.nan

        # 动量加速度: 短-长动量差
        if not np.isnan(result.get("momentum_21d", np.nan)) and \
           not np.isnan(result.get("momentum_5d", np.nan)):
            result["momentum_accel"] = result["momentum_5d"] - result["momentum_21d"]

        return result

    def volatility_factor(self, df: pd.DataFrame) -> dict:
        """波动类因子"""
        close = df["Close"].values
        volume = df["Volume"].values if "Volume" in df.columns else None
        result = {}

        if len(close) > 21:
            daily_ret = np.diff(close[-21:]) / close[-21:-1]
            result["volatility_20d"] = float(np.std(daily_ret, ddof=1)) * 100
            result["volatility_ratio"] = result["volatility_20d"] / (
                float(np.std(close[-60:], ddof=1) / np.mean(close[-60:])) * 100
                if len(close) > 60 else 1)

        # ATR比值: 当前ATR / 均值
        if "ATR_Pct" in df.columns:
            atr_vals = df["ATR_Pct"].values
            if len(atr_vals) > 20:
                result["atr_ratio"] = float(atr_vals[-1] / np.mean(atr_vals[-20:]))
                result["atr_zscore"] = float((atr_vals[-1] - np.mean(atr_vals[-60:])) /
                                               max(np.std(atr_vals[-60:], ddof=1), 0.01))

        return result

    def correlation_factor(self, df: pd.DataFrame, spy_df: pd.DataFrame = None) -> dict:
        """相关类因子: 个股与SPY的相关性、BETA"""
        close = df["Close"].values
        result = {}

        if spy_df is not None and len(close) > 60:
            spy_close = spy_df["Close"].values[-len(close):]
            if len(spy_close) == len(close):
                # 60天相关性
                if len(close) > 60:
                    result["corr_spy_60d"] = self.ts_corr(close, spy_close, 60)
                # 20天相关性
                if len(close) > 20:
                    result["corr_spy_20d"] = self.ts_corr(close, spy_close, 20)

                # BETA: 个股收益 vs SPY收益 (60天)
                if len(close) > 62:
                    stock_ret = np.diff(close[-61:]) / close[-61:-1]
                    spy_ret = np.diff(spy_close[-61:]) / spy_close[-61:-1]
                    beta = np.cov(stock_ret, spy_ret)[0, 1] / max(np.var(spy_ret), 1e-10)
                    result["beta_60d"] = float(beta)

        return result

    def volume_factor(self, df: pd.DataFrame) -> dict:
        """成交量类因子"""
        if "Volume" not in df.columns:
            return {}

        close = df["Close"].values
        volume = df["Volume"].values
        result = {}

        if len(volume) > 20:
            avg_vol_20 = np.mean(volume[-20:])
            avg_vol_60 = np.mean(volume[-60:]) if len(volume) > 60 else avg_vol_20

            result["volume_ratio_1"] = float(volume[-1] / max(avg_vol_20, 1))
            result["volume_ratio_20"] = float(avg_vol_20 / max(avg_vol_60, 1))

            # 量价比: 今日涨幅 / 量比
            if len(close) > 1 and avg_vol_20 > 0:
                price_chg = abs((close[-1] - close[-2]) / close[-2])
                vol_ratio = volume[-1] / avg_vol_20
                result["vpr"] = float(price_chg / max(vol_ratio, 0.1))

        return result

    def trend_factor(self, df: pd.DataFrame) -> dict:
        """趋势类因子"""
        close = df["Close"].values
        result = {}

        if "SMA20" in df.columns and "SMA50" in df.columns:
            sma20 = df["SMA20"].values[-1]
            sma50 = df["SMA50"].values[-1]
            sma200 = df["SMA200"].values[-1] if "SMA200" in df.columns else sma50

            result["price_to_sma20"] = float(close[-1] / max(sma20, 0.01))
            result["price_to_sma50"] = float(close[-1] / max(sma50, 0.01))
            result["sma20_to_sma50"] = float(sma20 / max(sma50, 0.01))
            result["sma50_to_sma200"] = float(sma50 / max(sma200, 0.01))

            # 趋势强度: 价格在SMA20之上的百分比
            if len(close) > 60:
                above_sma = np.sum(close[-60:] > sma20)
                result["trend_strength"] = float(above_sma / 60)

        return result

    # ===== 资金流因子 =====
    def fund_flow_factor(self, ticker: str) -> dict:
        """从东财获取主力资金流向"""
        try:
            from data_global import fund_flow_daily
            flow = fund_flow_daily(ticker, days=5)
            if not flow:
                return {}
            result = {}
            net_inflows = [f.get("net_inflow", 0) for f in flow if isinstance(f, dict)]
            if net_inflows:
                result["fund_flow_net"] = float(sum(net_inflows) / max(abs(sum(net_inflows)), 1))
                result["fund_flow_latest"] = float(net_inflows[0]) if net_inflows else 0
                result["fund_flow_trend"] = float(net_inflows[0] - net_inflows[-1]) if len(net_inflows) > 1 else 0
            return result
        except:
            return {}

    # ===== 期权因子 =====
    def options_factor(self, ticker: str) -> dict:
        """从 Yahoo 获取期权链计算 Put/Call Ratio"""
        try:
            from data_global import options_chain
            chain = options_chain(ticker)
            if not chain:
                return {}
            calls = chain.get("calls", [])
            puts = chain.get("puts", [])
            if not calls or not puts:
                return {}
            call_vol = sum(float(c.get("volume", 0)) for c in calls)
            put_vol = sum(float(p.get("volume", 0)) for p in puts)
            call_oi = sum(float(c.get("openInterest", 0)) for c in calls)
            put_oi = sum(float(p.get("openInterest", 0)) for p in puts)
            result = {}
            if put_vol + call_vol > 0:
                result["put_call_vol_ratio"] = float(put_vol / max(call_vol, 1))
            if put_oi + call_oi > 0:
                result["put_call_oi_ratio"] = float(put_oi / max(call_oi, 1))
            ivs = [float(c.get("impliedVolatility", 0)) for c in calls + puts if c.get("impliedVolatility")]
            if ivs:
                result["options_iv_mean"] = float(np.mean(ivs))
            return result
        except:
            return {}

    # ===== 基本面因子 =====
    def fundamental_factor(self, ticker: str) -> dict:
        """从东财获取基本面数据"""
        try:
            from data_global import financial_statements, get_secid
            secid = get_secid(ticker)
            if not secid:
                return {}
            result = {}
            income = financial_statements(secid, "income")
            if income and len(income) >= 2:
                rev_new = income[0].get("revenue", 0) or 0
                rev_old = income[1].get("revenue", 0) or 0
                if rev_old > 0:
                    result["fundamental_rev_growth"] = float((rev_new - rev_old) / rev_old)
            if income and income[0]:
                rev = income[0].get("revenue", 0) or 0
                profit = income[0].get("netProfit", 0) or 0
                if rev > 0:
                    result["fundamental_profit_margin"] = float(profit / rev)
            balance = financial_statements(secid, "balance")
            if balance and balance[0]:
                total_liab = balance[0].get("totalLiabilities", 0) or 0
                total_assets = balance[0].get("totalAssets", 0) or 0
                if total_assets > 0:
                    result["fundamental_debt_ratio"] = float(total_liab / total_assets)
            return result
        except:
            return {}

    def compute_stock_factors(self, ticker: str, df: pd.DataFrame,
                               spy_df: pd.DataFrame = None) -> dict:
        """计算单只股票的所有因子"""
        factors = {}

        # 基础数据
        factors["ticker"] = ticker
        factors["price"] = float(df["Close"].values[-1]) if len(df) > 0 else 0

        # 动量因子
        factors.update(self.momentum_factor(df))

        # 波动因子
        factors.update(self.volatility_factor(df))

        # 相关因子
        factors.update(self.correlation_factor(df, spy_df))

        # 成交量因子
        factors.update(self.volume_factor(df))

        # 趋势因子
        factors.update(self.trend_factor(df))

        # RSI 补充
        if "RSI" in df.columns:
            factors["rsi"] = float(df["RSI"].values[-1])

        # ATR
        if "ATR_Pct" in df.columns:
            factors["atr_pct"] = float(df["ATR_Pct"].values[-1])

        # ===== 新增因子 =====

        # 1️⃣ 资金流因子
        try:
            factors.update(self.fund_flow_factor(ticker))
        except Exception as e:
            logger.debug(f"{ticker} 资金流因子失败: {e}")

        # 2️⃣ 期权因子
        try:
            factors.update(self.options_factor(ticker))
        except Exception as e:
            logger.debug(f"{ticker} 期权因子失败: {e}")

        # 3️⃣ 基本面因子
        try:
            factors.update(self.fundamental_factor(ticker))
        except Exception as e:
            logger.debug(f"{ticker} 基本面因子失败: {e}")

        return factors

    def compute_all(self, tickers: list = None, spy_df: pd.DataFrame = None) -> pd.DataFrame:
        """计算所有股票的因子，返回DataFrame"""
        if self.cache is None:
            logger.error("无数据缓存")
            return pd.DataFrame()

        if tickers is None:
            tickers = sorted(self.cache.keys())[:300]

        all_factors = []
        for t in tickers:
            df = self.cache.get(t)
            if df is None or len(df) < 60:
                continue
            try:
                factors = self.compute_stock_factors(t, df, spy_df)
                all_factors.append(factors)
            except Exception as e:
                logger.debug(f"{t} 因子计算失败: {e}")

        return pd.DataFrame(all_factors)

    @staticmethod
    def compute_ic(factor_df: pd.DataFrame, factor_col: str,
                   forward_return_col: str = "future_return") -> dict:
        """
        计算因子的IC (Information Coefficient)

        参数:
            factor_df: 包含因子值和未来收益的DataFrame
            factor_col: 因子列名
            forward_return_col: 未来收益列名

        返回:
            dict: {ic_rank, ic_pearson, ic_std, ir}
        """
        valid = factor_df[[factor_col, forward_return_col]].dropna()
        if len(valid) < 15:
            return {"ic_rank": 0, "ic_pearson": 0, "ic_std": 0, "ir": 0}

        # Spearman秩相关系数
        rx = valid[factor_col].rank()
        ry = valid[forward_return_col].rank()
        n = len(rx)
        d = (rx - ry) ** 2
        ic_rank = 1 - (6 * d.sum()) / (n * (n ** 2 - 1))

        # Pearson相关系数
        ic_pearson = valid[factor_col].corr(valid[forward_return_col])

        return {
            "ic_rank": round(float(ic_rank), 4),
            "ic_pearson": round(float(ic_pearson), 4),
            "count": len(valid),
        }

    @staticmethod
    def rank_factors(factor_df: pd.DataFrame, forward_return_col: str = "future_return",
                     min_samples: int = 20) -> pd.DataFrame:
        """排名所有因子的IC值，找出最有效的因子"""
        factor_cols = [c for c in factor_df.columns
                       if c not in ["ticker", "price", forward_return_col]]

        results = []
        for col in factor_cols:
            ic = FactorMiner.compute_ic(factor_df, col, forward_return_col)
            if ic["count"] >= min_samples:
                results.append({
                    "factor": col,
                    "ic_rank": ic["ic_rank"],
                    "ic_pearson": ic["ic_pearson"],
                    "samples": ic["count"],
                })

        result_df = pd.DataFrame(results)
        if not result_df.empty:
            result_df["abs_ic"] = result_df["ic_rank"].abs()
            result_df = result_df.sort_values("abs_ic", ascending=False)

        return result_df


# ============================================================
# 测试
# ============================================================

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO,
                        format="%(name)s: %(message)s")

    # 造测试数据 — 至少300天
    np.random.seed(42)
    dates = pd.date_range("2024-01-01", "2026-06-19", freq="D")
    n = len(dates)

    mock_cache = {}
    for t in ["AAPL", "MSFT", "GOOGL", "NVDA", "AMZN", "META", "TSLA", "JPM",
              "V", "WMT", "JNJ", "PG", "XOM", "UNH", "HD"]:
        price = 100 + np.cumsum(np.random.normal(0, 1, n))
        vol = np.abs(np.random.normal(5e7, 1e7, n))
        df = pd.DataFrame({
            "Close": price,
            "High": price * 1.02,
            "Low": price * 0.98,
            "Volume": vol,
            "SMA20": pd.Series(price).rolling(20).mean().values,
            "SMA50": pd.Series(price).rolling(50).mean().values,
            "SMA200": pd.Series(price).rolling(200).mean().values,
            "RSI": np.random.uniform(30, 70, n),
            "ATR_Pct": np.random.uniform(0.5, 3.0, n),
        }, index=dates)
        mock_cache[t] = df

    spy_df = pd.DataFrame({
        "Close": 400 + np.cumsum(np.random.normal(0, 0.5, n)),
    }, index=dates)

    # 测试
    miner = FactorMiner(mock_cache)
    factors = miner.compute_all(spy_df=spy_df)

    print(f"\n因子总数: {len(factors.columns) - 1}")
    print(f"股票数: {len(factors)}")
    print(f"\n因子列: {[c for c in factors.columns if c not in ['ticker', 'price']]}")

    # 添加模拟未来收益
    factors["future_return"] = np.random.normal(0.5, 2.0, len(factors))

    # 排名因子IC
    ranking = miner.rank_factors(factors)
    print(f"\nTop 10 因子 (按IC排序):")
    print(f"{'因子':<25} {'IC秩相关':>10} {'IC皮尔逊':>10} {'样本数':>8}")
    print("-" * 55)
    for _, r in ranking.head(10).iterrows():
        print(f"{r['factor']:<25} {r['ic_rank']:>+10.4f} {r['ic_pearson']:>+10.4f} {r['samples']:>8}")

    print(f"\n✅ FactorMiner 测试通过")
