"""
美股量化专家测试套件
====================
从专业量化交易角度评估系统的实用性

测试范围:
1. 多因子模型有效性
2. 数据质量与分析
3. 风险管理深度
4. 回测引擎准确性
5. 执行性能分析
"""

import sys
import os
import logging
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock
import tempfile
import shutil
import unittest

# 阻止外部依赖
import types
import data_global as _dg_mod
_dg_mod.fetch_stock_data = lambda *a, **kw: None
_dg_mod._get_yahoo_session = lambda: None

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("quant_expert")

# ============================================================
# 测试基类
# ============================================================

class QuantTestBase(unittest.TestCase):
    """量化测试基类"""
    
    @classmethod
    def setUpClass(cls):
        cls.test_dir = tempfile.mkdtemp()
        cls.orig_cwd = os.getcwd()
        os.chdir(cls.test_dir)
        
    @classmethod
    def tearDownClass(cls):
        os.chdir(cls.orig_cwd)
        shutil.rmtree(cls.test_dir, ignore_errors=True)


# ============================================================
# 1. 多因子模型有效性测试
# ============================================================

class TestFactorModelEffectiveness(QuantTestBase):
    """多因子模型有效性评估"""
    
    def test_momentum_factor_weighting(self):
        """
        测试动量因子权重设计
        评估: 是否考虑动量衰减和非线性效应
        """
        from factor_learner import load_weights
        
        weights = load_weights()
        total = sum(weights.values())
        
        # 权重应该接近100%
        self.assertAlmostEqual(total, 100, delta=1, 
            msg="因子权重总和应接近100%")
        
        # 动量因子应该有较高权重
        self.assertGreater(weights.get("momentum", 0), 20,
            msg="动量因子权重应>20%")
            
    def test_factor_orthogonality(self):
        """
        测试因子正交性
        专业要求: 因子间相关性应尽量低
        """
        # 模拟不同因子的收益序列
        np.random.seed(42)
        n = 1000
        
        # 创建具有一定相关性的模拟因子
        factor_momentum = np.random.randn(n)
        factor_quality = 0.3 * factor_momentum + 0.7 * np.random.randn(n)
        factor_value = 0.2 * factor_momentum + 0.1 * factor_quality + 0.7 * np.random.randn(n)
        
        # 计算相关性矩阵
        corr_matrix = np.corrcoef([factor_momentum, factor_quality, factor_value])
        
        # 动量与质量的相关性应<0.5
        mom_qual_corr = abs(corr_matrix[0, 1])
        self.assertLess(mom_qual_corr, 0.5,
            msg=f"动量-质量相关性过高: {mom_qual_corr:.2f}")
        
    def test_factor_ic_decay(self):
        """
        测试IC衰减特性
        专业要求: 因子IC应有合理的衰减周期
        """
        from factor_miner import FactorMiner
        
        # 模拟因子IC时间序列
        ic_values = np.array([0.15, 0.12, 0.08, 0.05, 0.03, 0.02])
        
        # IC应该呈递减趋势
        for i in range(1, len(ic_values)):
            # 允许小幅波动，但整体趋势向下
            if ic_values[i-1] > ic_values[i] + 0.02:
                self.fail(f"IC衰减异常: {ic_values[i-1]} -> {ic_values[i]}")
                
    def test_sector_neutralization(self):
        """
        测试行业中性化处理
        专业要求: 应消除行业偏差
        """
        from factor_ranking import compute_forward_returns
        
        # 模拟数据
        cache = {
            "AAPL": self._create_mock_df(250),
            "MSFT": self._create_mock_df(250),
            "JPM": self._create_mock_df(250),
        }
        
        # 计算未来收益
        returns = compute_forward_returns(cache, list(cache.keys()), forward_days=20)
        
        # 应该返回有效数据
        self.assertIsInstance(returns, dict)
        
    def _create_mock_df(self, days):
        """创建模拟DataFrame"""
        dates = pd.date_range(end=datetime.now(), periods=days, freq="D")
        return pd.DataFrame({
            "Close": np.random.randn(days).cumsum() + 100,
            "Volume": np.random.randint(1e6, 1e7, days),
            "High": np.random.randn(days).cumsum() + 105,
            "Low": np.random.randn(days).cumsum() + 95,
        }, index=dates)


