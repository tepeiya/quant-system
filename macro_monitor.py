"""
宏观因子模块（快速版） - 美债/美元/黄金/通胀
=================================
数据源：FRED + yfinance
响应超时控制：5秒内没数据就返回默认值

优先使用 fred_data.py 模块（更完整的FRED数据）
"""

import os, json, logging
from datetime import datetime

logger = logging.getLogger("quant.macro")

CACHE_FILE = "data_cache/macro_cache.json"


def _build_from_fred() -> dict:
    """从 fred_data.py 构建宏观数据（优先使用）"""
    try:
        from fred_data import get_market_macro, get_macro_temperature, get_yield_curve
        import numpy as np

        # 获取完整宏观数据
        macro_data = get_market_macro()
        yield_curve = macro_data.get("yield_curve", {})
        yields = yield_curve.get("yields", {})
        spreads = yield_curve.get("spreads", {})

        # 获取宏观温度
        macro_temp = get_macro_temperature()
        temp_score = macro_temp.get("macro_temperature", 50)

        # 构建债券数据
        y10 = yields.get("10Y", 0) or 0
        spread_2_10 = spreads.get("2Y-10Y", 0) or 0
        bond_score = max(0, min(100, (5.5 - y10) * 20)) if y10 else 50

        # 构建美元数据
        dxy = macro_data.get("dxy") or 0
        vix = macro_data.get("vix") or 0
        dxy_score = max(0, min(100, (110 - dxy) * 5)) if dxy else 50

        # 构建黄金数据
        gold = macro_data.get("gold") or 0
        gold_score = 50  # 黄金评分需要结合实际利率综合判断

        # 构建通胀数据
        inflation = macro_data.get("inflation", {})
        cpi = inflation.get("cpi_yoy", 0) or 0
        ppi = inflation.get("ppi_yoy", 0) or 0
        if cpi < 2:
            inf_score = 80
        elif cpi < 4:
            inf_score = 60
        elif cpi < 6:
            inf_score = 40
        else:
            inf_score = 20

        # 判断曲线是否倒挂
        inverted = spread_2_10 < 0

        # 综合评分 = 宏观温度 * 0.6 + 债券评分 * 0.2 + 美元评分 * 0.2
        total_score = round(temp_score * 0.6 + bond_score * 0.2 + dxy_score * 0.2, 1)

        # 建议
        if total_score >= 70:
            verdict = "🟢 偏多"
            advice = "宏观环境有利，可适当增加风险敞口"
        elif total_score >= 50:
            verdict = "⚪ 中性"
            advice = "宏观中性，保持现有仓位"
        elif total_score >= 30:
            verdict = "🟠 偏弱"
            advice = "宏观偏弱，控制仓位谨慎操作"
        else:
            verdict = "🔴 偏空"
            advice = "宏观严峻，减少风险敞口"

        result = {
            "total_score": total_score,
            "verdict": verdict,
            "advice": advice,
            "bond": {
                "score": round(bond_score, 1),
                "10y_yield": round(y10, 2) if y10 else 0,
                "10y2y_spread": round(spread_2_10, 2) if spread_2_10 else 0,
                "inverted": inverted,
                "curve_shape": yield_curve.get("shape_desc", "?"),
            },
            "dollar": {
                "score": round(dxy_score, 1),
                "dxy": round(dxy, 2) if dxy else 0,
                "vix": round(vix, 2) if vix else 0,
                "above_200ma": True,  # fred_data不提供200ma
                "trend": "🟢 强" if dxy > 100 else "⚪ 中性",
            },
            "gold": {
                "score": round(gold_score, 1),
                "gld": round(gold, 2) if gold else 0,
                "real_rate": 0,  # 需要10Y国债收益率减去通胀计算
                "gld_trend": "?" if not gold else ("🟢 强势" if gold > 2000 else "⚪ 正常"),
            },
            "inflation": {
                "score": round(inf_score, 1),
                "cpi_yoy": round(cpi, 2) if cpi else 0,
                "ppi_yoy": round(ppi, 2) if ppi else 0,
            },
            "macro_temp": macro_temp,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        return result
    except Exception as e:
        logger.warning(f"fred_data获取失败: {e}")
        return None


def macro_summary() -> dict:
    """宏观概要（带缓存，优先使用fred_data.py）"""
    # 先检查缓存（1小时内有效）
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE) as f:
                cache = json.load(f)
            cache_time = cache.get("_time", "")
            if cache_time and (datetime.now() - datetime.strptime(cache_time[:19], "%Y-%m-%d %H:%M:%S")).seconds < 3600:
                return cache.get("data", {})
        except:
            pass

    # 优先使用fred_data.py（更完整的FRED数据）
    result = _build_from_fred()
    if result:
        try:
            os.makedirs("data_cache", exist_ok=True)
            with open(CACHE_FILE, "w") as f:
                json.dump({"_time": str(datetime.now()), "data": result}, f, indent=2)
        except:
            pass
        return result

    # fallback: 使用原来的快速获取逻辑
    result = _fetch_fallback()

    # 缓存
    try:
        os.makedirs("data_cache", exist_ok=True)
        with open(CACHE_FILE, "w") as f:
            json.dump({"_time": str(datetime.now()), "data": result}, f, indent=2)
    except:
        pass

    return result


