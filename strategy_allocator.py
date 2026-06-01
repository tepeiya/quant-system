"""
多策略组合引擎
- 趋势主策略
- 配对交易
- 轮式策略
按市场状态动态分配资金
"""

from datetime import datetime
import json
import os

STATE_FILE = "config/strategy_allocator.json"

DEFAULT_ALLOC = {
    "bull": {"trend": 0.65, "pairs": 0.20, "wheel": 0.15},
    "choppy": {"trend": 0.40, "pairs": 0.35, "wheel": 0.25},
    "bear": {"trend": 0.15, "pairs": 0.50, "wheel": 0.35},
}


def load_alloc():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except:
            pass
    return DEFAULT_ALLOC


def save_alloc(cfg):
    os.makedirs("config", exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


def detect_market_state(signal_market: dict) -> str:
    trend = signal_market.get("trend", "")
    action = signal_market.get("action", "")
    if "熊市" in trend or "空仓" in action:
        return "bear"
    if "震荡" in trend or "半仓" in action:
        return "choppy"
    return "bull"


def get_allocation(signal_market: dict) -> dict:
    cfg = load_alloc()
    st = detect_market_state(signal_market)
    alloc = cfg.get(st, DEFAULT_ALLOC["choppy"])
    return {"state": st, **alloc}


def allocation_report(signal_market: dict, equity: float) -> dict:
    a = get_allocation(signal_market)
    trend_cap = round(equity * a["trend"], 2)
    pairs_cap = round(equity * a["pairs"], 2)
    wheel_cap = round(equity * a["wheel"], 2)
    return {
        "state": a["state"],
        "weights": {"trend": a["trend"], "pairs": a["pairs"], "wheel": a["wheel"]},
        "capital": {"trend": trend_cap, "pairs": pairs_cap, "wheel": wheel_cap},
        "timestamp": str(datetime.now()),
    }


if __name__ == "__main__":
    m = {"trend": "🟢 多头", "action": "正常买入"}
    print(json.dumps(allocation_report(m, 100000), indent=2, ensure_ascii=False))
