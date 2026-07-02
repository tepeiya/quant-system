"""
GTJA191 因子库 (国泰君安191因子 / Alpha191)
============================================
基于国泰君安2017年发布的短周期量价因子研究

因子特点：
- 191个短周期交易型Alpha因子
- 基于OHLCV+VWAP数据
- 适合A股短周期交易

核心算子（与Alpha101共用）：
- DELTA, DELAY, SUM, STD, CORR, RANK, TSRANK
- SMA, MAX, MIN, COUNT, REGBETA, REGRESI
- WMA, COSE, SUMIF, FILTER
"""

import numpy as np
import pandas as pd
import logging
from typing import Dict, List
from alpha101 import (rank, ts_rank, delta, delay, correlation, covariance,
                       stddev, ts_sum, ts_max, ts_min, ts_argmax, ts_argmin,
                       scale, signedpower, product, decay_linear, ts_mean)

logger = logging.getLogger("quant.gtja191")


def wma(series, window):
    """加权移动平均"""
    weights = np.arange(1, window + 1, dtype=float)
    weights = weights / weights.sum()
    if isinstance(series, pd.Series):
        return series.rolling(window).apply(lambda x: np.dot(x, weights), raw=True)
    return pd.Series(series).rolling(window).apply(lambda x: np.dot(x, weights), raw=True)


def regbeta(y, x, window):
    """滚动回归Beta系数"""
    def _beta(arr_y, arr_x):
        if len(arr_y) < 2 or np.std(arr_x) == 0:
            return np.nan
        return np.cov(arr_y, arr_x)[0, 1] / np.var(arr_x)
    if isinstance(y, pd.Series) and isinstance(x, pd.Series):
        df = pd.DataFrame({"y": y, "x": x})
        return df.rolling(window).apply(lambda d: _beta(d["y"].values, d["x"].values), raw=False)
    return pd.Series(y).rolling(window).apply(lambda arr: _beta(arr, np.arange(len(arr))), raw=True)


def regresi(y, x, window):
    """滚动回归残差"""
    def _resi(arr_y, arr_x):
        if len(arr_y) < 2 or np.std(arr_x) == 0:
            return np.nan
        beta = np.cov(arr_y, arr_x)[0, 1] / np.var(arr_x)
        alpha = np.mean(arr_y) - beta * np.mean(arr_x)
        return arr_y[-1] - (alpha + beta * arr_x[-1])
    if isinstance(y, pd.Series) and isinstance(x, pd.Series):
        df = pd.DataFrame({"y": y, "x": x})
        return df.rolling(window).apply(lambda d: _resi(d["y"].values, d["x"].values), raw=False)
    return pd.Series(y).rolling(window).apply(lambda arr: _resi(arr, np.arange(len(arr))), raw=True)


def count(condition, window):
    """条件成立天数"""
    if isinstance(condition, pd.Series):
        return condition.rolling(window).sum()
    return pd.Series(condition).rolling(window).sum()


def sumif(series, condition, window):
    """条件求和"""
    masked = series.where(condition, 0)
    if isinstance(masked, pd.Series):
        return masked.rolling(window).sum()
    return pd.Series(masked).rolling(window).sum()


def filter(series, condition):
    """条件过滤"""
    return series.where(condition, 0)


def high_low_close_ratio(high, low, close, window):
    """高低收比"""
    return (high - low) / (close + 1e-10)


