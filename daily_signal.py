"""
每日信号输出系统
"""

import logging
import sys
import os
from datetime import datetime
import json
import pickle
import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s", stream=sys.stdout)
logger = logging.getLogger("quant.signal")

from data_prod import load_price_cache, compute_indicators
from quality_factor import compute_quality_scores
from multi_asset import multi_asset_signal

_alpha_manager_loaded = False
_fred_loaded = False
try:
    from alpha_manager import get_alpha_manager
    _alpha_manager_loaded = True
except Exception:
    pass
try:
    from fred_data import get_macro_temperature
    _fred_loaded = True
except Exception:
    pass

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "signals")
os.makedirs(OUTPUT_DIR, exist_ok=True)

SPY_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data_cache/spy_cache.pkl")
MAX_POS = 8


def _update_realtime_prices(cache: dict, max_tickers: int = 100) -> dict:
    """
    用Alpaca实时API更新缓存中每只股票的最新价格。
    如果Alpaca不可用直接返回缓存（不影响信号生成）。
    """
    KEY = os.environ.get("ALPACA_API_KEY_ID", "")
    SECRET = os.environ.get("ALPACA_SECRET_KEY", "")
    if not KEY or not SECRET:
        return cache

    import requests
    base = "https://data.alpaca.markets"
    auth = (KEY, SECRET)

    # 快速检查 Alpaca 是否可达
    try:
        requests.get(f"{base}/v2/stocks/AAPL/trades/latest", auth=auth, timeout=3)
    except:
        logger.warning("Alpaca 数据API不可达，跳过实时更新")
        return cache

    tickers = sorted(cache.keys())[:max_tickers]
    logger.info(f"实时数据: {len(tickers)}只...")
    updated = 0

    for sym in tickers:
        df = cache.get(sym)
        if df is None:
            continue
        try:
            r = requests.get(f"{base}/v2/stocks/{sym}/trades/latest",
                             auth=auth, timeout=5)
            if r.status_code == 200:
                t = r.json().get("trade", {})
                price = float(t.get("p", 0))
                ts = t.get("t", "")
                volume = int(t.get("s", 0))
                if price > 0 and ts:
                    dt = pd.Timestamp(ts).tz_convert("UTC").tz_localize(None)
                    last_dt = df.index[-1]
                    if dt > last_dt:
                        nr = pd.DataFrame([[price, price, price, price, volume]],
                                          columns=df.columns, index=[dt])
                        cache[sym] = pd.concat([df, nr])
                        updated += 1
        except:
            pass

        if updated > 0 and updated % 20 == 0:
            pass  # silent
    
    if updated > 0:
        logger.info(f"实时更新: {updated}只")
    else:
        logger.info("缓存已是最新，无需更新")
    return cache


import datetime as _dt

# 加载因子权重
def load_factor_weights() -> dict:
    import os, json
    wf = "config/factor_weights.json"
    if os.path.exists(wf):
        with open(wf) as f:
            return json.load(f)
    return {"momentum": 45, "quality": 25, "trend": 13, "value": 8, "lowvol": 5, "volume": 4}

_ts = _dt.datetime.now()