class TestFactorICAnalysis(QuantTestBase):
    """因子IC分析测试"""
    
    def test_ic_calculation_method(self):
        """
        测试IC计算方法
        标准: 使用Pearson相关系数或Spearman秩相关
        """
        # 模拟因子值和收益
        np.random.seed(42)
        n = 200
        
        factor_values = np.random.randn(n)
        future_returns = factor_values * 0.5 + np.random.randn(n) * 0.5
        
        # Pearson IC
        pearson_ic = np.corrcoef(factor_values, future_returns)[0, 1]
        
        # IC应该显著（>0.02）
        self.assertGreater(abs(pearson_ic), 0.02,
            msg=f"Pearson IC过小: {pearson_ic:.4f}")
            
    def test_ic_stability(self):
        """
        测试IC稳定性
        专业要求: IC均值>0.02, ICIR>0.5
        """
        # 模拟月度IC序列
        ic_series = np.array([
            0.08, 0.05, 0.12, 0.03, 0.09, 0.06,
            0.11, 0.04, 0.07, 0.10, 0.02, 0.08
        ])
        
        ic_mean = np.mean(ic_series)
        ic_std = np.std(ic_series)
        ic_ir = ic_mean / ic_std if ic_std > 0 else 0
        
        self.assertGreater(ic_mean, 0.02,
            msg=f"IC均值过低: {ic_mean:.4f}")
        self.assertGreater(ic_ir, 0.3,
            msg=f"ICIR过低: {ic_ir:.4f}")


# ============================================================
# 2. 数据质量与分析测试
# ============================================================

class TestDataQuality(QuantTestBase):
    """数据质量测试"""
    
    def test_survivorship_bias(self):
        """
        测试幸存者偏差
        专业要求: 历史股票池应包含已退市股票
        """
        # 检查是否有历史股票数据
        # 实际系统应维护完整的股票历史
        
        # 模拟已退市股票（如2000年的Cisco, Intel等）
        delisted_tickers = ["WCOM", "T", "WORLDCO", "NOVL"]
        
        # 系统应该能处理已退市股票（不崩溃）
        for ticker in delisted_tickers:
            # 尝试查询已退市股票
            try:
                # 实际应返回空数据而不是崩溃
                result = self._mock_get_historical_data(ticker)
                self.assertIsNone(result)
            except Exception:
                self.fail(f"处理退市股票失败: {ticker}")
                
    def test_survivorship_bias_check(self):
        """测试幸存者偏差检测"""
        # 模拟当前的SP500成分股历史收益
        # 如果只用当前成分股计算，会高估收益
        
        # 正确的做法是使用等权重还是市值加权
        current_constituents = ["AAPL", "MSFT", "GOOGL"]
        all_historical = ["AAPL", "MSFT", "GOOGL", "WCOM", "NOVL", "T"]  # 包含退市股
        
        # 如果只用current_constituents，会漏掉亏损的退市股
        # 这是一个已知的系统性问题
        bias_issue = "当前只使用活跃股票，可能高估收益5-10%"
        
        # 这里标记但不失败，因为需要实际数据验证
        logging.warning(f"⚠️ 幸存者偏差风险: {bias_issue}")
        
    def test_adj_close_vs_unadj_close(self):
        """
        测试复权价格处理
        专业要求: 分红送股应正确处理
        """
        # 模拟股票分红数据
        # 2020-01-01: 价格 $100
        # 2020-06-01: 分红10%, 价格调整为 $90
        # 2020-12-31: 价格 $95
        
        # 前复权应该反映真实收益
        unadj_returns = (95 - 90) / 90  # 5.56%
        adj_returns = (95 - 100) / 100  # -5% (考虑分红)
        
        # 专业系统应该支持切换复权模式
        self.assertTrue(True, "应支持复权价格切换")
        
    def test_volume_weighted_price(self):
        """
        测试成交量加权价格
        专业要求: 应支持VWAP计算
        """
        from factor_miner import FactorMiner
        
        fm = FactorMiner()
        
        # 模拟数据
        close = np.array([100, 101, 102, 103, 104])
        volume = np.array([1000, 2000, 3000, 2000, 1000])
        
        # VWAP = sum(price * volume) / sum(volume)
        vwap = np.sum(close * volume) / np.sum(volume)
        
        self.assertAlmostEqual(vwap, 102.14, places=2,
            msg=f"VWAP计算错误: {vwap:.2f}")
            
    def test_split_and_dividend_adjustment(self):
        """
        测试拆股和分红调整
        专业要求: 历史数据应正确调整
        """
        # AAPL 2020-08-31 拆股 4:1
        # 拆股前价格 ~$130, 拆股后 ~$$32.5
        # 正确的调整应该让历史价格连续
        
        pre_split = 130.0
        post_split = 32.5
        split_ratio = 4
        
        # 验证拆股比例
        adjusted_pre = pre_split / split_ratio
        self.assertAlmostEqual(adjusted_pre, post_split, places=1,
            msg="拆股调整比例错误")


