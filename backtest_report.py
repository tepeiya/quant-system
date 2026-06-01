import json
from datetime import datetime
from data_prod import load_price_cache, compute_indicators
from spy_source import get_spy
from quality_factor import compute_quality_scores
from strategy_vector import VectorStrategy

cache = load_price_cache()
if len(cache) < 30:
    print('缓存不足，请先补全数据')
    raise SystemExit

spy = compute_indicators(get_spy())
if getattr(spy.index, 'tz', None) is not None:
    spy.index = spy.index.tz_localize(None)

quality = compute_quality_scores(cache)
tickers = sorted(cache.keys())[:200]
prices = {t: cache[t] for t in tickers}

st = VectorStrategy(tickers, quality_scores=quality)
res = st.run(prices, spy, start='2025-01-01', end='2026-05-31')

spy_seg = spy.loc['2025-01-01':'2026-05-31']
spy_ret = 0
if len(spy_seg) > 2:
    spy_ret = (spy_seg['Close'].iloc[-1]/spy_seg['Close'].iloc[0]-1)*100

out = {
  'time': str(datetime.now()),
  'stock_count': len(tickers),
  'strategy': {
    'total_return_pct': round(res.get('total_return_pct',0),2),
    'annual_return_pct': round(res.get('annual_return_pct',0),2),
    'max_drawdown_pct': round(res.get('max_drawdown_pct',0),2),
    'sharpe_ratio': round(res.get('sharpe_ratio',0),2),
  },
  'benchmark': {'spy_return_pct': round(spy_ret,2)},
  'alpha': round(res.get('total_return_pct',0)-spy_ret,2)
}

print('\n=== 回测报告 ===')
print(json.dumps(out, ensure_ascii=False, indent=2))

with open('signals/backtest_report.json','w') as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print('已保存 signals/backtest_report.json')