class GTJA191:
    """国泰君安191因子库"""

    def __init__(self):
        self.factor_count = 191

    def _prepare_data(self, df: pd.DataFrame) -> Dict[str, pd.Series]:
        d = {}
        d["open"] = df["Open"].copy()
        d["close"] = df["Close"].copy()
        d["high"] = df["High"].copy()
        d["low"] = df["Low"].copy()
        d["volume"] = df["Volume"].copy()
        d["vwap"] = df.get("VWAP", d["close"]).copy()
        d["returns"] = d["close"].pct_change()
        d["amount"] = df.get("Amount", d["volume"] * d["close"]).copy()
        d["adv5"] = ts_mean(d["volume"], 5)
        d["adv10"] = ts_mean(d["volume"], 10)
        d["adv20"] = ts_mean(d["volume"], 20)
        d["adv30"] = ts_mean(d["volume"], 30)
        d["adv60"] = ts_mean(d["volume"], 60)
        d["adv120"] = ts_mean(d["volume"], 120)
        return d

    def compute(self, df: pd.DataFrame) -> Dict[str, pd.Series]:
        """计算核心GTJA191因子（精选30个代表性因子）"""
        d = self._prepare_data(df)
        results = {}

        # === 动量类因子 ===
        results["gtja_001"] = (-1 * correlation(d["returns"], ts_mean(d["volume"], 20), 6))
        results["gtja_002"] = (-1 * delta(rank(((d["close"] - d["low"]) - (d["high"] - d["close"])) / (d["high"] - d["low"] + 1e-10)), 5))
        results["gtja_003"] = (-1 * ts_sum(rank(d["close"]), 5) / 5)
        results["gtja_004"] = (-1 * rank(ts_std(d["returns"], 20) * d["close"]))
        results["gtja_005"] = (-1 * rank((d["open"] - d["vwap"]) * 1))

        # === 量价相关类 ===
        results["gtja_006"] = (-1 * correlation(d["open"], d["volume"], 10))
        results["gtja_007"] = pd.Series(np.where(d["adv20"] < d["volume"], 1, -1), index=d["close"].index) * (-1 * ts_rank(abs(delta(d["close"], 7)), 60) * sign(delta(d["close"], 7)))
        results["gtja_008"] = (-1 * rank(ts_sum(d["open"], 5) * ts_sum(d["returns"], 5) - delay(ts_sum(d["open"], 5) * ts_sum(d["returns"], 5), 10)))
        _dc1 = delta(d["close"], 1)
        _cond9a = ts_min(_dc1, 5) > 0
        _cond9b = ts_max(_dc1, 5) < 0
        results["gtja_009"] = pd.Series(np.where(_cond9a, _dc1, np.where(_cond9b, _dc1, -1 * _dc1)), index=d["close"].index)
        _cond10a = ts_min(_dc1, 4) > 0
        _cond10b = ts_max(_dc1, 4) < 0
        results["gtja_010"] = rank(pd.Series(np.where(_cond10a, _dc1, np.where(_cond10b, _dc1, -1 * _dc1)), index=d["close"].index))

        # === 反转类因子 ===
        results["gtja_011"] = (rank(ts_max((d["vwap"] - d["close"]), 3)) + rank(ts_min((d["vwap"] - d["close"]), 3)) + rank(delta(d["vwap"], 3)))
        results["gtja_012"] = (sign(delta(d["volume"], 1)) * (-1 * delta(d["close"], 1)))
        results["gtja_013"] = (-1 * rank(covariance(rank(d["close"]), rank(d["volume"]), 5)))
        results["gtja_014"] = ((-1 * rank(delta(d["returns"], 3))) * correlation(d["open"], d["volume"], 10))
        results["gtja_015"] = (-1 * ts_sum(rank(correlation(rank(d["high"]), rank(d["volume"]), 3)), 3))

        # === 波动率类因子 ===
        results["gtja_016"] = (-1 * rank(covariance(rank(d["high"]), rank(d["volume"]), 5)))
        results["gtja_017"] = ((-1 * rank(ts_rank(d["close"], 10))) * rank(delta(delta(d["close"], 1), 1)) * rank(ts_rank(d["volume"] / d["adv20"], 5)))
        results["gtja_018"] = (-1 * rank((stddev(abs((d["close"] - d["open"])), 5) + (d["close"] - d["open"])) + correlation(d["close"], d["open"], 10)))
        results["gtja_019"] = ((-1 * sign((d["close"] - delay(d["close"], 7) + delta(d["close"], 7)))) * (1 + rank(1 + ts_rank(d["volume"], 2))))
        results["gtja_020"] = (((-1 * rank(d["open"] - delay(d["open"], 1))) * (-1 * rank(d["open"] - delay(d["open"], 1)))) * (-1 * rank(d["returns"])))

        # === 成交量异常类 ===
        results["gtja_021"] = (d["volume"] / d["adv20"])
        results["gtja_022"] = (-1 * delta(correlation(d["close"], d["volume"], 5), 5) * rank(stddev(d["close"], 20)))
        results["gtja_023"] = (((d["high"] * 0.9) + (d["close"] * 0.1) - d["vwap"]) / (d["high"] - d["low"] + 1e-10))
        results["gtja_024"] = (-1 * delta(d["close"], 3))
        results["gtja_025"] = rank(((-1 * d["returns"]) * d["adv20"] * d["vwap"] * (d["high"] - d["low"])))

        # === 趋势类因子 ===
        results["gtja_026"] = (-1 * ts_max(correlation(ts_rank(d["volume"], 5), ts_rank(d["high"], 5), 5), 3))
        results["gtja_027"] = ((ts_mean(d["close"], 1) - ts_mean(d["close"], 4)) > 0).astype(float) * 2 - 1
        results["gtja_028"] = scale(correlation(d["adv20"], d["low"], 5) + ((d["high"] + d["low"]) / 2) - d["close"])
        results["gtja_029"] = ts_min(product(rank(rank(scale(np.log(ts_sum(ts_min(rank(rank(-1 * rank(delta(d["close"] - 1, 5)))), 2), 1))))), 1) + 5, 1)
        results["gtja_030"] = (1.0 - rank((sign(d["close"] - delay(d["close"], 1)) + sign(delay(d["close"], 1) - delay(d["close"], 2)) + sign(delay(d["close"], 2) - delay(d["close"], 3)))))

        # === 扩展因子（31-60）===
        results["gtja_031"] = (rank(ts_rank(d["close"], 10)) * rank(delta(d["close"], 3)) * sign(scale(correlation(d["adv20"], d["low"], 12))))
        results["gtja_032"] = scale(((ts_sum(d["close"], 7) / 7) - d["close"]) + 20 * scale(correlation(d["vwap"], delay(d["close"], 5), 230)))
        results["gtja_033"] = rank(-1 + ((d["open"] / d["close"]) * 1))
        results["gtja_034"] = rank(2 - rank(stddev(d["returns"], 2) / (stddev(d["returns"], 5) + 1e-10)) - rank(delta(d["close"], 1)))
        results["gtja_035"] = (ts_rank(d["volume"], 32) * (1 - ts_rank(((d["close"] + d["high"]) - d["low"]), 16)) * (1 - ts_rank(d["returns"], 32)))
        results["gtja_036"] = (1.0 + (((2 * rank((ts_rank(delta(d["close"], 1), 4) > 0).astype(float) * 2 - 1)) + 1)) * ((2 * rank((ts_rank(delta(d["volume"], 1), 4) > 0).astype(float) * 2 - 1)) + 1))
        results["gtja_037"] = rank(((-1 * d["returns"]) * d["adv20"] * d["vwap"] * (d["high"] - d["low"])))
        results["gtja_038"] = ((-1 * rank(ts_rank(d["close"], 10))) * rank((d["close"] / d["open"])))
        results["gtja_039"] = ((-1 * rank(ts_rank(delta(d["close"], 7), 4))) + 1)
        results["gtja_040"] = ((-1 * rank(stddev(d["high"], 10))) * correlation(d["high"], d["volume"], 10))

        # === 因子41-60 ===
        results["gtja_041"] = (((d["high"] * d["low"]) ** 0.5) - d["vwap"])
        results["gtja_042"] = rank((d["vwap"] - d["close"]) / ((d["vwap"] + d["close"]) / 2 + 1e-10))
        results["gtja_043"] = (ts_rank(d["volume"] / d["adv20"], 20) * ts_rank(-1 * delta(d["close"], 7), 8))
        results["gtja_044"] = (-1 * correlation(d["high"], ts_rank(d["volume"], 5), 5))
        results["gtja_045"] = (-1 * rank(ts_sum(delay(d["close"], 5), 20) / 20 * correlation(d["close"], d["volume"], 2) * correlation(ts_sum(d["close"], 5), ts_sum(d["close"], 20), 2)))
        results["gtja_046"] = ((ts_mean(d["close"], 3) + ts_mean(d["close"], 6) + ts_mean(d["close"], 12) + ts_mean(d["close"], 24)) / 4) * (1 / (abs(d["close"] - ts_mean(d["close"], 12)) / (ts_mean(d["close"], 12) + 1e-10)))
        results["gtja_047"] = ((rank(1 / d["close"]) * d["volume"] / d["adv20"]) * ((d["high"] * rank((d["high"] - d["close"]) / (d["close"] - d["low"] + 1e-10))) - rank((d["low"] - d["close"]) / (d["close"] - d["low"] + 1e-10))))
        results["gtja_048"] = (correlation(delta(d["close"], 1), delta(delay(d["close"], 1), 1), 25) / (stddev(delta(d["close"], 1), 25) / (stddev(delta(delay(d["close"], 1), 1), 25) + 1e-10)))
        results["gtja_049"] = count((d["high"] + d["low"]) > delay(d["close"], 1), 6)
        results["gtja_050"] = count((d["high"] + d["low"]) < delay(d["close"], 1), 6)

        # === 因子51-60 ===
        results["gtja_051"] = count((d["high"] + d["low"]) == delay(d["close"], 1), 6)
        results["gtja_052"] = (ts_sum(np.maximum(0, ts_max(d["high"], 2) - delay(d["close"], 2)), 20) / (ts_sum(np.maximum(0, delay(d["close"], 2) - ts_min(d["low"], 2)), 20) + 1e-10))
        results["gtja_053"] = count(d["close"] > delay(d["close"], 1), 12) - count(d["close"] < delay(d["close"], 1), 12)
        results["gtja_054"] = ((-1 * rank(d["low"])) * correlation(d["adv20"], d["close"], 5)) + (-1 * ((d["close"] - d["low"]) / (d["high"] - d["low"] + 1e-10)))
        results["gtja_055"] = ts_sum((d["close"] > ts_mean(d["close"], 5)).astype(float) * stddev(d["close"], 5), 12)
        results["gtja_056"] = (rank(d["open"] - ts_min(d["low"], 12))) / (rank(ts_max(d["high"], 12) - d["open"]) + 1e-10)
        results["gtja_057"] = -1 * ((d["close"] - d["vwap"]) / (decay_linear(rank(ts_argmax(d["close"], 30)), 2) + 1e-10))
        results["gtja_058"] = -1 * ts_rank(decay_linear(correlation(d["adv20"], d["vwap"], 5), 2), 5)
        results["gtja_059"] = -1 * rank(ts_min(d["close"], 2))
        results["gtja_060"] = (scale(((rank(ts_max(d["open"], 30)) * 2) - rank(ts_min(d["open"], 30)))) > 0).astype(float) * 2 - 1

        return results


def ts_std(series, window):
    """滚动标准差（GTJA风格）"""
    if isinstance(series, pd.Series):
        return series.rolling(window).std()
    return pd.Series(series).rolling(window).std()


def sign(series):
    """符号函数"""
    return np.sign(series)


if __name__ == "__main__":
    print("GTJA191 因子库（国泰君安191因子）")
    print(f"核心因子数量: 60")
    print("\n因子类别:")
    print("  - 动量类: gtja_001~005")
    print("  - 量价相关类: gtja_006~010")
    print("  - 反转类: gtja_011~015")
    print("  - 波动率类: gtja_016~020")
    print("  - 成交量异常类: gtja_021~025")
    print("  - 趋势类: gtja_026~030")
    print("  - 扩展因子: gtja_031~060")