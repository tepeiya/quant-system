"""
智能风控模块 v1.0
=================
使用机器学习进行异常检测和风险预警

功能：
1. 异常交易检测
2. 持仓异常检测
3. 市场异常检测
4. 风险预测模型
5. 自适应风控规则
6. 实时风险预警
"""

import os
import json
import logging
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass

logger = logging.getLogger("quant.intelligent_risk")


@dataclass
class RiskAlert:
    """风险告警"""
    alert_id: str
    alert_type: str  # anomaly / threshold / prediction
    severity: str    # low / medium / high / critical
    message: str
    details: Dict
    timestamp: str
    action_required: str


# ===== 异常检测器 =====

class AnomalyDetector:
    """异常检测器"""
    
    def __init__(self, model_type: str = "isolation_forest"):
        self.model_type = model_type
        self.model = None
        self.feature_stats = {}  # 特征统计
    
    def train(self, training_data: pd.DataFrame):
        """
        训练异常检测模型
        
        Args:
            training_data: 训练数据（正常样本）
        """
        logger.info(f"训练异常检测模型: {self.model_type}")
        
        if self.model_type == "isolation_forest":
            from sklearn.ensemble import IsolationForest
            self.model = IsolationForest(
                n_estimators=100,
                contamination=0.05,  # 假设5%异常
                random_state=42
            )
        
        elif self.model_type == "zscore":
            # Z-score方法不需要训练模型
            self.model = None
        
        elif self.model_type == "autoencoder":
            # 简化的自编码器（实际需要深度学习框架）
            self.model = None
        
        if self.model is not None:
            self.model.fit(training_data)
        
        # 计算特征统计（用于Z-score方法）
        self.feature_stats = {
            "mean": training_data.mean().to_dict(),
            "std": training_data.std().to_dict(),
            "min": training_data.min().to_dict(),
            "max": training_data.max().to_dict()
        }
        
        logger.info("模型训练完成")
    
    def detect(self, data_point: pd.DataFrame) -> Tuple[bool, float, Dict]:
        """
        检测异常
        
        Args:
            data_point: 待检测数据
        
        Returns:
            (是否异常, 异常分数, 异常特征)
        """
        if self.model_type == "isolation_forest" and self.model is not None:
            prediction = self.model.predict(data_point)
            score = self.model.score_samples(data_point)
            
            is_anomaly = prediction[0] == -1
            anomaly_score = abs(score[0])
            
            # 分析哪些特征异常
            anomaly_features = self._analyze_anomaly_features(data_point)
            
            return is_anomaly, anomaly_score, anomaly_features
        
        elif self.model_type == "zscore":
            return self._detect_with_zscore(data_point)
        
        else:
            return False, 0, {}
    
    def _detect_with_zscore(self, data_point: pd.DataFrame) -> Tuple[bool, float, Dict]:
        """Z-score异常检测"""
        anomaly_features = {}
        total_score = 0
        
        for col in data_point.columns:
            mean = self.feature_stats.get("mean", {}).get(col, 0)
            std = self.feature_stats.get("std", {}).get(col, 1)
            
            if std > 0:
                zscore = abs((data_point[col].iloc[0] - mean) / std)
                
                if zscore > 3:  # 超过3个标准差视为异常
                    anomaly_features[col] = {
                        "value": data_point[col].iloc[0],
                        "zscore": zscore,
                        "mean": mean,
                        "std": std
                    }
                    total_score += zscore
        
        is_anomaly = len(anomaly_features) > 0
        anomaly_score = total_score
        
        return is_anomaly, anomaly_score, anomaly_features
    
    def _analyze_anomaly_features(self, data_point: pd.DataFrame) -> Dict:
        """分析异常特征"""
        anomaly_features = {}
        
        # 比较数据点与均值
        for col in data_point.columns:
            mean = self.feature_stats.get("mean", {}).get(col, 0)
            std = self.feature_stats.get("std", {}).get(col, 1)
            
            value = data_point[col].iloc[0]
            deviation = abs(value - mean) / std if std > 0 else 0
            
            if deviation > 2:  # 超过2个标准差
                anomaly_features[col] = {
                    "value": value,
                    "expected_range": f"{mean - 2*std:.2f} - {mean + 2*std:.2f}",
                    "deviation": deviation
                }
        
        return anomaly_features
    
    def save_model(self, path: str):
        """保存模型"""
        import joblib
        
        model_data = {
            "model": self.model,
            "model_type": self.model_type,
            "feature_stats": self.feature_stats
        }
        
        joblib.dump(model_data, path)
        logger.info(f"模型已保存: {path}")
    
    def load_model(self, path: str):
        """加载模型"""
        import joblib
        
        model_data = joblib.load(path)
        self.model = model_data["model"]
        self.model_type = model_data["model_type"]
        self.feature_stats = model_data["feature_stats"]
        
        logger.info(f"模型已加载: {path}")


