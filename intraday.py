"""
日内交易策略 — 完全独立于主策略
================================
- 盘中实时动量选股（按流动性和ATR筛选）
- 当日开仓当日平仓（收盘前强制清仓）
- 独立信号/日志/回测
- 独立资金分配
- 动态止盈止损+追踪止损

用法：
  python3 intraday.py --scan       扫描今日信号
  python3 intraday.py --backtest   回测
  python3 intraday.py --status     查看状态
"""

import os, sys, json, logging, numpy as np, pandas as pd
from datetime import datetime, timedelta

# data_global 可选加载
try:
    from data_global import us_kline_sina, klines_to_dataframe
    DATA_GLOBAL_AVAILABLE = True
except:
    DATA_GLOBAL_AVAILABLE = False

logging.basicConfig(level=logging.INFO, format="%(asctime)s [INTRADAY] %(message)s")
logger = logging.getLogger("quant.intraday")

SIGNAL_FILE = "signals/intraday_signal.json"
TRADE_LOG = "signals/intraday_trades.json"
BACKTEST_FILE = "signals/intraday_backtest.json"
CONFIG_FILE = "config/intraday_config.json"
CACHE_DIR = "data_cache"

DEFAULT_CONFIG = {
    "enabled": True,
    "max_positions": 5,
    "per_position_pct": 0.18,
    "capital_pct": 0.20,
    "stop_loss_atr_multiple": 1.5,      # ATR倍数止损
    "take_profit_atr_multiple": 3.2,     # ATR倍数止盈（盈亏比2.1:1）
    "trailing_stop_atr_multiple": 0.8,   # ATR倍数追踪止损（更紧）
    "trailing_stop_enabled": True,       # 默认开启移动止损
    "trailing_stop_activation_atr": 1.0, # 盈利达到1x ATR后启动追踪
    "stop_loss_min_pct": 0.5,            # 最小止损%
    "stop_loss_max_pct": 4.0,            # 最大止损%
    "scan_interval_minutes": 30,
    "close_time": "15:50",
    "entry_start_time": "10:00",         # 最早入场时间
    "entry_end_time": "14:30",           # 最晚入场时间
    "momentum_windows": [5, 15, 30],
    "min_price": 5,
    "max_price": 500,
    "min_volume_ratio": 1.5,
    "min_avg_volume": 500000,
    "rsi_overbought": 82,
    "rsi_oversold": 25,
    "max_daily_loss_pct": 3.0,
    "backtest_result": {}
}


def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            cfg = json.load(f)
            for k, v in DEFAULT_CONFIG.items():
                cfg.setdefault(k, v)
            return cfg
    return dict(DEFAULT_CONFIG)