def generate_signals(use_cached_quality=True):
    import datetime as _dt
    
    # 0. 增量更新数据（后台静默执行，不阻塞）- 临时禁用，避免卡住
    # try:
    #     import subprocess, sys, threading
    #     def _bg_update():
    #         try:
    #             subprocess.run(
    #                 [sys.executable, "data_update.py"],
    #                 capture_output=True, timeout=120
    #             )
    #         except:
    #             pass
    #     t = threading.Thread(target=_bg_update, daemon=True)
    #     t.start()
    # except:
    #     pass

    ts = _dt.datetime.now()
    dt_str = _dt.datetime.now().strftime("%Y-%m-%d")
    weekday = _dt.datetime.now().weekday()
    logger.info(f"信号: {dt_str}")

    # 1. 加载缓存
    logger.info("Step 1: 加载缓存")
    cache = load_price_cache()
    if not cache:
        logger.error("无数据"); return
    logger.info(f"  缓存加载完成: {len(cache)}只")

    # 1.5 实时价格更新（只更新Top30，加快速度）
    # cache = _update_realtime_prices(cache, max_tickers=30)

    # 2. SPY大盘——优先用真实SPY，回退到合成
    logger.info("Step 2: 获取SPY")
    spy = None
    try:
        from spy_source import get_spy
        spy = get_spy()
        if spy is not None:
            spy = compute_indicators(spy)
        logger.info(f"  SPY获取完成: {spy is not None}")
    except Exception as e:
        logger.info(f"  SPY获取失败: {e}")

    if spy is None or len(spy) < 50:
        # 备选：从个股缓存构造合成SPY
        closes = {}
        for t, df in cache.items():
            if df is None or len(df) < 200: continue
            for date, row in df.tail(500).iterrows():
                d = str(date)[:10]
                closes.setdefault(d, []).append(row["Close"])
        dates = sorted(closes.keys())
        spy = pd.DataFrame({"Close": [np.mean(closes[d]) for d in dates]},
                           index=pd.to_datetime(dates)).sort_index()
        spy = compute_indicators(spy)

    if spy is None or len(spy) < 50:
        logger.error("SPY不可用"); return

    ls = spy.iloc[-1]
    spy_price = ls["Close"]
    sma20, sma50, sma200 = ls.get("SMA20",0), ls.get("SMA50",0), ls.get("SMA200",0)
    rsi = ls.get("RSI", 50)
    atr = ls.get("ATR_Pct", 0)
    
    # 4态择时
    uptrend = sma20 > sma50 > sma200
    bearish = spy_price < sma200 * 0.85 if sma200 > 0 else False
    extreme = rsi > 85
    # 高波震荡：多头但波动加剧
    high_vol = atr > 1.5 if not pd.isna(atr) else False
    choppy = uptrend and (high_vol or rsi > 72)

    if bearish:
        ml, ma = "🔴 熊市", "空仓"
    elif extreme:
        ml, ma = "🔴 极端过热", "减仓25%"
    elif choppy:
        ml, ma = "🟡 震荡偏多", "半仓操作"
    elif uptrend:
        ml, ma = "🟢 多头", "正常买入"  
    else:
        ml, ma = "⚪ 震荡", "部分仓位"

    # 3. 多资产信号
    logger.info("Step 3: 多资产信号")
    try:
        multi = multi_asset_signal()
        logger.info(f"  多资产信号完成: {multi is not None}")
    except Exception as e:
        multi = None
        logger.info(f"  多资产信号失败: {e}")
    if multi and multi.get("top2"):
        top_names = [ASSETS.get(s, {}).get("name", s) if False else s for s in multi["top2"]]

    # 4. 质量分
    logger.info("Step 4: 质量分")
    qc = f"{OUTPUT_DIR}/quality_scores.json"
    if use_cached_quality and os.path.exists(qc):
        logger.info("  使用缓存质量分")
        with open(qc) as f:
            quality = json.load(f)
    else:
        logger.info("  计算质量分")
        quality = compute_quality_scores(cache)
        with open(qc, "w") as f:
            json.dump(quality, f, default=str)
    logger.info(f"  质量分完成: {len(quality)}只")

    # 4. 评分
    logger.info("Step 5: 评分")
    tickers = sorted(cache.keys())[:200]
    scores = []
    from time_utils import align_ts
    weights = load_factor_weights()
    for i, t in enumerate(tickers):
        if i % 10 == 0:
            logger.info(f"  评分进度: {i}/{len(tickers)}")
        df = cache.get(t)
        if df is None: continue
        from time_utils import align_ts
        target_ts = align_ts(dt_str, df.index)
        idx = df.index.get_indexer([target_ts], method="nearest")
        if idx[0] < 0 or idx[0] >= len(df): continue
        row = df.iloc[idx[0]]
        c = row["Close"]
        mom = row.get("Momentum_12M", np.nan)
        s200 = row.get("SMA200", np.nan)
        rsi_v = row.get("RSI", np.nan)
        atr = row.get("ATR_Pct", np.nan)
        vr = row.get("Volume_Ratio", np.nan)
        if pd.isna(mom) or mom <= 0 or pd.isna(s200) or c < s200: continue
        if not pd.isna(rsi_v) and rsi_v > 80: continue

        # 从factor_weights.json读取动态权重
        weights = load_factor_weights()
        w_mom = weights.get("momentum", 45)
        w_qual = weights.get("quality", 25)
        w_trend = weights.get("trend", 15)
        w_value = weights.get("value", 8)
        w_lowvol = weights.get("lowvol", 7)
        w_volume = weights.get("volume", 6)

        ms = min(w_mom, mom * w_mom)
        qs = quality.get(t, 15) / 100 * w_qual if quality.get(t, 0) > 0 else 15 / 100 * w_qual
        ts = 12 if c > row.get("SMA20",0) > row.get("SMA50",0) and not pd.isna(row.get("SMA20")) else 6
        ts += 4 if not pd.isna(vr) and vr > 1.2 else 0
        ts = ts / 20 * w_trend
        # 价值 + 低波：从quality分派生（低PE>高分, 低ATR>高分）
        # 成交量独立因子
        vs = 0
        if not pd.isna(vr):
            if vr > 1.5: vs += w_volume
            elif vr > 1.2: vs += w_volume * 0.6
            elif vr < 0.5: vs -= w_volume * 0.3
        # 低波 + 价值
        lv = 0
        if not pd.isna(atr):
            if atr < 2.0: lv += w_lowvol
            elif atr < 3.5: lv += w_lowvol * 0.6
            elif atr < 5.0: lv += w_lowvol * 0.3
        if not pd.isna(rsi_v) and 30 < rsi_v < 70:
            lv += w_value * 0.5
        else:
            lv += w_value * 0.2
        scores.append({
            "ticker": t, "score": round(ms+qs+ts+vs+lv, 1), "price": round(c,2),
            "mom": round(mom*100,1), "quality": round(qs,1),
            "volume": round(vs,1), "value_lv": round(lv,1),
            "rsi": round(rsi_v,0) if not pd.isna(rsi_v) else None,
            "atr": round(atr,1) if not pd.isna(atr) else None,
        })
    scores.sort(key=lambda x: -x["score"])
    logger.info(f"  评分完成: {len(scores)}只")

    # 4.6 AlphaManager 339因子增强 — 对Top20候选股票计算全因子并融合（临时禁用，太慢，单只48秒）
    logger.info("Step 6: AlphaManager (已禁用)")

    # 4.7 FRED宏观温度过滤 — 根据宏观环境动态调整仓位
    macro_info = None
    macro_temp = 50
    macro_position_adjust = 1.0
    if _fred_loaded:
        try:
            macro_info = get_macro_temperature()
            macro_temp = macro_info.get("macro_temperature", 50)
            if macro_temp < 25:
                macro_position_adjust = 0.4
            elif macro_temp < 40:
                macro_position_adjust = 0.7
            elif macro_temp < 60:
                macro_position_adjust = 1.0
            else:
                macro_position_adjust = 1.0
            logger.info(f"FRED宏观温度: {macro_temp:.0f}/100, 仓位系数: {macro_position_adjust}")
        except Exception as e:
            logger.debug(f"FRED宏观温度获取跳过: {e}")

    # 4.5 因子排名增强 — 用当前最有效的因子重新调整Top候选
    try:
        ranking_file = "config/factor_ranking.json"
        if os.path.exists(ranking_file):
            with open(ranking_file) as f:
                ranking_data = json.load(f)
            top_factors = ranking_data.get("top_factors", [])
            if len(top_factors) >= 3:
                from factor_miner import FactorMiner
                # 计算增强分
                miner = FactorMiner(cache)
                tickers_to_enhance = [s["ticker"] for s in scores[:20]]
                factor_df = miner.compute_all(tickers=tickers_to_enhance, spy_df=spy if spy is not None else None)
                if not factor_df.empty:
                    available = [f for f in top_factors if f in factor_df.columns]
                    if len(available) >= 3:
                        # 标准化后加权
                        factor_df["enhance_score"] = 0
                        count = 0
                        for f in available:
                            col = factor_df[f]
                            valid = col.dropna()
                            if len(valid) < 5:
                                continue
                            mean, std = valid.mean(), valid.std()
                            if std > 0:
                                factor_df["enhance_score"] += (col - mean) / std
                                count += 1
                        if count > 0:
                            factor_df["enhance_score"] /= count
                            # 把增强分合并到scores
                            enhance_map = dict(zip(factor_df["ticker"], factor_df["enhance_score"]))
                            for s in scores:
                                es = enhance_map.get(s["ticker"])
                                if es is not None and not pd.isna(es):
                                    s["enhance_score"] = round(es, 2)
                            # 重新排序：原评分占70%，增强分占30%
                            has_enhance = [s for s in scores if "enhance_score" in s]
                            if has_enhance:
                                max_es = max(abs(s.get("enhance_score", 0)) for s in has_enhance)
                                if max_es > 0:
                                    for s in has_enhance:
                                        normalized_es = s["enhance_score"] / max_es
                                        s["score"] = round(s["score"] * 0.7 + normalized_es * 30, 1)
                                scores.sort(key=lambda x: -x["score"])
                                logger.info(f"因子排名增强: {len(available)}个有效因子")
    except Exception as e:
        logger.debug(f"因子排名增强跳过: {e}")

    # 5. 输出
    print(f"\n{'='*65}")
    print(f"  📊 Multi-Factor Momentum+ - 每日信号")
    print(f"  {dt_str} (周{'一二三四五六日'[weekday]})")
    print(f"{'='*65}")
    print(f"\n📈 大盘: SPY ${spy_price:.0f} | RSI {rsi:.0f} | {ml}")
    print(f"  {sma20:.0f}/{sma50:.0f}/{sma200:.0f} | 建议: {ma}")

    # 多资产轮动
    try:
        multi = multi_asset_signal()
    except:
        multi = None
    if multi and multi.get("top2"):
        from multi_asset import ASSETS as MA
        names = [f"{MA.get(s,{}).get('name',s)}" for s in multi["top2"]]
        print(f"\n🌍 多资产轮动: {' + '.join(names)}")
    else:
        print(f"\n🌍 多资产轮动: 数据不可用")

    # Top10
    print(f"\n🏆 全市场评分 Top 10")
    print(f"  {'股票':>6} {'评分':>6} {'价格':>8} {'动量%':>7} {'质量分':>6} {'RSI':>4}")
    for s in scores[:10]:
        print(f"  {s['ticker']:>6} {s['score']:>6.1f} ${s['price']:>7.2f} "
              f"{s['mom']:>+6.1f}% {s['quality']:>6.1f} {s['rsi'] or '':>4}")

    # 买入候选
    cand = []
    if not bearish and not extreme:
        held = set()
        cand = [s for s in scores if s["ticker"] not in held][:5]
        # 财报过滤（优先Finnhub）
        try:
            from earnings_filter import EarningsFilter
            ef = EarningsFilter()
            before = len(cand)
            cand = ef.filter_buys(cand)
            filtered_n = before - len(cand)
            if filtered_n > 0:
                print(f"\n📅 财报过滤: 排除了 {filtered_n} 只临近财报股票")
        except Exception as e:
            logger.warning(f"财报过滤失败: {str(e)[:80]}")

        # AI 辅助分析（如果启用）
        try:
            from ai_assist import ai_filter_candidates
            before = len(cand)
            market_ctx = {"spy_price": float(spy_price), "rsi": float(rsi),
                          "trend": ml, "action": ma}
            cand = ai_filter_candidates(cand, market_ctx)
            ai_filtered = before - len(cand)
            if ai_filtered > 0:
                print(f"\n🤖 AI分析: 过滤了 {ai_filtered} 只")
        except Exception as e:
            logger.debug(f"AI分析跳过: {e}")

        print(f"\n🟢 买入候选 Top 5")
        print(f"  {'股票':>6} {'评分':>6} {'价格':>8} {'动量%':>7} {'质量分':>6}")
        for s in cand:
            print(f"  {s['ticker']:>6} {s['score']:>6.1f} ${s['price']:>7.2f} "
                  f"{s['mom']:>+6.1f}% {s['quality']:>6.1f}")
    else:
        print(f"\n⚠️ 大盘风险，不买入")

    # 保存
    output = {
        "date": dt_str,
        "market": {"spy": float(spy_price), "rsi": float(rsi), "trend": ml, "action": ma},
        "macro": {
            "temperature": float(macro_temp),
            "position_adjust": float(macro_position_adjust),
            "info": macro_info,
        } if macro_info else None,
        "top_scores": scores[:10],
        "buy_candidates": cand,
    }
    op = f"{OUTPUT_DIR}/signal_{dt_str}.json"
    with open(op, "w") as f:
        json.dump(output, f, indent=2, default=str)
    logger.info(f"已保存: {op}")

    # === 写入信号总线 ===
    try:
        import signal_bus
        signal_bus.write_signal("conservative", output.get("top_scores", scores[:5]),
                                market=output.get("market"),
                                buy_list=[s["ticker"] for s in output.get("buy_candidates", [])],
                                metadata={"signal_file": op, "scores_count": len(scores)})
        logger.info("  ✅ 已写入信号总线")
    except Exception as e:
        logger.debug(f"  信号总线写入失败(不影响): {e}")

    logger.info(f"耗时: {(_dt.datetime.now()-_ts).total_seconds():.1f}s")
    return output


if __name__ == "__main__":
    generate_signals()