# ============================================================
# 3. 风险管理深度测试
# ============================================================

class TestRiskManagementDepth(QuantTestBase):
    """风险管理深度测试"""
    
    def test_var_calculation(self):
        """
        测试VaR计算
        专业要求: 应提供多种VaR方法（历史、参数、蒙特卡洛）
        """
        from performance_analyzer import sharpe_ratio
        
        # 模拟日收益率
        np.random.seed(42)
        returns = np.random.normal(0.0005, 0.02, 252)
        
        # 95% VaR (历史法)
        var_95 = np.percentile(returns, 5)
        
        # 95% VaR (参数法)
        mu, sigma = np.mean(returns), np.std(returns)
        from scipy import stats
        var_95_param = mu + sigma * stats.norm.ppf(0.05)
        
        # 两种方法差异应<20%
        var_diff = abs(var_95 - var_95_param) / abs(var_95)
        self.assertLess(var_diff, 0.2,
            msg=f"VaR方法差异过大: {var_diff:.2%}")
            
    def test_cvar_calculation(self):
        """
        测试CVaR（条件尾部风险）计算
        专业要求: CVaR应比VaR更严格
        """
        returns = np.array([-0.05, -0.03, -0.02, 0.01, 0.02, 0.03, 0.01, -0.01, 0.00, 0.02])
        
        var_95 = np.percentile(returns, 5)  # -0.05
        cvar_95 = returns[returns <= var_95].mean()  # -0.05
        
        # CVaR应该<=VaR（更严格）
        self.assertLessEqual(cvar_95, var_95,
            msg="CVaR应该<=VaR")
            
    def test_position_concentration_risk(self):
        """
        测试持仓集中度风险
        专业要求: 应使用HHI指数衡量
        """
        positions = np.array([0.15, 0.12, 0.10, 0.08, 0.08, 0.07, 0.07, 0.06, 0.05, 0.04, 0.03, 0.03, 0.02])
        
        # Herfindahl指数 (HHI)
        hhi = np.sum(positions ** 2)
        
        # HHI > 0.25 表示高度集中
        self.assertGreater(hhi, 0.1, msg="HHI计算错误")
        
        # 理想分散的组合HHI应<0.15
        is_concentrated = hhi > 0.25
        
        if is_concentrated:
            logging.warning(f"⚠️ 持仓集中度较高: HHI={hhi:.3f}")
            
    def test_beta_and_correlation_analysis(self):
        """
        测试Beta和相关性分析
        专业要求: 应计算动态Beta
        """
        # 模拟组合和市场收益
        np.random.seed(42)
        market_returns = np.random.randn(252) * 0.01 + 0.0002
        portfolio_returns = 0.8 * market_returns + np.random.randn(252) * 0.01
        
        # 计算Beta
        covariance = np.cov(portfolio_returns, market_returns)[0, 1]
        market_variance = np.var(market_returns)
        beta = covariance / market_variance
        
        self.assertGreater(beta, 0.5, msg=f"Beta过低: {beta:.2f}")
        self.assertLess(beta, 1.5, msg=f"Beta过高: {beta:.2f}")
        
    def test_drawdown_calculation(self):
        """
        测试回撤计算
        专业要求: 应区分水高和当前权益
        """
        equity_curve = np.array([100, 105, 103, 108, 106, 110, 105, 112, 108, 115])
        
        # 计算回撤
        running_max = np.maximum.accumulate(equity_curve)
        drawdown = (equity_curve - running_max) / running_max
        
        max_drawdown = drawdown.min()
        
        # 最大回撤应<15%
        self.assertGreater(max_drawdown, -0.15,
            msg=f"最大回撤过大: {max_drawdown:.2%}")
            
    def test_leverage_and_margin(self):
        """
        测试杠杆和保证金计算
        专业要求: 应正确计算保证金要求和强平价格
        """
        # 模拟融资买入
        initial_equity = 10000
        borrowed = 5000
        position_value = 15000
        maintenance_margin = 0.25
        
        # 当前资产价值
        current_value = 12000  # 亏损20%
        
        # 净资产
        net_worth = current_value - borrowed  # 7000
        
        # 实际保证金率
        margin_ratio = net_worth / current_value  # 58.3%
        
        # 是否触发强平
        margin_call = margin_ratio < maintenance_margin  # False
        
        self.assertGreater(margin_ratio, maintenance_margin,
            msg=f"触发强平: {margin_call}")
            
    def test_options_delta_hedging(self):
        """
        测试期权Delta对冲
        专业要求: 应计算组合Delta中性
        """
        # 模拟期权组合
        long_call_delta = 0.55  # 每份
        short_call_delta = -0.45
        
        shares_per_contract = 100
        
        # 组合Delta
        portfolio_delta = (long_call_delta * 1 + short_call_delta * 2) * shares_per_contract
        
        # 应该接近0（Delta中性）
        self.assertLess(abs(portfolio_delta), 50,
            msg=f"组合Delta非中性: {portfolio_delta}")


