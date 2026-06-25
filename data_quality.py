"""
数据质量监控模块 v1.0
=======================
监控和管理数据质量，确保量化系统的数据可靠性

功能：
1. 数据完整性检查（缺失值、异常值）
2. 数据时效性监控（过期数据告警）
3. 数据一致性检查（跨数据源对比）
4. 数据质量评分
5. 告警通知
"""

import os
import json
import logging
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple

logger = logging.getLogger("quant.data_quality")

# 配置
QUALITY_CONFIG_FILE = "config/data_quality_config.json"
ALERT_THRESHOLDS = {
    "missing_rate": 0.1,  # 缺失率超过10%告警
    "stale_hours": 24,     # 数据超过24小时未更新告警
    "zscore_threshold": 5, # Z-score超过5视为异常
    "duplicate_rate": 0.05 # 重复率超过5%告警
}


def _load_config() -> Dict:
    """加载质量配置"""
    if os.path.exists(QUALITY_CONFIG_FILE):
        with open(QUALITY_CONFIG_FILE) as f:
            return json.load(f)
    return {}


def _save_config(config: Dict):
    """保存质量配置"""
    os.makedirs(os.path.dirname(QUALITY_CONFIG_FILE), exist_ok=True)
    with open(QUALITY_CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


class DataQualityChecker:
    """数据质量检查器"""
    
    def __init__(self):
        self.config = _load_config()
        self.alerts = []
    
    def check_missing_values(self, data: List[float], field_name: str = "数据") -> Dict:
        """
        检查缺失值
        
        Returns:
            {
                "field": 字段名,
                "total_count": 总数,
                "missing_count": 缺失数,
                "missing_rate": 缺失率,
                "status": "ok" | "warning" | "error"
            }
        """
        total = len(data)
        missing = sum(1 for v in data if v is None or (isinstance(v, float) and np.isnan(v)))
        missing_rate = missing / total if total > 0 else 0
        
        if missing_rate > 0.2:
            status = "error"
        elif missing_rate > ALERT_THRESHOLDS["missing_rate"]:
            status = "warning"
        else:
            status = "ok"
        
        return {
            "field": field_name,
            "total_count": total,
            "missing_count": missing,
            "missing_rate": round(missing_rate, 4),
            "status": status
        }
    
    def check_outliers(self, data: List[float], field_name: str = "数据", 
                      method: str = "zscore") -> Dict:
        """
        检查异常值
        
        Args:
            data: 数据序列
            method: "zscore" | "iqr"
        
        Returns:
            {
                "field": 字段名,
                "outlier_count": 异常数,
                "outlier_rate": 异常率,
                "outliers": 异常值列表,
                "status": "ok" | "warning" | "error"
            }
        """
        data = np.array([v for v in data if v is not None and not np.isnan(v)])
        
        if len(data) == 0:
            return {"field": field_name, "status": "error", "message": "无有效数据"}
        
        if method == "zscore":
            # Z-score方法
            mean = np.mean(data)
            std = np.std(data)
            if std == 0:
                zscores = np.zeros_like(data)
            else:
                zscores = np.abs((data - mean) / std)
            
            outlier_mask = zscores > ALERT_THRESHOLDS["zscore_threshold"]
            outliers = data[outlier_mask].tolist()
            
        else:
            # IQR方法
            q1 = np.percentile(data, 25)
            q3 = np.percentile(data, 75)
            iqr = q3 - q1
            lower = q1 - 1.5 * iqr
            upper = q3 + 1.5 * iqr
            
            outlier_mask = (data < lower) | (data > upper)
            outliers = data[outlier_mask].tolist()
        
        outlier_rate = len(outliers) / len(data)
        
        if outlier_rate > 0.1:
            status = "error"
        elif outlier_rate > 0.05:
            status = "warning"
        else:
            status = "ok"
        
        return {
            "field": field_name,
            "outlier_count": len(outliers),
            "outlier_rate": round(outlier_rate, 4),
            "outliers": outliers[:10],  # 最多返回10个
            "status": status
        }
    
    def check_timeliness(self, last_update: datetime, 
                        data_type: str = "行情数据") -> Dict:
        """
        检查数据时效性
        
        Args:
            last_update: 最后更新时间
            data_type: 数据类型描述
        
        Returns:
            {
                "data_type": 数据类型,
                "last_update": 最后更新时间,
                "hours_stale": 过期小时数,
                "status": "ok" | "warning" | "error"
            }
        """
        now = datetime.now()
        hours_stale = (now - last_update).total_seconds() / 3600
        
        if hours_stale > 72:
            status = "error"
        elif hours_stale > ALERT_THRESHOLDS["stale_hours"]:
            status = "warning"
        else:
            status = "ok"
        
        return {
            "data_type": data_type,
            "last_update": last_update.isoformat(),
            "hours_stale": round(hours_stale, 2),
            "status": status
        }
    
    def check_duplicates(self, data: List, field_name: str = "数据") -> Dict:
        """
        检查重复值
        
        Returns:
            {
                "field": 字段名,
                "total_count": 总数,
                "unique_count": 唯一值数,
                "duplicate_count": 重复数,
                "duplicate_rate": 重复率,
                "status": "ok" | "warning" | "error"
            }
        """
        total = len(data)
        unique = len(set(data))
        duplicate = total - unique
        duplicate_rate = duplicate / total if total > 0 else 0
        
        if duplicate_rate > 0.2:
            status = "error"
        elif duplicate_rate > ALERT_THRESHOLDS["duplicate_rate"]:
            status = "warning"
        else:
            status = "ok"
        
        return {
            "field": field_name,
            "total_count": total,
            "unique_count": unique,
            "duplicate_count": duplicate,
            "duplicate_rate": round(duplicate_rate, 4),
            "status": status
        }
    
    def calculate_quality_score(self, checks: List[Dict]) -> Tuple[int, str]:
        """
        计算综合质量评分
        
        Args:
            checks: 检查结果列表
        
        Returns:
            (score: 0-100, grade: 等级)
        """
        if not checks:
            return 0, "N/A"
        
        scores = []
        for check in checks:
            if check.get("status") == "error":
                scores.append(0)
            elif check.get("status") == "warning":
                scores.append(50)
            else:
                scores.append(100)
        
        avg_score = np.mean(scores)
        
        if avg_score >= 90:
            grade = "A"
        elif avg_score >= 80:
            grade = "B"
        elif avg_score >= 70:
            grade = "C"
        elif avg_score >= 60:
            grade = "D"
        else:
            grade = "F"
        
        return int(avg_score), grade


class DataQualityMonitor:
    """数据质量监控器"""
    
    def __init__(self):
        self.checker = DataQualityChecker()
        self.history = []
    
    def monitor_price_data(self, ticker: str, prices: List[Dict]) -> Dict:
        """
        监控行情数据质量
        
        Args:
            ticker: 股票代码
            prices: 价格数据列表
        
        Returns:
            质量报告
        """
        report = {
            "ticker": ticker,
            "timestamp": datetime.now().isoformat(),
            "record_count": len(prices),
            "checks": [],
            "issues": []
        }
        
        if not prices:
            report["quality_score"] = 0
            report["grade"] = "F"
            report["issues"].append("无数据")
            return report
        
        # 提取各字段
        close_prices = [p.get("close") for p in prices]
        volumes = [p.get("volume", 0) for p in prices]
        dates = [p.get("date") for p in prices]
        
        # 检查缺失值
        close_check = self.checker.check_missing_values(close_prices, "收盘价")
        volume_check = self.checker.check_missing_values(volumes, "成交量")
        report["checks"].append(close_check)
        report["checks"].append(volume_check)
        
        if close_check["status"] != "ok":
            report["issues"].append(f"收盘价{close_check['status']}: 缺失率{close_check['missing_rate']:.1%}")
        
        # 检查异常值
        outlier_check = self.checker.check_outliers(close_prices, "收盘价")
        report["checks"].append(outlier_check)
        
        if outlier_check["status"] != "ok":
            report["issues"].append(f"收盘价异常值: {outlier_check['outlier_count']}个")
        
        # 检查重复
        dup_check = self.checker.check_duplicates(dates, "日期")
        report["checks"].append(dup_check)
        
        if dup_check["status"] != "ok":
            report["issues"].append(f"日期重复: {dup_check['duplicate_count']}条")
        
        # 计算评分
        score, grade = self.checker.calculate_quality_score(report["checks"])
        report["quality_score"] = score
        report["grade"] = grade
        
        return report
    
    def monitor_factor_data(self, factor_name: str, ic_values: List[float]) -> Dict:
        """
        监控因子数据质量
        
        Args:
            factor_name: 因子名称
            ic_values: IC值序列
        
        Returns:
            质量报告
        """
        report = {
            "factor": factor_name,
            "timestamp": datetime.now().isoformat(),
            "checks": [],
            "issues": []
        }
        
        if not ic_values:
            report["quality_score"] = 0
            report["grade"] = "F"
            report["issues"].append("无IC数据")
            return report
        
        # 检查缺失值
        check = self.checker.check_missing_values(ic_values, "IC值")
        report["checks"].append(check)
        
        # 检查稳定性（IC标准差）
        ic_array = np.array([v for v in ic_values if v is not None])
        if len(ic_array) > 1:
            ic_std = np.std(ic_array)
            ic_mean = np.abs(np.mean(ic_array))
            
            # IC标准差过大说明不稳定
            if ic_std > ic_mean * 2:
                report["issues"].append(f"IC波动过大: std={ic_std:.4f}")
                report["checks"].append({
                    "field": "IC稳定性",
                    "status": "warning",
                    "detail": f"std={ic_std:.4f}, mean={ic_mean:.4f}"
                })
            else:
                report["checks"].append({
                    "field": "IC稳定性",
                    "status": "ok",
                    "detail": "正常"
                })
        
        # 计算评分
        score, grade = self.checker.calculate_quality_score(report["checks"])
        report["quality_score"] = score
        report["grade"] = grade
        
        return report
    
    def check_data_source_health(self, source_name: str, 
                                 last_success: datetime,
                                 error_rate: float = 0) -> Dict:
        """
        检查数据源健康状态
        
        Args:
            source_name: 数据源名称
            last_success: 最后成功时间
            error_rate: 错误率 (0-1)
        
        Returns:
            健康报告
        """
        timeliness = self.checker.check_timeliness(last_success, source_name)
        
        health_score = 100
        issues = []
        
        # 时效性
        if timeliness["status"] == "error":
            health_score -= 50
            issues.append("数据过期")
        elif timeliness["status"] == "warning":
            health_score -= 25
            issues.append("数据即将过期")
        
        # 错误率
        if error_rate > 0.1:
            health_score -= 40
            issues.append(f"错误率过高: {error_rate:.1%}")
        elif error_rate > 0.05:
            health_score -= 20
            issues.append(f"偶发错误: {error_rate:.1%}")
        
        health_score = max(0, health_score)
        
        return {
            "source": source_name,
            "last_success": last_success.isoformat(),
            "health_score": health_score,
            "error_rate": error_rate,
            "issues": issues,
            "status": "healthy" if health_score >= 80 else "degraded" if health_score >= 50 else "unhealthy"
        }
    
    def generate_alert(self, level: str, title: str, message: str, details: Dict = None):
        """生成告警"""
        alert = {
            "level": level,  # info / warning / error / critical
            "title": title,
            "message": message,
            "details": details or {},
            "timestamp": datetime.now().isoformat(),
            "id": f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{hash(title) % 10000}"
        }
        
        self.alerts.append(alert)
        
        # 根据级别打印日志
        if level in ["error", "critical"]:
            logger.error(f"🚨 [{level.upper()}] {title}: {message}")
        elif level == "warning":
            logger.warning(f"⚠️ {title}: {message}")
        else:
            logger.info(f"ℹ️ {title}: {message}")
        
        return alert
    
    def get_alerts(self, level: str = None, hours: int = 24) -> List[Dict]:
        """获取告警列表"""
        cutoff = datetime.now() - timedelta(hours=hours)
        
        filtered = []
        for alert in self.alerts:
            alert_time = datetime.fromisoformat(alert["timestamp"])
            if alert_time > cutoff:
                if level is None or alert["level"] == level:
                    filtered.append(alert)
        
        return sorted(filtered, key=lambda x: x["timestamp"], reverse=True)
    
    def save_report(self, report: Dict, report_type: str = "quality"):
        """保存报告"""
        os.makedirs("data/reports", exist_ok=True)
        
        filename = f"data/reports/{report_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(filename, "w") as f:
            json.dump(report, f, indent=2, default=str)
        
        logger.info(f"📄 报告已保存: {filename}")
        return filename


# ===== 全局实例 =====

_monitor = None

def get_monitor() -> DataQualityMonitor:
    """获取全局监控器"""
    global _monitor
    if _monitor is None:
        _monitor = DataQualityMonitor()
    return _monitor


def check_price_quality(ticker: str, prices: List[Dict]) -> Dict:
    """快捷函数：检查行情数据质量"""
    return get_monitor().monitor_price_data(ticker, prices)


def check_factor_quality(factor_name: str, ic_values: List[float]) -> Dict:
    """快捷函数：检查因子数据质量"""
    return get_monitor().monitor_factor_data(factor_name, ic_values)


def get_data_alerts(hours: int = 24) -> List[Dict]:
    """快捷函数：获取数据告警"""
    return get_monitor().get_alerts(hours=hours)


# ===== 测试 =====

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print("\n🧪 数据质量监控测试")
    print("=" * 50)
    
    # 测试行情数据检查
    test_prices = [
        {"date": "2024-01-01", "close": 100, "volume": 1000000},
        {"date": "2024-01-02", "close": 101, "volume": 1200000},
        {"date": "2024-01-03", "close": None, "volume": 1100000},  # 缺失
        {"date": "2024-01-04", "close": 103, "volume": 1000000},
        {"date": "2024-01-05", "close": 500, "volume": 1000000},   # 异常值
    ]
    
    report = check_price_quality("TEST", test_prices)
    print(f"\n📊 TEST行情质量报告")
    print(f"  记录数: {report['record_count']}")
    print(f"  质量分: {report['quality_score']} ({report['grade']})")
    print(f"  问题: {report['issues']}")
    
    # 测试因子数据检查
    test_ic = [0.05, 0.03, 0.04, 0.02, 0.06, 0.04, 0.03]
    factor_report = check_factor_quality("momentum", test_ic)
    print(f"\n📈 momentum因子质量报告")
    print(f"  质量分: {factor_report['quality_score']} ({factor_report['grade']})")
    
    print("\n" + "=" * 50)
