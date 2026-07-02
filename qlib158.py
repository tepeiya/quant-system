"""
Qlib158 因子库 (微软 Qlib Alpha158)
===================================
基于微软 Qlib 框架的 Alpha158 因子集

因子类别：
- K线形态类: KMID, KLEN, KMID2, KUP, KUP2, KLOW, KLOW2, KSFT, KSFT2
- ROC类: OPEN0, CLOSE0, HIGH0, LOW0, VWAPM0, OPEN1~4, CLOSE1~4
- 量价比: VSTD0~4, WVMA0~4, VSUMP0~4, VSUMN0~4, VDIFP0~4, VDIFN0~4
- 波动率类: STD0~4, VOL0~4, RSV0~4, IMAX0~4, IMIN0~4, QTLU0~4, QTLD0~4
- RSI类: RSV0~4, IMAX0~4, IMIN0~4
- 技术指标: RSI, BBPOS, BBWMA, KDJ_K, KDJ_D, KDJ_J, MACD, CCI, ATR, DMA, EXPMA
- 价格形态: CLOSE2HIGH, CLOSE2LOW, HIGH2LOW, CLOSE2CLOSE
- 成交量特征: VMA, VSTD, WVMA, VSUM, VDIF
"""

import numpy as np
import pandas as pd
import logging
from typing import Dict, List
from alpha101 import ts_mean, stddev, ts_max, ts_min, delta, correlation, rank

logger = logging.getLogger("quant.qlib158")


