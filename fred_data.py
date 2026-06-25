"""
FRED宏观数据模块 v1.0
=====================
从圣路易斯联储的FRED数据库获取宏观数据

功能：
1. 美债收益率曲线（1Y, 2Y, 5Y, 10Y, 30Y）
2. 美元指数（DXY）
3. 黄金价格（GC）
4. 通胀数据（CPI, PPI）
5. VIX恐慌指数
6. 宏观经济指标

配置：
- 环境变量 FRED_API_KEY（可选，用于提高请求限制）
- 默认使用公开数据
"""

import os
import json
import time
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

import requests

logger = logging.getLogger("quant.fred")

# FRED API配置
FRED_API_KEY = os.environ.get("FRED_API_KEY", "")
FRED_BASE_URL = "https://api.stlouisfed.org/fred"

# 缓存配置
CACHE_FILE = "data_cache/fred_cache.json"
CACHE_TTL = 3600  # 1小时更新一次


def _load_cache() -> Dict:
    """加载缓存"""
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE) as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"加载FRED缓存失败: {e}")
    return {}


def _save_cache(data: Dict):
    """保存缓存"""
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.warning(f"保存FRED缓存失败: {e}")


def _is_cache_valid(cache: Dict, key: str) -> bool:
    """检查缓存是否有效"""
    if key not in cache:
        return False
    
    cached_time = cache[key].get("timestamp", 0)
    if time.time() - cached_time > CACHE_TTL:
        return False
    
    return True


def fetch_fred_series(series_id: str, observation_start: str = None, observation_end: str = None) -> Optional[Dict]:
    """
    从FRED获取数据序列
    
    Args:
        series_id: FRED序列ID (如 "DGS10" 表示10年期国债收益率)
        observation_start: 开始日期 (YYYY-MM-DD)
        observation_end: 结束日期 (YYYY-MM-DD)
    
    Returns:
        包含日期和值的字典
    """
    if observation_start is None:
        # 默认获取最近3个月
        start = datetime.now() - timedelta(days=90)
        observation_start = start.strftime("%Y-%m-%d")
    
    if observation_end is None:
        observation_end = datetime.now().strftime("%Y-%m-%d")
    
    url = f"{FRED_BASE_URL}/series/observations"
    params = {
        "series_id": series_id,
        "observation_start": observation_start,
        "observation_end": observation_end,
        "api_key": FRED_API_KEY,
        "file_type": "json"
    }
    
    try:
        response = requests.get(url, params=params, timeout=10)
        
        if response.status_code == 429:
            logger.warning("FRED API请求超限，使用缓存数据")
            cache = _load_cache()
            return cache.get(series_id, {}).get("data")
        
        if response.status_code == 200:
            data = response.json()
            observations = data.get("observations", [])
            
            result = {
                "series_id": series_id,
                "name": data.get("seriestable", [{}])[0].get("title", series_id),
                "data": [(obs["date"], float(obs["value"]) if obs["value"] != "." else None) 
                         for obs in observations if obs["value"] != "."]
            }
            
            # 更新缓存
            cache = _load_cache()
            cache[series_id] = {
                "data": result,
                "timestamp": time.time()
            }
            _save_cache(cache)
            
            return result
        
        logger.error(f"FRED API错误: {response.status_code}")
        return None
        
    except Exception as e:
        logger.error(f"获取FRED数据失败 {series_id}: {e}")
        
        # 尝试返回缓存数据
        cache = _load_cache()
        if series_id in cache:
            logger.info(f"使用缓存数据: {series_id}")
            return cache[series_id]["data"]
        
        return None


def get_bond_yields() -> Dict[str, float]:
    """获取美国国债收益率"""
    yields = {}
    
    # 关键期限
    series = {
        "1Y": "DGS1",
        "2Y": "DGS2",
        "5Y": "DGS5",
        "10Y": "DGS10",
        "30Y": "DGS30"
    }
    
    for name, series_id in series.items():
        data = fetch_fred_series(series_id)
        if data and data["data"]:
            latest = data["data"][-1]
            yields[name] = latest[1]
    
    return yields