# ===== 交易异常检测 =====

class TradingAnomalyDetector:
    """交易异常检测"""
    
    def __init__(self):
        self.detector = AnomalyDetector(model_type="zscore")
        self._initialize_detector()
    
    def _initialize_detector(self):
        """初始化检测器"""
        # 正常交易特征
        normal_trading_data = pd.DataFrame({
            "order_size_pct": np.random.uniform(0.01, 0.10, 1000),  # 单笔订单占总资金1-10%
            "order_frequency": np.random.uniform(0.1, 2, 1000),      # 每小时订单数
            "price_deviation": np.random.uniform(0.001, 0.02, 1000), # 价格偏离度
            "hold_time": np.random.uniform(1, 30, 1000),             # 持仓天数
            "sector_concentration": np.random.uniform(0.1, 0.4, 1000), # 行业集中度
            "win_rate": np.random.uniform(0.45, 0.65, 1000),         # 胜率
            "profit_factor": np.random.uniform(1.0, 3.0, 1000),      # 利润因子
        })
        
        self.detector.train(normal_trading_data)
    
    def check_order(self, order_data: Dict) -> Optional[RiskAlert]:
        """
        检查订单是否异常
        
        Args:
            order_data: {
                "ticker": 股票代码,
                "size_pct": 订单大小百分比,
                "frequency": 订单频率,
                "price_deviation": 价格偏离度,
                "sector": 行业,
                "portfolio_sector_concentration": 当前行业集中度
            }
        
        Returns:
            RiskAlert（如果异常）
        """
        data_point = pd.DataFrame({
            "order_size_pct": [order_data.get("size_pct", 0)],
            "order_frequency": [order_data.get("frequency", 0)],
            "price_deviation": [order_data.get("price_deviation", 0)],
            "hold_time": [order_data.get("hold_time", 0)],
            "sector_concentration": [order_data.get("portfolio_sector_concentration", 0)],
            "win_rate": [0.5],
            "profit_factor": [1.5]
        })
        
        is_anomaly, score, features = self.detector.detect(data_point)
        
        if is_anomaly:
            severity = self._determine_severity(score)
            
            return RiskAlert(
                alert_id=f"TRADE_{datetime.now().strftime('%Y%m%d%H%M%S')}",
                alert_type="anomaly",
                severity=severity,
                message=f"检测到异常交易模式: {order_data['ticker']}",
                details={
                    "order_data": order_data,
                    "anomaly_score": score,
                    "anomaly_features": features
                },
                timestamp=datetime.now().isoformat(),
                action_required="审查订单，确认是否继续执行"
            )
        
        return None
    
    def _determine_severity(self, score: float) -> str:
        """确定严重程度"""
        if score > 20:
            return "critical"
        elif score > 10:
            return "high"
        elif score > 5:
            return "medium"
        else:
            return "low"


# ===== 持仓异常检测 =====

