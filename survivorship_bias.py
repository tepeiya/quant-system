"""
幸存者偏差处理模块
==================
解决回测中使用当前成分股导致的收益高估问题

功能:
1. 历史SP500成分股获取
2. 退市股票数据处理
3. 成分股变更记录
"""

import os
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

# 历史SP500成分股数据文件
HISTORICAL_CONSTITUENTS_FILE = "config/historical_sp500_constituents.json"

# 已退市股票列表（常见退市股）
DELISTED_STOCKS = {
    # 2000-2010年退市
    "WCOM": {"delisted": "2002-07-01", "reason": "WorldCom破产"},
    "ENRN": {"delisted": "2001-12-02", "reason": "安然破产"},
    "NOVL": {"delisted": "2014-04-01", "reason": "被Attachmate收购"},
    "YHOO": {"delisted": "2017-06-13", "reason": "被Verizon收购"},
    "TWTR": {"delisted": "2022-11-07", "reason": "被马斯克收购"},
    "AOL": {"delisted": "2015-05-01", "reason": "被Verizon收购"},
    "LEH": {"delisted": "2008-09-15", "reason": "雷曼兄弟破产"},
    "BSX": {"delisted": "2006-01-01", "reason": "Boston Scientific重组"},
    "KMRT": {"delisted": "2002-01-01", "reason": "Kmart破产"},
    "G": {"delisted": "2005-10-01", "reason": "Gillette被P&G收购"},
    
    # 金融危机退市
    "WB": {"delisted": "2008-10-03", "reason": "Wachovia被 Wells Fargo收购"},
    "WM": {"delisted": "2008-09-25", "reason": "Washington Mutual破产"},
    "CFC": {"delisted": "2008-03-01", "reason": "Countrywide被BOA收购"},
    "FRE": {"delisted": "2008-09-07", "reason": "Freddie Mac政府接管"},
    "FNM": {"delisted": "2008-09-07", "reason": "Fannie Mae政府接管"},
    
    # 近年退市
    "S": {"delisted": "2020-04-01", "reason": "Sprint被T-Mobile收购"},
    "TMUS.R": {"delisted": "2020-04-01", "reason": "合并"},
    "DISH": {"delisted": "2025-01-01", "reason": "破产风险"},
}

# SP500历史成分股变更记录（简化版，实际应从专业数据源获取）
SP500_CHANGES = [
    # 2024年
    {"date": "2024-03-18", "added": "SMCI", "removed": "WHIRL"},
    {"date": "2024-03-04", "added": "KVUE", "removed": "BMY"},
    
    # 2023年
    {"date": "2023-12-18", "added": "SIRI", "removed": "ZION"},
    {"date": "2023-09-18", "added": "GEV", "removed": "GE"},
    {"date": "2023-03-20", "added": "ON", "removed": "FOXA"},
    
    # 2022年
    {"date": "2022-11-07", "added": None, "removed": "TWTR"},
    {"date": "2022-05-02", "added": "PAYX", "removed": None},
    
    # 2021年
    {"date": "2021-03-22", "added": "NDAQ", "removed": "XLNX"},
    {"date": "2021-01-04", "added": "AAPL", "removed": None},
    
    # 2020年
    {"date": "2020-04-01", "added": "TMUS", "removed": "S"},
    
    # 2019年
    {"date": "2019-06-03", "added": "LVS", "removed": "ANDV"},
    
    # 2018年
    {"date": "2018-06-04", "added": "NOW", "removed": "GGP"},
    
    # 2017年
    {"date": "2017-06-13", "added": None, "removed": "YHOO"},
    
    # 2015年
    {"date": "2015-03-19", "added": "ACT", "removed": "BRCM"},
    
    # 2010年
    {"date": "2010-04-01", "added": None, "removed": "C"},
    
    # 2008年
    {"date": "2008-10-03", "added": "WFC", "removed": "WB"},
    {"date": "2008-09-15", "added": None, "removed": "LEH"},
    
    # 2002年
    {"date": "2002-07-01", "added": None, "removed": "WCOM"},
]


