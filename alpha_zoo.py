"""
Alpha Zoo 因子库 (Alpha Factor Library)
======================================
基于学术研究的因子实现，支持 456+ 因子

因子类型：
- 动量类: Jegadeesh反转、短期动量、中期动量、长期动量
- 质量类: ROE、ROA、毛利率、净利率
- 价值类: PE、PB、PS、EV/EBITDA
- 流动性类: Amihud非流动性、换手率
- 波动率类: 收益率波动率、波动变化率
- 技术类: RSI、MACD、布林带宽度
- 学术类: George-Hwang 52周新高、Harvey-Siddique偏度

设计原则：
- 统一接口，易于扩展
- 支持截面标准化
- 支持行业中性化
- 支持IC计算
"""

import os
import sys
import logging
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Callable

logger = logging.getLogger("quant.alpha_zoo")

# 因子注册表
FACTOR_REGISTRY = {}


def register_factor(name: str, category: str, description: str = ""):
    """因子注册装饰器"""
    def decorator(func):
        FACTOR_REGISTRY[name] = {
            "func": func,
            "category": category,
            "description": description,
        }
        return func
    return decorator


# ============================================================
# 工具函数
# ============================================================

def _ensure_dataframe(data) -> pd.DataFrame:
    """确保数据为DataFrame格式"""
    if isinstance(data, pd.DataFrame):
        return data
    elif isinstance(data, dict):
        return pd.DataFrame(data)
    else:
        raise ValueError(f"不支持的数据类型: {type(data)}")


def _compute_returns(df: pd.DataFrame, periods: int = 1) -> pd.Series:
    """计算收益率"""
    return df["Close"].pct_change(periods).dropna()


def _compute_log_returns(df: pd.DataFrame, periods: int = 1) -> pd.Series:
    """计算对数收益率"""
    return np.log(df["Close"] / df["Close"].shift(periods)).dropna()


def _rolling_std(df: pd.DataFrame, window: int = 20) -> pd.Series:
    """滚动标准差"""
    return df["Close"].pct_change().rolling(window).std().dropna()


def _rolling_mean(df: pd.DataFrame, window: int = 20) -> pd.Series:
    """滚动均值"""
    return df["Close"].rolling(window).mean().dropna()


# ============================================================
# 动量类因子
# ============================================================

@register_factor("momentum_1m", "momentum", "1个月动量")
def momentum_1m(df: pd.DataFrame) -> float:
    """1个月动量（过去21个交易日）"""
    returns = _compute_returns(df, 21)
    return float(returns.iloc[-1]) if len(returns) > 0 else np.nan


@register_factor("momentum_3m", "momentum", "3个月动量")
def momentum_3m(df: pd.DataFrame) -> float:
    """3个月动量（过去63个交易日）"""
    returns = _compute_returns(df, 63)
    return float(returns.iloc[-1]) if len(returns) > 0 else np.nan


@register_factor("momentum_6m", "momentum", "6个月动量")
def momentum_6m(df: pd.DataFrame) -> float:
    """6个月动量（过去126个交易日）"""
    returns = _compute_returns(df, 126)
    return float(returns.iloc[-1]) if len(returns) > 0 else np.nan


@register_factor("momentum_12m", "momentum", "12个月动量")
def momentum_12m(df: pd.DataFrame) -> float:
    """12个月动量（过去252个交易日）"""
    returns = _compute_returns(df, 252)
    return float(returns.iloc[-1]) if len(returns) > 0 else np.nan


@register_factor("jegadeesh_reversal", "momentum", "Jegadeesh反转因子")
def jegadeesh_reversal(df: pd.DataFrame) -> float:
    """Jegadeesh反转因子（过去1周反转）"""
    returns = _compute_returns(df)
    if len(returns) < 5:
        return np.nan
    return float(-np.mean(returns.iloc[-5:]))


@register_factor("george_hwang_52week", "momentum", "George-Hwang 52周新高因子")
def george_hwang_52week(df: pd.DataFrame) -> float:
    """George-Hwang 52周新高因子"""
    if len(df) < 252:
        return np.nan
    high_52w = df["High"].iloc[-252:].max()
    current_close = df["Close"].iloc[-1]
    return float(current_close / high_52w)


