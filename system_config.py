"""
系统参数管理
===========
所有可配置参数集中在此文件。
Web面板读写 → 各模块启动时读取。

文件：config/system_config.json
"""

import os
import json
import logging
from datetime import datetime

logger = logging.getLogger("quant.config")

CONFIG_FILE = "config/system_config.json"


DEFAULT_CONFIG = {
    # ===== 策略参数 =====
    "stop_loss_pct": 15,
    "stop_loss_atr_multiple": 3.0,    # ATR动态止损：入场价 - N倍ATR
    "stop_loss_min_pct": 5,           # 动态止损最低值（极端情况保护）
    "stop_loss_max_pct": 25,          # 动态止损最高值
    "trailing_stop_activate_pct": 15,  # 盈利超过此值后激活跟踪止损
    "trailing_stop_atr_multiple": 2.0, # 跟踪止损：最高价 - N倍ATR
    "trailing_stop_min_pct": 8,       # 跟踪止损最小值
    "rsi_exit": 88,
    "rsi_entry": 80,         # 买入RSI上限
    "market_overheat_rsi": 80,
    "market_extreme_rsi": 85,
    "market_reduce_ratio": 0.25,
    "max_positions": 8,
    "score_threshold": 50,
    "mom_rank_top_pct": 0.7, # 动量排名前30%才进入候选

    # ===== 仓位控制 =====
    "max_position_pct": 0.12,
    "max_sector_pct": 0.35,
    "semi_single_limit": 0.08,
    "semi_total_limit": 0.25,
    "atr_low_threshold": 2.5,    # ATR<2.5% → 仓位上限15%
    "atr_medium_threshold": 4.0, # ATR<4.0% → 仓位上限12%
    "atr_high_threshold": 6.0,   # ATR<6.0% → 仓位上限8%
    "atr_cap_low": 0.15,
    "atr_cap_medium": 0.12,
    "atr_cap_high": 0.08,
    "atr_cap_extreme": 0.06,
    "buy_cash_ratio": 0.95,      # 买入占用现金比例
    "max_share_price": 300,      # 单股价格上限（超过则走候补池）

    # ===== 因子权重 =====
    "momentum_weight": 45,
    "quality_weight": 26,
    "trend_weight": 13,
    "volume_weight": 5,

    # ===== 宏观 =====
    "bond_weight": 0.3,
    "dollar_weight": 0.2,
    "gold_weight": 0.2,
    "inflation_weight": 0.3,

    # ===== 通知 =====
    "notify_on_trade": True,
    "notify_on_alert": True,
    "daily_report": True,
    "push_to_phone": True,

    # ===== 风控告警 =====
    "alert_total_drawdown": 10,
    "alert_single_loss": 15,

    # ===== 交易执行 =====
    "min_hold_days": 5,
    "churn_keep_score": 40,
    "split_buy_first": 0.6,
    "split_buy_drop": 2.0,
    "split_sell_first": 0.5,
    "split_sell_rise": 3.0,
    "split_min_wait": 120,

    # ===== 熔断保护 =====
    "circuit_daily_loss": 10.0,
    "circuit_consecutive_loss": 5.0,
    "circuit_max_drawdown": 25.0,
    "circuit_cooldown_hours": 24,

    # ===== 对冲参数 =====
    "hedge_spy_ma200": True,
    "hedge_vix_trigger": 30,
    "hedge_ratio_base": 0.5,
    "hedge_ratio_max": 0.75,
    "hedge_signal_timeout": 3,

    # ===== 对外 =====
    "timezone": "Asia/Shanghai",
    "language": "zh",
}


def load() -> dict:
    """加载配置"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE) as f:
                cfg = json.load(f)
            for k, v in DEFAULT_CONFIG.items():
                cfg.setdefault(k, v)
            return cfg
        except:
            pass
    return dict(DEFAULT_CONFIG)


def save(cfg: dict):
    """保存配置"""
    os.makedirs("config", exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)
    logger.info(f"配置已保存: {len(cfg)}项")


def get(key: str, default=None):
    """读取单个配置项"""
    return load().get(key, default)


def update(key: str, value):
    """更新单个配置项"""
    cfg = load()
    cfg[key] = value
    save(cfg)


def reset():
    """恢复出厂设置"""
    save(dict(DEFAULT_CONFIG))
    logger.info("配置已重置为默认值")


if __name__ == "__main__":
    cfg = load()
    for k, v in cfg.items():
        print(f"  {k:30s} = {v}")