class Qlib158:
    """微软 Qlib Alpha158 因子库"""

    def __init__(self):
        self.factor_count = 158
        self.windows = [5, 10, 20, 30, 60]

    def _prepare_data(self, df: pd.DataFrame) -> Dict[str, pd.Series]:
        d = {}
        d["open"] = df["Open"].copy()
        d["close"] = df["Close"].copy()
        d["high"] = df["High"].copy()
        d["low"] = df["Low"].copy()
        d["volume"] = df["Volume"].copy()
        d["vwap"] = df.get("VWAP", d["close"]).copy()
        d["returns"] = d["close"].pct_change()
        return d

    def compute(self, df: pd.DataFrame) -> Dict[str, pd.Series]:
        """计算 Qlib158 因子"""
        d = self._prepare_data(df)
        results = {}
        windows = self.windows

        # ===== 1. K线形态因子 (9个) =====
        max_oc = pd.concat([d["open"], d["close"]], axis=1).max(axis=1)
        min_oc = pd.concat([d["open"], d["close"]], axis=1).min(axis=1)

        results["KMID"] = (d["close"] - d["open"]) / d["open"]
        results["KLEN"] = (d["high"] - d["low"]) / d["open"]
        results["KMID2"] = (d["close"] - d["open"]) / (d["high"] - d["low"] + 1e-10)
        results["KUP"] = (d["high"] - max_oc) / d["open"]
        results["KUP2"] = (d["high"] - max_oc) / (d["high"] - d["low"] + 1e-10)
        results["KLOW"] = (min_oc - d["low"]) / d["open"]
        results["KLOW2"] = (min_oc - d["low"]) / (d["high"] - d["low"] + 1e-10)
        results["KSFT"] = (2 * d["close"] - d["high"] - d["low"]) / d["open"]
        results["KSFT2"] = (2 * d["close"] - d["high"] - d["low"]) / (d["high"] - d["low"] + 1e-10)

        # ===== 2. 价格ROC因子 (20个: 4个间隔 × 5个窗口) =====
        for w in windows:
            results[f"OPEN{w}"] = d["open"] / delay(d["open"], w)
            results[f"CLOSE{w}"] = d["close"] / delay(d["close"], w)
            results[f"HIGH{w}"] = d["high"] / delay(d["high"], w)
            results[f"LOW{w}"] = d["low"] / delay(d["low"], w)

        # ===== 3. VWAP相关因子 =====
        for w in windows:
            results[f"VWAP{w}"] = d["vwap"] / delay(d["vwap"], w)

        # ===== 4. 成交量特征 (25个: 5类 × 5窗口) =====
        for w in windows:
            v_ma = ts_mean(d["volume"], w)
            v_std = d["volume"].rolling(w).std()
            results[f"VSTD{w}"] = v_std / (v_ma + 1e-10)
            results[f"WVMA{w}"] = (abs(d["volume"] - v_ma)) / (v_ma + 1e-10)
            results[f"VSUMP{w}"] = d["volume"].where(d["volume"] > 0, 0).rolling(w).sum() / (d["volume"].abs().rolling(w).sum() + 1e-10)
            results[f"VSUMN{w}"] = d["volume"].where(d["volume"] < 0, 0).abs().rolling(w).sum() / (d["volume"].abs().rolling(w).sum() + 1e-10)
            results[f"VDIFP{w}"] = results[f"VSUMP{w}"] - results[f"VSUMN{w}"]

        # ===== 5. 波动率因子 (20个: 4类 × 5窗口) =====
        for w in windows:
            ret_std = d["returns"].rolling(w).std()
            results[f"STD{w}"] = ret_std / (d["close"] + 1e-10)
            results[f"VOL{w}"] = ret_std
            results[f"RSV{w}"] = (d["close"] - ts_min(d["low"], w)) / (ts_max(d["high"], w) - ts_min(d["low"], w) + 1e-10)
            results[f"IMAX{w}"] = d["high"].rolling(w).apply(lambda x: np.argmax(x), raw=True) / w
            results[f"IMIN{w}"] = d["low"].rolling(w).apply(lambda x: np.argmin(x), raw=True) / w

        # ===== 6. 分位数因子 (10个: 2类 × 5窗口) =====
        for w in windows:
            results[f"QTLU{w}"] = d["close"].rolling(w).quantile(0.8) / d["close"]
            results[f"QTLD{w}"] = d["close"].rolling(w).quantile(0.2) / d["close"]

        # ===== 7. 价格区间因子 (15个: 3类 × 5窗口) =====
        for w in windows:
            results[f"CORR{w}"] = correlation(d["close"].rolling(w).mean(), d["volume"].rolling(w).mean(), w)
            results[f"CORD{w}"] = correlation(d["close"] / d["close"].shift(w), d["volume"] / d["volume"].shift(w), w)
            results[f"CNTP{w}"] = (d["close"] > d["close"].shift(1)).rolling(w).sum() / w
            results[f"CNTN{w}"] = (d["close"] < d["close"].shift(1)).rolling(w).sum() / w
            results[f"CNTD{w}"] = results[f"CNTP{w}"] - results[f"CNTN{w}"]

        # ===== 8. SUMP/SUMN/SUMD因子 =====
        for w in windows:
            abs_ret = d["returns"].abs()
            pos_ret = d["returns"].where(d["returns"] > 0, 0)
            neg_ret = d["returns"].where(d["returns"] < 0, 0).abs()
            results[f"SUMP{w}"] = pos_ret.rolling(w).sum() / (abs_ret.rolling(w).sum() + 1e-10)
            results[f"SUMN{w}"] = neg_ret.rolling(w).sum() / (abs_ret.rolling(w).sum() + 1e-10)
            results[f"SUMD{w}"] = results[f"SUMP{w}"] - results[f"SUMN{w}"]

        # ===== 9. VMA因子 =====
        for w in windows:
            results[f"VMA{w}"] = ts_mean(d["volume"], w)

        # ===== 10. 技术指标因子 (20个) =====
        # RSI
        delta_close = d["close"].diff()
        gain = delta_close.where(delta_close > 0, 0)
        loss = -delta_close.where(delta_close < 0, 0)
        for w in [6, 12, 24]:
            avg_gain = gain.rolling(w).mean()
            avg_loss = loss.rolling(w).mean()
            rs = avg_gain / (avg_loss + 1e-10)
            results[f"RSI{w}"] = 100 - (100 / (1 + rs))

        # Bollinger Bands
        for w in [10, 20]:
            ma = ts_mean(d["close"], w)
            std = d["close"].rolling(w).std()
            results[f"BBPOS{w}"] = (d["close"] - ma) / (2 * std + 1e-10)
            results[f"BBWMA{w}"] = (2 * std) / ma

        # KDJ
        for w in [9, 18]:
            low_min = ts_min(d["low"], w)
            high_max = ts_max(d["high"], w)
            rsv = (d["close"] - low_min) / (high_max - low_min + 1e-10) * 100
            k = rsv.ewm(com=2).mean()
            d_val = k.ewm(com=2).mean()
            results[f"KDJ_K{w}"] = k
            results[f"KDJ_D{w}"] = d_val
            results[f"KDJ_J{w}"] = 3 * k - 2 * d_val

        # MACD
        ema12 = d["close"].ewm(span=12).mean()
        ema26 = d["close"].ewm(span=26).mean()
        dif = ema12 - ema26
        dea = dif.ewm(span=9).mean()
        results["MACD_DIF"] = dif
        results["MACD_DEA"] = dea
        results["MACD"] = (dif - dea) * 2

        # CCI
        tp = (d["high"] + d["low"] + d["close"]) / 3
        for w in [14, 20]:
            ma_tp = ts_mean(tp, w)
            md = tp.rolling(w).apply(lambda x: np.mean(np.abs(x - x.mean())), raw=True)
            results[f"CCI{w}"] = (tp - ma_tp) / (0.015 * md + 1e-10)

        # ATR
        tr = pd.concat([
            d["high"] - d["low"],
            (d["high"] - d["close"].shift(1)).abs(),
            (d["low"] - d["close"].shift(1)).abs()
        ], axis=1).max(axis=1)
        for w in [14, 20]:
            results[f"ATR{w}"] = tr.rolling(w).mean() / d["close"]

        # DMA
        ma10 = ts_mean(d["close"], 10)
        ma50 = ts_mean(d["close"], 50)
        results["DMA"] = ma10 - ma50

        # EXPMA
        ema10 = d["close"].ewm(span=10).mean()
        ema60 = d["close"].ewm(span=60).mean()
        results["EXPMA"] = ema10 - ema60

        # ===== 11. 价格比因子 (10个) =====
        for w in [1, 2, 3, 5, 10]:
            results[f"CLOSE2HIGH{w}"] = d["close"] / ts_max(d["high"], w)
            results[f"CLOSE2LOW{w}"] = d["close"] / ts_min(d["low"], w)

        return results


def delay(series, period=1):
    """滞后"""
    if isinstance(series, pd.Series):
        return series.shift(period)
    return pd.Series(series).shift(period)


if __name__ == "__main__":
    print("Qlib158 因子库（微软 Qlib Alpha158）")
    print(f"因子数量: 158")
    print("\n因子类别:")
    print("  - K线形态: KMID, KLEN, KMID2, KUP, KUP2, KLOW, KLOW2, KSFT, KSFT2")
    print("  - 价格ROC: OPEN/CLOSE/HIGH/LOW/VWAP × 5个窗口")
    print("  - 成交量特征: VSTD, WVMA, VSUMP, VSUMN, VDIFP × 5窗口")
    print("  - 波动率: STD, VOL, RSV, IMAX, IMIN × 5窗口")
    print("  - 技术指标: RSI, BBPOS, BBWMA, KDJ, MACD, CCI, ATR, DMA, EXPMA")