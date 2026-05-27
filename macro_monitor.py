"""
宏观因子模块（快速版） - 美债/美元/黄金/通胀
=================================
数据源：FRED + yfinance
响应超时控制：5秒内没数据就返回默认值
"""

import os, json, logging
from datetime import datetime

logger = logging.getLogger("quant.macro")

CACHE_FILE = "data_cache/macro_cache.json"


def macro_summary() -> dict:
    """宏观概要（带5秒超时和缓存）"""
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

    # 默认值
    result = {
        "total_score": 0,
        "verdict": "⚪ 中性",
        "advice": "谨慎乐观，控制仓位",
        "bond": {"score": 0, "10y_yield": 0},
        "dollar": {"score": 0, "dxy": 0, "vix": 0, "above_200ma": True, "trend": "?"},
        "gold": {"score": 0, "gld": 0, "real_rate": 0, "gld_trend": "?"},
        "inflation": {"score": 0, "cpi_yoy": 0},
        "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }

    # 尝试快速获取数据
    try:
        import threading, numpy as np
        
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

    # 缓存
    try:
        os.makedirs("data_cache", exist_ok=True)
        with open(CACHE_FILE, "w") as f:
            json.dump({"_time": str(datetime.now()), "data": result}, f, indent=2)
    except:
        pass

    return result


if __name__ == "__main__":
    import json
    s = macro_summary()
    print(json.dumps(s, indent=2, ensure_ascii=False))
