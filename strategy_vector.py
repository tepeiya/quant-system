"""
向量化策略引擎 v4 — 专业版
=========================
升级内容：
1. 动量加权仓位：动量越强仓位越大（不再是等权）
2. 波动率调整：高波动缩仓位，低波动放仓位
3. 综合评分排序 + 金字塔建仓
4. ATR动态止损 + 跟踪止盈
5. 大盘择时（4态）+ 市场宽度信号
"""

import numpy as np
import pandas as pd
import logging
from system_config import load as load_config
import json, os

logger = logging.getLogger("quant.vector")

SECTOR_FILE = "config/factor_evolution.json"


def load_sector_map() -> dict:
    """加载行业映射"""
    if os.path.exists(SECTOR_FILE):
        try:
            with open(SECTOR_FILE) as f:
                return json.load(f)
        except:
            pass
    return {}


def load_factor_weights() -> dict:
    path = "config/factor_weights.json"
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}


class VectorStrategy:
    def __init__(self, tickers: list[str], quality_scores: dict = None):
        self.tickers = tickers
        self.n = len(tickers)
        self.ticker_idx = {t: i for i, t in enumerate(tickers)}
        self.quality = np.array([quality_scores.get(t, 50) if quality_scores else 50 for t in tickers])
        sectors = load_sector_map()
        if isinstance(sectors, dict):
            self.sector_semi_hv = np.array([sectors.get(t, {}).get("semi", 0) if isinstance(sectors.get(t), dict) else 0 for t in tickers])
        else:
            self.sector_semi_hv = np.zeros(len(tickers))

    def run(self, prices: dict[str, pd.DataFrame],
            spy: pd.DataFrame,
            start: str = "2020-01-01",
            end: str = None) -> dict:
        if end is None:
            end = pd.Timestamp.now().strftime("%Y-%m-%d")

        cfg = load_config()
        dates = pd.bdate_range(start, end, freq="W")
        if hasattr(spy.index, 'tz') and spy.index.tz is not None:
            dates = dates.tz_localize(None)
        T = len(dates)

        # ===== 构建价格矩阵 =====
        logger.info("构建价格矩阵...")
        P = np.full((T, self.n), np.nan)
        M = np.full((T, self.n), np.nan)
        ATR = np.full((T, self.n), np.nan)
        RSI_mat = np.full((T, self.n), np.nan)
        SMA20 = np.full((T, self.n), np.nan)
        SMA50 = np.full((T, self.n), np.nan)
        SMA200 = np.full((T, self.n), np.nan)
        VR = np.full((T, self.n), np.nan)

        for ticker, df in prices.items():
            j = self.ticker_idx.get(ticker)
            if j is None:
                continue
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

        # ===== 大盘信号 =====
        logger.info("计算大盘信号...")
        spy_index_clean = spy.index
        if hasattr(spy_index_clean, 'tz') and spy_index_clean.tz is not None:
            spy_index_clean = spy_index_clean.tz_localize(None)
        spy_idx = [spy_index_clean.get_indexer([d], method="nearest")[0] for d in dates]
        spy_rows = spy.iloc[spy_idx]
        spy_sma20 = spy_rows["SMA20"].values
        spy_sma50 = spy_rows["SMA50"].values
        spy_sma200 = spy_rows["SMA200"].values
        spy_rsi = spy_rows["RSI"].values
        spy_close = spy_rows["Close"].values
        spy_atr = spy_rows["ATR_Pct"].values if "ATR_Pct" in spy_rows.columns else np.full(len(spy_rows), 1.0)

        # 市场状态
        uptrend = (spy_sma20 > spy_sma50) & (spy_sma50 > spy_sma200) & (~np.isnan(spy_sma20))
        bear = (spy_close < spy_sma200 * 0.85) & (~np.isnan(spy_sma200))
        high_vol = spy_atr > np.percentile(spy_atr[~np.isnan(spy_atr)], 80) if np.sum(~np.isnan(spy_atr)) > 100 else np.full(T, False)
        overheat = spy_rsi > cfg.get("market_overheat_rsi", 81)
        extreme = spy_rsi > cfg.get("market_extreme_rsi", 86)
        choppy = uptrend & (high_vol | (spy_rsi > 70))
        severe = bear

        # ===== [升级] 动量排名 + 综合评分 =====
        logger.info("计算综合评分...")
        mom_rank = np.zeros((T, self.n))
        for i in range(T):
            row = M[i]
            valid = ~np.isnan(row)
            if valid.sum() > 0:
                r = pd.Series(row[valid]).rank(pct=True).values
                mom_rank[i, valid] = r

        # 因子权重
        weights = load_factor_weights()
        w_mom = weights.get("momentum", 45)
        w_qual = weights.get("quality", 26)
        w_trend = weights.get("trend", 13)

        # 综合评分
        total_score = np.zeros((T, self.n))
        total_score += mom_rank * w_mom
        for j in range(self.n):
            total_score[:, j] += self.quality[j] / 100 * w_qual

        trend_score = np.zeros((T, self.n))
        trend_score += np.where((P > SMA20) & (SMA20 > SMA50) & ~np.isnan(SMA20), 12, 6)
        trend_score += np.where(VR > 1.2, 4, 0)
        trend_score += np.where(P > SMA200, 4, 0)
        trend_score = trend_score / 20 * w_trend
        total_score += trend_score

        # 候选条件
        mom_top = cfg.get("mom_rank_top_pct", 0.6)
        rsi_entry = cfg.get("rsi_entry", 82)
        candidate = (mom_rank >= mom_top) & (P > SMA200) & (RSI_mat < rsi_entry) & ~np.isnan(P)
        total_score[~candidate] = 0

        # ===== [升级] 组合模拟 =====
        logger.info("执行组合模拟...")
        cash = np.full(T, np.nan)
        equity = np.full(T, np.nan)
        cash[0] = 100_000
        equity[0] = 100_000

        entry_price = np.zeros((T, self.n))
        shares = np.zeros((T, self.n), dtype=int)

        max_pos = int(cfg.get("max_positions", 10))
        thresh = cfg.get("score_threshold", 52)
        stop_loss_pct = cfg.get("stop_loss_pct", 12) / 100.0
        stop_loss_min = cfg.get("stop_loss_min_pct", 4) / 100.0
        stop_loss_max = cfg.get("stop_loss_max_pct", 20) / 100.0
        atr_multiple = cfg.get("stop_loss_atr_multiple", 2.8)
        trailing_activate = cfg.get("trailing_stop_activate_pct", 12) / 100.0
        trailing_atr_multiple = cfg.get("trailing_stop_atr_multiple", 1.8)
        trailing_min = cfg.get("trailing_stop_min_pct", 6) / 100.0
        rsi_exit = cfg.get("rsi_exit", 90)
        peak_price = np.zeros(self.n)

        for i in range(1, T):
            entry_price[i] = entry_price[i-1].copy()
            shares[i] = shares[i-1].copy()

            if severe[i]:
                cash[i] = equity[i-1]
                entry_price[i] = 0
                shares[i] = 0
                equity[i] = cash[i]
                continue

            if extreme[i]:
                to_reduce = shares[i] // 4
                proceeds = np.sum(to_reduce * P[i, :])
                cash[i] = cash[i-1] + proceeds
                shares[i] -= to_reduce
                zero = shares[i] <= 0
                entry_price[i, zero] = 0
                shares[i, zero] = 0
                equity[i] = cash[i] + np.sum(shares[i] * P[i, :])
                continue

            # 卖出
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
                peak_price[j] = max(peak_price[j], cur_p)

                # ATR 动态止损
                stop_atr = max(stop_loss_min, min(stop_loss_max, cur_atr / 100.0 * atr_multiple))
                # 跟踪止损
                if pnl > trailing_activate and peak_price[j] > entry_price[i, j]:
                    trailing_dist = max(trailing_min, cur_atr / 100.0 * trailing_atr_multiple)
                    if cur_p < peak_price[j] * (1 - trailing_dist):
                        cash[i] += shares[i, j] * cur_p
                        entry_price[i, j] = 0
                        shares[i, j] = 0
                        continue

                if pnl < -stop_loss_pct or pnl < -stop_atr:
                    cash[i] += shares[i, j] * cur_p
                    entry_price[i, j] = 0
                    shares[i, j] = 0
                elif not np.isnan(RSI_mat[i, j]) and RSI_mat[i, j] > rsi_exit:
                    cash[i] += shares[i, j] * cur_p
                    entry_price[i, j] = 0
                    shares[i, j] = 0

            # 买入（按大盘状态）
            if uptrend[i] and not choppy[i]:
                buy_ratio = 1.0
            elif uptrend[i] and choppy[i]:
                buy_ratio = cfg.get("market_reduce_ratio", 0.50)
            else:
                buy_ratio = 0.0

            if buy_ratio > 0 and cash[i] > 0:
                current_n = np.sum(entry_price[i] > 0)
                n_to_buy = max_pos - current_n
                if n_to_buy > 0:
                    scores = total_score[i].copy()
                    scores[entry_price[i] > 0] = 0
                    scores[scores < thresh] = 0
                    best = np.argsort(-scores)[:int(n_to_buy * 1.5)]
                    best = best[scores[best] > 0]

                    if len(best) > 0:
                        buy_cash = cash[i] * cfg.get("buy_cash_ratio", 0.90) * buy_ratio

                        # ===== [升级] 动量加权分配 =====
                        selected_scores = scores[best] + 1  # 避免除零
                        total_s = np.sum(selected_scores)
                        for idx, j in enumerate(best):
                            if idx >= n_to_buy:
                                break
                            price = P[i, j]
                            if np.isnan(price) or price <= 0:
                                continue
                            atr = ATR[i, j] if not np.isnan(ATR[i, j]) else 3.0

                            # 动量加权：得分越高仓位越大
                            weight = selected_scores[idx] / total_s if total_s > 0 else 1.0 / len(best)
                            # 波动率调整：高波动缩仓位
                            vol_adj = max(0.5, min(1.5, 3.0 / max(atr, 0.5)))
                            # 最终分配
                            alloc = buy_cash * weight * vol_adj
                            max_pct = cfg.get("max_position_pct", 0.15)
                            alloc = min(alloc, equity[i] * max_pct)
                            alloc = min(alloc, cash[i])

                            n_shares = int(alloc / max(price, 1))
                            cost = n_shares * price
                            if cost > cash[i]:
                                n_shares = int(cash[i] / max(price, 1))
                                cost = n_shares * price
                            if n_shares > 0 and cost <= cash[i]:
                                shares[i, j] += n_shares
                                entry_price[i, j] = price
                                cash[i] -= cost
                                peak_price[j] = price

            equity[i] = cash[i] + np.sum(shares[i] * P[i, :])

        # ===== 报告 =====
        eq = pd.Series(equity, index=dates, name="equity")
        total_ret = (eq.iloc[-1] - eq.iloc[0]) / eq.iloc[0] * 100
        years = max((dates[-1] - dates[0]).days / 365.25, 0.1)
        ann_ret = (eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1
        rolling_max = eq.cummax()
        dd = (eq - rolling_max) / rolling_max
        max_dd = dd.min() * 100
        daily_ret = eq.pct_change().dropna()
        sharpe = np.sqrt(52) * daily_ret.mean() / daily_ret.std() if daily_ret.std() > 0 else 0

        logger.info(f"结果: 总收益{total_ret:+.1f}% 年化{ann_ret*100:+.1f}%  回撤{max_dd:.1f}% 夏普{sharpe:.2f}")

        return {
            "total_return": round(total_ret, 1),
            "annual_return": round(ann_ret * 100, 1),
            "max_drawdown": round(max_dd, 1),
            "sharpe": round(sharpe, 2),
            "equity_curve": eq,
            "drawdown_curve": dd,
        }
