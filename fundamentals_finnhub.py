import os
import requests
import logging

logger = logging.getLogger('quant.fundamentals')


def _finnhub_get(symbol: str):
    key = os.environ.get('FINNHUB_API_KEY', '')
    if not key:
        return None
    try:
        # 基本面概览
        m_url = 'https://finnhub.io/api/v1/stock/metric'
        m = requests.get(m_url, params={
            'symbol': symbol,
            'metric': 'all',
            'token': key,
        }, timeout=12)
        if m.status_code != 200:
            return None
        mj = m.json() or {}
        metric = mj.get('metric', {}) if isinstance(mj, dict) else {}

        # 财报日历（最近）
        e_url = 'https://finnhub.io/api/v1/stock/earnings'
        e = requests.get(e_url, params={
            'symbol': symbol,
            'limit': 1,
            'token': key,
        }, timeout=12)
        earnings = None
        if e.status_code == 200:
            ej = e.json()
            if isinstance(ej, list) and ej:
                earnings = ej[0].get('period')

        return {
            'pe': metric.get('peBasicExclExtraTTM') or metric.get('peTTM') or metric.get('peAnnual'),
            'pb': metric.get('pbAnnual'),
            'roe': metric.get('roeTTM') or metric.get('roeRfy'),
            'profit_margin': metric.get('netMarginTTM') or metric.get('netMarginAnnual'),
            'debt_to_equity': metric.get('totalDebt/totalEquityAnnual') or metric.get('totalDebt/totalEquityQuarterly'),
            'market_cap': metric.get('marketCapitalization'),
            'dividend_yield': metric.get('dividendYieldIndicatedAnnual') or metric.get('dividendYieldAnnual'),
            'earnings_date': earnings,
            'source': 'finnhub',
        }
    except Exception as ex:
        logger.warning(f'Finnhub {symbol} 失败: {str(ex)[:80]}')
        return None