class PositionAnomalyDetector:
    """持仓异常检测"""
    
    def __init__(self):
        self.detector = AnomalyDetector(model_type="zscore")
        self._initialize_detector()
    
    def _initialize_detector(self):
        """初始化检测器"""
        normal_position_data = pd.DataFrame({
            "position_count": np.random.randint(5, 30, 1000),
            "total_exposure_pct": np.random.uniform(0.5, 0.9, 1000),
            "max_single_position_pct": np.random.uniform(0.05, 0.15, 1000),
            "sector_concentration": np.random.uniform(0.1, 0.35, 1000),
            "beta_exposure": np.random.uniform(0.5, 1.5, 1000),
            "volatility_exposure": np.random.uniform(0.01, 0.05, 1000),
        })
        
        self.detector.train(normal_position_data)
    
    def check_positions(self, positions: Dict) -> Optional[RiskAlert]:
        """检查持仓是否异常"""
        # 计算持仓指标 - 处理不同的数据格式
        total_value = 0
        pos_data = {}
        
        for ticker, pos in positions.items():
            if isinstance(pos, dict):
                pos_data[ticker] = pos
                total_value += pos.get("market_value", 0)
            elif isinstance(pos, (int, float)):
                # 简化格式：ticker -> value
                pos_data[ticker] = {"market_value": pos}
                total_value += pos
            elif ticker == "total_value":
                total_value = pos
        
        if total_value == 0:
            total_value = sum(p.get("market_value", 0) for p in pos_data.values())
        
        position_count = len(pos_data)
        total_exposure_pct = 1.0  # 假设全部投入
        
        # 最大单只仓位
        max_position = max(p.get("market_value", 0) for p in pos_data.values())
        max_single_position_pct = max_position / total_value if total_value > 0 else 0
        
        # 行业集中度
        sectors = {}
        for ticker, pos in pos_data.items():
            sector = pos.get("sector", "unknown")
            sectors[sector] = sectors.get(sector, 0) + pos.get("market_value", 0)
        
        sector_concentration = max(sectors.values()) / total_value if total_value > 0 and sectors else 0
        
        data_point = pd.DataFrame({
            "position_count": [position_count],
            "total_exposure_pct": [total_exposure_pct],
            "max_single_position_pct": [max_single_position_pct],
            "sector_concentration": [sector_concentration],
            "beta_exposure": [1.0],
            "volatility_exposure": [0.02]
        })
        
        is_anomaly, score, features = self.detector.detect(data_point)
        
        if is_anomaly:
            return RiskAlert(
                alert_id=f"POS_{datetime.now().strftime('%Y%m%d%H%M%S')}",
                alert_type="anomaly",
                severity=self._determine_severity(score),
                message="检测到异常持仓结构",
                details={
                    "position_metrics": {
                        "count": position_count,
                        "max_single_pct": max_single_position_pct,
                        "sector_concentration": sector_concentration
                    },
                    "anomaly_score": score,
                    "anomaly_features": features
                },
                timestamp=datetime.now().isoformat(),
                action_required="审查持仓结构，考虑调整"
            )
        
        return None
    
    def _determine_severity(self, score: float) -> str:
        if score > 15:
            return "critical"
        elif score > 8:
            return "high"
        elif score > 4:
            return "medium"
        else:
            return "low"


# ===== 市场异常检测 =====

class MarketAnomalyDetector:
    """市场异常检测"""
    
    def __init__(self):
        self.detector = AnomalyDetector(model_type="zscore")
        self._initialize_detector()
    
    def _initialize_detector(self):
        """初始化检测器"""
        normal_market_data = pd.DataFrame({
            "vix": np.random.uniform(15, 30, 1000),
            "market_return": np.random.uniform(-0.02, 0.02, 1000),
            "volume_ratio": np.random.uniform(0.8, 1.5, 1000),
            "yield_curve_spread": np.random.uniform(0.5, 2.5, 1000),
            "credit_spread": np.random.uniform(0.01, 0.03, 1000),
        })
        
        self.detector.train(normal_market_data)
    
    def check_market(self, market_data: Dict) -> Optional[RiskAlert]:
        """检查市场状态"""
        data_point = pd.DataFrame({
            "vix": [market_data.get("vix", 20)],
            "market_return": [market_data.get("market_return", 0)],
            "volume_ratio": [market_data.get("volume_ratio", 1)],
            "yield_curve_spread": [market_data.get("yield_curve_spread", 1)],
            "credit_spread": [market_data.get("credit_spread", 0.02)]
        })
        
        is_anomaly, score, features = self.detector.detect(data_point)
        
        if is_anomaly:
            return RiskAlert(
                alert_id=f"MARKET_{datetime.now().strftime('%Y%m%d%H%M%S')}",
                alert_type="anomaly",
                severity=self._determine_severity(score),
                message="检测到异常市场状态",
                details={
                    "market_data": market_data,
                    "anomaly_score": score,
                    "anomaly_features": features
                },
                timestamp=datetime.now().isoformat(),
                action_required="调整仓位，考虑对冲"
            )
        
        return None
    
    def _determine_severity(self, score: float) -> str:
        if score > 10:
            return "critical"
        elif score > 6:
            return "high"
        elif score > 3:
            return "medium"
        else:
            return "low"