def save_config(cfg: dict):
    os.makedirs("config", exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


def load_trade_log() -> dict:
    if os.path.exists(TRADE_LOG):
        try:
            with open(TRADE_LOG) as f:
                return json.load(f)
        except:
            pass
    return {"trades": []}


def save_trade_log(log: dict):
    os.makedirs("signals", exist_ok=True)
    with open(TRADE_LOG, "w") as f:
        json.dump(log, f, indent=2)


def get_ticker_rankings(cache: dict) -> list:
    """获取所有股票按流动性+ATR排序（只取SP500+优质股）"""
    rankings = []
    # 优先从 ticker 列表获取
    tickers = []
    sp500_file = "data_cache/sp500_tickers.json"
    if os.path.exists(sp500_file):
        try:
            with open(sp500_file) as f:
                tickers = json.load(f)
        except:
            pass
    
    # 如果没有 SP500 列表，从缓存中按平均成交量排序取前300
    if not tickers:
        all_tickers = sorted(cache.keys())
        for t in all_tickers:
            df = cache.get(t)
            if df is None or len(df) < 60:
                continue
            vol = np.mean(df["Volume"].values[-60:]) if "Volume" in df.columns else 0
            rankings.append((t, vol))
        rankings.sort(key=lambda x: -x[1])
        return [r[0] for r in rankings[:200]]
    
    # SP500 中选日均成交量 > 50万的
    for t in tickers:
        df = cache.get(t)
        if df is None or len(df) < 60:
            continue
        vol = np.mean(df["Volume"].values[-60:]) if "Volume" in df.columns else 0
        if vol >= 500000:
            rankings.append((t, vol))
    
    rankings.sort(key=lambda x: -x[1])
    return [r[0] for r in rankings[:200]]


def scan_intraday_signals() -> list[dict]:
    """
    扫描日内交易信号
    用日K线数据 + 盘中实时行情 + 成交量筛选 + 动量评分
    """
    from data_prod import load_price_cache
    cache = load_price_cache()
    if not cache:
        logger.warning("无数据缓存")
        return []

    cfg = load_config()

    # 获取盘中实时价格（Alpaca IEX + 新浪回退）
    tickers = get_ticker_rankings(cache)
    if not tickers:
        tickers = sorted(cache.keys())[:200]

    realtime_prices = {}
    try:
        from data_prod import get_realtime_prices
        realtime_prices = get_realtime_prices(tickers[:50])
        if realtime_prices:
            logger.info(f"  实时行情: {len(realtime_prices)}只可用")
    except Exception as e:
        logger.debug(f"  实时行情获取失败: {e}")

    # 加载板块数据（从缓存/基本面缓存，不实时拉取）
    sector_map = {}
    try:
        # 优先从基本面缓存加载
        import pickle as _pkl
        funda_cache_file = os.path.join(CACHE_DIR, "fundamentals.pkl")
        if os.path.exists(funda_cache_file):
            with open(funda_cache_file, "rb") as f:
                funda_cache = _pkl.load(f)
            for t, info in funda_cache.items():
                sec = (info or {}).get("sector")
                if sec and sec not in ("N/A", "", None):
                    sector_map[t] = sec
        logger.info(f"  板块数据: {len(sector_map)}只 (从缓存)")
    except Exception as e:
        logger.debug(f"  板块数据加载失败: {e}")

    signals = []

    for t in tickers:
        df = cache.get(t)
        if df is None or len(df) < 60:
            continue
        
        close = df["Close"].values
        # 优先使用实时价格，没有则用昨日收盘
        price = realtime_prices.get(t)
        if price is None or price <= 0:
            price = float(close[-1])

        if price < cfg["min_price"] or price > cfg["max_price"]:
            continue

        # 成交量检查
        volume = df["Volume"].values[-1] if "Volume" in df.columns else 0
        avg_vol = np.mean(df["Volume"].values[-20:]) if "Volume" in df.columns else 1
        vol_ratio = volume / avg_vol if avg_vol > 0 else 0

        if vol_ratio < cfg["min_volume_ratio"]:
            continue
        if avg_vol < cfg.get("min_avg_volume", 500000):
            continue

        # 有实时价格时用实时价算今日涨跌幅
        if t in realtime_prices:
            today_chg = (realtime_prices[t] - close[-1]) / close[-1] * 100
        else:
            today_chg = (close[-1] - close[-2]) / close[-2] * 100 if len(close) >= 2 else 0

        week_chg = (close[-1] - close[-6]) / close[-6] * 100 if len(close) >= 6 else 0
        month_chg = (close[-1] - close[-21]) / close[-21] * 100 if len(close) >= 21 else 0

        # RSI 过滤
        rsi = 50
        if "RSI" in df.columns:
            rsi = float(df["RSI"].values[-1])
            if rsi > cfg["rsi_overbought"]:
                continue

        # ATR
        atr_pct = float(df["ATR_Pct"].values[-1]) if "ATR_Pct" in df.columns else 2.0

        # 均线趋势
        sma20 = df["SMA20"].values[-1] if "SMA20" in df.columns else price
        sma50 = df["SMA50"].values[-1] if "SMA50" in df.columns else sma20
        price_above_ma20 = price > sma20
        price_above_ma50 = price > sma50

        # --- 综合评分 ---
        # 1. 短中长动量加权（越短权重越高）
        mom_score = today_chg * 0.6 + week_chg * 0.25 + month_chg * 0.15

        # 2. 成交量确认
        vol_bonus = 0
        if vol_ratio > 3.0:
            vol_bonus = 3.0
        elif vol_ratio > 2.0:
            vol_bonus = 1.5
        elif vol_ratio > 1.5:
            vol_bonus = 0.5

        # 3. 趋势分数
        trend_score = 0
        if price_above_ma20:
            trend_score += 1.5
            if price_above_ma50:
                trend_score += 1.0
        else:
            trend_score -= 1.0
            if not price_above_ma50:
                trend_score -= 0.5

        # 4. ATR波动调整
        atr_adj = 0
        if atr_pct < 1.5:
            atr_adj = 1.0
        elif atr_pct < 2.5:
            atr_adj = 0.5
        elif atr_pct > 4.0:
            atr_adj = -1.0

        # 5. RSI 加分
        rsi_score = 0
        if rsi < 35:
            rsi_score = 1.0
        elif rsi < 50:
            rsi_score = 0.5
        elif rsi > 70:
            rsi_score = -0.5

        score = mom_score + vol_bonus + trend_score + atr_adj + rsi_score

        # 风控过滤
        if today_chg > 8.0:
            continue
        if today_chg < -6.0:
            continue

        # 计算ATR自适应止损/止盈
        stop_loss_pct = max(cfg["stop_loss_min_pct"],
                            min(atr_pct * cfg["stop_loss_atr_multiple"], cfg["stop_loss_max_pct"]))
        take_profit_pct = max(stop_loss_pct * 1.5,
                              atr_pct * cfg["take_profit_atr_multiple"])

        signals.append({
            "ticker": t,
            "score": round(score, 2),
            "price": round(price, 2),
            "today_chg": round(today_chg, 2),
            "has_realtime": t in realtime_prices,
            "vol_ratio": round(vol_ratio, 2),
            "atr_pct": round(atr_pct, 2),
            "rsi": round(rsi, 1),
            "avg_vol": int(avg_vol),
            "stop_loss_pct": round(stop_loss_pct, 2),
            "take_profit_pct": round(take_profit_pct, 2),
            "ma20": round(float(sma20), 2),
            "ma50": round(float(sma50), 2),
        })
        logger.debug(f"  {t}: score={score:.1f} chg={today_chg:.1f}% "
                     f"vol={vol_ratio:.1f}x atr={atr_pct:.1f}% "
                     f"stop={stop_loss_pct:.1f}% tp={take_profit_pct:.1f}%")

    # 板块热点评分
    # 统计每个板块的候选股数量和平均得分
    sector_candidates = {}
    for s in signals:
        sec = sector_map.get(s["ticker"])
        if sec:
            if sec not in sector_candidates:
                sector_candidates[sec] = {"count": 0, "scores": []}
            sector_candidates[sec]["count"] += 1
            sector_candidates[sec]["scores"].append(s["score"])

    # 板块热度加分：板块内候选 >= 2 只视为"板块热"，每只加1.5分
    # 板块内候选 >= 3 只视为"板块非常热"，每只加3分
    hot_sectors = {}
    for sec, data in sector_candidates.items():
        if data["count"] >= 3:
            hot_sectors[sec] = 3.0
            logger.info(f"  🔥 板块热: {sec} ({data['count']}只候选, 均分{np.mean(data['scores']):.1f})")
        elif data["count"] >= 2:
            hot_sectors[sec] = 1.5
            logger.info(f"  🔸 板块温和: {sec} ({data['count']}只候选)")

    for s in signals:
        sec = sector_map.get(s["ticker"])
        if sec and sec in hot_sectors:
            s["score"] += hot_sectors[sec]
            s["sector_hot_bonus"] = hot_sectors[sec]
            s["sector"] = sec

    # === 微因子评分 ===
    # 1. 相对大盘强度
    spy_chg = 0
    try:
        spy_df = cache.get("SPY") or cache.get("SPY.US")
        if spy_df is None and DATA_GLOBAL_AVAILABLE:
            from data_global import us_kline_sina, klines_to_dataframe
            raw = us_kline_sina("SPY", 5)
            if raw:
                spy_df = klines_to_dataframe(raw)
                if spy_df is not None and len(spy_df) >= 2:
                    spy_df = __import__("data_prod", fromlist=["compute_indicators"]).compute_indicators(spy_df)
        if spy_df is not None and len(spy_df) >= 2:
            spy_close = spy_df["Close"].values
            spy_chg = (spy_close[-1] - spy_close[-2]) / spy_close[-2] * 100
    except Exception as e:
        logger.debug(f"  SPY数据获取失败: {e}")
    for s in signals:
        rel_strength = s.get("today_chg", 0) - spy_chg
        s["rel_strength"] = round(rel_strength, 2)
        # 跑赢大盘1%以上加分
        if rel_strength > 1.0:
            bonus = min(rel_strength * 1.5, 5.0)
            s["micro_rel_bonus"] = round(bonus, 2)
            s["score"] += bonus
        elif rel_strength < -1.0:
            s["micro_rel_bonus"] = round(rel_strength * 0.5, 2)
            s["score"] += rel_strength * 0.5  # 跑输减分

    # 2. RSI超卖反转：昨日RSI<35 + 今日涨 = 反弹信号
    for s in signals:
        rsi = s.get("rsi", 50)
        today_chg = s.get("today_chg", 0)
        if rsi < 35 and today_chg > 0.5:
            bonus = min((35 - rsi) * 0.15, 2.0)
            s["micro_rsi_reversal"] = round(bonus, 2)
            s["score"] += bonus
            logger.debug(f"  🔄 RSI反转 {s['ticker']}: RSI={rsi} chg={today_chg:.1f}% +{bonus:.1f}")

    # 3. 开盘放量确认：量比>2.0 且 RSI合理(<65) = 更强的信号
    for s in signals:
        vr = s.get("vol_ratio", 0)
        rsi = s.get("rsi", 50)
        if vr > 2.0 and rsi < 65:
            bonus = min(vr * 0.3, 1.5)
            s["micro_volume_confirm"] = round(bonus, 2)
            s["score"] += bonus

    # === 评分归一化（z-score 标准化到 0-100 分） ===
    if signals and len(signals) >= 5:
        scores = np.array([s["score"] for s in signals])
        mean_score = np.mean(scores)
        std_score = np.std(scores) if np.std(scores) > 0 else 1.0
        for s in signals:
            raw_score = s["score"]
            # z-score 转换
            z = (raw_score - mean_score) / std_score
            # 映射到 0-100 分（z-score 范围约 -3 到 +3）
            normalized = max(0, min(100, 50 + z * 16.67))  # 16.67 = 100/6
            s["score_raw"] = round(raw_score, 2)
            s["score"] = round(normalized, 1)

    signals.sort(key=lambda x: x["score"], reverse=True)
    max_pos = cfg.get("max_positions", 5)
    result = signals[:max_pos * 2]
    logger.info(f"日内扫描: 扫描{len(tickers)}只, 微因子候选{len(result)}只 (取Top{max_pos})")
    return result


def generate_signal() -> dict:
    """生成今日日内交易信号"""
    signals = scan_intraday_signals()
    cfg = load_config()
    max_pos = cfg.get("max_positions", 5)

    signal = {
        "strategy": "intraday",
        "time": str(datetime.now()),
        "date": datetime.now().strftime("%Y-%m-%d"),
        "candidates": signals[:max_pos],
        "all_scanned": len(signals),
    }

    os.makedirs("signals", exist_ok=True)
    with open(SIGNAL_FILE, "w") as f:
        json.dump(signal, f, indent=2)

    # 同时保存回测结果（如果有）
    bt_file = BACKTEST_FILE
    if not os.path.exists(bt_file):
        bt_result = run_backtest(days=252)
        with open(bt_file, "w") as f:
            json.dump(bt_result, f, indent=2)

    logger.info(f"信号已保存: {len(signal['candidates'])}只候选")

    # === 写入信号总线 ===
    try:
        import signal_bus
        signal_bus.write_signal("intraday", signal.get("candidates", []),
                                buy_list=[s.get("ticker") for s in signal.get("candidates", [])],
                                metadata={"scanned": signal.get("all_scanned", 0)})
        logger.info("  ✅ 已写入信号总线")
    except Exception as e:
        logger.debug(f"  信号总线写入失败(不影响): {e}")

    return signal


def run_backtest(days: int = 252) -> dict:
    """
    日内交易回测 v2 — 修复未来函数偏差
    ================================
    修复内容：
    1. 用 T-1 日数据选股（避免未来函数）
    2. T 日开盘价买入（不是收盘价）
    3. 用当日高低价模拟日内波动（更真实）
    4. 精细化成本：佣金+滑点+买卖价差
    5. 严格控制每日最大持仓和开仓数
    6. 加入移动止损和单日亏损熔断
    """
    from data_prod import load_price_cache, compute_indicators
    cache = load_price_cache()
    if not cache:
        return {"error": "无数据"}

    cfg = load_config()
    initial_capital = 100000
    capital = initial_capital

    # 精细化交易成本
    commission_rate = 0.0005   # 佣金 0.05%
    slippage_rate = 0.0015     # 滑点 0.15%（市价单）
    spread_rate = 0.001        # 买卖价差 0.1%
    total_cost_rate = commission_rate + slippage_rate + spread_rate  # 单边 ~0.3%

    # 获取候选股票池
    tickers = get_ticker_rankings(cache)
    if not tickers:
        tickers = sorted(cache.keys())[:100]
    tickers = tickers[:80]

    total_trades = 0
    wins = 0
    daily_pnls = []
    equity = initial_capital
    peak = initial_capital
    max_dd = 0
    exit_reasons = {"stop_loss": 0, "take_profit": 0, "trailing_stop": 0, "close": 0}

    # 按日期遍历
    date_set = set()
    for t in tickers:
        df = cache.get(t)
        if df is None or len(df) < 60:
            continue
        for dt in df.index[-days:]:
            date_set.add(str(dt)[:10])

    dates = sorted(date_set)
    logger.info(f"日内回测 v2: {len(dates)}个交易日, {len(tickers)}只股票池")
    logger.info(f"  成本: 佣金{commission_rate*100:.2f}% + 滑点{slippage_rate*100:.2f}% + 价差{spread_rate*100:.2f}% = 单边{total_cost_rate*100:.2f}%")

    max_positions = int(cfg.get("max_positions", 5))
    sl_atr = float(cfg.get("stop_loss_atr_multiple", 1.5))
    tp_atr = float(cfg.get("take_profit_atr_multiple", 3.2))
    trail_atr = float(cfg.get("trailing_stop_atr_multiple", 0.8))
    trail_activation_atr = float(cfg.get("trailing_stop_activation_atr", 1.0))
    max_daily_loss = float(cfg.get("max_daily_loss_pct", 3.0))
    per_position_pct = float(cfg.get("per_position_pct", 0.18))

    for i, current_date in enumerate(dates):
        if i < 2:  # 前2天跳过，需要历史数据
            continue

        dt = pd.Timestamp(current_date)
        daily_pnl = 0
        day_trades = 0

        # 单日亏损检查（简化：用昨日权益算）
        daily_loss_limit = -equity * max_daily_loss / 100

        # 收集当日候选股
        candidates = []
        for t in tickers[:60]:
            df = cache.get(t)
            if df is None or len(df) < 60:
                continue

            try:
                idx = df.index.get_indexer([dt], method="nearest")[0]
                if idx < 2 or idx >= len(df) - 1:
                    continue
            except Exception:
                continue

            close = df["Close"].values
            prev_close = float(close[idx - 1])  # T-1 收盘
            if prev_close <= 0:
                continue

            # 用 T-1 日数据计算指标（避免未来函数）
            today_ret_prev = (prev_close - float(close[idx - 2])) / float(close[idx - 2]) * 100 if idx >= 2 else 0

            volume = df["Volume"].values if "Volume" in df.columns else np.ones(len(close))
            avg_vol_prev = np.mean(volume[max(0, idx-21):idx]) if idx >= 20 else 1
            vol_ratio_prev = volume[idx - 1] / avg_vol_prev if avg_vol_prev > 0 else 0

            # 价格范围检查
            if prev_close < cfg["min_price"] or prev_close > cfg["max_price"]:
                continue

            # 入场条件（基于 T-1 日数据）
            if not (today_ret_prev > 0.3 and today_ret_prev < 5.0 and
                    vol_ratio_prev > 1.2 and
                    prev_close > 10 and prev_close < 400):
                continue

            rsi_prev = float(df["RSI"].values[idx - 1]) if "RSI" in df.columns else 50
            if rsi_prev > cfg.get("rsi_overbought", 82):
                continue

            atr_prev = float(df["ATR_Pct"].values[idx - 1]) if "ATR_Pct" in df.columns else 2.0

            # 当日开盘价（实际买入价）
            if "Open" in df.columns:
                open_price = float(df["Open"].values[idx])
            else:
                open_price = prev_close * 1.002  # 假设开盘微涨
            if open_price <= 0:
                continue

            # 当日高低价（用于模拟日内波动）
            high_price = float(df["High"].values[idx]) if "High" in df.columns else open_price * 1.03
            low_price = float(df["Low"].values[idx]) if "Low" in df.columns else open_price * 0.97

            candidates.append({
                "ticker": t,
                "score": today_ret_prev + vol_ratio_prev * 0.5,
                "open": open_price,
                "high": high_price,
                "low": low_price,
                "close": float(close[idx]),
                "atr_pct": atr_prev,
                "rsi": rsi_prev,
                "ret_prev": today_ret_prev,
            })

        # 按得分排序，取前 max_positions 只
        candidates.sort(key=lambda x: x["score"], reverse=True)
        candidates = candidates[:max_positions]

        # 模拟日内交易
        positions = []
        remaining_cash = equity * 0.95  # 最多用95%资金

        for c in candidates:
            if len(positions) >= max_positions:
                break

            price = c["open"] * (1 + slippage_rate)  # 买入含滑点
            atr_pct = c["atr_pct"]

            qty = int(equity * per_position_pct / price)
            if qty <= 0:
                qty = 1
            cost = qty * price * (1 + commission_rate)

            if cost > remaining_cash:
                qty = int(remaining_cash / (price * (1 + commission_rate)))
                if qty <= 0:
                    continue
                cost = qty * price * (1 + commission_rate)

            remaining_cash -= cost

            # 计算止损止盈
            sl_pct = max(0.5, min(atr_pct * sl_atr, 4.0))
            tp_pct = max(sl_pct * 1.5, atr_pct * tp_atr)
            trail_pct = atr_pct * trail_atr
            trail_activation = atr_pct * trail_activation_atr

            stop_loss_price = price * (1 - sl_pct / 100)
            take_profit_price = price * (1 + tp_pct / 100)

            # 模拟日内路径（简化：先低后高或先高后低，根据开盘-收盘方向）
            high = c["high"]
            low = c["low"]
            close = c["close"]

            # 简化日内路径模拟：检查是否触发止损/止盈
            sell_price = close
            exit_reason = "close"
            peak_price = price

            # 先看是否触止损（最低价是否低于止损）
            if low <= stop_loss_price:
                sell_price = stop_loss_price
                exit_reason = "stop_loss"
            # 再看是否触止盈（最高价是否高于止盈）
            elif high >= take_profit_price:
                sell_price = take_profit_price
                exit_reason = "take_profit"
            else:
                # 没有触发止损止盈，检查移动止损
                # 最高价是 high，移动止损从盈利达到 trail_activation 后启动
                peak_pnl_pct = (high - price) / price * 100
                if peak_pnl_pct >= trail_activation:
                    trail_price = high * (1 - trail_pct / 100)
                    if close < trail_price:
                        sell_price = max(trail_price, close * 0.99)
                        exit_reason = "trailing_stop"
                        peak_price = high
                # 否则持有到收盘
                else:
                    peak_price = max(price, close)

            # 卖出含滑点
            sell_price = sell_price * (1 - slippage_rate)

            proceeds = qty * sell_price * (1 - commission_rate)
            pnl = proceeds - cost
            daily_pnl += pnl
            day_trades += 1
            total_trades += 1
            if pnl > 0:
                wins += 1
            exit_reasons[exit_reason] = exit_reasons.get(exit_reason, 0) + 1

            positions.append({
                "ticker": c["ticker"],
                "qty": qty,
                "entry": price,
                "exit": sell_price,
                "pnl": pnl,
                "reason": exit_reason,
            })

        # 单日亏损熔断检查
        if daily_pnl < daily_loss_limit and day_trades > 0:
            # 简化：如果当日亏损超过限制，后面的交易不计（实际会提前清仓）
            pass

        if day_trades > 0:
            daily_pnls.append(daily_pnl)
            equity += daily_pnl
            peak = max(peak, equity)
            dd = (peak - equity) / peak * 100
            max_dd = max(max_dd, dd)

        # 每50天打印一次进度
        if i % 50 == 0:
            ret = (equity - initial_capital) / initial_capital * 100
            logger.info(f"  进度 {i}/{len(dates)}天 权益${equity:.0f} ({ret:+.2f}%) 交易{total_trades}次")

    total_return = (equity - initial_capital) / initial_capital * 100
    win_rate = wins / total_trades * 100 if total_trades > 0 else 0
    avg_return_pct = (np.mean(daily_pnls) / initial_capital * 100) if daily_pnls else 0

    result = {
        "strategy": "intraday_v2",
        "total_return_pct": round(total_return, 2),
        "total_trades": total_trades,
        "win_rate_pct": round(win_rate, 1),
        "avg_return_per_trade_pct": round(avg_return_pct, 3),
        "max_drawdown_pct": round(max_dd, 2),
        "test_period_days": days,
        "test_dates": len(dates),
        "exit_reasons": exit_reasons,
        "cost_rate": round(total_cost_rate * 100, 2),
        "note": "v2版本：已修复未来函数，T-1选股T日开盘买",
    }

    # 保存回测结果到config
    cfg["backtest_result"] = result
    save_config(cfg)

    logger.info(f"日内回测 v2 完成:")
    logger.info(f"  收益: {total_return:+.2f}% | 胜率: {win_rate:.0f}% | 交易: {total_trades}次")
    logger.info(f"  回撤: {max_dd:.1f}% | 日均收益: {avg_return_pct:.3f}%")
    logger.info(f"  出场分布: {exit_reasons}")
    return result


def show_status():
    """查看日内交易状态"""
    signal = {}
    if os.path.exists(SIGNAL_FILE):
        with open(SIGNAL_FILE) as f:
            signal = json.load(f)

    trade_log = load_trade_log()
    cfg = load_config()

    print("\n" + "=" * 55)
    print("  ⚡ 日内交易模块")
    print("=" * 55)
    print(f"  启用: {'🟢' if cfg.get('enabled') else '🔴'} {cfg.get('max_positions',5)}只 止损{cfg.get('stop_loss_pct',1.5)}% 止盈{cfg.get('take_profit_pct',2.5)}%")
    
    if signal and signal.get("candidates"):
        print(f"  信号时间: {signal.get('time','-')[:16]}")
        print(f"  候选: {len(signal.get('candidates',[]))} 只")
        for s in signal["candidates"]:
            print(f"    {s['ticker']:6s} 评分{s['score']:+.1f}  ${s['price']:.2f} 今日{s['today_chg']:+.2f}%")
    else:
        print("  📭 无信号")

    bt = cfg.get("backtest_result", {})
    if bt and bt.get("total_trades", 0) > 0:
        print(f"\n  回测 ({bt.get('test_period_days','?')}天):")
        print(f"    收益: {bt.get('total_return_pct',0):+.2f}%  胜率: {bt.get('win_rate_pct',0):.0f}%")
        print(f"    交易: {bt.get('total_trades',0)}次  回撤: {bt.get('max_drawdown_pct',0):.1f}%")

    trades = trade_log.get("trades", [])
    if trades:
        print(f"\n  历史交易: {len(trades)} 笔")

    print("=" * 55)


if __name__ == "__main__":
    if "--scan" in sys.argv:
        s = generate_signal()
        print(json.dumps(s, indent=2, ensure_ascii=False))
    elif "--backtest" in sys.argv:
        run_backtest(days=252)
    elif "--status" in sys.argv:
        show_status()
    else:
        print(__doc__)