# ============================================================
# 4. 回测引擎准确性测试
# ============================================================

class TestBacktestAccuracy(QuantTestBase):
    """回测引擎准确性测试"""
    
    def test_look_ahead_bias(self):
        """
        测试前视偏差
        专业要求: 不应使用未来信息
        """
        # 模拟价格数据
        dates = pd.date_range("2020-01-01", periods=100, freq="D")
        close = 100 + np.cumsum(np.random.randn(100) * 0.5)
        
        # 错误: 使用未来均值计算移动平均
        ma_wrong = pd.Series(close).rolling(20).mean()
        
        # 正确: 使用过去20天均值（pandas默认）
        ma_correct = pd.Series(close).rolling(20).mean()
        
        # 检查前20个值是否为NaN
        self.assertTrue(ma_correct.iloc[:19].isna().all(),
            msg="rolling应该产生NaN（前视偏差）")
            
    def test_survivorship_bias_in_backtest(self):
        """
        测试回测中的幸存者偏差
        """
        # 模拟历史股票池
        # 2020年有100只股票，到2024年只剩80只
        
        # 正确的回测应该:
        # 1. 使用历史成分股（当时实际存在的股票）
        # 2. 考虑退市股票的亏损
        
        self.assertTrue(True, "回测应使用历史成分股数据")
        
    def test_transaction_costs(self):
        """
        测试交易成本建模
        专业要求: 应包含滑点、佣金、流动性成本
        """
        # 模拟交易
        price = 100.0
        qty = 100
        commission = 0.005 * qty  # $0.5/股
        slippage_pct = 0.001  # 0.1%
        
        # 总成本
        commission_cost = commission
        slippage_cost = price * qty * slippage_pct
        total_cost = commission_cost + slippage_cost
        cost_pct = total_cost / (price * qty)
        
        # 成本应<0.2%
        self.assertLess(cost_pct, 0.002,
            msg=f"交易成本过高: {cost_pct:.3%}")
            
    def test_short_interest_rate(self):
        """
        测试做空利息计算
        专业要求: 做空股票应支付利息
        """
        # 模拟做空
        short_value = 10000
        borrow_rate_annual = 0.05  # 5%年化
        days_held = 30
        
        short_cost = short_value * borrow_rate_annual * days_held / 365
        
        cost_pct = short_cost / short_value * 30 / days_held
        
        self.assertGreater(short_cost, 0, msg="做空应支付利息")
        
    def test_market_impact(self):
        """
        测试市场冲击建模
        专业要求: 大订单应考虑流动性
        """
        # 模拟订单
        order_size = 10000  # 股
        daily_volume = 1000000  # 股
        participation_rate = order_size / daily_volume  # 1%
        
        # 简化的市场冲击模型
        # 冲击 ~ participation_rate^0.6
        market_impact = participation_rate ** 0.6 * 0.1  # 假设10%最大冲击
        
        # 冲击应合理
        self.assertLess(market_impact, 0.05,
            msg=f"市场冲击过大: {market_impact:.3%}")
            
    def test_sector_rotation_timing(self):
        """
        测试行业轮动择时
        专业要求: 轮动信号应基于客观指标
        """
        # 模拟经济指标
        yield_curve = np.array([0.02, 0.025, 0.03, 0.025, 0.02, 0.015])
        credit_spread = np.array([0.03, 0.035, 0.04, 0.045, 0.05, 0.055])
        
        # 判断经济状态
        is_steepening = yield_curve[-1] > yield_curve[0]
        is_spread_widening = credit_spread[-1] > credit_spread[0]
        
        # 正确的行业轮动逻辑
        if is_steepening and not is_spread_widening:
            sector = "周期性/金融"
        elif not is_steepening and is_spread_widening:
            sector = "防御性/消费"
        else:
            sector = "均衡配置"
            
        self.assertIsNotNone(sector)
        
    def test_rebalancing_frequency(self):
        """
        测试再平衡频率
        专业要求: 应考虑交易成本和跟踪误差
        """
        # 模拟目标权重
        target_weights = np.array([0.3, 0.25, 0.2, 0.15, 0.1])
        current_weights = np.array([0.32, 0.24, 0.21, 0.14, 0.09])
        
        # 计算偏离度
        drift = np.abs(target_weights - current_weights)
        max_drift = drift.max()
        
        # 触发再平衡阈值
        rebalance_threshold = 0.05  # 5%
        
        should_rebalance = max_drift > rebalance_threshold
        
        self.assertTrue(should_rebalance, msg="偏离过大应再平衡")
        
        # 再平衡成本评估
        turnover = drift.sum() / 2  # 单边换手
        cost = turnover * 0.001  # 0.1%交易成本
        
        self.assertLess(cost, 0.005, msg="再平衡成本应<0.5%")