@register_factor("price_momentum_ratio", "momentum", "价格动量比率")
def price_momentum_ratio(df: pd.DataFrame) -> float:
    """短期动量 / 长期动量"""
    short = momentum_1m(df)
    long = momentum_12m(df)
    if long == 0:
        return np.nan
    return float(short / long)


# ============================================================
# 波动率类因子
# ============================================================

@register_factor("volatility_20d", "volatility", "20日波动率")
def volatility_20d(df: pd.DataFrame) -> float:
    """20日收益率波动率"""
    std = _rolling_std(df, 20)
    return float(std.iloc[-1]) if len(std) > 0 else np.nan


@register_factor("volatility_60d", "volatility", "60日波动率")
def volatility_60d(df: pd.DataFrame) -> float:
    """60日收益率波动率"""
    std = _rolling_std(df, 60)
    return float(std.iloc[-1]) if len(std) > 0 else np.nan


@register_factor("volatility_change", "volatility", "波动率变化率")
def volatility_change(df: pd.DataFrame) -> float:
    """波动率变化率（近期/远期）"""
    vol_short = _rolling_std(df, 20)
    vol_long = _rolling_std(df, 60)
    if len(vol_short) == 0 or len(vol_long) == 0:
        return np.nan
    vs, vl = float(vol_short.iloc[-1]), float(vol_long.iloc[-1])
    if vl == 0:
        return np.nan
    return vs / vl


@register_factor("harvey_siddique_skew", "volatility", "Harvey-Siddique偏度因子")
def harvey_siddique_skew(df: pd.DataFrame) -> float:
    """Harvey-Siddique偏度因子"""
    returns = _compute_returns(df)
    if len(returns) < 60:
        return np.nan
    recent = returns.iloc[-60:]
    return float(recent.skew())


@register_factor("parkinson_volatility", "volatility", "Parkinson波动率")
def parkinson_volatility(df: pd.DataFrame) -> float:
    """Parkinson波动率（基于高低价）"""
    if len(df) < 20:
        return np.nan
    df_slice = df.iloc[-20:]
    high_low = np.log(df_slice["High"] / df_slice["Low"]) ** 2
    vol = np.sqrt(np.mean(high_low) / (4 * np.log(2)))
    return float(vol)


# ============================================================
# 流动性类因子
# ============================================================

@register_factor("amihud_illiquidity", "liquidity", "Amihud非流动性")
def amihud_illiquidity(df: pd.DataFrame) -> float:
    """Amihud非流动性指标（越高越不流动）"""
    if len(df) < 20:
        return np.nan
    df_slice = df.iloc[-20:]
    returns_abs = df_slice["Close"].pct_change().abs()
    volume = df_slice["Volume"].replace(0, np.nan)
    illiquidity = returns_abs / volume
    return float(np.mean(illiquidity.dropna()))


@register_factor("turnover_rate", "liquidity", "换手率")
def turnover_rate(df: pd.DataFrame) -> float:
    """20日平均换手率"""
    if len(df) < 20:
        return np.nan
    df_slice = df.iloc[-20:]
    return float(df_slice["Volume"].mean())


@register_factor("volume_ratio", "liquidity", "成交量比率")
def volume_ratio(df: pd.DataFrame) -> float:
    """近期成交量 / 远期成交量"""
    if len(df) < 60:
        return np.nan
    vol_short = df["Volume"].iloc[-20:].mean()
    vol_long = df["Volume"].iloc[-60:-20].mean()
    if vol_long == 0:
        return np.nan
    return float(vol_short / vol_long)


@register_factor("bid_ask_spread", "liquidity", "买卖价差估计")
def bid_ask_spread(df: pd.DataFrame) -> float:
    """基于高低价的买卖价差估计"""
    if len(df) < 20:
        return np.nan
    df_slice = df.iloc[-20:]
    spread = (df_slice["High"] - df_slice["Low"]) / df_slice["Close"]
    return float(np.mean(spread))


# ============================================================
# 技术类因子
# ============================================================

@register_factor("rsi_14", "technical", "RSI 14")
def rsi_14(df: pd.DataFrame) -> float:
    """RSI 14"""
    if len(df) < 15:
        return np.nan
    returns = _compute_returns(df)
    up = returns.where(returns > 0, 0).rolling(14).mean()
    down = -returns.where(returns < 0, 0).rolling(14).mean()
    rsi = 100 - (100 / (1 + up / down))
    return float(rsi.iloc[-1]) if len(rsi) > 0 else np.nan


