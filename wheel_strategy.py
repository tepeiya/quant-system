"""
Wheel Strategy 轮式期权策略模块
=============================
功能：
1. Cash-Secured Put — 低价建仓，先收权利金
2. Covered Call — 持仓收租，被行权止盈
3. 完整轮子：卖Put→接货→卖Call→被行权→再卖Put
4. Web面板：展示当前期权状态、预期收益

数据源：Alpaca 纸交易 + yfinance 期权链
"""

import os
import json
import logging
from datetime import datetime, timedelta

logger = logging.getLogger("quant.wheel")

CONFIG_FILE = "config/wheel_config.json"
POSITIONS_FILE = "signals/wheel_positions.json"

DEFAULT_CONFIG = {
    "enabled": False,                     # 是否启用轮式
    "put_delta_target": 0.25,             # 卖Put目标Delta
    "put_dte": 35,                        # 卖Put到期天数
    "put_credit_pct": 0.02,              # 卖Put权利金目标 2%
    "call_delta_target": 0.25,           # 卖Call目标Delta
    "call_dte": 35,                       # 卖Call到期天数
    "call_credit_pct": 0.02,            # 卖Call权利金目标 2%
    "max_positions": 5,                  # 最多同时持几只期权
    "single_exposure_pct": 0.20,        # 单只占用资金 ≤20%
    "only_high_quality": True,          # 只对评分>80分的票做
    "auto_roll": True,                  # 到期自动展期
}

# ===== 配置管理 =====

def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            cfg = json.load(f)
            for k, v in DEFAULT_CONFIG.items():
                cfg.setdefault(k, v)
            return cfg
    return dict(DEFAULT_CONFIG)

def save_config(cfg: dict):
    os.makedirs("config", exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)

# ===== 持仓管理 =====

def load_positions() -> list:
    if os.path.exists(POSITIONS_FILE):
        with open(POSITIONS_FILE) as f:
            return json.load(f)
    return []

def save_positions(positions: list):
    os.makedirs("signals", exist_ok=True)
    with open(POSITIONS_FILE, "w") as f:
        json.dump(positions[-50:], f, indent=2)

# ===== 核心逻辑 =====

def get_option_chain(symbol: str) -> dict:
    """获取期权链数据（通过yfinance）"""
    import yfinance as yf
    import pandas as pd

    try:
        import multiprocessing as _mp
        result_holder = {}
        def _fetch():
            import yfinance as yf
            result_holder['ticker'] = yf.Ticker(symbol)
        t = _mp.Process(target=_fetch)
        t.start()
        t.join(timeout=8)
        if 'ticker' not in result_holder:
            t.terminate()
            return {"error": "超时"}
        ticker = result_holder['ticker']
        expirations = ticker.options
        if not expirations:
            return {"error": "无期权数据"}
        
        # 找最近>30天的到期日
        target_dte = load_config().get("put_dte", 35)
        now = datetime.now()
        best_expiry = None
        
        for exp in expirations:
            exp_date = datetime.strptime(exp, "%Y-%m-%d")
            dte = (exp_date - now).days
            if dte >= target_dte - 7 and dte <= target_dte + 7:
                best_expiry = exp
                break
        
        if not best_expiry:
            best_expiry = expirations[0] if expirations else None
        
        if not best_expiry:
            return {"error": "无可用的到期日"}
        
        # 获取看跌和看涨
        puts = ticker.option_chain(best_expiry).puts
        calls = ticker.option_chain(best_expiry).calls
        
        current_price = None
        if len(puts) > 0 and "underlyingPrice" in puts.columns:
            current_price = float(puts["underlyingPrice"].iloc[0])
        
        return {
            "symbol": symbol,
            "expiry": best_expiry,
            "current_price": current_price,
            "puts": puts.to_dict("records") if puts is not None else [],
            "calls": calls.to_dict("records") if calls is not None else [],
        }
    except Exception as e:
        logger.error(f"期权链获取失败 {symbol}: {e}")
        return {"error": str(e)}


