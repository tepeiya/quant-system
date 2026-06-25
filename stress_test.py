"""
压力测试模块 v1.0
=================
历史情景回放和自定义压力测试

功能：
1. 历史危机情景回放（2008金融危机、2020新冠暴跌等）
2. 自定义压力测试
3. 蒙特卡洛模拟
4. 敞口压力测试
5. 组合韧性评分
"""

import os
import json
import logging
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass

logger = logging.getLogger("quant.stress_test")


@dataclass
class StressTestResult:
    """压力测试结果"""
    scenario_name: str
    portfolio_loss: float
    portfolio_loss_pct: float
    worst_position: str
    worst_position_loss: float
    recovery_days: int
    risk_score: float
    recommendations: List[str]


# ===== 历史危机情景库 =====

HISTORICAL_SCENARIOS = {
    "2008_financial_crisis": {
        "name": "2008金融危机",
        "start_date": "2008-09-01",
        "end_date": "2009-03-09",
        "description": "雷曼兄弟倒闭，全球金融危机",
        "market_impact": {
            "SPY": -0.52,  # S&P500下跌52%
            "AAPL": -0.58,
            "MSFT": -0.45,
            "GOOGL": -0.42,
            "AMZN": -0.35,
            "META": -0.48,
            "JPM": -0.72,  # 银行股跌幅更大
            "BAC": -0.85,
            "GS": -0.70,
            "XOM": -0.40,  # 能源股相对抗跌
            "CVX": -0.42,
        },
        "volatility_spike": 3.5,  # VIX从25飙升至80+
        "correlation_change": 0.8,  # 相关性上升，分散化效果减弱
        "liquidity_impact": 0.7,   # 流动性下降70%
        "recovery_time": 200       # 恢复天数
    },
    
    "2020_covid_crash": {
        "name": "2020新冠暴跌",
        "start_date": "2020-02-19",
        "end_date": "2020-03-23",
        "description": "COVID-19疫情，全球股市暴跌",
        "market_impact": {
            "SPY": -0.34,
            "AAPL": -0.28,
            "MSFT": -0.26,
            "GOOGL": -0.32,
            "AMZN": -0.15,  # 科技股相对抗跌
            "META": -0.32,
            "JPM": -0.45,
            "BAC": -0.52,
            "GS": -0.42,
            "XOM": -0.60,  # 能源股大跌
            "CVX": -0.55,
            "TSLA": -0.45,
            "NFLX": -0.22,
        },
        "volatility_spike": 2.8,
        "correlation_change": 0.9,
        "liquidity_impact": 0.5,
        "recovery_time": 90
    },
    
    "2022_inflation_crash": {
        "name": "2022通胀加息",
        "start_date": "2022-01-01",
        "end_date": "2022-12-31",
        "description": "高通胀导致美联储激进加息",
        "market_impact": {
            "SPY": -0.19,
            "AAPL": -0.27,
            "MSFT": -0.29,
            "GOOGL": -0.39,
            "AMZN": -0.50,
            "META": -0.64,  # Meta跌幅最大
            "TSLA": -0.65,
            "NVDA": -0.50,
        },
        "volatility_spike": 1.5,
        "correlation_change": 0.6,
        "liquidity_impact": 0.3,
        "recovery_time": 180
    },
    
    "2018_vol_crash": {
        "name": "2018波动率崩盘",
        "start_date": "2018-02-05",
        "end_date": "2018-02-09",
        "description": "波动率产品崩盘引发的市场冲击",
        "market_impact": {
            "SPY": -0.10,
            "AAPL": -0.08,
            "MSFT": -0.07,
        },
        "volatility_spike": 4.0,  # 短期剧烈波动
        "correlation_change": 0.95,
        "liquidity_impact": 0.4,
        "recovery_time": 15
    },
    
    "dot_com_bubble": {
        "name": "2000互联网泡沫",
        "start_date": "2000-03-01",
        "end_date": "2002-10-01",
        "description": "互联网泡沫破裂",
        "market_impact": {
            "SPY": -0.49,
            "CSCO": -0.88,  # Cisco大跌88%
            "INTC": -0.80,
            "ORCL": -0.75,
            "YHOO": -0.90,  # Yahoo跌90%
            "AMZN": -0.85,
        },
        "volatility_spike": 2.0,
        "correlation_change": 0.7,
        "liquidity_impact": 0.6,
        "recovery_time": 365
    },
    
    "flash_crash_2010": {
        "name": "2010闪崩",
        "start_date": "2010-05-06",
        "end_date": "2010-05-06",
        "description": "日内闪电崩盘",
        "market_impact": {
            "SPY": -0.09,  # 日内跌幅
            "AAPL": -0.08,
        },
        "volatility_spike": 10.0,  # 极端瞬时波动
        "correlation_change": 1.0,
        "liquidity_impact": 0.9,
        "recovery_time": 1  # 当日恢复
    },
}