def get_yield_curve() -> Dict:
    """获取完整的收益率曲线"""
    yields = get_bond_yields()
    
    # 计算关键利差
    curve = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "yields": yields,
        "spreads": {}
    }
    
    # 2-10利差（衰退预警）
    if "2Y" in yields and "10Y" in yields:
        curve["spreads"]["2Y-10Y"] = yields["10Y"] - yields["2Y"]
    
    # 5-30利差
    if "5Y" in yields and "30Y" in yields:
        curve["spreads"]["5Y-30Y"] = yields["30Y"] - yields["5Y"]
    
    # 判断曲线形态
    if curve["spreads"].get("2Y-10Y", 0) > 0:
        curve["shape"] = "normal"
        curve["shape_desc"] = "正常曲线"
    elif curve["spreads"].get("2Y-10Y", 0) > -0.5:
        curve["shape"] = "flat"
        curve["shape_desc"] = "平坦曲线"
    else:
        curve["shape"] = "inverted"
        curve["shape_desc"] = "倒挂曲线 ⚠️"
    
    return curve


def get_vix() -> Optional[float]:
    """获取VIX恐慌指数"""
    data = fetch_fred_series("VIXCLS")
    if data and data["data"]:
        return data["data"][-1][1]
    return None


def get_dollar_index() -> Optional[float]:
    """获取美元指数"""
    # DXY指数
    data = fetch_fred_series("DTWEXBGS")
    if data and data["data"]:
        return data["data"][-1][1]
    return None


def get_gold_price() -> Optional[float]:
    """获取黄金价格（美元/盎司）"""
    data = fetch_fred_series("GOLDAMGBD228NLBM")
    if data and data["data"]:
        return data["data"][-1][1]
    return None


def get_inflation_data() -> Dict:
    """获取通胀数据"""
    inflation = {}
    
    # CPI同比
    cpi = fetch_fred_series("CPIAUCSL")
    if cpi and len(cpi["data"]) >= 12:
        # 计算同比
        current = cpi["data"][-1][1]
        year_ago = cpi["data"][-12][1]
        if year_ago and year_ago > 0:
            inflation["cpi_yoy"] = (current - year_ago) / year_ago * 100
            inflation["cpi_date"] = cpi["data"][-1][0]
    
    # PPI同比
    ppi = fetch_fred_series("PPIFIS")
    if ppi and len(ppi["data"]) >= 12:
        current = ppi["data"][-1][1]
        year_ago = ppi["data"][-12][1]
        if year_ago and year_ago > 0:
            inflation["ppi_yoy"] = (current - year_ago) / year_ago * 100
            inflation["ppi_date"] = ppi["data"][-1][0]
    
    return inflation