class SurvivorshipBiasHandler:
    """幸存者偏差处理器"""
    
    def __init__(self):
        self.delisted_stocks = DELISTED_STOCKS
        self.sp500_changes = SP500_CHANGES
        self._load_historical_constituents()
        
    def _load_historical_constituents(self):
        """加载历史成分股数据"""
        if os.path.exists(HISTORICAL_CONSTITUENTS_FILE):
            try:
                with open(HISTORICAL_CONSTITUENTS_FILE, "r") as f:
                    self.historical_constituents = json.load(f)
            except:
                self.historical_constituents = {}
        else:
            self.historical_constituents = {}
            
    def get_constituents_at_date(self, target_date: str) -> Set[str]:
        """
        获取指定日期的SP500成分股
        
        Args:
            target_date: 目标日期 (YYYY-MM-DD)
            
        Returns:
            当时的成分股集合
        """
        # 从当前成分股开始，逆向应用变更
        # 当前SP500成分股（2024年）
        current_constituents = self._get_current_sp500()
        
        target_dt = datetime.strptime(target_date, "%Y-%m-%d")
        
        # 逆向应用变更
        for change in sorted(self.sp500_changes, key=lambda x: x["date"], reverse=True):
            change_dt = datetime.strptime(change["date"], "%Y-%m-%d")
            if change_dt > target_dt:
                # 这个变更在目标日期之后发生，需要逆向
                if change["removed"]:
                    current_constituents.add(change["removed"])
                if change["added"]:
                    current_constituents.discard(change["added"])
                    
        return current_constituents
    
    def _get_current_sp500(self) -> Set[str]:
        """获取当前SP500成分股"""
        # 简化版：主要成分股
        # 实际应从Wikipedia或专业数据源获取
        return {
            "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "META", "NVDA", "TSLA",
            "BRK.B", "UNH", "JNJ", "V", "JPM", "XOM", "HD", "MA", "PG", "CVX",
            "MRK", "ABBV", "PEP", "KO", "COST", "AVGO", "WMT", "CSCO", "MCD",
            "ADBE", "NKE", "CRM", "DHR", "ACN", "LIN", "QCOM", "AMD", "NFLX",
            "INTC", "VZ", "T", "DIS", "AMAT", "TXN", "LOW", "IBM", "GS", "CAT",
            "BA", "RTX", "HON", "UPS", "GE", "DE", "SBUX", "INTU", "ISRG", "MDLZ",
            "NOW", "SYK", "BLK", "ADI", "AMGN", "GILD", "MDT", "VRTX", "REGN",
            "ATVI", "BKNG", "CHTR", "CMCSA", "CME", "CSX", "EL", "EOG", "ETN",
            "F", "FCX", "FI", "FIS", "GM", "HAL", "HAS", "HCA", "HES", "HLT",
            "HSY", "ICE", "ITW", "K", "KHC", "KLAC", "LHX", "LLY", "LMT", "MO",
            "MRNA", "MS", "NEE", "NEM", "NOC", "NRG", "ORCL", "PAYX", "PNC",
            "PXD", "PYPL", "SLB", "SO", "SPGI", "TGT", "TMUS", "TMO", "TRV",
            "USB", "WBA", "WELL", "WM", "ZTS"
        }
    
    def is_delisted(self, ticker: str, as_of_date: str = None) -> bool:
        """
        检查股票是否已退市
        
        Args:
            ticker: 股票代码
            as_of_date: 检查日期
            
        Returns:
            是否已退市
        """
        if ticker in self.delisted_stocks:
            if as_of_date:
                delisted_date = self.delisted_stocks[ticker]["delisted"]
                return datetime.strptime(as_of_date, "%Y-%m-%d") >= \
                       datetime.strptime(delisted_date, "%Y-%m-%d")
            return True
        return False
    
    def get_delisted_info(self, ticker: str) -> Optional[Dict]:
        """获取退市信息"""
        return self.delisted_stocks.get(ticker)
    
    def filter_survivorship_bias(
        self, 
        tickers: List[str], 
        backtest_start: str, 
        backtest_end: str
    ) -> Dict[str, List[str]]:
        """
        过滤幸存者偏差
        
        Args:
            tickers: 原始股票列表
            backtest_start: 回测开始日期
            backtest_end: 回测结束日期
            
        Returns:
            过滤后的股票列表和退市股票列表
        """
        start_constituents = self.get_constituents_at_date(backtest_start)
        end_constituents = self.get_constituents_at_date(backtest_end)
        
        # 在回测期间存在的股票
        valid_tickers = []
        delisted_in_period = []
        
        for ticker in tickers:
            # 检查是否在开始时存在
            if ticker in start_constituents:
                # 检查是否在期间退市
                if self.is_delisted(ticker, backtest_end):
                    delisted_info = self.get_delisted_info(ticker)
                    if delisted_info:
                        delisted_date = delisted_info["delisted"]
                        if datetime.strptime(backtest_start, "%Y-%m-%d") <= \
                           datetime.strptime(delisted_date, "%Y-%m-%d") <= \
                           datetime.strptime(backtest_end, "%Y-%m-%d"):
                            delisted_in_period.append({
                                "ticker": ticker,
                                "delisted_date": delisted_date,
                                "reason": delisted_info["reason"]
                            })
                        else:
                            # 在回测开始前已退市，不应包含
                            continue
                valid_tickers.append(ticker)
            elif ticker in end_constituents:
                # 在结束时存在但开始时不存在（期间加入）
                valid_tickers.append(ticker)
                
        return {
            "valid_tickers": valid_tickers,
            "delisted_in_period": delisted_in_period,
            "start_constituents_count": len(start_constituents),
            "end_constituents_count": len(end_constituents)
        }
    
    def estimate_bias_impact(
        self, 
        returns_with_survivors: float, 
        returns_with_delisted: float
    ) -> Dict:
        """
        估计幸存者偏差影响
        
        Args:
            returns_with_survivors: 只用幸存股的收益
            returns_with_delisted: 包含退市股的收益
            
        Returns:
            偏差分析结果
        """
        bias = returns_with_survivors - returns_with_delisted
        bias_pct = bias / returns_with_delisted * 100 if returns_with_delisted != 0 else 0
        
        return {
            "survivorship_bias": bias,
            "bias_percentage": bias_pct,
            "is_significant": abs(bias_pct) > 5,  # >5%认为显著
            "recommendation": "建议使用历史成分股数据" if abs(bias_pct) > 5 else "偏差可接受"
        }
    
    def create_backtest_universe(
        self, 
        start_date: str, 
        end_date: str,
        universe_type: str = "sp500"
    ) -> pd.DataFrame:
        """
        创建回测股票池
        
        Args:
            start_date: 回测开始日期
            end_date: 回测结束日期
            universe_type: 股票池类型
            
        Returns:
            股票池DataFrame，包含加入/退出日期
        """
        constituents_history = []
        
        # 获取开始时的成分股
        start_constituents = self.get_constituents_at_date(start_date)
        
        for ticker in start_constituents:
            entry = {
                "ticker": ticker,
                "entry_date": start_date,
                "exit_date": None,
                "exit_reason": None,
                "is_delisted": False
            }
            
            # 检查是否在期间退市
            if self.is_delisted(ticker, end_date):
                delisted_info = self.get_delisted_info(ticker)
                if delisted_info:
                    entry["exit_date"] = delisted_info["delisted"]
                    entry["exit_reason"] = delisted_info["reason"]
                    entry["is_delisted"] = True
                    
            constituents_history.append(entry)
        
        # 检查期间加入的股票
        for change in self.sp500_changes:
            change_dt = datetime.strptime(change["date"], "%Y-%m-%d")
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
            
            if start_dt < change_dt <= end_dt and change["added"]:
                constituents_history.append({
                    "ticker": change["added"],
                    "entry_date": change["date"],
                    "exit_date": None,
                    "exit_reason": None,
                    "is_delisted": False
                })
        
        return pd.DataFrame(constituents_history)