# ===== 自定义压力测试参数 =====

CUSTOM_STRESS_PARAMETERS = {
    "market_crash_10": {
        "name": "市场下跌10%",
        "market_impact_multiplier": -0.10,
        "volatility_spike": 1.5,
    },
    
    "market_crash_20": {
        "name": "市场下跌20%",
        "market_impact_multiplier": -0.20,
        "volatility_spike": 2.0,
    },
    
    "market_crash_30": {
        "name": "市场下跌30%",
        "market_impact_multiplier": -0.30,
        "volatility_spike": 2.5,
    },
    
    "interest_rate_up_200": {
        "name": "利率上升200bps",
        "sector_impact": {
            "tech": -0.15,
            "finance": -0.20,
            "real_estate": -0.25,
            "utilities": -0.30,
            "consumer": -0.10,
        },
        "volatility_spike": 1.3,
    },
    
    "oil_price_shock": {
        "name": "油价冲击",
        "sector_impact": {
            "energy": -0.30,
            "transport": -0.15,
            "consumer": 0.05,  # 消费受益
        },
        "volatility_spike": 1.2,
    },
    
    "credit_spread_widen": {
        "name": "信用利差扩大",
        "sector_impact": {
            "finance": -0.25,
            "high_yield": -0.40,
            "investment_grade": -0.15,
        },
        "volatility_spike": 1.5,
    },
}


# ===== 压力测试引擎 =====