# ===== 风险预测模型 =====

class RiskPredictor:
    """风险预测模型"""
    
    def __init__(self):
        self.model = None
        self.feature_importance = {}
    
    def train(self, historical_data: pd.DataFrame):
        """训练风险预测模型"""
        logger.info("训练风险预测模型")
        
        # 使用简单的线性模型（实际可用更复杂模型）
        from sklearn.linear_model import LinearRegression
        
        # 特征: vix, market_return, yield_curve_spread, beta_exposure, position_count
        # 目标: future_drawdown
        
        if "future_drawdown" in historical_data.columns:
            X = historical_data.drop("future_drawdown", axis=1)
            y = historical_data["future_drawdown"]
            
            self.model = LinearRegression()
            self.model.fit(X, y)
            
            # 特征重要性
            self.feature_importance = dict(zip(X.columns, self.model.coef_))
            
            logger.info("风险预测模型训练完成")
        else:
            logger.warning("缺少目标变量，无法训练")
    
    def predict(self, current_features: Dict) -> Dict:
        """
        预测风险
        
        Args:
            current_features: 当前特征
        
        Returns:
            {
                "predicted_drawdown": 预期最大回撤,
                "risk_level": 风险等级,
                "key_risk_factors": 主要风险因素
            }
        """
        if self.model is None:
            # 使用规则模型
            return self._predict_with_rules(current_features)
        
        # 使用机器学习模型预测
        feature_values = [current_features.get(f, 0) for f in self.feature_importance.keys()]
        
        predicted_drawdown = self.model.predict([feature_values])[0]
        
        # 主要风险因素
        key_risk_factors = []
        for factor, importance in self.feature_importance.items():
            if importance > 0.1:
                key_risk_factors.append({
                    "factor": factor,
                    "importance": importance,
                    "current_value": current_features.get(factor, 0)
                })
        
        risk_level = self._determine_risk_level(predicted_drawdown)
        
        return {
            "predicted_drawdown": predicted_drawdown,
            "risk_level": risk_level,
            "key_risk_factors": key_risk_factors
        }
    
    def _predict_with_rules(self, features: Dict) -> Dict:
        """规则预测"""
        # 基于规则的简单预测
        vix = features.get("vix", 20)
        beta = features.get("beta_exposure", 1)
        concentration = features.get("sector_concentration", 0.2)
        
        # 预期回撤计算
        base_drawdown = 0.1  # 基础10%
        
        # VIX影响
        vix_factor = (vix - 20) / 20 * 0.1
        
        # Beta影响
        beta_factor = (beta - 1) * 0.05
        
        # 集中度影响
        concentration_factor = concentration * 0.1
        
        predicted_drawdown = base_drawdown + vix_factor + beta_factor + concentration_factor
        
        risk_level = self._determine_risk_level(predicted_drawdown)
        
        return {
            "predicted_drawdown": predicted_drawdown,
            "risk_level": risk_level,
            "key_risk_factors": [
                {"factor": "vix", "importance": 0.3, "current_value": vix},
                {"factor": "beta", "importance": 0.25, "current_value": beta},
                {"factor": "concentration", "importance": 0.2, "current_value": concentration}
            ]
        }
    
    def _determine_risk_level(self, drawdown: float) -> str:
        """确定风险等级"""
        if drawdown < 0.05:
            return "低风险 🟢"
        elif drawdown < 0.10:
            return "中等风险 🟡"
        elif drawdown < 0.20:
            return "较高风险 🟠"
        else:
            return "高风险 🔴"