def find_best_put(chain: dict) -> dict:
    """
    寻找最佳卖Put：
    - 虚值（行权价 < 现价）
    - Delta ≈ 0.25
    - 权利金/保证金 > 2%/月
    """
    puts = chain.get("puts", [])
    current_price = chain.get("current_price", 0)
    if not puts or not current_price:
        return {"error": "无可用数据"}

    cfg = load_config()
    target_delta = cfg.get("put_delta_target", 0.25)
    target_credit = cfg.get("put_credit_pct", 0.02)
    dte = cfg.get("put_dte", 35)

    candidates = []
    for p in puts:
        strike = float(p.get("strike", 0))
        delta = float(p.get("delta", 0))
        bid = float(p.get("bid", 0))
        ask = float(p.get("ask", 0))
        mid = (bid + ask) / 2 if bid > 0 and ask > 0 else bid
        
        if strike >= current_price:
            continue  # 只考虑虚值Put
        if delta == 0 or abs(delta) > 0.4:
            continue
        if mid <= 0:
            continue
        
        # 权利金占保证金比例（年化）
        collateral = strike * 100  # 每张合约的保证金
        monthly_return = mid * 100 / collateral if collateral > 0 else 0
        
        candidates.append({
            "strike": round(strike, 2),
            "delta": round(float(delta), 3),
            "bid": round(bid, 2),
            "ask": round(ask, 2),
            "mid": round(mid, 2),
            "premium_received": round(mid * 100, 2),
            "collateral_required": round(collateral, 2),
            "monthly_return_pct": round(monthly_return * 100, 2),
            "distance_pct": round((1 - strike / current_price) * 100, 1),
        })
    
    if not candidates:
        return {"error": "无符合条件的Put"}
    
    # 按Delta最接近目标排序
    candidates.sort(key=lambda x: abs(abs(x["delta"]) - target_delta))
    
    return {
        "symbol": chain.get("symbol"),
        "expiry": chain.get("expiry"),
        "current_price": current_price,
        "best": candidates[0],
        "candidates": candidates[:5],
    }


def find_best_call(chain: dict, cost_basis: float = None) -> dict:
    """
    寻找最佳卖Covered Call：
    - 虚值（行权价 > 现价）
    - Delta ≈ 0.25
    - 权利金/股价 > 2%/月
    """
    calls = chain.get("calls", [])
    current_price = chain.get("current_price", 0)
    if not calls or not current_price:
        return {"error": "无可用数据"}

    cfg = load_config()
    target_delta = cfg.get("call_delta_target", 0.25)
    target_credit = cfg.get("call_credit_pct", 0.02)
    dte = cfg.get("call_dte", 35)

    candidates = []
    for c in calls:
        strike = float(c.get("strike", 0))
        delta = float(c.get("delta", 0))
        bid = float(c.get("bid", 0))
        ask = float(c.get("ask", 0))
        mid = (bid + ask) / 2 if bid > 0 and ask > 0 else bid
        
        if strike <= current_price:
            continue  # 只考虑虚值Call
        if delta == 0 or delta > 0.4:
            continue
        if mid <= 0:
            continue
        
        monthly_return = mid / current_price if current_price > 0 else 0
        
        # 如果被行权，总收益
        total_profit = None
        if cost_basis:
            total_profit = ((strike - cost_basis) / cost_basis + monthly_return) * 100
        
        candidates.append({
            "strike": round(strike, 2),
            "delta": round(float(delta), 3),
            "bid": round(bid, 2),
            "ask": round(ask, 2),
            "mid": round(mid, 2),
            "premium_received": round(mid * 100, 2),
            "monthly_return_pct": round(monthly_return * 100, 2),
            "upside_pct": round((strike / current_price - 1) * 100, 1),
            "total_profit_if_assigned_pct": round(total_profit, 2) if total_profit else None,
        })
    
    if not candidates:
        return {"error": "无符合条件的Call"}
    
    candidates.sort(key=lambda x: abs(x["delta"] - target_delta))
    
    return {
        "symbol": chain.get("symbol"),
        "expiry": chain.get("expiry"),
        "current_price": current_price,
        "best": candidates[0],
        "candidates": candidates[:5],
    }


def analyze_wheel_candidates() -> list:
    """
    从今日信号中选出适合做轮式的股票。
    条件：
    1. 评分 > 80
    2. 有期权链数据
    3. 波动率适中（有权利金收）
    """
    from daily_signal import load_factor_weights
    
    # 读取今日信号
    signal_file = None
    import glob
    files = sorted(glob.glob("signals/signal_*.json"))
    if not files:
        return []
    
    with open(files[-1]) as f:
        import json
        signal = json.load(f)
    
    candidates = signal.get("buy_candidates", [])
    cfg = load_config()
    score_threshold = 80 if cfg.get("only_high_quality") else 60
    
    results = []
    for c in candidates:
        if c.get("score", 0) < score_threshold:
            continue
        
        # 用简化模型估算期权价格（不依赖实时期权链）
        price = c.get("price", 0)
        if price <= 0:
            continue
        
        put_strike = round(price * 0.90, 2)  # 虚值10%
        put_premium_per_share = round(price * 0.025, 2)  # 估算权利金2.5%
        collateral = put_strike * 100
        monthly_return = put_premium_per_share * 100 / collateral * 100 if collateral > 0 else 0
        
        call_strike = round(price * 1.10, 2)  # 虚值10%  
        call_premium_per_share = round(price * 0.02, 2)  # 估算权利金2%
        
        results.append({
            "ticker": c["ticker"],
            "score": c["score"],
            "price": price,
            "put": {
                "strike": put_strike,
                "premium_received": round(put_premium_per_share * 100, 2),
                "collateral_required": collateral,
                "monthly_return_pct": round(monthly_return, 2),
                "break_even": round(put_strike - put_premium_per_share, 2),
                "premium": round(put_premium_per_share * 100, 2),
            },
            "call": {
                "strike": call_strike,
                "premium_received": round(call_premium_per_share * 100, 2),
                "monthly_return_pct": round(call_premium_per_share / max(price, 1) * 100, 2),
            },
        })
        
        if len(results) >= 5:
            break
    
    return results


