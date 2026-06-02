"""
多策略执行器
根据 strategy_allocator 的资金分配结果，协调：
- 趋势主策略（paper_trader）
- 配对交易（pairs_executor）
- 轮式策略（wheel_strategy，当前仅生成计划）
"""

import json
import logging
from datetime import datetime

logger = logging.getLogger('quant.multi')


def load_latest_signal_market():
    import glob, os
    market = {"trend": "⚪", "action": "部分仓位"}
    files = sorted(glob.glob('signals/signal_*.json'))
    if files:
        with open(files[-1]) as f:
            sig = json.load(f)
        market = sig.get('market', market)
    return market


def get_portfolio_snapshot():
    from portfolio_tracker import load_portfolio, sync_from_alpaca
    p = load_portfolio() or {}
    if not p or not p.get('equity'):
        p = sync_from_alpaca() or {}
    return p or {}


def run_all(auto=False):
    from strategy_allocator import allocation_report

    market = load_latest_signal_market()
    p = get_portfolio_snapshot()
    equity = float(p.get('equity', 0) or 0)
    cash = float(p.get('cash', 0) or 0)
    rep = allocation_report(market, equity, cash)

    result = {
        'time': str(datetime.now()),
        'market': market,
        'allocation': rep,
        'steps': []
    }

    # 1) 趋势主策略（总是可运行）
    try:
        result['steps'].append({'name': 'trend', 'capital': rep['capital'].get('trend', 0), 'status': 'planned'})
        if auto:
            from paper_trader import rebalance
            rebalance(auto=True)
            result['steps'][-1]['status'] = 'executed'
    except Exception as e:
        result['steps'].append({'name': 'trend', 'status': 'error', 'error': str(e)})

    # 2) 配对交易（仅在分配资金>0时）
    try:
        pairs_cap = rep['capital'].get('pairs', 0)
        st = {'name': 'pairs', 'capital': pairs_cap, 'status': 'planned'}
        if auto and pairs_cap > 0:
            from data_prod import load_price_cache
            from pairs_executor import execute_pairs_auto
            execute_pairs_auto(load_price_cache())
            st['status'] = 'executed'
        result['steps'].append(st)
    except Exception as e:
        result['steps'].append({'name': 'pairs', 'status': 'error', 'error': str(e)})

    # 3) 轮式策略（当前生成计划，不自动下期权单）
    try:
        wheel_cap = rep['capital'].get('wheel', 0)
        from wheel_strategy import generate_wheel_plan
        plan = generate_wheel_plan()
        result['steps'].append({
            'name': 'wheel',
            'capital': wheel_cap,
            'status': 'planned',
            'positions': len(plan.get('positions', [])) if isinstance(plan, dict) else 0
        })
    except Exception as e:
        result['steps'].append({'name': 'wheel', 'status': 'error', 'error': str(e)})

    return result


if __name__ == '__main__':
    print(json.dumps(run_all(auto=False), ensure_ascii=False, indent=2))
