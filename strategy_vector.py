"""
向量化策略引擎 - 全S&P 500 (含质量因子)
================================
基于 v3.1 已验证逻辑 + 质量因子的纯NumPy实现。

质量因子（来自 quality_factor.py）：
- ATR稳定性 0-10
- 年度正收益 0-15
- 回撤控制 0-15
合计 0-40，选股时归一化到 0-25 分

其他逻辑同v3.1：
- 大盘趋势过滤（SPY SMA20>SMA50>SMA200 + RSI<75）
- 动量排名（12-1月动量前30%）
- ATR波动率仓位
- 子行业集中度
- 止损15%/移动止损12%/RSI>88退出
- 大盘过热减仓25%
"""

import numpy as np
import pandas as pd
import logging
import os, json
from datetime import datetime
from system_config import load as load_config

logger = logging.getLogger("quant.vector")

# 半导体行业股票（用于子行业集中度控制）
SEMI = {
    "AMD", "INTC", "NVDA", "AVGO", "QCOM", "TXN", "ASML", "AMAT",
    "KLAC", "LRCX", "MU", "MRVL", "NXPI", "MCHP", "STM", "ADI",
    "ON", "SWKS", "QRVO", "TER", "WOLF", "ENTG", "UCTT", "COHU",
    "ACMR", "AMKR", "RMBS", "ALGM", "DIOD", "MTSI", "POWI",
    "SMTC", "GSIT", "CEVA", "SIMO",
}
HIGH_VOL_SEMI = {"AMD", "NVDA", "MRVL", "MCHP", "ON", "WOLF", "STM"}

logger = logging.getLogger("quant.vector")

# 缓存配置
_config = {}

# 因子权重加载
def load_factor_weights() -> dict:
    """从 factor_weights.json 加载动态权重"""
    import os, json
    fw_file = "config/factor_weights.json"
    if os.path.exists(fw_file):
        with open(fw_file) as f:
            w = json.load(f)
    else:
        w = {"momentum": 41, "quality": 26, "trend": 13}
    defaults = {"value": 8, "lowvol": 6, "volume": 6}
    for k, v in defaults.items():
        w.setdefault(k, v)
    total = sum(w.values())
    if total != 100:
        for k in list(w.keys()):
            w[k] = int(w[k] / total * 100)
        diff = 100 - sum(w.values())
        if diff:
            max_k = max(w, key=w.get)
            w[max_k] += diff
    return w