def generate_wheel_plan() -> dict:
    """
    生成完整的轮式策略计划
    """
    candidates = analyze_wheel_candidates()
    
    if not candidates:
        return {"error": "无可用的轮式候选"}
    
    plan = []
    total_collateral = 0
    
    for c in candidates:
        if not c.get("put"):
            continue
        
        put = c["put"]
        collateral = put.get("collateral_required", 0)
        total_collateral += collateral
        
        plan.append({
            "ticker": c["ticker"],
            "score": c["score"],
            "action": "SELL_PUT",
            "strike": put["strike"],
            "premium": put["premium_received"],
            "collateral": collateral,
            "monthly_return": put["monthly_return_pct"],
            "break_even": round(put["strike"] - put["premium_received"] / 100, 2),
            "status": "pending",
        })
    
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "market_trend": candidates[0].get("score", 0),
        "total_collateral": round(total_collateral, 2),
        "estimated_monthly_income": round(sum(p["premium"] for p in plan), 2),
        "estimated_annual_yield": round(sum(p["premium"] for p in plan) / total_collateral * 1200, 1) if total_collateral > 0 else 0,
        "positions": plan[:5],
    }


def execute_wheel_plan(plan: dict, auto: bool = False):
    """执行轮式计划（通过Alpaca下单）"""
    if "error" in plan:
        return plan
    
    positions = load_positions()
    cfg = load_config()
    
    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import MarketOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce
    
    KEY = os.environ.get("ALPACA_API_KEY_ID", "")
    SECRET = os.environ.get("ALPACA_SECRET_KEY", "")
    if not KEY or not SECRET:
        return {"error": "Alpaca Key未设置"}
    
    client = TradingClient(KEY, SECRET, paper=True)
    
    results = []
    for pos in plan.get("positions", []):
        if not auto:
            results.append({**pos, "status": "preview"})
            continue
        
        try:
            # Alpaca暂不支持期权交易，记录为计划
            entry = {
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "ticker": pos["ticker"],
                "action": pos["action"],
                "strike": pos["strike"],
                "premium": pos["premium"],
                "status": "pending_manual",
                "note": "期权需在券商端手动执行（Alpaca暂不支持期权）",
            }
            positions.append(entry)
            save_positions(positions)
            
            results.append({**pos, "status": "pending_manual"})
            logger.info(f"[轮式] 计划: {pos['ticker']} {pos['action']} @${pos['strike']}")
        except Exception as e:
            results.append({**pos, "status": "error", "error": str(e)})
    
    return {
        "executed": auto,
        "results": results,
        "note": "Alpaca纸交易暂不支持期权，请到券商端手动执行。计划已记录。"
    }


# ===== Web API 兼容 =====

def get_status() -> dict:
    """获取当前轮式策略状态"""
    cfg = load_config()
    positions = load_positions()
    
    active = [p for p in positions if p.get("status") in ("active", "pending_manual")]
    
    return {
        "enabled": cfg.get("enabled", False),
        "active_positions": len(active),
        "total_positions": len(positions),
        "config": {k: v for k, v in cfg.items() if k != "enabled"},
        "recent": positions[-5:] if positions else [],
    }


if __name__ == "__main__":
    import sys
    if "--plan" in sys.argv:
        plan = generate_wheel_plan()
        import json as _json
        print(_json.dumps(plan, indent=2, ensure_ascii=False, default=str))
    elif "--execute" in sys.argv:
        plan = generate_wheel_plan()
        result = execute_wheel_plan(plan, auto="--auto" in sys.argv)
        import json as _json
        print(_json.dumps(result, indent=2, ensure_ascii=False, default=str))
    else:
        print("\n轮式策略")
        print("  python3 wheel_strategy.py --plan        查看轮式计划")
        print("  python3 wheel_strategy.py --execute     执行（预览）")
        print("  python3 wheel_strategy.py --execute --auto  执行（下单）")
        print()
        
        plan = generate_wheel_plan()
        if "error" in plan:
            print("⚠️ %s" % plan["error"])
        else:
            print("📋 轮式计划:")
            print("  总保证金: $%.0f" % plan["total_collateral"])
            print("  月收入:   $%.0f" % plan["estimated_monthly_income"])
            print("  年化:     %.1f%%" % plan["estimated_annual_yield"])
            print()
            for p in plan["positions"][:5]:
                print("  %s 评分%.0f: 卖Put @$%.0f 收$%.0f (月%.1f%%)" % (
                    p["ticker"], p["score"], p["strike"], p["premium"], p["monthly_return"]))