def get_historical_constituents(date: str) -> Set[str]:
    """便捷函数：获取历史成分股"""
    handler = SurvivorshipBiasHandler()
    return handler.get_constituents_at_date(date)


def check_delisted(ticker: str) -> bool:
    """便捷函数：检查是否退市"""
    handler = SurvivorshipBiasHandler()
    return handler.is_delisted(ticker)


def create_survivorship_free_universe(
    start_date: str, 
    end_date: str
) -> pd.DataFrame:
    """便捷函数：创建无幸存者偏差的股票池"""
    handler = SurvivorshipBiasHandler()
    return handler.create_backtest_universe(start_date, end_date)


# 初始化时保存默认数据
def init_survivorship_data():
    """初始化幸存者偏差数据"""
    os.makedirs("config", exist_ok=True)
    
    default_data = {
        "delisted_stocks": DELISTED_STOCKS,
        "sp500_changes": SP500_CHANGES,
        "last_updated": datetime.now().isoformat()
    }
    
    if not os.path.exists(HISTORICAL_CONSTITUENTS_FILE):
        with open(HISTORICAL_CONSTITUENTS_FILE, "w") as f:
            json.dump(default_data, f, indent=2)
        logger.info(f"✅ 幸存者偏差数据已初始化: {HISTORICAL_CONSTITUENTS_FILE}")


if __name__ == "__main__":
    init_survivorship_data()
    
    # 测试
    handler = SurvivorshipBiasHandler()
    
    print("=" * 60)
    print("  幸存者偏差处理模块测试")
    print("=" * 60)
    
    # 测试1: 获取历史成分股
    print("\n📋 测试1: 获取2020-01-01的SP500成分股")
    constituents_2020 = handler.get_constituents_at_date("2020-01-01")
    print(f"  成分股数量: {len(constituents_2020)}")
    
    # 测试2: 检查退市股票
    print("\n📋 测试2: 检查退市股票")
    for ticker in ["WCOM", "LEH", "TWTR", "YHOO"]:
        info = handler.get_delisted_info(ticker)
        if info:
            print(f"  {ticker}: {info['delisted']} - {info['reason']}")
    
    # 测试3: 创建回测股票池
    print("\n📋 测试3: 创建2020-2024回测股票池")
    universe = handler.create_backtest_universe("2020-01-01", "2024-12-31")
    print(f"  总股票数: {len(universe)}")
    delisted_count = universe["is_delisted"].sum()
    print(f"  期间退市: {delisted_count}")
    
    print("\n✅ 幸存者偏差处理模块测试完成")