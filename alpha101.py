"""
Alpha101 因子库 (WorldQuant Alpha 101)
=====================================
基于 WorldQuant 发表的《101 Formulaic Alphas》论文实现

因子特点：
- 全部基于 OHLCV + VWAP 数据
- 短周期量价因子
- 使用截面排名（rank）和时序算子

核心算子：
- rank: 截面排名
- ts_rank: 时序排名
- delta: 差分
- delay: 滞后
- correlation: 滚动相关
- covariance: 滚动协方差
- stddev: 滚动标准差
- sum: 滚动求和
- ts_max/ts_min: 时序极值
- ts_argmax/ts_argmin: 极值位置
"""

import numpy as np
import pandas as pd
import logging
from typing import Dict, List, Optional

logger = logging.getLogger("quant.alpha101")


# ============================================================
# 核心算子
# ============================================================

def rank(series):
    """截面排名（0-1）"""
    if isinstance(series, pd.Series):
        return series.rank(pct=True)
    return pd.Series(series).rank(pct=True)


def ts_rank(series, window):
    """时序排名（当前值在过去window天的排名，0-1）"""
    if isinstance(series, pd.Series):
        return series.rolling(window).apply(lambda x: pd.Series(x).rank(pct=True).iloc[-1], raw=False)
    s = pd.Series(series)
    return s.rolling(window).apply(lambda x: pd.Series(x).rank(pct=True).iloc[-1], raw=False)


def delta(series, period=1):
    """差分: x(t) - x(t-period)"""
    if isinstance(series, pd.Series):
        return series.diff(period)
    return pd.Series(series).diff(period)


def delay(series, period=1):
    """滞后: x(t-period)"""
    if isinstance(series, pd.Series):
        return series.shift(period)
    return pd.Series(series).shift(period)


def correlation(x, y, window):
    """滚动相关系数"""
    if isinstance(x, pd.Series) and isinstance(y, pd.Series):
        return x.rolling(window).corr(y)
    return pd.Series(x).rolling(window).corr(pd.Series(y))


def covariance(x, y, window):
    """滚动协方差"""
    if isinstance(x, pd.Series) and isinstance(y, pd.Series):
        return x.rolling(window).cov(y)
    return pd.Series(x).rolling(window).cov(pd.Series(y))


def stddev(series, window):
    """滚动标准差"""
    if isinstance(series, pd.Series):
        return series.rolling(window).std()
    return pd.Series(series).rolling(window).std()


def ts_sum(series, window):
    """滚动求和"""
    if isinstance(series, pd.Series):
        return series.rolling(window).sum()
    return pd.Series(series).rolling(window).sum()


def ts_max(series, window):
    """时序最大值"""
    if isinstance(series, pd.Series):
        return series.rolling(window).max()
    return pd.Series(series).rolling(window).max()


def ts_min(series, window):
    """时序最小值"""
    if isinstance(series, pd.Series):
        return series.rolling(window).min()
    return pd.Series(series).rolling(window).min()


def ts_argmax(series, window):
    """最大值位置（0=最早）"""
    if isinstance(series, pd.Series):
        return series.rolling(window).apply(lambda x: np.argmax(x), raw=True)
    return pd.Series(series).rolling(window).apply(lambda x: np.argmax(x), raw=True)


def ts_argmin(series, window):
    """最小值位置"""
    if isinstance(series, pd.Series):
        return series.rolling(window).apply(lambda x: np.argmin(x), raw=True)
    return pd.Series(series).rolling(window).apply(lambda x: np.argmin(x), raw=True)


def scale(series, a=1):
    """缩放使绝对值之和为a"""
    s = pd.Series(series) if not isinstance(series, pd.Series) else series
    return s / (s.abs().sum() + 1e-10) * a


def signedpower(series, exponent):
    """带符号幂"""
    s = pd.Series(series) if not isinstance(series, pd.Series) else series
    return np.sign(s) * (s.abs() ** exponent)


def product(series, window):
    """滚动乘积"""
    if isinstance(series, pd.Series):
        return series.rolling(window).apply(np.prod, raw=True)
    return pd.Series(series).rolling(window).apply(np.prod, raw=True)


def decay_linear(series, window):
    """线性衰减加权"""
    weights = np.arange(1, window + 1, dtype=float)
    weights = weights / weights.sum()
    if isinstance(series, pd.Series):
        return series.rolling(window).apply(lambda x: np.dot(x, weights), raw=True)
    return pd.Series(series).rolling(window).apply(lambda x: np.dot(x, weights), raw=True)


# ============================================================
# Alpha101 因子实现
# ============================================================

