"""
算法交易模块
================
提供专业的算法交易执行策略

包含:
1. TWAP (时间加权平均价格) 执行
2. VWAP (成交量加权平均价格) 执行
3. 冰山订单 (Iceberg Order)
4. 市场冲击估计
5. 执行质量评估
"""

import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


# ============================================================
# TWAP 执行算法
# ============================================================

def calculate_twap_schedule(
    total_quantity: int,
    start_time: datetime,
    end_time: datetime,
    n_slices: int = 10
) -> List[Dict]:
    """
    计算TWAP执行计划
    
    将订单均匀分布在时间窗口内
    
    Args:
        total_quantity: 总订单量
        start_time: 开始时间
        end_time: 结束时间
        n_slices: 分片数量
    
    Returns:
        执行计划列表 [{time, quantity}]
    """
    if n_slices <= 0:
        n_slices = 10
    
    time_delta = (end_time - start_time) / n_slices
    quantity_per_slice = total_quantity // n_slices
    remainder = total_quantity % n_slices
    
    schedule = []
    for i in range(n_slices):
        slice_time = start_time + time_delta * i
        slice_qty = quantity_per_slice
        
        # 将余数分配到前几个切片
        if i < remainder:
            slice_qty += 1
        
        schedule.append({
            "slice_id": i + 1,
            "time": slice_time.isoformat(),
            "quantity": slice_qty,
            "cumulative_qty": sum([s["quantity"] for s in schedule]) + slice_qty,
        })
    
    return schedule


def calculate_twap_price(
    prices: np.ndarray,
    times: Optional[np.ndarray] = None
) -> float:
    """
    计算TWAP价格
    
    Args:
        prices: 价格序列
        times: 时间序列 (可选)
    
    Returns:
        TWAP价格
    """
    if len(prices) == 0:
        return 0.0
    
    # 简单时间加权平均
    twap = np.mean(prices)
    
    return twap


# ============================================================
# VWAP 执行算法
# ============================================================

def calculate_vwap_schedule(
    total_quantity: int,
    expected_volume_profile: np.ndarray,
    n_slices: int = 10
) -> List[Dict]:
    """
    计算VWAP执行计划
    
    根据预期成交量分布分配订单
    
    Args:
        total_quantity: 总订单量
        expected_volume_profile: 预期成交量分布 (每小时)
        n_slices: 分片数量
    
    Returns:
        执行计划列表
    """
    if len(expected_volume_profile) == 0:
        # 默认均匀分布
        expected_volume_profile = np.ones(n_slices)
    
    # 归一化成交量分布
    volume_weights = expected_volume_profile / expected_volume_profile.sum()
    
    # 按成交量权重分配订单
    quantities = total_quantity * volume_weights
    quantities = np.round(quantities).astype(int)
    
    # 调整确保总量正确
    diff = total_quantity - quantities.sum()
    quantities[0] += diff
    
    schedule = []
    cumulative = 0
    
    for i, qty in enumerate(quantities):
        cumulative += qty
        schedule.append({
            "slice_id": i + 1,
            "quantity": int(qty),
            "volume_weight": volume_weights[i],
            "cumulative_qty": cumulative,
        })
    
    return schedule


def calculate_vwap_price(
    prices: np.ndarray,
    volumes: np.ndarray
) -> float:
    """
    计算VWAP价格
    
    VWAP = sum(price * volume) / sum(volume)
    
    Args:
        prices: 价格序列
        volumes: 成交量序列
    
    Returns:
        VWAP价格
    """
    if len(prices) == 0 or len(volumes) == 0:
        return 0.0
    
    min_len = min(len(prices), len(volumes))
    prices = prices[:min_len]
    volumes = volumes[:min_len]
    
    total_volume = volumes.sum()
    if total_volume == 0:
        return np.mean(prices)
    
    vwap = (prices * volumes).sum() / total_volume
    
    return vwap


def get_typical_intraday_volume_profile() -> np.ndarray:
    """
    获取典型日内成交量分布
    
    美股典型分布:
    - 开盘前30分钟: 高成交量
    - 中午: 低成交量
    - 收盘前30分钟: 高成交量
    
    Returns:
        6.5小时交易时段的成交量分布 (每小时)
    """
    # 美股交易时段 9:30-16:00 = 6.5小时
    # 典型分布 (相对权重)
    profile = np.array([
        2.5,   # 9:30-10:30 开盘高峰
        1.5,   # 10:30-11:30
        1.0,   # 11:30-12:30
        0.8,   # 12:30-13:30 午间低谷
        1.0,   # 13:30-14:30
        1.2,   # 14:30-15:30
        2.0,   # 15:30-16:00 收盘高峰
    ])
    
    return profile


# ============================================================
# 冰山订单
# ============================================================