def get_macro_temperature() -> Dict:
    """
    计算宏观温度（综合评分）
    基于多个宏观指标的量化评分
    """
    score = 0
    details = {}
    
    # 1. 收益率曲线
    try:
        yields = get_yield_yields()
        if yields:
            # 2-10利差
            spread_2_10 = yields.get("10Y", 0) - yields.get("2Y", 0)
            
            if spread_2_10 > 0.5:
                # 正常曲线，经济健康
                score += 30
                details["yield_curve"] = {"value": spread_2_10, "score": 30, "desc": "正常"}
            elif spread_2_10 > 0:
                # 轻微平坦
                score += 15
                details["yield_curve"] = {"value": spread_2_10, "score": 15, "desc": "轻微平坦"}
            else:
                # 倒挂，衰退风险
                score -= 20
                details["yield_curve"] = {"value": spread_2_10, "score": -20, "desc": "倒挂⚠️"}
    except Exception as e:
        logger.warning(f"收益率分析失败: {e}")
    
    # 2. VIX恐慌指数
    try:
        vix = get_vix()
        if vix:
            if vix < 15:
                # 低波动，市场平静
                score += 20
                details["vix"] = {"value": vix, "score": 20, "desc": "低波动"}
            elif vix < 25:
                # 中等波动
                score += 10
                details["vix"] = {"value": vix, "score": 10, "desc": "中等"}
            else:
                # 高波动，市场恐慌
                score -= 30
                details["vix"] = {"value": vix, "score": -30, "desc": "高波动⚠️"}
    except Exception as e:
        logger.warning(f"VIX分析失败: {e}")
    
    # 3. 通胀水平
    try:
        inflation = get_inflation_data()
        if "cpi_yoy" in inflation:
            cpi = inflation["cpi_yoy"]
            if cpi < 2:
                # 低通胀，央行可宽松
                score += 15
                details["inflation"] = {"value": cpi, "score": 15, "desc": "低通胀"}
            elif cpi < 4:
                # 温和通胀
                score += 10
                details["inflation"] = {"value": cpi, "score": 10, "desc": "温和通胀"}
            elif cpi < 6:
                # 较高通胀
                score -= 10
                details["inflation"] = {"value": cpi, "score": -10, "desc": "较高通胀"}
            else:
                # 高通胀，央行紧缩
                score -= 25
                details["inflation"] = {"value": cpi, "score": -25, "desc": "高通胀⚠️"}
    except Exception as e:
        logger.warning(f"通胀分析失败: {e}")
    
    # 4. 美元强弱
    try:
        dxy = get_dollar_index()
        if dxy:
            if dxy < 95:
                # 美元偏弱，利于风险资产
                score += 10
                details["dxy"] = {"value": dxy, "score": 10, "desc": "美元偏弱"}
            elif dxy < 105:
                # 美元中性
                score += 5
                details["dxy"] = {"value": dxy, "score": 5, "desc": "美元中性"}
            else:
                # 美元强势，新兴市场压力
                score -= 15
                details["dxy"] = {"value": dxy, "score": -15, "desc": "美元强势⚠️"}
    except Exception as e:
        logger.warning(f"美元分析失败: {e}")
    
    # 标准化到0-100
    macro_temp = max(0, min(100, (score + 75)))
    
    # 判断宏观状态
    if macro_temp >= 75:
        macro_status = "🟢 宏观向好"
    elif macro_temp >= 50:
        macro_status = "🟡 宏观中性"
    elif macro_temp >= 25:
        macro_status = "🟠 宏观偏弱"
    else:
        macro_status = "🔴 宏观严峻"
    
    return {
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "macro_temperature": macro_temp,
        "raw_score": score,
        "status": macro_status,
        "details": details
    }


# ===== 便捷函数（简化接口）=====

def get_yield_yields() -> Dict[str, float]:
    """获取收益率（拼写修正别名）"""
    return get_bond_yields()


def get_market_macro() -> Dict:
    """获取市场宏观综合数据"""
    result = {
        "timestamp": datetime.now().isoformat(),
        "yield_curve": get_yield_curve(),
        "vix": get_vix(),
        "dxy": get_dollar_index(),
        "gold": get_gold_price(),
        "inflation": get_inflation_data(),
        "macro_temp": get_macro_temperature()
    }
    return result


# ===== 测试 =====

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print("\n📊 FRED宏观数据测试")
    print("=" * 50)
    
    # 收益率曲线
    curve = get_yield_curve()
    print(f"\n📈 收益率曲线 ({curve.get('date', 'N/A')})")
    for term, yield_val in curve.get("yields", {}).items():
        print(f"  {term}: {yield_val:.3f}%" if yield_val else f"  {term}: N/A")
    print(f"  形态: {curve.get('shape_desc', 'N/A')}")
    
    # VIX
    vix = get_vix()
    print(f"\n😱 VIX恐慌指数: {vix:.2f}" if vix else "\n😱 VIX: N/A")
    
    # 美元
    dxy = get_dollar_index()
    print(f"\n💵 美元指数: {dxy:.2f}" if dxy else "\n💵 美元指数: N/A")
    
    # 黄金
    gold = get_gold_price()
    print(f"\n🥇 黄金价格: ${gold:.2f}/盎司" if gold else "\n🥇 黄金价格: N/A")
    
    # 通胀
    inf = get_inflation_data()
    if inf:
        print(f"\n📊 通胀数据")
        print(f"  CPI同比: {inf.get('cpi_yoy', 0):.2f}%")
        print(f"  PPI同比: {inf.get('ppi_yoy', 0):.2f}%")
    
    # 宏观温度
    macro = get_macro_temperature()
    print(f"\n🌡️ 宏观温度")
    print(f"  综合评分: {macro['macro_temperature']:.0f}/100")
    print(f"  状态: {macro['status']}")
    
    print("\n" + "=" * 50)