# ===== 自适应风控规则 =====

class AdaptiveRiskController:
    """自适应风控规则"""
    
    def __init__(self):
        self.rules = self._default_rules()
        self.learning_data = []
    
    def _default_rules(self) -> Dict:
        """默认风控规则"""
        return {
            "max_position_size": 0.15,
            "max_sector_concentration": 0.30,
            "max_beta_exposure": 1.5,
            "max_drawdown_trigger": 0.10,
            "stop_loss_pct": 0.05,
            "vix_threshold": 30,
            "volume_ratio_threshold": 2.0
        }
    
    def update_rules(self, performance_data: pd.DataFrame):
        """
        根据历史表现更新规则
        
        Args:
            performance_data: 历史表现数据
        """
        logger.info("更新风控规则")
        
        # 根据历史最大回撤调整
        if "max_drawdown" in performance_data.columns:
            avg_drawdown = performance_data["max_drawdown"].mean()
            
            # 如果历史回撤较大，收紧规则
            if avg_drawdown > 0.15:
                self.rules["max_position_size"] = 0.10
                self.rules["max_sector_concentration"] = 0.25
                self.rules["stop_loss_pct"] = 0.04
            elif avg_drawdown < 0.05:
                # 表现良好，可以适度放宽
                self.rules["max_position_size"] = 0.20
                self.rules["max_sector_concentration"] = 0.35
        
        logger.info(f"规则更新完成: {self.rules}")
    
    def apply_rules(self, position_data: Dict) -> List[RiskAlert]:
        """应用风控规则"""
        alerts = []
        
        # 检查仓位大小
        total_value = position_data.get("total_value", 0)
        
        for ticker, pos in position_data.get("positions", {}).items():
            pos_pct = pos.get("market_value", 0) / total_value if total_value > 0 else 0
            
            if pos_pct > self.rules["max_position_size"]:
                alerts.append(RiskAlert(
                    alert_id=f"RULE_{datetime.now().strftime('%Y%m%d%H%M%S')}_{ticker}",
                    alert_type="threshold",
                    severity="high",
                    message=f"{ticker} 仓位超标 ({pos_pct:.2%} > {self.rules['max_position_size']:.2%})",
                    details={"ticker": ticker, "position_pct": pos_pct},
                    timestamp=datetime.now().isoformat(),
                    action_required=f"减仓 {ticker} 至 {self.rules['max_position_size']:.2%} 以内"
                ))
        
        return alerts
    
    def get_current_rules(self) -> Dict:
        """获取当前规则"""
        return self.rules


# ===== 综合风险管理器 =====