def calculate_iceberg_slices(
    total_quantity: int,
    visible_quantity: int,
    randomize: bool = True
) -> List[Dict]:
    """
    计算冰山订单切片
    
    只显示部分订单量，隐藏真实总量
    
    Args:
        total_quantity: 总订单量
        visible_quantity: 每次显示的数量
        randomize: 是否随机化显示数量
    
    Returns:
        冰山订单切片列表
    """
    if visible_quantity <= 0:
        visible_quantity = total_quantity // 10
    
    slices = []
    remaining = total_quantity
    slice_id = 1
    
    while remaining > 0:
        # 计算本次显示量
        if randomize:
            # 随机化 ±20%
            variance = visible_quantity * 0.2
            display_qty = int(visible_quantity + np.random.uniform(-variance, variance))
        else:
            display_qty = visible_quantity
        
        # 确保不超过剩余量
        display_qty = min(display_qty, remaining)
        
        slices.append({
            "slice_id": slice_id,
            "display_quantity": display_qty,
            "hidden_quantity": remaining - display_qty,
            "total_remaining": remaining,
        })
        
        remaining -= display_qty
        slice_id += 1
    
    return slices


# ============================================================
# 市场冲击估计
# ============================================================

def estimate_market_impact(
    order_value: float,
    daily_volume: float,
    volatility: float = 0.02
) -> Dict:
    """
    估计市场冲击成本
    
    使用简化的Almgren-Chriss模型
    
    Args:
        order_value: 订单金额
        daily_volume: 日均成交量
        volatility: 日波动率
    
    Returns:
        市场冲击估计
    """
    if daily_volume <= 0:
        return {"impact": 0, "impact_pct": 0}
    
    # 参与率
    participation_rate = order_value / daily_volume
    
    # 临时冲击 (temporary impact)
    # 临时冲击与参与率成正比
    temp_impact_coeff = 0.1  # 假设系数
    temp_impact = temp_impact_coeff * participation_rate
    
    # 永久冲击 (permanent impact)
    # 永久冲击与参与率的平方根成正比
    perm_impact_coeff = 0.05
    perm_impact = perm_impact_coeff * np.sqrt(participation_rate)
    
    # 总冲击
    total_impact = temp_impact + perm_impact
    
    # 考虑波动率调整
    volatility_adjustment = volatility * np.sqrt(participation_rate)
    
    return {
        "participation_rate": participation_rate,
        "temporary_impact": temp_impact,
        "permanent_impact": perm_impact,
        "total_impact": total_impact,
        "impact_pct": total_impact * 100,
        "volatility_adjustment": volatility_adjustment,
        "estimated_cost": order_value * total_impact,
    }


def estimate_execution_cost(
    order_value: float,
    spread: float = 0.001,
    commission: float = 0.0005,
    market_impact: Optional[float] = None
) -> Dict:
    """
    估计总执行成本
    
    Args:
        order_value: 订单金额
        spread: 买卖价差 (百分比)
        commission: 佣金费率
        market_impact: 市场冲击 (可选，自动计算)
    
    Returns:
        执行成本估计
    """
    # 买卖价差成本 (假设只能买或卖，不是双向)
    spread_cost = order_value * spread / 2
    
    # 佣金成本
    commission_cost = order_value * commission
    
    # 市场冲击 (如果未提供)
    if market_impact is None:
        # 简化估计
        market_impact = 0.001  # 默认0.1%
    
    impact_cost = order_value * market_impact
    
    # 总成本
    total_cost = spread_cost + commission_cost + impact_cost
    total_cost_pct = total_cost / order_value
    
    return {
        "spread_cost": spread_cost,
        "spread_pct": spread / 2 * 100,
        "commission_cost": commission_cost,
        "commission_pct": commission * 100,
        "impact_cost": impact_cost,
        "impact_pct": market_impact * 100,
        "total_cost": total_cost,
        "total_cost_pct": total_cost_pct * 100,
    }


# ============================================================
# 执行质量评估
# ============================================================

def calculate_execution_quality(
    expected_price: float,
    actual_price: float,
    benchmark_price: float,
    quantity: int
) -> Dict:
    """
    计算执行质量
    
    Args:
        expected_price: 预期价格 (如VWAP)
        actual_price: 实际成交均价
        benchmark_price: 基准价格 (如开盘价)
        quantity: 成交数量
    
    Returns:
        执行质量指标
    """
    # 实现 shortfall
    implementation_shortfall = (actual_price - expected_price) / expected_price
    
    # 相对基准的表现
    benchmark_performance = (actual_price - benchmark_price) / benchmark_price
    
    # 成交金额差异
    value_diff = (actual_price - expected_price) * quantity
    
    return {
        "expected_price": expected_price,
        "actual_price": actual_price,
        "benchmark_price": benchmark_price,
        "implementation_shortfall": implementation_shortfall,
        "implementation_shortfall_pct": implementation_shortfall * 100,
        "benchmark_performance": benchmark_performance,
        "benchmark_performance_pct": benchmark_performance * 100,
        "value_difference": value_diff,
        "is_good_execution": implementation_shortfall < 0.001,  # <0.1%为好执行
    }