def _fetch_fallback() -> dict:
    """降级方案：使用原来的快速获取逻辑（不需要fred_data）"""
    import threading, numpy as np
    import pandas as pd

    # 默认值
    result = {
        "total_score": 0,
        "verdict": "⚪ 中性",
        "advice": "谨慎乐观，控制仓位",
        "bond": {"score": 0, "10y_yield": 0, "10y2y_spread": 0, "inverted": False},
        "dollar": {"score": 0, "dxy": 0, "vix": 0, "above_200ma": True, "trend": "?"},
        "gold": {"score": 0, "gld": 0, "real_rate": 0, "gld_trend": "?"},
        "inflation": {"score": 0, "cpi_yoy": 0},
        "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }

    try:
        results = {}

        def get_bond():
            try:
                import requests
                api_key = os.environ.get("FRED_API_KEY", "")
                if api_key:
                    r = requests.get(
                        f"https://api.stlouisfed.org/fred/series/observations?series_id=GS10&api_key={api_key}&file_type=json&sort_order=desc&limit=1",
                        timeout=3
                    )
                    if r.status_code == 200:
                        data = r.json()
                        obs = data.get("observations", [])
                        if obs:
                            y = float(obs[0]["value"])
                            results["10y"] = y
            except:
                pass

        def get_dollar():
            try:
                import yfinance as yf
                dxyn = yf.download("DX-Y.NYB", period="1mo", progress=False, auto_adjust=True)
                vix = yf.download("^VIX", period="1mo", progress=False, auto_adjust=True)
                if dxyn is not None and len(dxyn) > 0:
                    if isinstance(dxyn.columns, pd.MultiIndex):
                        dxyn.columns = dxyn.columns.get_level_values(0)
                    results["dxy"] = float(dxyn["Close"].iloc[-1])
                    sma200 = dxyn["Close"].rolling(200).mean().iloc[-1]
                    if not np.isnan(sma200):
                        results["dxy_above_200"] = results["dxy"] > sma200
                if vix is not None and len(vix) > 0:
                    if isinstance(vix.columns, pd.MultiIndex):
                        vix.columns = vix.columns.get_level_values(0)
                    results["vix"] = float(vix["Close"].iloc[-1])
            except:
                pass

        threads = [
            threading.Thread(target=get_bond, daemon=True),
            threading.Thread(target=get_dollar, daemon=True),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=4)

        # 如果有数据，更新 result
        if "10y" in results:
            y = results["10y"]
            result["bond"]["10y_yield"] = round(y, 2)
            result["bond"]["score"] = max(0, min(100, (5.5 - y) * 20))

        if "dxy" in results:
            dxy = results["dxy"]
            result["dollar"]["dxy"] = round(dxy, 2)
            result["dollar"]["above_200ma"] = results.get("dxy_above_200", True)
            result["dollar"]["trend"] = "🟢 强" if results.get("dxy_above_200", True) else "🔴 弱"
            result["dollar"]["score"] = max(0, min(100, (110 - dxy) * 5))

        if "vix" in results:
            vix = results["vix"]
            result["dollar"]["vix"] = round(vix, 2)

        # 综合评分
        scores = [result["bond"]["score"], result["dollar"]["score"]]
        active = [s for s in scores if s > 0]
        result["total_score"] = round(sum(active) / len(active), 1) if active else 0

        if result["total_score"] >= 60:
            result["verdict"] = "🟢 偏多"
        elif result["total_score"] >= 40:
            result["verdict"] = "⚪ 中性"
        else:
            result["verdict"] = "🔴 偏空"

    except Exception as e:
        logger.warning(f"宏观数据获取失败: {e}")

    return result


if __name__ == "__main__":
    import json
    s = macro_summary()
    print(json.dumps(s, indent=2, ensure_ascii=False))