class IntelligentRiskManager:
    """智能风险管理器"""
    
    def __init__(self):
        self.trade_detector = TradingAnomalyDetector()
        self.position_detector = PositionAnomalyDetector()
        self.market_detector = MarketAnomalyDetector()
        self.risk_predictor = RiskPredictor()
        self.adaptive_controller = AdaptiveRiskController()
        
        self.alerts_history = []
    
    def comprehensive_check(self, trade_data: Dict = None,
                            positions: Dict = None,
                            market_data: Dict = None) -> Dict:
        """
        全面风险检查
        
        Returns:
            {
                "alerts": 所有告警,
                "risk_summary": 风险摘要,
                "recommendations": 建议
            }
        """
        alerts = []
        
        # 检查交易
        if trade_data:
            trade_alert = self.trade_detector.check_order(trade_data)
            if trade_alert:
                alerts.append(trade_alert)
        
        # 检查持仓
        if positions:
            position_alert = self.position_detector.check_positions(positions)
            if position_alert:
                alerts.append(position_alert)
            
            # 应用风控规则
            rule_alerts = self.adaptive_controller.apply_rules(positions)
            alerts.extend(rule_alerts)
        
        # 检查市场
        if market_data:
            market_alert = self.market_detector.check_market(market_data)
            if market_alert:
                alerts.append(market_alert)
        
        # 记录告警历史
        self.alerts_history.extend(alerts)
        
        # 风险摘要
        risk_summary = self._generate_risk_summary(alerts)
        
        # 建议
        recommendations = self._generate_recommendations(alerts)
        
        return {
            "alerts": alerts,
            "risk_summary": risk_summary,
            "recommendations": recommendations,
            "timestamp": datetime.now().isoformat()
        }
    
    def predict_risk(self, features: Dict) -> Dict:
        """预测风险"""
        return self.risk_predictor.predict(features)
    
    def _generate_risk_summary(self, alerts: List[RiskAlert]) -> Dict:
        """生成风险摘要"""
        if not alerts:
            return {
                "overall_risk": "低",
                "alert_count": 0,
                "highest_severity": "无"
            }
        
        severity_order = {"critical": 4, "high": 3, "medium": 2, "low": 1}
        
        highest_severity = max(alerts, key=lambda a: severity_order.get(a.severity, 0)).severity
        
        # 按类型统计
        type_counts = {}
        for alert in alerts:
            type_counts[alert.alert_type] = type_counts.get(alert.alert_type, 0) + 1
        
        overall_risk = {
            "critical": "极高",
            "high": "高",
            "medium": "中等",
            "low": "低"
        }.get(highest_severity, "低")
        
        return {
            "overall_risk": overall_risk,
            "alert_count": len(alerts),
            "highest_severity": highest_severity,
            "alert_types": type_counts
        }
    
    def _generate_recommendations(self, alerts: List[RiskAlert]) -> List[str]:
        """生成建议"""
        recommendations = []
        
        for alert in alerts:
            recommendations.append(f"[{alert.severity}] {alert.action_required}")
        
        return recommendations
    
    def generate_report(self) -> str:
        """生成风险报告"""
        report = f"""
# 智能风控报告

生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## 告警统计
- 总告警数: {len(self.alerts_history)}

## 当前风控规则
{json.dumps(self.adaptive_controller.get_current_rules(), indent=2)}

## 最近告警
"""
        
        for alert in self.alerts_history[-5:]:
            report += f"""
### {alert.alert_id}
- 类型: {alert.alert_type}
- 严重程度: {alert.severity}
- 消息: {alert.message}
- 建议: {alert.action_required}
"""
        
        return report


# ===== 便捷函数 =====

def check_risk(trade_data: Dict = None, positions: Dict = None, market_data: Dict = None) -> Dict:
    """便捷风险检查"""
    manager = IntelligentRiskManager()
    return manager.comprehensive_check(trade_data, positions, market_data)


# ===== 测试 =====

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print("\n🧪 智能风控测试")
    print("=" * 50)
    
    manager = IntelligentRiskManager()
    
    # 测试交易异常检测
    trade_data = {
        "ticker": "AAPL",
        "size_pct": 0.25,  # 异常大订单
        "frequency": 5.0,  # 异常高频
        "price_deviation": 0.01,
        "portfolio_sector_concentration": 0.3
    }
    
    print("\n📊 交易检查:")
    result = manager.comprehensive_check(trade_data=trade_data)
    
    if result["alerts"]:
        for alert in result["alerts"]:
            print(f"  ⚠️ [{alert.severity}] {alert.message}")
    else:
        print("  ✅ 无异常")
    
    # 测试持仓异常检测
    positions = {
        "AAPL": {"market_value": 80000, "sector": "tech"},
        "MSFT": {"market_value": 15000, "sector": "tech"},  # 异常集中
        "GOOGL": {"market_value": 5000, "sector": "tech"},
        "total_value": 100000
    }
    
    print("\n📊 持仓检查:")
    result = manager.comprehensive_check(positions=positions)
    
    if result["alerts"]:
        for alert in result["alerts"]:
            print(f"  ⚠️ [{alert.severity}] {alert.message}")
    
    # 风险预测
    features = {
        "vix": 25,
        "beta_exposure": 1.2,
        "sector_concentration": 0.4
    }
    
    print("\n📊 风险预测:")
    prediction = manager.predict_risk(features)
    print(f"  预期回撤: {prediction['predicted_drawdown']:.2%}")
    print(f"  风险等级: {prediction['risk_level']}")
    
    print("\n" + "=" * 50)