class StressTestEngine:
    """压力测试引擎"""
    
    def __init__(self):
        self.scenarios = HISTORICAL_SCENARIOS
        self.custom_params = CUSTOM_STRESS_PARAMETERS
    
    def run_historical_scenario(self, scenario_id: str, 
                                 positions: Dict[str, float]) -> StressTestResult:
        """
        运行历史情景回放
        
        Args:
            scenario_id: 情景ID
            positions: 持仓 {ticker: market_value}
        
        Returns:
            StressTestResult
        """
        if scenario_id not in self.scenarios:
            raise ValueError(f"未知情景: {scenario_id}")
        
        scenario = self.scenarios[scenario_id]
        
        logger.info(f"🧪 运行压力测试: {scenario['name']}")
        
        # 计算各持仓损失
        total_loss = 0
        total_value = sum(positions.values())
        position_losses = {}
        
        for ticker, market_value in positions.items():
            impact = scenario["market_impact"].get(ticker, scenario["market_impact"].get("SPY", -0.30))
            loss = market_value * impact
            position_losses[ticker] = loss
            total_loss += loss
        
        # 最差持仓
        worst_ticker = min(position_losses, key=position_losses.get)
        worst_loss = position_losses[worst_ticker]
        
        # 总损失百分比
        loss_pct = total_loss / total_value if total_value > 0 else 0
        
        # 风险评分
        risk_score = self._calculate_risk_score(loss_pct, scenario)
        
        # 改进建议
        recommendations = self._generate_recommendations(position_losses, scenario)
        
        return StressTestResult(
            scenario_name=scenario["name"],
            portfolio_loss=total_loss,
            portfolio_loss_pct=loss_pct,
            worst_position=worst_ticker,
            worst_position_loss=worst_loss,
            recovery_days=scenario["recovery_time"],
            risk_score=risk_score,
            recommendations=recommendations
        )
    
    def run_custom_stress(self, stress_id: str, 
                          positions: Dict[str, float],
                          sector_mapping: Dict[str, str] = None) -> StressTestResult:
        """
        运行自定义压力测试
        
        Args:
            stress_id: 压力测试ID
            positions: 持仓
            sector_mapping: 股票-行业映射 {ticker: sector}
        
        Returns:
            StressTestResult
        """
        if stress_id not in self.custom_params:
            raise ValueError(f"未知压力测试: {stress_id}")
        
        params = self.custom_params[stress_id]
        
        logger.info(f"🧪 运行自定义压力测试: {params['name']}")
        
        total_loss = 0
        total_value = sum(positions.values())
        position_losses = {}
        
        for ticker, market_value in positions.items():
            # 根据压力类型计算影响
            if "market_impact_multiplier" in params:
                impact = params["market_impact_multiplier"]
            elif "sector_impact" in params and sector_mapping:
                sector = sector_mapping.get(ticker, "general")
                impact = params["sector_impact"].get(sector, params["sector_impact"].get("general", -0.10))
            else:
                impact = -0.20
            
            loss = market_value * impact
            position_losses[ticker] = loss
            total_loss += loss
        
        worst_ticker = min(position_losses, key=position_losses.get)
        worst_loss = position_losses[worst_ticker]
        loss_pct = total_loss / total_value if total_value > 0 else 0
        
        # 自定义压力的恢复时间估计
        recovery_days = int(abs(loss_pct) * 100 * 3)  # 每1%跌幅约需3天恢复
        
        risk_score = self._calculate_risk_score(loss_pct, params)
        recommendations = self._generate_recommendations(position_losses, params)
        
        return StressTestResult(
            scenario_name=params["name"],
            portfolio_loss=total_loss,
            portfolio_loss_pct=loss_pct,
            worst_position=worst_ticker,
            worst_position_loss=worst_loss,
            recovery_days=recovery_days,
            risk_score=risk_score,
            recommendations=recommendations
        )
    
    def run_monte_carlo(self, positions: Dict[str, float],
                        n_simulations: int = 1000,
                        confidence_level: float = 0.95,
                        days: int = 10) -> Dict:
        """
        蒙特卡洛模拟
        
        Args:
            positions: 持仓
            n_simulations: 模拟次数
            confidence_level: 置信水平
            days: 模拟天数
        
        Returns:
            {
                "expected_loss": 预期损失,
                "worst_case_loss": 最坏情况损失,
                "probability_distribution": 概率分布,
                "recovery_probability": 恢复概率
            }
        """
        logger.info(f"🎲 蒙特卡洛模拟: {n_simulations}次, {days}天")
        
        total_value = sum(positions.values())
        
        # 模拟组合收益（假设服从正态分布）
        daily_return_mean = 0.0005  # 日均收益0.05%
        daily_return_std = 0.02     # 日波动率2%
        
        # 模拟
        simulation_results = []
        
        for i in range(n_simulations):
            # 生成随机收益路径
            daily_returns = np.random.normal(daily_return_mean, daily_return_std, days)
            cumulative_return = np.sum(daily_returns)
            
            final_value = total_value * (1 + cumulative_return)
            loss = total_value - final_value
            
            simulation_results.append({
                "simulation_id": i,
                "cumulative_return": cumulative_return,
                "final_value": final_value,
                "loss": loss
            })
        
        # 统计分析
        losses = [r["loss"] for r in simulation_results]
        
        expected_loss = np.mean(losses)
        worst_case_loss = np.percentile(losses, (1 - confidence_level) * 100)
        
        # 概率分布
        hist, bins = np.histogram(losses, bins=50)
        probability_distribution = {
            "bins": bins.tolist(),
            "counts": hist.tolist()
        }
        
        # 恢复概率（损失<0的概率）
        recovery_probability = sum(1 for l in losses if l < 0) / len(losses)
        
        return {
            "expected_loss": expected_loss,
            "worst_case_loss": worst_case_loss,
            "worst_case_pct": worst_case_loss / total_value,
            "confidence_level": confidence_level,
            "probability_distribution": probability_distribution,
            "recovery_probability": recovery_probability,
            "n_simulations": n_simulations,
            "simulation_days": days
        }
    
    def run_all_scenarios(self, positions: Dict[str, float]) -> Dict:
        """运行所有历史情景"""
        results = {}
        
        for scenario_id in self.scenarios.keys():
            try:
                result = self.run_historical_scenario(scenario_id, positions)
                results[scenario_id] = {
                    "name": result.scenario_name,
                    "loss_pct": result.portfolio_loss_pct,
                    "risk_score": result.risk_score,
                    "recovery_days": result.recovery_days
                }
            except Exception as e:
                logger.warning(f"情景 {scenario_id} 测试失败: {e}")
        
        # 计算综合韧性评分
        avg_loss_pct = np.mean([r["loss_pct"] for r in results.values()])
        avg_risk_score = np.mean([r["risk_score"] for r in results.values()])
        
        resilience_score = 100 - avg_risk_score
        
        results["summary"] = {
            "average_loss_pct": avg_loss_pct,
            "average_risk_score": avg_risk_score,
            "resilience_score": resilience_score,
            "n_scenarios_tested": len(results) - 1
        }
        
        return results
    
    def _calculate_risk_score(self, loss_pct: float, scenario: Dict) -> float:
        """计算风险评分（0-100）"""
        # 基础评分基于损失
        base_score = abs(loss_pct) * 100
        
        # 根据情景调整
        volatility_factor = scenario.get("volatility_spike", 1.0)
        liquidity_factor = scenario.get("liquidity_impact", 0.0)
        
        adjusted_score = base_score * (1 + volatility_factor * 0.1 + liquidity_factor * 0.2)
        
        return min(100, adjusted_score)
    
    def _generate_recommendations(self, position_losses: Dict, scenario: Dict) -> List[str]:
        """生成改进建议"""
        recommendations = []
        
        # 1. 风险敞口建议
        worst_ticker = min(position_losses, key=position_losses.get)
        worst_loss_pct = position_losses[worst_ticker] / abs(position_losses[worst_ticker])
        
        if abs(worst_loss_pct) > 0.5:
            recommendations.append(f"⚠️ {worst_ticker} 跌幅过大，建议减仓或设置止损")
        
        # 2. 分散化建议
        if len(position_losses) < 10:
            recommendations.append("💡 持仓数量不足10只，建议增加分散化")
        
        # 3. 流动性建议
        if scenario.get("liquidity_impact", 0) > 0.5:
            recommendations.append("⚠️ 该情景流动性下降明显，建议预留现金")
        
        # 4. 恢复建议
        recovery_days = scenario.get("recovery_time", 0)
        if recovery_days > 180:
            recommendations.append(f"⚠️ 预计恢复时间{recovery_days}天，建议调整投资期限")
        
        # 5. 对冲建议
        if "interest_rate_up_200" in scenario.get("name", ""):
            recommendations.append("💡 利率上升情景，建议增加债券久期对冲")
        
        return recommendations
    
    def generate_report(self, result: StressTestResult) -> str:
        """生成压力测试报告"""
        report = f"""
# 压力测试报告

## 情景: {result.scenario_name}

### 损失分析
- 组合总损失: $${abs(result.portfolio_loss):,.2f}
- 损失百分比: {result.portfolio_loss_pct:.2%}
- 最差持仓: {result.worst_position}
- 最差持仓损失: $${abs(result.worst_position_loss):,.2f}

### 恢复预估
- 预计恢复天数: {result.recovery_days} 天

### 风险评分
- 风险评分: {result.risk_score:.1f} / 100
- 风险等级: {self._get_risk_grade(result.risk_score)}

### 改进建议
{chr(10).join(f'- {r}' for r in result.recommendations)}

---
生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        
        return report
    
    def _get_risk_grade(self, score: float) -> str:
        """获取风险等级"""
        if score < 20:
            return "低风险 🟢"
        elif score < 40:
            return "中等风险 🟡"
        elif score < 60:
            return "较高风险 🟠"
        elif score < 80:
            return "高风险 🔴"
        else:
            return "极高风险 ⚫"


# ===== 敞口压力测试 =====

class ExposureStressTest:
    """敞口压力测试"""
    
    def __init__(self):
        pass
    
    def test_factor_exposure(self, factor_exposures: Dict[str, float],
                             factor_shocks: Dict[str, float]) -> Dict:
        """
        测试因子敞口
        
        Args:
            factor_exposures: 因子敞口 {factor_name: exposure}
            factor_shocks: 因子冲击 {factor_name: shock_pct}
        
        Returns:
            {
                "total_impact": 总影响,
                "factor_contributions": 各因子贡献
            }
        """
        total_impact = 0
        factor_contributions = {}
        
        for factor, exposure in factor_exposures.items():
            shock = factor_shocks.get(factor, 0)
            impact = exposure * shock
            factor_contributions[factor] = impact
            total_impact += impact
        
        return {
            "total_impact": total_impact,
            "factor_contributions": factor_contributions,
            "most_sensitive_factor": max(factor_contributions, key=factor_contributions.get),
            "worst_factor_impact": max(factor_contributions.values())
        }
    
    def test_sector_exposure(self, sector_weights: Dict[str, float],
                             sector_shocks: Dict[str, float]) -> Dict:
        """测试行业敞口"""
        return self.test_factor_exposure(sector_weights, sector_shocks)


# ===== 便捷函数 =====

def quick_stress_test(positions: Dict[str, float]) -> Dict:
    """快速压力测试"""
    engine = StressTestEngine()
    return engine.run_all_scenarios(positions)


# ===== 测试 =====

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print("\n🧪 压力测试模块测试")
    print("=" * 50)
    
    # 测试持仓
    positions = {
        "AAPL": 50000,
        "MSFT": 40000,
        "GOOGL": 30000,
        "AMZN": 20000,
        "META": 10000,
        "SPY": 30000
    }
    
    engine = StressTestEngine()
    
    # 运行2008金融危机情景
    result = engine.run_historical_scenario("2008_financial_crisis", positions)
    
    print(f"\n📊 {result.scenario_name} 测试结果:")
    print(f"  组合损失: {result.portfolio_loss_pct:.2%}")
    print(f"  最差持仓: {result.worst_position} ({result.worst_position_loss:.2%})")
    print(f"  风险评分: {result.risk_score:.1f}")
    print(f"  恢复天数: {result.recovery_days}")
    
    # 运行所有情景
    all_results = engine.run_all_scenarios(positions)
    
    print(f"\n📊 所有情景测试结果:")
    print(f"  平均损失: {all_results['summary']['average_loss_pct']:.2%}")
    print(f"  韧性评分: {all_results['summary']['resilience_score']:.1f}")
    
    # 蒙特卡洛模拟
    mc_result = engine.run_monte_carlo(positions, n_simulations=1000)
    
    print(f"\n📊 蒙特卡洛模拟结果:")
    print(f"  预期损失: ${mc_result['expected_loss']:,.2f}")
    print(f"  最坏情况(95%置信): ${mc_result['worst_case_loss']:,.2f} ({mc_result['worst_case_pct']:.2%})")
    print(f"  恢复概率: {mc_result['recovery_probability']:.2%}")
    
    print("\n" + "=" * 50)