"""
多策略组合引擎（稳健增强版）
- 趋势主策略
- 配对交易
- 轮式策略
- 现金停泊（SGOV/BIL）
- 防守轮动（XLU/XLP/IEF/TLT）
按市场状态动态分配资金
"""

from datetime import datetime
import json
import os

STATE_FILE = "config/strategy_allocator.json"

DEFAULT_CFG = {
    "enabled": True,
    "defensive_rotation_enabled": True,
    "cash_park_enabled": True,

    # 市场状态下的策略权重（总和=1）
    "bull":   {"trend": 0.70, "pairs": 0.20, "wheel": 0.10},
    "choppy": {"trend": 0.40, "pairs": 0.35, "wheel": 0.25},
    "bear":   {"trend": 0.20, "pairs": 0.45, "wheel": 0.35},

    # 现金停泊
    "cash_park_symbol": "SGOV",
    "cash_park_min_usd": 300,
    "cash_park_max_pct": 0.35,

    # 防守轮动
    "defense_universe": ["XLU", "XLP", "IEF", "TLT"],
    "defense_max_pct": 0.30,

    # 配对风险上限
    "pairs_single_max_pct": 0.08,
    "pairs_total_max_pct": 0.25,
}


def load_cfg():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                cfg = json.load(f)
            # 缺省补齐
            for k, v in DEFAULT_CFG.items():
                cfg.setdefault(k, v)
            return cfg
        except:
            pass
    return dict(DEFAULT_CFG)


def save_cfg(cfg):
    os.makedirs("config", exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def detect_market_state(signal_market: dict) -> str:
    trend = signal_market.get("trend", "")
    action = signal_market.get("action", "")
    if "熊市" in trend or "空仓" in action:
        return "bear"
    if "震荡" in trend or "半仓" in action:
        return "choppy"
    return "bull"


def get_allocation(signal_market: dict) -> dict:
    cfg = load_cfg()
    st = detect_market_state(signal_market)
    alloc = cfg.get(st, cfg["choppy"])
    return {"state": st, **alloc}


def allocation_report(signal_market: dict, equity: float, cash: float = 0) -> dict:
    cfg = load_cfg()
    a = get_allocation(signal_market)

    trend_cap = round(equity * a["trend"], 2)
    pairs_cap = round(equity * a["pairs"], 2)
    wheel_cap = round(equity * a["wheel"], 2)

    # 现金停泊建议
    cash_park = 0
    if cfg.get("cash_park_enabled", True) and cash >= cfg.get("cash_park_min_usd", 300):
        cash_park = round(min(cash * cfg.get("cash_park_max_pct", 0.35), cash), 2)

    # 防守轮动建议（仅震荡/熊市）
    defense_cap = 0
    if cfg.get("defensive_rotation_enabled", True) and a["state"] in ("choppy", "bear"):
        defense_cap = round(equity * cfg.get("defense_max_pct", 0.30), 2)

    return {
        "state": a["state"],
        "weights": {"trend": a["trend"], "pairs": a["pairs"], "wheel": a["wheel"]},
        "capital": {
            "trend": trend_cap,
            "pairs": min(pairs_cap, round(equity * cfg.get("pairs_total_max_pct", 0.25), 2)),
            "wheel": wheel_cap,
            "cash_park": cash_park,
            "defense": defense_cap,
        },
        "limits": {
            "pairs_single_max_pct": cfg.get("pairs_single_max_pct", 0.08),
            "pairs_total_max_pct": cfg.get("pairs_total_max_pct", 0.25),
        },
        "timestamp": str(datetime.now()),
    }


if __name__ == "__main__":
    m = {"trend": "🟢 多头", "action": "正常买入"}
    print(json.dumps(allocation_report(m, 100000, 25000), indent=2, ensure_ascii=False))