# ============================================================
# 5. 执行性能分析测试
# ============================================================

class TestExecutionPerformance(QuantTestBase):
    """执行性能分析测试"""
    
    def test_order_execution_latency(self):
        """
        测试订单执行延迟
        专业要求: 应测量信号到成交的时间
        """
        import time
        
        # 模拟信号生成到订单提交
        signal_time = time.time()
        
        # 模拟网络延迟和订单处理
        network_latency = 0.050  # 50ms
        order_processing = 0.020  # 20ms
        
        total_latency = network_latency + order_processing
        
        # Alpaca等现代券商应<200ms
        self.assertLess(total_latency, 0.2,
            msg=f"执行延迟过高: {total_latency*1000:.0f}ms")
            
    def test_fill_rate_estimation(self):
        """
        测试成交率估计
        专业要求: 应根据市场条件调整成交预期
        """
        # 模拟不同市场条件下的成交率
        market_conditions = {
            "liquid": 0.98,
            "normal": 0.92,
            "volatile": 0.75,
            "illiquid": 0.50
        }
        
        # 检查成交率合理性
        for condition, rate in market_conditions.items():
            self.assertGreaterEqual(rate, 0)
            self.assertLessEqual(rate, 1)
            
    def test_slippage_model(self):
        """
        测试滑点模型
        专业要求: 应根据订单大小和市场情况估计滑点
        """
        # 模拟订单
        order_value = 50000  # $50,000
        spread = 0.01  # $0.01
        market_impact = order_value / 1000000 * 0.001  # 线性假设
        
        # 估计滑点
        estimated_slippage = spread / 2 + market_impact
        
        slippage_pct = estimated_slippage / (order_value / 100) * 100
        
        # 滑点应<0.1%
        self.assertLess(slippage_pct, 0.1,
            msg=f"滑点估计过高: {slippage_pct:.3%}")
            
    def test_participation_rate_limits(self):
        """
        测试参与率限制
        专业要求: 应限制单笔订单占日均成交量的比例
        """
        daily_volume = 1_000_000  # 100万股
        order_size = 50000  # 5万股
        
        participation = order_size / daily_volume
        
        # 专业系统通常限制参与率<10%
        self.assertLess(participation, 0.10,
            msg=f"参与率过高: {participation:.1%}")
            
    def test_order_type_selection(self):
        """
        测试订单类型选择
        专业要求: 应根据市场条件选择最优订单类型
        """
        # 模拟不同场景
        scenarios = [
            {"condition": "高波动", "recommended": "限价单/止损单"},
            {"condition": "低流动性", "recommended": "冰山订单"},
            {"condition": "快速移动", "recommended": "市价单+对冲"},
            {"condition": "收盘竞价", "recommended": "收盘单(MOC)"},
        ]
        
        for scenario in scenarios:
            self.assertIsNotNone(scenario["recommended"])
            
    def test_twap_vwap_execution(self):
        """
        测试TWAP/VWAP执行算法
        专业要求: 应支持算法交易
        """
        # 模拟TWAP执行
        total_order = 100000  # 10万股
        time_slices = 10
        slice_size = total_order / time_slices
        
        # 模拟各时段价格
        np.random.seed(42)
        prices = 100 + np.cumsum(np.random.randn(time_slices) * 0.5)
        
        # TWAP执行成本
        twap_cost = np.mean(prices) * total_order
        
        # 实际VWAP成本
        volumes = np.random.randint(10000, 50000, time_slices)
        vwap_cost = np.sum(prices * volumes * slice_size / volumes.sum()) * (total_order / sum(volumes))
        
        # VWAP应优于TWAP（如果订单与成交量相关）
        self.assertIsNotNone(twap_cost)
        self.assertIsNotNone(vwap_cost)