def calculate_slippage(
    target_price: float,
    execution_price: float,
    direction: str = "buy"
) -> float:
    """
    计算滑点
    
    Args:
        target_price: 目标价格
        execution_price: 实际成交价
        direction: "buy" 或 "sell"
    
    Returns:
        滑点 (百分比)
    """
    if direction == "buy":
        # 买入时，实际价格高于目标价格为正滑点
        slippage = (execution_price - target_price) / target_price
    else:
        # 卖出时，实际价格低于目标价格为正滑点
        slippage = (target_price - execution_price) / target_price
    
    return slippage


# ============================================================
# 执行报告生成
# ============================================================

def generate_execution_report(
    symbol: str,
    total_quantity: int,
    executions: List[Dict],
    benchmark_vwap: Optional[float] = None
) -> Dict:
    """
    生成执行报告
    
    Args:
        symbol: 股票代码
        total_quantity: 总成交量
        executions: 执行记录列表 [{price, quantity, time}]
        benchmark_vwap: 基准VWAP (可选)
    
    Returns:
        执行报告
    """
    if len(executions) == 0:
        return {"error": "无执行记录"}
    
    # 计算实际成交均价
    total_value = sum([e["price"] * e["quantity"] for e in executions])
    avg_price = total_value / total_quantity
    
    # 计算实际VWAP
    prices = np.array([e["price"] for e in executions])
    volumes = np.array([e["quantity"] for e in executions])
    actual_vwap = calculate_vwap_price(prices, volumes)
    
    # 执行时间分析
    first_time = executions[0]["time"]
    last_time = executions[-1]["time"]
    
    # 执行质量
    if benchmark_vwap:
        quality = calculate_execution_quality(
            benchmark_vwap, avg_price, executions[0]["price"], total_quantity
        )
    else:
        quality = {"implementation_shortfall": 0}
    
    return {
        "symbol": symbol,
        "total_quantity": total_quantity,
        "total_value": total_value,
        "average_price": avg_price,
        "actual_vwap": actual_vwap,
        "benchmark_vwap": benchmark_vwap,
        "n_executions": len(executions),
        "first_execution_time": first_time,
        "last_execution_time": last_time,
        "execution_quality": quality,
        "generated_at": datetime.now().isoformat(),
    }


# ============================================================
# 测试
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("  算法交易模块测试")
    print("=" * 60)
    
    # TWAP测试
    print("\n📋 TWAP执行计划:")
    start = datetime.now()
    end = start + timedelta(hours=6.5)
    twap_schedule = calculate_twap_schedule(10000, start, end, n_slices=10)
    print(f"  总量: 10000股, 分片: 10")
    for s in twap_schedule[:3]:
        print(f"  切片{s['slice_id']}: {s['quantity']}股 @ {s['time'][:19]}")
    
    # VWAP测试
    print("\n📋 VWAP执行计划:")
    volume_profile = get_typical_intraday_volume_profile()
    vwap_schedule = calculate_vwap_schedule(10000, volume_profile)
    print(f"  总量: 10000股, 按成交量分布")
    for s in vwap_schedule[:3]:
        print(f"  切片{s['slice_id']}: {s['quantity']}股 (权重{s['volume_weight']:.2%})")
    
    # VWAP价格计算
    print("\n📋 VWAP价格计算:")
    prices = np.array([100, 101, 102, 103, 104])
    volumes = np.array([1000, 2000, 3000, 2000, 1000])
    vwap = calculate_vwap_price(prices, volumes)
    print(f"  VWAP价格: ${vwap:.2f}")
    
    # 冰山订单测试
    print("\n📋 冰山订单:")
    iceberg = calculate_iceberg_slices(10000, 1000, randomize=True)
    print(f"  总量: 10000股, 可见: 1000股")
    print(f"  切片数: {len(iceberg)}")
    
    # 市场冲击测试
    print("\n📋 市场冲击估计:")
    impact = estimate_market_impact(50000, 1000000, 0.02)
    print(f"  订单金额: $50,000")
    print(f"  参与率: {impact['participation_rate']:.1%}")
    print(f"  估计冲击: {impact['impact_pct']:.3%}")
    print(f"  估计成本: ${impact['estimated_cost']:.2f}")
    
    # 执行成本测试
    print("\n📋 总执行成本:")
    costs = estimate_execution_cost(50000, spread=0.001, commission=0.0005)
    print(f"  买卖价差成本: ${costs['spread_cost']:.2f}")
    print(f"  佣金成本: ${costs['commission_cost']:.2f}")
    print(f"  总成本: ${costs['total_cost']:.2f} ({costs['total_cost_pct']:.3%})")
    
    # 执行质量测试
    print("\n📋 执行质量评估:")
    quality = calculate_execution_quality(100.0, 100.5, 99.5, 1000)
    print(f"  预期价格: $100.00")
    print(f"  实际价格: $100.50")
    print(f"  实现 shortfall: {quality['implementation_shortfall_pct']:.2f}%")
    print(f"  执行质量: {'好' if quality['is_good_execution'] else '差'}")
    
    print("\n✅ 算法交易模块测试完成")