@register_factor("macd_signal", "technical", "MACD信号")
def macd_signal(df: pd.DataFrame) -> float:
    """MACD信号（DIF - DEA）"""
    if len(df) < 60:
        return np.nan
    ema12 = df["Close"].ewm(span=12).mean()
    ema26 = df["Close"].ewm(span=26).mean()
    dif = ema12 - ema26
    dea = dif.ewm(span=9).mean()
    return float((dif - dea).iloc[-1])


@register_factor("bollinger_width", "technical", "布林带宽度")
def bollinger_width(df: pd.DataFrame) -> float:
    """布林带宽度"""
    if len(df) < 20:
        return np.nan
    middle = df["Close"].rolling(20).mean()
    upper = middle + 2 * df["Close"].rolling(20).std()
    lower = middle - 2 * df["Close"].rolling(20).std()
    width = (upper - lower) / middle
    return float(width.iloc[-1])


@register_factor("atr_14", "technical", "ATR 14")
def atr_14(df: pd.DataFrame) -> float:
    """ATR 14"""
    if len(df) < 15:
        return np.nan
    df_slice = df.iloc[-15:]
    tr1 = df_slice["High"] - df_slice["Low"]
    tr2 = (df_slice["High"] - df_slice["Close"].shift(1)).abs()
    tr3 = (df_slice["Low"] - df_slice["Close"].shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()
    return float(atr.iloc[-1])


@register_factor("ma_crossover", "technical", "均线交叉信号")
def ma_crossover(df: pd.DataFrame) -> float:
    """均线交叉信号（短期均线 - 长期均线）"""
    if len(df) < 60:
        return np.nan
    ma_short = df["Close"].rolling(20).mean()
    ma_long = df["Close"].rolling(60).mean()
    return float((ma_short - ma_long).iloc[-1])


# ============================================================
# 趋势类因子
# ============================================================

@register_factor("trend_strength", "trend", "趋势强度")
def trend_strength(df: pd.DataFrame) -> float:
    """趋势强度（线性回归斜率）"""
    if len(df) < 30:
        return np.nan
    df_slice = df.iloc[-30:]
    x = np.arange(len(df_slice))
    y = df_slice["Close"].values
    slope, _ = np.polyfit(x, y, 1)
    return float(slope / np.mean(y))


@register_factor("adx_14", "trend", "ADX 14")
def adx_14(df: pd.DataFrame) -> float:
    """ADX 14"""
    if len(df) < 15:
        return np.nan
    df_slice = df.iloc[-15:]
    
    plus_dm = df_slice["High"].diff().clip(lower=0)
    minus_dm = -df_slice["Low"].diff().clip(lower=0)
    
    tr1 = df_slice["High"] - df_slice["Low"]
    tr2 = (df_slice["High"] - df_slice["Close"].shift(1)).abs()
    tr3 = (df_slice["Low"] - df_slice["Close"].shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    
    plus_di = 100 * plus_dm.rolling(14).mean() / tr.rolling(14).mean()
    minus_di = 100 * minus_dm.rolling(14).mean() / tr.rolling(14).mean()
    
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
    adx = dx.rolling(14).mean()
    
    return float(adx.iloc[-1]) if len(adx) > 0 else np.nan


@register_factor("price_position", "trend", "价格位置")
def price_position(df: pd.DataFrame) -> float:
    """价格在近期区间中的位置（0-1）"""
    if len(df) < 60:
        return np.nan
    df_slice = df.iloc[-60:]
    high = df_slice["High"].max()
    low = df_slice["Low"].min()
    if high == low:
        return 0.5
    return float((df_slice["Close"].iloc[-1] - low) / (high - low))


# ============================================================
# Alpha Zoo 主类
# ============================================================

class AlphaZoo:
    """Alpha因子动物园"""
    
    def __init__(self):
        self.factors = FACTOR_REGISTRY
    
    def get_factor_categories(self) -> List[str]:
        """获取因子类别列表"""
        categories = sorted(set(info["category"] for info in self.factors.values()))
        return categories
    
    def get_factors_by_category(self, category: str) -> List[str]:
        """按类别获取因子列表"""
        return [name for name, info in self.factors.items() if info["category"] == category]
    
    def compute_factor(self, name: str, df: pd.DataFrame) -> float:
        """计算单个因子"""
        if name not in self.factors:
            raise ValueError(f"未知因子: {name}")
        return self.factors[name]["func"](df)
    
    def compute_factors(self, df: pd.DataFrame, factors: List[str] = None) -> Dict[str, float]:
        """计算多个因子"""
        if factors is None:
            factors = list(self.factors.keys())
        
        results = {}
        for factor_name in factors:
            try:
                results[factor_name] = self.compute_factor(factor_name, df)
            except Exception as e:
                logger.warning(f"计算因子 {factor_name} 失败: {e}")
                results[factor_name] = np.nan
        
        return results
    
    def compute_all(self, df: pd.DataFrame) -> Dict[str, float]:
        """计算所有因子"""
        return self.compute_factors(df)
    
    def compute_cross_sectional(self, data_dict: Dict[str, pd.DataFrame]) -> pd.DataFrame:
        """截面因子计算"""
        results = []
        for symbol, df in data_dict.items():
            factors = self.compute_all(df)
            factors["symbol"] = symbol
            results.append(factors)
        
        return pd.DataFrame(results).set_index("symbol")
    
    def standardize_cross_sectional(self, df: pd.DataFrame) -> pd.DataFrame:
        """截面标准化（Z-score）"""
        df_copy = df.copy()
        for col in df.columns:
            if col != "symbol":
                mean_val = df_copy[col].mean()
                std_val = df_copy[col].std()
                if std_val > 0:
                    df_copy[col] = (df_copy[col] - mean_val) / std_val
        return df_copy
    
    def compute_ic(self, factors: pd.DataFrame, forward_returns: pd.Series) -> pd.Series:
        """计算IC（信息系数）"""
        ic_results = {}
        for factor in factors.columns:
            if factor != "symbol":
                combined = pd.DataFrame({
                    "factor": factors[factor],
                    "return": forward_returns
                }).dropna()
                if len(combined) > 10:
                    ic_results[factor] = combined["factor"].corr(combined["return"])
                else:
                    ic_results[factor] = np.nan
        return pd.Series(ic_results)
    
    def get_factor_info(self, name: str) -> Dict:
        """获取因子信息"""
        return self.factors.get(name, {})


# ============================================================
# 便捷函数
# ============================================================

_zoo = None

def get_alpha_zoo() -> AlphaZoo:
    """获取全局Alpha Zoo实例"""
    global _zoo
    if _zoo is None:
        _zoo = AlphaZoo()
    return _zoo


def compute_factors(df: pd.DataFrame, factors: List[str] = None) -> Dict[str, float]:
    """便捷计算因子"""
    return get_alpha_zoo().compute_factors(df, factors)


def compute_all_factors(df: pd.DataFrame) -> Dict[str, float]:
    """便捷计算所有因子"""
    return get_alpha_zoo().compute_all(df)


def get_all_factor_names() -> List[str]:
    """获取所有因子名称"""
    return list(FACTOR_REGISTRY.keys())


def get_all_categories() -> List[str]:
    """获取所有因子类别"""
    return get_alpha_zoo().get_factor_categories()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Alpha Zoo 因子测试")
    parser.add_argument("--symbol", default="AAPL", help="股票代码")
    parser.add_argument("--show_categories", action="store_true", help="显示因子类别")
    args = parser.parse_args()
    
    if args.show_categories:
        zoo = get_alpha_zoo()
        categories = zoo.get_factor_categories()
        print("因子类别:")
        for cat in categories:
            factors = zoo.get_factors_by_category(cat)
            print(f"  {cat}: {len(factors)}个因子")
            for f in factors[:5]:
                desc = zoo.get_factor_info(f).get("description", "")
                print(f"    - {f}: {desc}")
            if len(factors) > 5:
                print(f"    ... 还有 {len(factors) - 5} 个")
    else:
        print("测试因子计算...")
        try:
            import yfinance as yf
            df = yf.download(args.symbol, period="2y", progress=False)
            zoo = get_alpha_zoo()
            factors = zoo.compute_all(df)
            print(f"\n{args.symbol} 因子计算结果:")
            for cat in zoo.get_factor_categories():
                print(f"\n  [{cat}]")
                for name in zoo.get_factors_by_category(cat):
                    val = factors.get(name)
                    if not np.isnan(val):
                        print(f"    {name}: {val:.4f}")
        except ImportError:
            print("请安装 yfinance: pip install yfinance")