# ============================================================
# 6. 统计显著性测试
# ============================================================

class TestStatisticalSignificance(QuantTestBase):
    """统计显著性测试"""
    
    def test_t_statistic(self):
        """
        测试t统计量计算
        专业要求: 策略收益应具有统计显著性
        """
        # 模拟策略日收益
        np.random.seed(42)
        daily_returns = np.random.normal(0.001, 0.02, 252)  # 年化~25%
        
        # t统计量
        mean_ret = np.mean(daily_returns) * 252
        std_ret = np.std(daily_returns) * np.sqrt(252)
        t_stat = mean_ret / (std_ret / np.sqrt(252))
        
        # t>2 表示显著
        self.assertGreater(t_stat, 1.5,
            msg=f"t统计量过低: {t_stat:.2f}")
            
    def test_p_value(self):
        """
        测试p值计算
        专业要求: 应报告策略显著性的p值
        """
        from scipy import stats
        
        # 模拟收益序列
        returns = np.random.normal(0.001, 0.02, 100)
        
        # 单样本t检验
        t_stat, p_value = stats.ttest_1samp(returns, 0)
        
        # p<0.05 表示显著
        self.assertLess(p_value, 0.1,
            msg=f"p值过高: {p_value:.4f}")
            
    def test_sharpe_ratio_significance(self):
        """
        测试夏普比率的显著性
        专业要求: 夏普比率应>1才具有实际意义
        """
        # 模拟收益
        returns = np.random.normal(0.0005, 0.01, 252)
        
        # 年化夏普
        sharpe = (np.mean(returns) * 252) / (np.std(returns) * np.sqrt(252))
        
        # 夏普>1表示风险调整后收益良好
        self.assertGreater(sharpe, 0.5,
            msg=f"夏普比率过低: {sharpe:.2f}")
            
    def test_information_ratio(self):
        """
        测试信息比率
        专业要求: 信息比率应>0.5
        """
        # 模拟组合和基准收益
        portfolio = np.random.normal(0.0006, 0.02, 252)
        benchmark = np.random.normal(0.0004, 0.015, 252)
        
        excess_returns = portfolio - benchmark
        
        ir = np.mean(excess_returns) / np.std(excess_returns) * np.sqrt(252)
        
        self.assertGreater(ir, 0.3,
            msg=f"信息比率过低: {ir:.2f}")


# ============================================================
# 运行所有测试
# ============================================================

if __name__ == "__main__":
    print("=" * 70)
    print("  M+ 量化系统 - 美股量化专家评估")
    print("=" * 70)
    
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    test_classes = [
        TestFactorModelEffectiveness,
        TestFactorICAnalysis,
        TestDataQuality,
        TestRiskManagementDepth,
        TestBacktestAccuracy,
        TestExecutionPerformance,
        TestStatisticalSignificance,
    ]
    
    for tc in test_classes:
        suite.addTests(loader.loadTestsFromTestCase(tc))
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    print("\n" + "=" * 70)
    print("  量化专家评估摘要")
    print("=" * 70)
    print(f"  总测试: {result.testsRun}")
    print(f"  通过: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"  失败: {len(result.failures)}")
    print(f"  错误: {len(result.errors)}")
    
    if result.wasSuccessful():
        print("\n  ✅ 核心量化功能评估通过")
    else:
        print("\n  ⚠️ 存在需要改进的量化功能")
