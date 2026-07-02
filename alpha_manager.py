"""
统一因子管理器 (Unified Alpha Manager)
=====================================
整合4大因子库，总计 400+ 因子

因子库：
1. Alpha101  - WorldQuant 101个量价因子
2. GTJA191   - 国泰君安 191个短周期因子（核心60个）
3. Qlib158   - 微软 Qlib 158个因子
4. Academic  - 学术因子 20+个

使用方法：
    from alpha_manager import AlphaManager
    manager = AlphaManager()
    # 计算单个股票的所有因子
    factors = manager.compute_all(df)
    # 按库筛选
    factors = manager.compute_by_library(df, "alpha101")
"""

import os
import sys
import logging
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("quant.alpha_manager")


class AlphaManager:
    """统一因子管理器"""

    def __init__(self):
        self._alpha101 = None
        self._gtja191 = None
        self._qlib158 = None
        self._academic = None

    def _get_alpha101(self):
        if self._alpha101 is None:
            from alpha101 import Alpha101
            self._alpha101 = Alpha101()
        return self._alpha101

    def _get_gtja191(self):
        if self._gtja191 is None:
            from gtja191 import GTJA191
            self._gtja191 = GTJA191()
        return self._gtja191

    def _get_qlib158(self):
        if self._qlib158 is None:
            from qlib158 import Qlib158
            self._qlib158 = Qlib158()
        return self._qlib158

    def _get_academic(self):
        if self._academic is None:
            from alpha_zoo import get_alpha_zoo
            self._academic = get_alpha_zoo()
        return self._academic

    def get_libraries(self) -> Dict[str, Dict]:
        """获取所有因子库信息"""
        return {
            "alpha101": {
                "name": "Alpha101 (WorldQuant)",
                "description": "WorldQuant 101个经典量价因子",
                "count": 101,
                "category": "量价因子",
            },
            "gtja191": {
                "name": "GTJA191 (国泰君安)",
                "description": "国泰君安191个短周期量价因子",
                "count": 60,
                "category": "A股短周期因子",
                "note": "核心精选60个",
            },
            "qlib158": {
                "name": "Qlib158 (微软Qlib)",
                "description": "微软Qlib框架158个因子",
                "count": 158,
                "category": "综合因子",
            },
            "academic": {
                "name": "Academic (学术因子)",
                "description": "学术研究因子（动量、波动率、流动性、技术、趋势）",
                "count": 20,
                "category": "学术因子",
            },
        }

    def get_total_count(self) -> int:
        """获取因子总数"""
        libs = self.get_libraries()
        return sum(lib["count"] for lib in libs.values())

    def compute_by_library(self, df: pd.DataFrame, library: str) -> Dict[str, float]:
        """按库计算因子（返回最新值）"""
        try:
            if library == "alpha101":
                alpha = self._get_alpha101()
                factors = alpha.compute(df)
            elif library == "gtja191":
                alpha = self._get_gtja191()
                factors = alpha.compute(df)
            elif library == "qlib158":
                alpha = self._get_qlib158()
                factors = alpha.compute(df)
            elif library == "academic":
                zoo = self._get_academic()
                return zoo.compute_all(df)
            else:
                return {}
            
            # 取最新值
            result = {}
            for name, series in factors.items():
                if isinstance(series, pd.Series) and len(series) > 0:
                    val = series.iloc[-1]
                    result[name] = float(val) if not np.isnan(val) else None
                else:
                    result[name] = None
            return result

        except Exception as e:
            logger.error(f"计算因子库 {library} 失败: {e}")
            return {}

    def compute_all(self, df: pd.DataFrame) -> Dict[str, float]:
        """计算所有因子库的因子"""
        results = {}
        for lib_name in ["alpha101", "gtja191", "qlib158", "academic"]:
            lib_factors = self.compute_by_library(df, lib_name)
            # 添加库前缀避免冲突
            for name, val in lib_factors.items():
                if name.startswith(("alpha", "gtja", "KMID", "KLEN", "RSI", "MACD", "KDJ", "BB", "CCI", "ATR", "DMA", "EXP", "VMA", "STD", "VOL", "RSV", "CORR")):
                    results[name] = val
                else:
                    results[f"{lib_name}_{name}"] = val
        return results

    def compute_series_by_library(self, df: pd.DataFrame, library: str) -> Dict[str, pd.Series]:
        """按库计算因子（返回完整时间序列）"""
        try:
            if library == "alpha101":
                alpha = self._get_alpha101()
                return alpha.compute(df)
            elif library == "gtja191":
                alpha = self._get_gtja191()
                return alpha.compute(df)
            elif library == "qlib158":
                alpha = self._get_qlib158()
                return alpha.compute(df)
            elif library == "academic":
                # 学术因子返回标量，需要单独处理
                zoo = self._get_academic()
                result = zoo.compute_all(df)
                return {k: pd.Series([v], index=[df.index[-1] if hasattr(df, 'index') else 0]) for k, v in result.items()}
            else:
                return {}
        except Exception as e:
            logger.error(f"计算因子库 {library} 失败: {e}")
            return {}

    def get_factor_list(self, library: str = None) -> List[str]:
        """获取因子列表"""
        if library:
            libs = self.get_libraries()
            if library not in libs:
                return []
            # 返回该库的因子名
            try:
                # 生成假数据获取因子名
                dummy = pd.DataFrame({
                    "Open": [100]*300, "High": [101]*300, "Low": [99]*300,
                    "Close": [100]*300, "Volume": [1000]*300, "VWAP": [100]*300,
                })
                factors = self.compute_by_library(dummy, library)
                return list(factors.keys())
            except:
                return []
        else:
            all_factors = []
            for lib in ["alpha101", "gtja191", "qlib158", "academic"]:
                all_factors.extend(self.get_factor_list(lib))
            return all_factors


# 全局实例
_manager = None

def get_alpha_manager() -> AlphaManager:
    """获取全局因子管理器"""
    global _manager
    if _manager is None:
        _manager = AlphaManager()
    return _manager


def compute_all_factors(df: pd.DataFrame) -> Dict[str, float]:
    """便捷计算所有因子"""
    return get_alpha_manager().compute_all(df)


def get_factor_libraries() -> Dict[str, Dict]:
    """获取因子库信息"""
    return get_alpha_manager().get_libraries()


def get_total_factor_count() -> int:
    """获取因子总数"""
    return get_alpha_manager().get_total_count()


if __name__ == "__main__":
    print("=" * 60)
    print("  统一因子管理器 (Alpha Manager)")
    print("=" * 60)

    manager = get_alpha_manager()
    libs = manager.get_libraries()

    print(f"\n因子库总数: {len(libs)}")
    print(f"因子总数: {manager.get_total_count()}")
    print()
    print("因子库详情:")
    print("-" * 60)
    for name, info in libs.items():
        print(f"  {info['name']}")
        print(f"    描述: {info['description']}")
        print(f"    数量: {info['count']}个")
        print(f"    类别: {info['category']}")
        if 'note' in info:
            print(f"    备注: {info['note']}")
        print()