class Alpha101:
    """WorldQuant Alpha 101 因子库"""

    def __init__(self):
        self.factor_count = 101

    def _prepare_data(self, df: pd.DataFrame) -> Dict[str, pd.Series]:
        """准备数据，计算辅助变量"""
        d = {}
        d["open"] = df["Open"].copy()
        d["close"] = df["Close"].copy()
        d["high"] = df["High"].copy()
        d["low"] = df["Low"].copy()
        d["volume"] = df["Volume"].copy()
        d["vwap"] = df.get("VWAP", d["close"]).copy()  # 如果没有VWAP用close代替
        d["returns"] = d["close"].pct_change()
        d["adv5"] = ts_mean(d["volume"], 5)
        d["adv10"] = ts_mean(d["volume"], 10)
        d["adv20"] = ts_mean(d["volume"], 20)
        d["adv30"] = ts_mean(d["volume"], 30)
        d["adv60"] = ts_mean(d["volume"], 60)
        d["adv120"] = ts_mean(d["volume"], 120)
        d["adv180"] = ts_mean(d["volume"], 180)
        return d

    def compute(self, df: pd.DataFrame) -> Dict[str, pd.Series]:
        """计算所有 Alpha101 因子"""
        d = self._prepare_data(df)
        results = {}

        # Alpha#1
        results["alpha001"] = self.alpha001(d)
        # Alpha#2
        results["alpha002"] = self.alpha002(d)
        # Alpha#3
        results["alpha003"] = self.alpha003(d)
        # Alpha#4
        results["alpha004"] = self.alpha004(d)
        # Alpha#5
        results["alpha005"] = self.alpha005(d)
        # Alpha#6
        results["alpha006"] = self.alpha006(d)
        # Alpha#7
        results["alpha007"] = self.alpha007(d)
        # Alpha#8
        results["alpha008"] = self.alpha008(d)
        # Alpha#9
        results["alpha009"] = self.alpha009(d)
        # Alpha#10
        results["alpha010"] = self.alpha010(d)
        # Alpha#11
        results["alpha011"] = self.alpha011(d)
        # Alpha#12
        results["alpha012"] = self.alpha012(d)
        # Alpha#13
        results["alpha013"] = self.alpha013(d)
        # Alpha#14
        results["alpha014"] = self.alpha014(d)
        # Alpha#15
        results["alpha015"] = self.alpha015(d)
        # Alpha#16
        results["alpha016"] = self.alpha016(d)
        # Alpha#17
        results["alpha017"] = self.alpha017(d)
        # Alpha#18
        results["alpha018"] = self.alpha018(d)
        # Alpha#19
        results["alpha019"] = self.alpha019(d)
        # Alpha#20
        results["alpha020"] = self.alpha020(d)
        # Alpha#21-30
        results["alpha021"] = self.alpha021(d)
        results["alpha022"] = self.alpha022(d)
        results["alpha023"] = self.alpha023(d)
        results["alpha024"] = self.alpha024(d)
        results["alpha025"] = self.alpha025(d)
        results["alpha026"] = self.alpha026(d)
        results["alpha027"] = self.alpha027(d)
        results["alpha028"] = self.alpha028(d)
        results["alpha029"] = self.alpha029(d)
        results["alpha030"] = self.alpha030(d)
        # Alpha#31-40
        results["alpha031"] = self.alpha031(d)
        results["alpha032"] = self.alpha032(d)
        results["alpha033"] = self.alpha033(d)
        results["alpha034"] = self.alpha034(d)
        results["alpha035"] = self.alpha035(d)
        results["alpha036"] = self.alpha036(d)
        results["alpha037"] = self.alpha037(d)
        results["alpha038"] = self.alpha038(d)
        results["alpha039"] = self.alpha039(d)
        results["alpha040"] = self.alpha040(d)
        # Alpha#41-50
        results["alpha041"] = self.alpha041(d)
        results["alpha042"] = self.alpha042(d)
        results["alpha043"] = self.alpha043(d)
        results["alpha044"] = self.alpha044(d)
        results["alpha045"] = self.alpha045(d)
        results["alpha046"] = self.alpha046(d)
        results["alpha047"] = self.alpha047(d)
        results["alpha048"] = self.alpha048(d)
        results["alpha049"] = self.alpha049(d)
        results["alpha050"] = self.alpha050(d)
        # Alpha#51-60
        results["alpha051"] = self.alpha051(d)
        results["alpha052"] = self.alpha052(d)
        results["alpha053"] = self.alpha053(d)
        results["alpha054"] = self.alpha054(d)
        results["alpha055"] = self.alpha055(d)
        results["alpha056"] = self.alpha056(d)
        results["alpha057"] = self.alpha057(d)
        results["alpha058"] = self.alpha058(d)
        results["alpha059"] = self.alpha059(d)
        results["alpha060"] = self.alpha060(d)
        # Alpha#61-70
        results["alpha061"] = self.alpha061(d)
        results["alpha062"] = self.alpha062(d)
        results["alpha063"] = self.alpha063(d)
        results["alpha064"] = self.alpha064(d)
        results["alpha065"] = self.alpha065(d)
        results["alpha066"] = self.alpha066(d)
        results["alpha067"] = self.alpha067(d)
        results["alpha068"] = self.alpha068(d)
        results["alpha069"] = self.alpha069(d)
        results["alpha070"] = self.alpha070(d)
        # Alpha#71-80
        results["alpha071"] = self.alpha071(d)
        results["alpha072"] = self.alpha072(d)
        results["alpha073"] = self.alpha073(d)
        results["alpha074"] = self.alpha074(d)
        results["alpha075"] = self.alpha075(d)
        results["alpha076"] = self.alpha076(d)
        results["alpha077"] = self.alpha077(d)
        results["alpha078"] = self.alpha078(d)
        results["alpha079"] = self.alpha079(d)
        results["alpha080"] = self.alpha080(d)
        # Alpha#81-90
        results["alpha081"] = self.alpha081(d)
        results["alpha082"] = self.alpha082(d)
        results["alpha083"] = self.alpha083(d)
        results["alpha084"] = self.alpha084(d)
        results["alpha085"] = self.alpha085(d)
        results["alpha086"] = self.alpha086(d)
        results["alpha087"] = self.alpha087(d)
        results["alpha088"] = self.alpha088(d)
        results["alpha089"] = self.alpha089(d)
        results["alpha090"] = self.alpha090(d)
        # Alpha#91-101
        results["alpha091"] = self.alpha091(d)
        results["alpha092"] = self.alpha092(d)
        results["alpha093"] = self.alpha093(d)
        results["alpha094"] = self.alpha094(d)
        results["alpha095"] = self.alpha095(d)
        results["alpha096"] = self.alpha096(d)
        results["alpha097"] = self.alpha097(d)
        results["alpha098"] = self.alpha098(d)
        results["alpha099"] = self.alpha099(d)
        results["alpha100"] = self.alpha100(d)
        results["alpha101"] = self.alpha101(d)

        return results

    # ===== 因子实现 =====

    def alpha001(self, d):
        """Alpha#1: rank(ts_argmax(SignedPower(returns<0 ? stddev(returns,20) : close, 2), 5)) - 0.5"""
        cond = d["returns"] < 0
        inner = pd.Series(np.where(cond, stddev(d["returns"], 20), d["close"]), index=d["close"].index)
        return rank(ts_argmax(signedpower(inner, 2), 5)) - 0.5

    def alpha002(self, d):
        """Alpha#2: -1 * correlation(rank(delta(log(volume),2)), rank(((close-open)/open)), 6)"""
        return -1 * correlation(rank(delta(np.log(d["volume"]), 2)), rank((d["close"] - d["open"]) / d["open"]), 6)

    def alpha003(self, d):
        """Alpha#3: -1 * correlation(rank(open), rank(volume), 10)"""
        return -1 * correlation(rank(d["open"]), rank(d["volume"]), 10)

    def alpha004(self, d):
        """Alpha#4: -1 * ts_rank(rank(low), 9)"""
        return -1 * ts_rank(rank(d["low"]), 9)

    def alpha005(self, d):
        """Alpha#5: rank(open - sum(vwap,10)/10) * (-1 * abs(rank(close - vwap)))"""
        return rank(d["open"] - ts_sum(d["vwap"], 10) / 10) * (-1 * abs(rank(d["close"] - d["vwap"])))

    def alpha006(self, d):
        """Alpha#6: -1 * correlation(open, volume, 10)"""
        return -1 * correlation(d["open"], d["volume"], 10)

    def alpha007(self, d):
        """Alpha#7: (adv20 < volume ? ((-1*ts_rank(abs(delta(close,7)),60))*sign(delta(close,7))) : -1)"""
        adv20 = d["adv20"]
        cond = adv20 < d["volume"]
        return pd.Series(np.where(cond, (-1 * ts_rank(abs(delta(d["close"], 7)), 60)) * np.sign(delta(d["close"], 7)), -1), index=d["close"].index)

    def alpha008(self, d):
        """Alpha#8: -1 * rank(sum(open,5)*sum(returns,5) - delay(sum(open,5)*sum(returns,5),10))"""
        return -1 * rank(ts_sum(d["open"], 5) * ts_sum(d["returns"], 5) - delay(ts_sum(d["open"], 5) * ts_sum(d["returns"], 5), 10))

    def alpha009(self, d):
        """Alpha#9: ((0 < ts_min(delta(close,1),5)) ? delta(close,1) : ((ts_max(delta(close,1),5) < 0) ? delta(close,1) : (-1*delta(close,1))))"""
        delta_close = delta(d["close"], 1)
        cond1 = ts_min(delta_close, 5) > 0
        cond2 = ts_max(delta_close, 5) < 0
        return pd.Series(np.where(cond1, delta_close, np.where(cond2, delta_close, -1 * delta_close)), index=d["close"].index)

    def alpha010(self, d):
        """Alpha#10: rank(((0 < ts_min(delta(close,1),4)) ? delta(close,1) : ((ts_max(delta(close,1),4) < 0) ? delta(close,1) : (-1*delta(close,1)))))"""
        delta_close = delta(d["close"], 1)
        cond1 = ts_min(delta_close, 4) > 0
        cond2 = ts_max(delta_close, 4) < 0
        return rank(pd.Series(np.where(cond1, delta_close, np.where(cond2, delta_close, -1 * delta_close)), index=d["close"].index))

    def alpha011(self, d):
        """Alpha#11: ((ts_rank(1/n,3)*3) + (ts_rank(vwap,3)*3) + (ts_rank(volume,3)*3))"""
        return (ts_rank(1/d["close"], 3) * 3) + (ts_rank(d["vwap"], 3) * 3) + (ts_rank(d["volume"], 3) * 3)

    def alpha012(self, d):
        """Alpha#12: sign(delta(volume,1)) * (-1 * delta(close,1))"""
        return np.sign(delta(d["volume"], 1)) * (-1 * delta(d["close"], 1))

    def alpha013(self, d):
        """Alpha#13: -1 * rank(covariance(rank(close), rank(volume), 5))"""
        return -1 * rank(covariance(rank(d["close"]), rank(d["volume"]), 5))

    def alpha014(self, d):
        """Alpha#14: ((-1 * rank(delta(returns,3))) * correlation(open, volume, 10))"""
        return (-1 * rank(delta(d["returns"], 3))) * correlation(d["open"], d["volume"], 10)

    def alpha015(self, d):
        """Alpha#15: -1 * sum(rank(correlation(rank(high), rank(volume), 3)), 3)"""
        return -1 * ts_sum(rank(correlation(rank(d["high"]), rank(d["volume"]), 3)), 3)

    def alpha016(self, d):
        """Alpha#16: -1 * rank(covariance(rank(high), rank(volume), 5))"""
        return -1 * rank(covariance(rank(d["high"]), rank(d["volume"]), 5))

    def alpha017(self, d):
        """Alpha#17: ((-1*rank(ts_rank(close,10)))*rank(delta(delta(close,1),1))*rank(ts_rank(volume/(adv20),5)))"""
        return ((-1 * rank(ts_rank(d["close"], 10))) * rank(delta(delta(d["close"], 1), 1)) * rank(ts_rank(d["volume"] / d["adv20"], 5)))

    def alpha018(self, d):
        """Alpha#18: -1 * rank(((stddev(abs((close-open)),5) + (close-open)) + correlation(close,open,10)))"""
        return -1 * rank((stddev(abs(d["close"] - d["open"]), 5) + (d["close"] - d["open"])) + correlation(d["close"], d["open"], 10))

    def alpha019(self, d):
        """Alpha#19: ((-1*sign((close-delay(close,7)+delta(close,7))))*1+(rank(1+ts_rank(volume,2))))"""
        return ((-1 * np.sign((d["close"] - delay(d["close"], 7) + delta(d["close"], 7)))) * 1 + rank(1 + ts_rank(d["volume"], 2)))

    def alpha020(self, d):
        """Alpha#20: (((-1*rank(open-delay(open,1)))*(-1*rank(open-delay(open,1))))*(-1*rank(returns)))"""
        return (((-1 * rank(d["open"] - delay(d["open"], 1))) * (-1 * rank(d["open"] - delay(d["open"], 1)))) * (-1 * rank(d["returns"])))

    def alpha021(self, d):
        """Alpha#21: 0 < ts_mean(volume,5)*2 < ts_mean(volume,20) || volume == 0 ? -1 : 1"""
        return pd.Series(np.where((d["volume"] == 0) | ((ts_mean(d["volume"], 5) * 2) < ts_mean(d["volume"], 20)), -1, 1), index=d["close"].index)

    def alpha022(self, d):
        """Alpha#22: -1*(delta(correlation(close,volume,5),5)*rank(stddev(close,20)))"""
        return -1 * (delta(correlation(d["close"], d["volume"], 5), 5) * rank(stddev(d["close"], 20)))

    def alpha023(self, d):
        """Alpha#23: 0 < ts_mean(high,20) < high ? -1*delta(high,2) : 0"""
        return pd.Series(np.where((d["high"] > 0) & (ts_mean(d["high"], 20) < d["high"]), -1 * delta(d["high"], 2), 0), index=d["close"].index)

    def alpha024(self, d):
        """Alpha#24: -1 * delta(close,3)"""
        return -1 * delta(d["close"], 3)

    def alpha025(self, d):
        """Alpha#25: rank(((-1*returns)*adv20*vwap*(high-low))*1)"""
        return rank(((-1 * d["returns"]) * d["adv20"] * d["vwap"] * (d["high"] - d["low"])) * 1)

    def alpha026(self, d):
        """Alpha#26: (-1*ts_max(correlation(ts_rank(volume,5),ts_rank(high,5),5),3))"""
        return -1 * ts_max(correlation(ts_rank(d["volume"], 5), ts_rank(d["high"], 5), 5), 3)

    def alpha027(self, d):
        """Alpha#27: 0 < ts_mean(close,1)-ts_mean(close,4) ? 1 : 0"""
        return pd.Series(np.where(ts_mean(d["close"], 1) - ts_mean(d["close"], 4) > 0, 1, 0), index=d["close"].index)

    def alpha028(self, d):
        """Alpha#28: scale(correlation(adv20,low,5) + ((high+low)/2)-close)"""
        return scale(correlation(d["adv20"], d["low"], 5) + ((d["high"] + d["low"]) / 2) - d["close"])

    def alpha029(self, d):
        """Alpha#29: min(product(rank(rank(scale(log(ts_sum(ts_min(rank(rank(-1*rank(delta((close-1),5))),2),1),1))))),1)+5,1)"""
        inner = -1 * rank(delta(d["close"] - 1, 5))
        return ts_min(product(rank(rank(scale(np.log(ts_sum(ts_min(rank(rank(inner)), 2), 1))))), 1) + 5, 1)

    def alpha030(self, d):
        """Alpha#30: 1.0 - rank((sign(close-delay(close,1))+sign(delay(close,1)-delay(close,2))+sign(delay(close,2)-delay(close,3))))"""
        sign1 = np.sign(d["close"] - delay(d["close"], 1))
        sign2 = np.sign(delay(d["close"], 1) - delay(d["close"], 2))
        sign3 = np.sign(delay(d["close"], 2) - delay(d["close"], 3))
        return 1.0 - rank(sign1 + sign2 + sign3)

    def alpha031(self, d):
        """Alpha#31: ((rank(rank(rank(decay_linear((-1*rank(rank(delta(close,10)))),10))))+rank((-1*delta(close,3))))+sign(scale(correlation(adv20,low,12))))"""
        return ((rank(rank(rank(decay_linear((-1 * rank(rank(delta(d["close"], 10)))), 10))))) + rank((-1 * delta(d["close"], 3)))) + np.sign(scale(correlation(d["adv20"], d["low"], 12)))

    def alpha032(self, d):
        """Alpha#32: scale(((sum(close,7)/7)-close)+20*scale(correlation(vwap,delay(close,5),230)))"""
        return scale(((ts_sum(d["close"], 7) / 7) - d["close"]) + 20 * scale(correlation(d["vwap"], delay(d["close"], 5), 230)))

    def alpha033(self, d):
        """Alpha#33: rank(-1+((open/close)*1))"""
        return rank(-1 + ((d["open"] / d["close"]) * 1))

    def alpha034(self, d):
        """Alpha#34: rank(2-rank(stddev(returns,2)/stddev(returns,5))-rank(delta(close,1)))"""
        return rank(2 - rank(stddev(d["returns"], 2) / stddev(d["returns"], 5)) - rank(delta(d["close"], 1)))

    def alpha035(self, d):
        """Alpha#35: ((ts_rank(volume,32)*(1-ts_rank(((close+high)-low),16)))*(1-ts_rank(returns,32)))"""
        return ((ts_rank(d["volume"], 32) * (1 - ts_rank(((d["close"] + d["high"]) - d["low"]), 16))) * (1 - ts_rank(d["returns"], 32)))

    def alpha036(self, d):
        """Alpha#36: 1.0+(((2*rank(((ts_rank(delta(close,1),4)>0)?1:-1)))+1))*((2*rank(((ts_rank(delta(volume,1),4)>0)?1:-1)))+1)"""
        cond1 = ts_rank(delta(d["close"], 1), 4) > 0
        cond2 = ts_rank(delta(d["volume"], 1), 4) > 0
        val1 = rank(pd.Series(np.where(cond1, 1, -1), index=d["close"].index))
        val2 = rank(pd.Series(np.where(cond2, 1, -1), index=d["close"].index))
        return 1.0 + (((2 * val1) + 1)) * ((2 * val2) + 1)

    def alpha037(self, d):
        """Alpha#37: rank(((-1*returns)*adv20*vwap*(high-low))*1)"""
        return rank(((-1 * d["returns"]) * d["adv20"] * d["vwap"] * (d["high"] - d["low"])) * 1)

    def alpha038(self, d):
        """Alpha#38: ((-1*rank(ts_rank(close,10)))*rank((close/open)*1))"""
        return (-1 * rank(ts_rank(d["close"], 10))) * rank((d["close"] / d["open"]) * 1)

    def alpha039(self, d):
        """Alpha#39: (-1*rank(ts_rank(delta(close,7),4)))+1"""
        return (-1 * rank(ts_rank(delta(d["close"], 7), 4))) + 1

    def alpha040(self, d):
        """Alpha#40: ((-1*rank(stddev(high,10)))*correlation(high,volume,10))*1"""
        return ((-1 * rank(stddev(d["high"], 10))) * correlation(d["high"], d["volume"], 10)) * 1

    def alpha041(self, d):
        """Alpha#41: (((high*low)**0.5)-vwap)"""
        return (((d["high"] * d["low"]) ** 0.5) - d["vwap"])

    def alpha042(self, d):
        """Alpha#42: rank((vwap-close)/((vwap+close)/2))*1"""
        return rank((d["vwap"] - d["close"]) / ((d["vwap"] + d["close"]) / 2)) * 1

    def alpha043(self, d):
        """Alpha#43: ts_rank(volume/adv20,20)*ts_rank(-1*delta(close,7),8)"""
        return ts_rank(d["volume"] / d["adv20"], 20) * ts_rank(-1 * delta(d["close"], 7), 8)

    def alpha044(self, d):
        """Alpha#44: -1*correlation(high, ts_rank(volume,5), 5)"""
        return -1 * correlation(d["high"], ts_rank(d["volume"], 5), 5)

    def alpha045(self, d):
        """Alpha#45: -1*rank(ts_sum(delay(close,5),20/20)*correlation(close,volume,2)*correlation(ts_sum(close,5),ts_sum(close,20),2))"""
        return -1 * rank(ts_sum(delay(d["close"], 5), 20) / 20 * correlation(d["close"], d["volume"], 2) * correlation(ts_sum(d["close"], 5), ts_sum(d["close"], 20), 2))

    def alpha046(self, d):
        """Alpha#46: ((ts_mean(close,3)+ts_mean(close,6)+ts_mean(close,12)+ts_mean(close,24))/4)*(1/(abs(close-ts_mean(close,12))/(ts_mean(close,12)+0.001)))"""
        mean3 = ts_mean(d["close"], 3)
        mean6 = ts_mean(d["close"], 6)
        mean12 = ts_mean(d["close"], 12)
        mean24 = ts_mean(d["close"], 24)
        return ((mean3 + mean6 + mean12 + mean24) / 4) * (1 / (abs(d["close"] - mean12) / (mean12 + 0.001)))

    def alpha047(self, d):
        """Alpha#47: ((rank((1/close))*volume)/adv20)*((high*rank((high-close)/(close-low))) - rank((low-close)/(close-low)))"""
        return ((rank(1 / d["close"]) * d["volume"]) / d["adv20"]) * ((d["high"] * rank((d["high"] - d["close"]) / (d["close"] - d["low"]))) - rank((d["low"] - d["close"]) / (d["close"] - d["low"])))

    def alpha048(self, d):
        """Alpha#48: (correlation(delta(close,1), delta(delay(close,1),1), 25) / (stddev(delta(close,1),25) / stddev(delta(delay(close,1),1),25)))"""
        return (correlation(delta(d["close"], 1), delta(delay(d["close"], 1), 1), 25) / (stddev(delta(d["close"], 1), 25) / stddev(delta(delay(d["close"], 1), 1), 25)))

    def alpha049(self, d):
        """Alpha#49: sum(((high+low)>delay(close,1) ? 1 : 0)*1, 6)"""
        cond = (d["high"] + d["low"]) > delay(d["close"], 1)
        return ts_sum(pd.Series(np.where(cond, 1, 0), index=d["close"].index) * 1, 6)

    def alpha050(self, d):
        """Alpha#50: sum(((high+low)<delay(close,1) ? 1 : 0)*1, 6)"""
        cond = (d["high"] + d["low"]) < delay(d["close"], 1)
        return ts_sum(pd.Series(np.where(cond, 1, 0), index=d["close"].index) * 1, 6)

    def alpha051(self, d):
        """Alpha#51: sum(((high+low)==delay(close,1) ? 1 : 0)*1, 6)"""
        cond = (d["high"] + d["low"]) == delay(d["close"], 1)
        return ts_sum(pd.Series(np.where(cond, 1, 0), index=d["close"].index) * 1, 6)

    def alpha052(self, d):
        """Alpha#52: sum(max(0, ts_max(high,2)-delay(close,2)), 20) / sum(max(0, delay(close,2)-ts_min(low,2)), 20)"""
        numerator = ts_sum(np.maximum(0, ts_max(d["high"], 2) - delay(d["close"], 2)), 20)
        denominator = ts_sum(np.maximum(0, delay(d["close"], 2) - ts_min(d["low"], 2)), 20)
        return numerator / (denominator + 1e-10)

    def alpha053(self, d):
        """Alpha#53: count((close>delay(close,1) ? 1 : -1), 12)"""
        cond = d["close"] > delay(d["close"], 1)
        return ts_sum(pd.Series(np.where(cond, 1, -1), index=d["close"].index), 12)

    def alpha054(self, d):
        """Alpha#54: ((-1*rank(low))*correlation(adv20,close,5))+((-1*((close-low)*1)/(high-low+0.001)))"""
        return ((-1 * rank(d["low"])) * correlation(d["adv20"], d["close"], 5)) + (-1 * ((d["close"] - d["low"]) * 1) / (d["high"] - d["low"] + 0.001))

    def alpha055(self, d):
        """Alpha#55: sum((close>ts_mean(close,5) ? stddev(close,5)*1 : 0)*1, 12)"""
        cond = d["close"] > ts_mean(d["close"], 5)
        return ts_sum(pd.Series(np.where(cond, stddev(d["close"], 5) * 1, 0), index=d["close"].index) * 1, 12)

    def alpha056(self, d):
        """Alpha#56: (rank((open-ts_min(low,12)))*1)/(rank(ts_max(high,12)-open)*1)"""
        return (rank(d["open"] - ts_min(d["low"], 12)) * 1) / (rank(ts_max(d["high"], 12) - d["open"]) * 1 + 1e-10)

    def alpha057(self, d):
        """Alpha#57: -1 * ((close-vwap)/decay_linear(rank(ts_argmax(close,30)),2))"""
        return -1 * ((d["close"] - d["vwap"]) / (decay_linear(rank(ts_argmax(d["close"], 30)), 2) + 1e-10))

    def alpha058(self, d):
        """Alpha#58: -1*ts_rank(decay_linear(correlation(adv20,vwap,5),2),5)"""
        return -1 * ts_rank(decay_linear(correlation(d["adv20"], d["vwap"], 5), 2), 5)

    def alpha059(self, d):
        """Alpha#59: -1 * rank(ts_min(close,2))"""
        return -1 * rank(ts_min(d["close"], 2))

    def alpha060(self, d):
        """Alpha#60: (0 < scale(((rank(ts_max(open,30))*2)-rank(ts_min(open,30))))*1 ? 1 : -1)"""
        return pd.Series(np.where(scale(((rank(ts_max(d["open"], 30)) * 2) - rank(ts_min(d["open"], 30)))) * 1 > 0, 1, -1), index=d["close"].index)

    def alpha061(self, d):
        """Alpha#61: (rank((vwap-ts_max(vwap,16)))<(rank(correlation(vwap,ts_mean(volume,180),5)))) ? 1 : -1"""
        return pd.Series(np.where(rank(d["vwap"] - ts_max(d["vwap"], 16)) < rank(correlation(d["vwap"], ts_mean(d["volume"], 180), 5)), 1, -1), index=d["close"].index)

    def alpha062(self, d):
        """Alpha#62: ((rank(correlation(vwap,ts_mean(volume,20),6))<rank((rank(open)*1)+rank(open*1)+rank((open+close)/2)))) ? 1 : -1)"""
        cond = rank(correlation(d["vwap"], ts_mean(d["volume"], 20), 6)) < rank((rank(d["open"]) * 1) + rank(d["open"] * 1) + rank((d["open"] + d["close"]) / 2))
        return pd.Series(np.where(cond, 1, -1), index=d["close"].index)

    def alpha063(self, d):
        """Alpha#63: ((rank(decay_linear(delta(d["vwap"],5),10))<rank(((low*0.7)+vwap*0.3))) ? 1 : -1)"""
        return pd.Series(np.where(rank(decay_linear(delta(d["vwap"], 5), 10)) < rank(((d["low"] * 0.7) + d["vwap"] * 0.3)), 1, -1), index=d["close"].index)

    def alpha064(self, d):
        """Alpha#64: ((rank(correlation(ts_sum(((open*0.25)+(low*0.75)),4),ts_sum(adv20,4),5))>0.25) ? 1 : -1)"""
        return pd.Series(np.where(rank(correlation(ts_sum(((d["open"] * 0.25) + (d["low"] * 0.75)), 4), ts_sum(d["adv20"], 4), 5)) > 0.25, 1, -1), index=d["close"].index)

    def alpha065(self, d):
        """Alpha#65: ((rank(correlation(((open*0.25)+(low*0.75)),ts_mean(volume,10),5))>0) ? 1 : -1)"""
        return pd.Series(np.where(rank(correlation(((d["open"] * 0.25) + (d["low"] * 0.75)), ts_mean(d["volume"], 10), 5)) > 0, 1, -1), index=d["close"].index)

    def alpha066(self, d):
        """Alpha#66: ((rank(decay_linear(delta(vwap,4),5)))<rank(decay_linear(correlation(vwap,ts_mean(volume,50),10),5))) ? 1 : -1)"""
        return pd.Series(np.where(rank(decay_linear(delta(d["vwap"], 4), 5)) < rank(decay_linear(correlation(d["vwap"], ts_mean(d["volume"], 50), 10), 5)), 1, -1), index=d["close"].index)

    def alpha067(self, d):
        """Alpha#67: ((rank(ts_max(delta(close,2),4))*1)<rank(correlation(vwap,ts_mean(volume,120),5))) ? 1 : -1)"""
        return pd.Series(np.where((rank(ts_max(delta(d["close"], 2), 4)) * 1) < rank(correlation(d["vwap"], ts_mean(d["volume"], 120), 5)), 1, -1), index=d["close"].index)

    def alpha068(self, d):
        """Alpha#68: ((2-rank(ts_rank(close,5)))*1)<((1+1)*rank(correlation(adv20,close,10))) ? 1 : -1)"""
        return pd.Series(np.where(((2 - rank(ts_rank(d["close"], 5))) * 1) < ((1 + 1) * rank(correlation(d["adv20"], d["close"], 10))), 1, -1), index=d["close"].index)

    def alpha069(self, d):
        """Alpha#69: (rank(ts_rank(ts_mean(volume,10),5))*rank(delta(close,1)))*1<0 ? 1 : -1"""
        return pd.Series(np.where((rank(ts_rank(ts_mean(d["volume"], 10), 5)) * rank(delta(d["close"], 1))) * 1 < 0, 1, -1), index=d["close"].index)

    def alpha070(self, d):
        """Alpha#70: ((rank(delta(close,1))<0) ? 1 : (rank(delta(close,1))>0) ? -1 : 0)*1"""
        dc = rank(delta(d["close"], 1))
        return pd.Series(np.where(dc < 0, 1, np.where(dc > 0, -1, 0)) * 1, index=d["close"].index)

    def alpha071(self, d):
        """Alpha#71: 1-rank(((0.3*sum(((close-low)*1)/(high-low+0.001),20))*1))-rank((0.3*sum(((close-low)*1)/(high-low+0.001),20))*1)"""
        return 1 - rank((0.3 * ts_sum(((d["close"] - d["low"]) * 1) / (d["high"] - d["low"] + 0.001), 20)) * 1) - rank((0.3 * ts_sum(((d["close"] - d["low"]) * 1) / (d["high"] - d["low"] + 0.001), 20)) * 1)

    def alpha072(self, d):
        """Alpha#72: rank(decay_linear(correlation(((high+low)/2),ts_mean(volume,40),9),10))/rank(decay_linear(correlation(rank(vwap),rank(volume),7),3))"""
        return rank(decay_linear(correlation(((d["high"] + d["low"]) / 2), ts_mean(d["volume"], 40), 9), 10)) / (rank(decay_linear(correlation(rank(d["vwap"]), rank(d["volume"]), 7), 3)) + 1e-10)

    def alpha073(self, d):
        """Alpha#73: rank(decay_linear(delta(vwap,5),3))+rank(decay_linear(correlation(ts_mean(volume,10),ts_mean(volume,30),10),10))"""
        return rank(decay_linear(delta(d["vwap"], 5), 3)) + rank(decay_linear(correlation(ts_mean(d["volume"], 10), ts_mean(d["volume"], 30), 10), 10))

    def alpha074(self, d):
        """Alpha#74: ((rank(correlation(close,ts_sum(ts_mean(volume,30),37),15))<rank(correlation(rank(((high*0.1)+(vwap*0.9))),rank(volume),11))) ? 1 : -1)"""
        return pd.Series(np.where(rank(correlation(d["close"], ts_sum(ts_mean(d["volume"], 30), 37), 15)) < rank(correlation(rank(((d["high"] * 0.1) + (d["vwap"] * 0.9))), rank(d["volume"]), 11)), 1, -1), index=d["close"].index)

    def alpha075(self, d):
        """Alpha#75: rank(decay_linear(correlation(delta(close,1),delta(delay(close,1),1),12),6))<rank(decay_linear(correlation(vwap,ts_mean(volume,80),7),4)) ? 1 : -1"""
        return pd.Series(np.where(rank(decay_linear(correlation(delta(d["close"], 1), delta(delay(d["close"], 1), 1), 12), 6)) < rank(decay_linear(correlation(d["vwap"], ts_mean(d["volume"], 80), 7), 4)), 1, -1), index=d["close"].index)

    def alpha076(self, d):
        """Alpha#76: rank(decay_linear(delta(vwap,3),6))*1"""
        return rank(decay_linear(delta(d["vwap"], 3), 6)) * 1

    def alpha077(self, d):
        """Alpha#77: rank(decay_linear(((((high-low)/(ts_sum(close,5)/5))*volume)-(((high-low)/(ts_sum(close,5)/5))*ts_mean(volume,5))),11))"""
        return rank(decay_linear(((((d["high"] - d["low"]) / (ts_sum(d["close"], 5) / 5)) * d["volume"]) - (((d["high"] - d["low"]) / (ts_sum(d["close"], 5) / 5)) * ts_mean(d["volume"], 5))), 11))

    def alpha078(self, d):
        """Alpha#78: ((rank(decay_linear(correlation(ts_mean(close,7),ts_mean(adv20,7),5),3))*1)<0) ? 1 : ((rank(decay_linear(correlation(ts_mean(close,7),ts_mean(adv20,7),5),3))*1)*1)"""
        val = rank(decay_linear(correlation(ts_mean(d["close"], 7), ts_mean(d["adv20"], 7), 5), 3)) * 1
        return pd.Series(np.where(val < 0, 1, val * 1), index=d["close"].index)

    def alpha079(self, d):
        """Alpha#79: (rank(delta(decay_linear(correlation(((open*1)*1),adv20,3),5),5))*1)>0 ? 1 : -1"""
        return pd.Series(np.where((rank(delta(decay_linear(correlation((d["open"] * 1) * 1, d["adv20"], 3), 5), 5)) * 1) > 0, 1, -1), index=d["close"].index)

    def alpha080(self, d):
        """Alpha#80: ((rank(ts_sum(sign(sign(correlation(vwap,ts_mean(volume,10),5))*sign(delta(close,1))),5))-ts_sum(sign(sign(correlation(vwap,ts_mean(volume,10),5))*sign(delta(close,1))),5))*1<4) ? -1 : 1)"""
        inner = np.sign(np.sign(correlation(d["vwap"], ts_mean(d["volume"], 10), 5)) * np.sign(delta(d["close"], 1)))
        s = ts_sum(inner, 5)
        return pd.Series(np.where((rank(s) - s) * 1 < 4, -1, 1), index=d["close"].index)

    def alpha081(self, d):
        """Alpha#81: ((rank(log(product(rank((rank(correlation(vwap,ts_sum(ts_mean(volume,10),50),12))*1))*1),1)))*1)<rank(correlation(rank(vwap),rank(volume),1)) ? 1 : -1"""
        return pd.Series(np.where(((rank(np.log(product(rank((rank(correlation(d["vwap"], ts_sum(ts_mean(d["volume"], 10), 50), 12) * 1)) * 1), 1)))) * 1) < rank(correlation(rank(d["vwap"]), rank(d["volume"]), 1)), 1, -1), index=d["close"].index)

    def alpha082(self, d):
        """Alpha#82: (rank(decay_linear(delta(close,1),5))*1)<1 ? 1 : -1"""
        return pd.Series(np.where((rank(decay_linear(delta(d["close"], 1), 5)) * 1) < 1, 1, -1), index=d["close"].index)

    def alpha083(self, d):
        """Alpha#83: ((rank(delay(((high-low)/ts_sum(close,5)/5)*1,5))*1)<0) ? 1 : (-1*rank(delay(((high-low)/ts_sum(close,5)/5)*1,5))*1)"""
        val = rank(delay(((d["high"] - d["low"]) / (ts_sum(d["close"], 5) / 5)) * 1, 5)) * 1
        return pd.Series(np.where(val < 0, 1, -1 * val), index=d["close"].index)

    def alpha084(self, d):
        """Alpha#84: signedpower(ts_rank(vwap/ts_max(vwap,15),21),delta(close,5))"""
        return signedpower(ts_rank(d["vwap"] / ts_max(d["vwap"], 15), 21), delta(d["close"], 5))

    def alpha085(self, d):
        """Alpha#85: (rank(correlation(((high*0.9)+(close*0.1)),adv20,6))*1)<0 ? 1 : -1"""
        return pd.Series(np.where((rank(correlation(((d["high"] * 0.9) + (d["close"] * 0.1)), d["adv20"], 6)) * 1) < 0, 1, -1), index=d["close"].index)

    def alpha086(self, d):
        """Alpha#86: ((rank(ts_mean(delay(close,5),20))*1)<0) ? 1 : (0-(rank(ts_mean(delay(close,5),20))*1))"""
        val = rank(ts_mean(delay(d["close"], 5), 20)) * 1
        return pd.Series(np.where(val < 0, 1, 0 - val), index=d["close"].index)

    def alpha087(self, d):
        """Alpha#87: (rank(decay_linear(delta(vwap,4),5))*1)<0 ? 1 : -1"""
        return pd.Series(np.where((rank(decay_linear(delta(d["vwap"], 4), 5)) * 1) < 0, 1, -1), index=d["close"].index)

    def alpha088(self, d):
        """Alpha#88: (rank(decay_linear(((rank(open)+rank(low))-(rank(high)+rank(close))),8))*1)<0 ? 1 : -1"""
        return pd.Series(np.where((rank(decay_linear(((rank(d["open"]) + rank(d["low"])) - (rank(d["high"]) + rank(d["close"]))), 8)) * 1) < 0, 1, -1), index=d["close"].index)

    def alpha089(self, d):
        """Alpha#89: (rank(decay_linear(correlation(delta(close,1)*1,open,10),4))*1)<0 ? 1 : -1"""
        return pd.Series(np.where((rank(decay_linear(correlation(delta(d["close"], 1) * 1, d["open"], 10), 4)) * 1) < 0, 1, -1), index=d["close"].index)

    def alpha090(self, d):
        """Alpha#90: (rank(decay_linear(correlation(((rank(close)*1)+rank(low)),ts_mean(volume,6),7),4))*1)<0 ? 1 : -1"""
        return pd.Series(np.where((rank(decay_linear(correlation(((rank(d["close"]) * 1) + rank(d["low"])), ts_mean(d["volume"], 6), 7), 4)) * 1) < 0, 1, -1), index=d["close"].index)

    def alpha091(self, d):
        """Alpha#91: ((rank(ts_min(close,2))*1)<((ts_min(rank(correlation(rank(vwap),rank(volume),5)),5))*1)) ? 1 : -1"""
        return pd.Series(np.where((rank(ts_min(d["close"], 2)) * 1) < ((ts_min(rank(correlation(rank(d["vwap"]), rank(d["volume"]), 5)), 5)) * 1), 1, -1), index=d["close"].index)

    def alpha092(self, d):
        """Alpha#92: (ts_max(rank(decay_linear(delta(((close*0.35)+(vwap*0.65)),2),3)),5)<0) ? 1 : -1"""
        return pd.Series(np.where(ts_max(rank(decay_linear(delta(((d["close"] * 0.35) + (d["vwap"] * 0.65)), 2), 3)), 5) < 0, 1, -1), index=d["close"].index)

    def alpha093(self, d):
        """Alpha#93: (ts_max(rank(decay_linear(delta(((close*0.35)+(vwap*0.65)),2),3)),5)<0) ? 1 : -1"""
        return pd.Series(np.where(ts_max(rank(decay_linear(delta(((d["close"] * 0.35) + (d["vwap"] * 0.65)), 2), 3)), 5) < 0, 1, -1), index=d["close"].index)

    def alpha094(self, d):
        """Alpha#94: ((rank(ts_rank(ts_mean(close,8),13))-rank(ts_rank(ts_mean(close,8),13)))*1<0) ? 1 : -1"""
        return pd.Series(np.where((rank(ts_rank(ts_mean(d["close"], 8), 13)) - rank(ts_rank(ts_mean(d["close"], 8), 13))) * 1 < 0, 1, -1), index=d["close"].index)

    def alpha095(self, d):
        """Alpha#95: (rank(decay_linear(correlation(vwap,ts_mean(volume,50),12),7))*1<0) ? 1 : -1"""
        return pd.Series(np.where((rank(decay_linear(correlation(d["vwap"], ts_mean(d["volume"], 50), 12), 7)) * 1) < 0, 1, -1), index=d["close"].index)

    def alpha096(self, d):
        """Alpha#96: (rank(decay_linear(delta(close,2),5))*1<0) ? 1 : -1"""
        return pd.Series(np.where((rank(decay_linear(delta(d["close"], 2), 5)) * 1) < 0, 1, -1), index=d["close"].index)

    def alpha097(self, d):
        """Alpha#97: (rank(decay_linear(delta(vwap,3),5))*1<0) ? 1 : -1"""
        return pd.Series(np.where((rank(decay_linear(delta(d["vwap"], 3), 5)) * 1) < 0, 1, -1), index=d["close"].index)

    def alpha098(self, d):
        """Alpha#98: ((rank(decay_linear(((high+low)/2+vwap)-close,5))*1)<0) ? 1 : -1"""
        return pd.Series(np.where((rank(decay_linear(((d["high"] + d["low"]) / 2 + d["vwap"]) - d["close"], 5)) * 1) < 0, 1, -1), index=d["close"].index)

    def alpha099(self, d):
        """Alpha#99: (rank(decay_linear(delta(close,2),5))*1<0) ? 1 : -1"""
        return pd.Series(np.where((rank(decay_linear(delta(d["close"], 2), 5)) * 1) < 0, 1, -1), index=d["close"].index)

    def alpha100(self, d):
        """Alpha#100: rank(scale(((0 < ts_min(delta(close,1),4)) ? delta(close,1) : ((ts_max(delta(close,1),4) < 0) ? delta(close,1) : (-1*delta(close,1))))))"""
        delta_close = delta(d["close"], 1)
        cond1 = ts_min(delta_close, 4) > 0
        cond2 = ts_max(delta_close, 4) < 0
        val = pd.Series(np.where(cond1, delta_close, np.where(cond2, delta_close, -1 * delta_close)), index=d["close"].index)
        return rank(scale(val))

    def alpha101(self, d):
        """Alpha#101: ((close-open)/((high-low)+0.001))"""
        return (d["close"] - d["open"]) / ((d["high"] - d["low"]) + 0.001)


def ts_mean(series, window):
    """滚动均值"""
    if isinstance(series, pd.Series):
        return series.rolling(window).mean()
    return pd.Series(series).rolling(window).mean()


if __name__ == "__main__":
    print("Alpha101 因子库")
    print(f"因子数量: 101")
    print("\n核心算子:")
    print("  rank, ts_rank, delta, delay, correlation, covariance")
    print("  stddev, ts_sum, ts_max, ts_min, ts_argmax, ts_argmin")
    print("  scale, signedpower, product, decay_linear")
    print("\n使用方法:")
    print("  from alpha101 import Alpha101")
    print("  alpha = Alpha101()")
    print("  factors = alpha.compute(df)  # df需要包含 Open, High, Low, Close, Volume, VWAP")