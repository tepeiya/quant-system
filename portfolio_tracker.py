"""
持仓记录管理器
============
功能：
1. 每次调仓后自动保存持仓记录到 signals/portfolio.json
2. 每次跑信号前读取当前持仓，计算PnL
3. 与Alpaca实际持仓同步
"""

import os
import json
import logging
from datetime import datetime

logger = logging.getLogger("quant.portfolio")

PORTFOLIO_FILE = "signals/portfolio.json"
TRADE_LOG_FILE = "signals/trade_log.json"


def load_portfolio() -> dict:
    """读取本地持仓记录"""
    if os.path.exists(PORTFOLIO_FILE):
        with open(PORTFOLIO_FILE) as f:
            return json.load(f)
    return {"cash": 0, "positions": {}, "last_update": None}


def save_portfolio(data: dict):
    """保存持仓记录"""
    os.makedirs("signals", exist_ok=True)
    with open(PORTFOLIO_FILE, "w") as f:
        json.dump(data, f, indent=2)
    logger.info(f"持仓已保存: {len(data.get('positions', {}))}只")


def sync_from_alpaca(username: str = None):
    """从Alpaca拉取实际持仓，同步到本地（缓存优先 + 网络备选）
    支持按用户隔离"""
    # 尝试从缓存读取
    cached = load_portfolio()
    if cached and cached.get("equity", 0) > 0:
        return cached

    import requests, os
    
    # iSH SSL workaround
    if os.environ.get("SSL_CERT_FILE"):
        pass  # already configured, see below
    
    # 优先使用用户的Key
    if username:
        try:
            from web.blueprints.auth import get_user_broker_keys
            k = get_user_broker_keys(username)
            KEY = k.get("ALPACA_API_KEY_ID", os.environ.get("ALPACA_API_KEY_ID", ""))
            SECRET = k.get("ALPACA_SECRET_KEY", os.environ.get("ALPACA_SECRET_KEY", ""))
        except:
            KEY = os.environ.get("ALPACA_API_KEY_ID", "")
            SECRET = os.environ.get("ALPACA_SECRET_KEY", "")
    else:
        KEY = os.environ.get("ALPACA_API_KEY_ID", "")
        SECRET = os.environ.get("ALPACA_SECRET_KEY", "")
    if not KEY or not SECRET:
        logger.warning("Alpaca Key未设置")
        return None
    
    base = "https://paper-api.alpaca.markets"
    auth = (KEY, SECRET)
    
    # 账户
    r = requests.get(f"{base}/v2/account", auth=auth, timeout=10)
    if r.status_code != 200:
        logger.error(f"Alpaca账户查询失败: {r.status_code}")
        return None
    acct = r.json()
    
    # 持仓
    r2 = requests.get(f"{base}/v2/positions", auth=auth, timeout=10)
    if r2.status_code != 200:
        logger.error(f"持仓查询失败: {r2.status_code}")
        return None
    alpaca_positions = r2.json()
    
    # 构建本地格式
    positions = {}
    for p in alpaca_positions:
        sym = p["symbol"]
        qty = int(p["qty"])
        avg_entry = float(p.get("avg_entry_price", 0))
        current = float(p.get("current_price", 0))
        cost = float(p.get("cost_basis", 0))
        market_value = float(p.get("market_value", 0))
        
        positions[sym] = {
            "qty": qty,
            "avg_entry_price": round(avg_entry, 2),
            "current_price": round(current, 2),
            "cost_basis": round(cost, 2),
            "market_value": round(market_value, 2),
            "pnl_pct": round(((current - avg_entry) / avg_entry * 100) if avg_entry > 0 else 0, 2),
            "pnl_amount": round(market_value - cost, 2),
        }
    
    portfolio = {
        "cash": round(float(acct["cash"]), 2),
        "equity": round(float(acct["equity"]), 2),
        "positions": positions,
        "position_count": len(positions),
        "last_update": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    
    save_portfolio(portfolio)
    # 额外缓存供dashboard低延迟使用
    cpf = "signals/cached_portfolio.json"
    with open(cpf, "w") as f:
        json.dump(portfolio, f, indent=2)
    return portfolio


def record_trade(symbol: str, side: str, qty: int, price: float, order_id: str = ""):
    """记录一笔交易到交易日志"""
    entry = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "symbol": symbol,
        "side": side,
        "qty": qty,
        "price": round(price, 2),
        "value": round(qty * price, 2),
        "order_id": order_id,
    }
    
    existing = []
    if os.path.exists(TRADE_LOG_FILE):
        with open(TRADE_LOG_FILE) as f:
            existing = json.load(f)
    
    existing.append(entry)
    # 只保留最近200条
    with open(TRADE_LOG_FILE, "w") as f:
        json.dump(existing[-200:], f, indent=2)
    
    return entry


def get_daily_pnl() -> dict:
    """计算今日PnL"""
    portfolio = sync_from_alpaca()
    if not portfolio:
        return {"error": "无法获取持仓"}
    
    positions = portfolio.get("positions", {})
    total_pnl = sum(p.get("pnl_amount", 0) for p in positions.values())
    total_cost = sum(p.get("cost_basis", 0) for p in positions.values())
    
    return {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "equity": portfolio.get("equity", 0),
        "cash": portfolio.get("cash", 0),
        "position_count": len(positions),
        "total_pnl": round(total_pnl, 2),
        "total_pnl_pct": round((total_pnl / total_cost * 100) if total_cost > 0 else 0, 2),
        "positions": positions,
    }


def print_portfolio():
    """打印持仓报告"""
    portfolio = sync_from_alpaca()
    if not portfolio:
        print("\n❌ 无法获取持仓数据")
        return
    
    positions = portfolio.get("positions", {})
    equity = portfolio.get("equity", 0)
    cash = portfolio.get("cash", 0)
    
    print(f"\n{'='*55}")
    print(f"  📋 持仓报告")
    print(f"  {portfolio['last_update']}")
    print(f"{'='*55}")
    print(f"总权益: ${equity:>10,.2f}")
    print(f"现金:   ${cash:>10,.2f}")
    print(f"仓位:   {len(positions)}只")
    
    if positions:
        print(f"\n  {'股票':>6} {'数量':>5} {'成本价':>8} {'现价':>8} {'市值':>10} {'PnL':>10}")
        print(f"  {'-'*55}")
        total_pnl = 0
        for sym, p in sorted(positions.items()):
            pnl = p.get("pnl_amount", 0)
            total_pnl += pnl
            pnl_str = f"${pnl:>+7.2f}" if abs(pnl) > 1 else f"${pnl:>+7.2f}"
            print(f"  {sym:>6} {p['qty']:>5} ${p['avg_entry_price']:>7.2f} "
                  f"${p['current_price']:>7.2f} ${p['market_value']:>9,.2f} {pnl_str}")
        print(f"  {'-'*55}")
        total_pnl_pct = portfolio.get("total_pnl_pct", 0) if "total_pnl_pct" in portfolio else 0
        print(f"  总PnL: ${total_pnl:>+9,.2f} ({total_pnl_pct:+.2f}%)")


if __name__ == "__main__":
    import sys
    if "--sync" in sys.argv:
        sync_from_alpaca()
    elif "--pnl" in sys.argv:
        pnl = get_daily_pnl()
        print(json.dumps(pnl, indent=2))
    else:
        print_portfolio()