class VectorStrategy:
    """
    全向量化策略引擎。
    所有操作在 NumPy 矩阵上完成，无 Python 循环。
    """

    def __init__(self, tickers: list[str], quality_scores: dict[str, float] = None):
        self.tickers = tickers
        self.n = len(tickers)
        self.ticker_idx = {t: i for i, t in enumerate(tickers)}

        # 质量+价值因子总矩阵（0-55分，归一化到0-25权重）
        self.quality = np.zeros(self.n)
        if quality_scores:
            for t, q in quality_scores.items():
                j = self.ticker_idx.get(t)
                if j is not None:
                    self.quality[j] = min(q / 55 * 25, 25)  # 归一化到0-25

        # 预计算行业映射（矩阵形式）
        self.sector_semi_hv = np.array([
            1 if t in HIGH_VOL_SEMI else 0 for t in tickers
        ], dtype=bool)
        self.sector_semi = np.array([
            1 if t in SEMI else 0 for t in tickers
        ], dtype=bool)

    def run(self, prices: dict[str, pd.DataFrame],
            spy: pd.DataFrame,
            start: str = "2020-01-01",
            end: str = "2026-05-17") -> dict:
        cfg = load_config()
        """
        全向量化回测。
        返回：{total_return, annual_return, max_drawdown, sharpe,
              equity_curve, drawdown_curve}
        """
        # 1. 构建日期（统一转为无时区，和 yfinance 数据匹配）
        dates = pd.bdate_range(start, end, freq="W")
        if hasattr(spy.index, 'tz') and spy.index.tz is not None:
            dates = dates.tz_localize(None)
        T = len(dates)

        # 2. 构建价格矩阵 (T x N) — 向量化
        logger.info("构建价格矩阵...")
        P = np.full((T, self.n), np.nan)
        M = np.full((T, self.n), np.nan)
        ATR = np.full((T, self.n), np.nan)
        RSI_mat = np.full((T, self.n), np.nan)
        SMA20 = np.full((T, self.n), np.nan)
        SMA50 = np.full((T, self.n), np.nan)
        SMA200 = np.full((T, self.n), np.nan)
        VR = np.full((T, self.n), np.nan)

        # 把dates转成整数索引查找
        date_indices = {d: i for i, d in enumerate(dates)}

        for ticker, df in prices.items():
            j = self.ticker_idx.get(ticker)
            if j is None:
                continue
            # 找出dates中每行在df中的最近索引
            df_index = df.index
            if hasattr(df_index, 'tz') and df_index.tz is not None:
                df_index = df_index.tz_localize(None)
            for i, d in enumerate(dates):
                idx = df_index.get_indexer([d], method="nearest")
                if idx[0] < 0 or idx[0] >= len(df):
                    continue
                row = df.iloc[idx[0]]
                P[i, j] = row["Close"]
                M[i, j] = row.get("Momentum_12M", np.nan)
                ATR[i, j] = row.get("ATR_Pct", np.nan)
                RSI_mat[i, j] = row.get("RSI", np.nan)
                SMA20[i, j] = row.get("SMA20", np.nan)
                SMA50[i, j] = row.get("SMA50", np.nan)
                SMA200[i, j] = row.get("SMA200", np.nan)
                VR[i, j] = row.get("Volume_Ratio", np.nan)

        # 3. 大盘信号——4态择时（多头/震荡/高波/空头）
        logger.info("计算大盘信号...")
        # 统一 SPY index 无时区
        spy_index_clean = spy.index
        if hasattr(spy_index_clean, 'tz') and spy_index_clean.tz is not None:
            spy_index_clean = spy_index_clean.tz_localize(None)
        spy_idx = []
        for d in dates:
            idx = spy_index_clean.get_indexer([d], method="nearest")
            spy_idx.append(idx[0] if idx[0] >= 0 else 0)

        spy_rows = spy.iloc[spy_idx]
        spy_sma20 = spy_rows["SMA20"].values
        spy_sma50 = spy_rows["SMA50"].values
        spy_sma200 = spy_rows["SMA200"].values
        spy_rsi = spy_rows["RSI"].values
        spy_close = spy_rows["Close"].values
        spy_atr = spy_rows["ATR_Pct"].values if "ATR_Pct" in spy_rows.columns else np.full(len(spy_rows), 1.0)

        # 4态模式：
        #   uptrend: 均线多头排列 + RSI<75 → 正常买入
        #   choppy:  均线纠缠或RSI在45-55之间 → 半仓
        #   highvol: VIX高/ATR高 → 减仓
        #   bear:    价格<200日均线85%以下 → 空仓
        spy_uptrend = (spy_sma20 > spy_sma50) & (spy_sma50 > spy_sma200) & (~np.isnan(spy_sma20))
        bear_market = (spy_close < spy_sma200 * 0.85) & (~np.isnan(spy_sma200))
        high_vol = spy_atr > np.percentile(spy_atr, 80) if len(spy_atr) > 100 else np.full(len(spy_atr), False)
        high_vol = spy_atr > np.percentile(spy_atr, 80) if len(spy_atr) > 100 else np.full(len(spy_atr), False)

        # 过热/极端仍保留
        spy_overheat = spy_rsi > cfg.get("market_overheat_rsi", 80)
        spy_extreme = spy_rsi > cfg.get("market_extreme_rsi", 85)
        spy_severe = bear_market

        # 震荡：多头但波动加剧 或 RSI偏高
        spy_choppy = spy_uptrend & (high_vol | (spy_rsi > 70))

        # 4. 动量排名矩阵 (T x N)
        logger.info("计算动量排名...")
        # 每行排序，得到排名
        mom_rank = np.zeros((T, self.n))
        for i in range(T):
            row = M[i]
            # 有效值排名
            valid = ~np.isnan(row)
            if valid.sum() > 0:
                r = pd.Series(row[valid]).rank(pct=True).values
                mom_rank[i, valid] = r

        # 5. 候选标记（参数从system_config读取）
        mom_top = cfg.get("mom_rank_top_pct", 0.7)
        rsi_entry = cfg.get("rsi_entry", 80)
        top_mom = mom_rank >= mom_top
        above200 = P > SMA200
        rsi_ok = RSI_mat < rsi_entry
        valid_price = ~np.isnan(P)

        candidate = top_mom & above200 & rsi_ok & valid_price

        # 6. 综合评分（从factor_weights.json读取权重）
        weights = load_factor_weights()
        w_momentum = weights.get("momentum", 55)
        w_quality = weights.get("quality", 25)
        w_trend = weights.get("trend", 20)
        w_value = weights.get("value", 10)
        w_lowvol = weights.get("lowvol", 10)

        total_w = w_momentum + w_quality + w_trend + w_value + w_lowvol
        momentum_score = mom_rank * w_momentum  # w_momentum%
        # 质量分
        quality_score = np.zeros((T, self.n))
        for j in range(self.n):
            quality_score[:, j] = self.quality[j] / 100 * w_quality  # w_quality%
        # 趋势分
        trend_score = np.zeros((T, self.n))
        trend_score += np.where((P > SMA20) & (SMA20 > SMA50) & ~np.isnan(SMA20), 12, 6)
        trend_score += np.where(VR > 1.2, 4, 0)
        trend_score += np.where(P > SMA200, 4, 0)
        trend_score = trend_score / 20 * w_trend  # w_trend%

        total_score = momentum_score + quality_score + trend_score
        total_score[~candidate] = 0

        # 7. 组合模拟（纯NumPy）
        logger.info("执行组合模拟...")
        cash = np.full(T, np.nan)
        equity = np.full(T, np.nan)
        cash[0] = 100_000
        equity[0] = 100_000

        # 持仓：entry_price[i,j] > 0 表示持有，值为买入价
        entry_price = np.zeros((T, self.n))
        shares = np.zeros((T, self.n), dtype=int)

        cfg = load_config()
        max_pos = int(cfg.get("max_positions", 8))
        thresh = cfg.get("score_threshold", 50)
        stop_loss_static = cfg.get("stop_loss_pct", 15) / 100.0
        stop_loss_min = cfg.get("stop_loss_min_pct", 5) / 100.0
        stop_loss_max = cfg.get("stop_loss_max_pct", 25) / 100.0
        atr_multiple = cfg.get("stop_loss_atr_multiple", 3.0)
        trailing_activate = cfg.get("trailing_stop_activate_pct", 15) / 100.0
        trailing_atr_multiple = cfg.get("trailing_stop_atr_multiple", 2.0)
        trailing_min = cfg.get("trailing_stop_min_pct", 8) / 100.0
        rsi_exit = cfg.get("rsi_exit", 88)

        # 跟踪止损：记录每只股票买入后的最高价
        peak_price = np.zeros(self.n)

        for i in range(1, T):
            # 继承上期
            entry_price[i] = entry_price[i-1].copy()
            shares[i] = shares[i-1].copy()

            # 大盘极端熊
            if spy_severe[i]:
                cash[i] = equity[i-1]
                entry_price[i] = 0
                shares[i] = 0
                equity[i] = cash[i]
                continue

            # 大盘极端过热：减仓25%
            if spy_extreme[i]:
                # 每只持仓卖25%
                to_reduce = shares[i] // 4
                proceeds = np.sum(to_reduce * P[i, :])
                cash[i] = cash[i-1] + proceeds
                shares[i] -= to_reduce
                # 清掉零股的持仓
                zero = shares[i] <= 0
                entry_price[i, zero] = 0
                shares[i, zero] = 0
                equity[i] = cash[i] + np.sum(shares[i] * P[i, :])
                continue

            # 卖出检查 — ATR动态止损 + 跟踪止损
            cash[i] = cash[i-1]
            for j in range(self.n):
                if entry_price[i, j] <= 0:
                    continue
                cur_p = P[i, j]
                cur_atr = ATR[i, j] if not np.isnan(ATR[i, j]) else 3.0
                if np.isnan(cur_p):
                    entry_price[i, j] = 0
                    shares[i, j] = 0
                    continue

                pnl = (cur_p - entry_price[i, j]) / entry_price[i, j]

                # 更新最高价（跟踪止损用）
                peak_price[j] = max(peak_price[j], cur_p)

                # === ATR动态止损 ===
                # 止损价 = min(静态止损, ATR动态止损)
                stop_loss_atr = cur_atr / 100.0 * atr_multiple  # ATR百分比 × 倍数
                stop_loss_dynamic = max(stop_loss_min, min(stop_loss_max, stop_loss_atr))

                # === 跟踪止损（浮盈后激活）===
                if pnl > trailing_activate and peak_price[j] > entry_price[i, j]:
                    # 从最高点回落 N倍ATR
                    trailing_dist = cur_atr / 100.0 * trailing_atr_multiple
                    trailing_dist = max(trailing_min, trailing_dist)
                    if cur_p < peak_price[j] * (1 - trailing_dist):
                        cash[i] += shares[i, j] * cur_p
                        entry_price[i, j] = 0
                        shares[i, j] = 0
                        continue

                # 常规止损（两个条件任一触发）
                if pnl < -stop_loss_static or pnl < -stop_loss_dynamic:
                    cash[i] += shares[i, j] * cur_p
                    entry_price[i, j] = 0
                    shares[i, j] = 0
                # RSI过热退出
                elif not np.isnan(RSI_mat[i, j]) and RSI_mat[i, j] > rsi_exit:
                    cash[i] += shares[i, j] * cur_p
                    entry_price[i, j] = 0
                    shares[i, j] = 0

            # 买入（大盘判断）
            # 大盘状态决定买入力度
            if spy_uptrend[i] and not spy_choppy[i]:
                # 状态1: 稳健多头 → 正常买入
                buy_ratio = 1.0
            elif spy_uptrend[i] and spy_choppy[i]:
                # 状态2: 多头但震荡 → 半仓
                buy_ratio = cfg.get("market_reduce_ratio", 0.50)
            else:
                # 状态3/4: 震荡下跌或熊市 → 不买入
                buy_ratio = 0.0

            if buy_ratio > 0:
                current_n = np.sum(entry_price[i] > 0)
                n_to_buy = max_pos - current_n
                if n_to_buy > 0:
                    # 评分排序
                    scores = total_score[i].copy()
                    scores[entry_price[i] > 0] = 0  # 排除已持有
                    scores[scores < thresh] = 0
                    best = np.argsort(-scores)[:int(n_to_buy)]
                    best = best[scores[best] > 0]

                    if len(best) > 0:
                        buy_cash_ratio = cfg.get("buy_cash_ratio", 0.90)
                        buy_cash = cash[i] * buy_cash_ratio * buy_ratio
                        per_stock = buy_cash / max_pos

                        atr_low = cfg.get("atr_low_threshold", 2.5)
                        atr_med = cfg.get("atr_medium_threshold", 4.0)
                        atr_high = cfg.get("atr_high_threshold", 6.0)
                        cap_low = cfg.get("atr_cap_low", 0.15)
                        cap_med = cfg.get("atr_cap_medium", 0.12)
                        cap_high = cfg.get("atr_cap_high", 0.08)
                        cap_extreme = cfg.get("atr_cap_extreme", 0.06)
                        semi_total_pct = cfg.get("semi_total_limit", 0.25)

                        for j in best:
                            price = P[i, j]
                            if np.isnan(price) or price <= 0:
                                continue
                            atr = ATR[i, j] if not np.isnan(ATR[i, j]) else 3.0
                            if atr < atr_low:
                                cap = cap_low
                            elif atr < atr_med:
                                cap = cap_med
                            elif atr < atr_high:
                                cap = cap_high
                            else:
                                cap = cap_extreme
                            semi_limit = cfg.get("semi_single_limit", 0.08)
                            if self.sector_semi_hv[j]:
                                cap = min(cap, semi_limit)
                            # 子行业总仓位
                            if self.sector_semi_hv[j]:
                                hv_val = np.sum(shares[i] * P[i, :] * self.sector_semi_hv)
                                if hv_val + per_stock > equity[i] * semi_total_pct:
                                    continue

                            max_cost = min(per_stock, equity[i] * cap)
                            n_shares = int(max_cost / max(price, 1))
                            if n_shares <= 0:
                                continue
                            cost = n_shares * price
                            if cost > cash[i]:
                                continue
                            shares[i, j] += n_shares
                            entry_price[i, j] = price
                            cash[i] -= cost

            equity[i] = cash[i] + np.sum(shares[i] * P[i, :])

        # 8. 报告
        eq = pd.Series(equity, index=dates, name="equity")
        total_ret = (eq.iloc[-1] - eq.iloc[0]) / eq.iloc[0] * 100
        years = max((dates[-1] - dates[0]).days / 365.25, 0.1)
        ann_ret = (eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1
        rolling_max = eq.cummax()
        dd = (eq - rolling_max) / rolling_max
        max_dd = dd.min() * 100
        daily_ret = eq.pct_change().dropna()
        sharpe = np.sqrt(52) * daily_ret.mean() / daily_ret.std() if daily_ret.std() > 0 else 0

        logger.info(
            f"结果: 总收益{total_ret:+.1f}% 年化{ann_ret*100:+.1f}%  "
            f"回撤{max_dd:.1f}% 夏普{sharpe:.2f}"
        )

        return {
            "total_return_pct": round(total_ret, 2),
            "annual_return_pct": round(ann_ret * 100, 2),
            "max_drawdown_pct": round(max_dd, 2),
            "sharpe_ratio": round(sharpe, 2),
            "equity_curve": eq,
            "drawdown_curve": dd * 100,
        }
