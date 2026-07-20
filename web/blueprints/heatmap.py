"""
股票热图 - Blueprint (缓存+后台渐进式加载)
"""
from flask import Blueprint, jsonify, render_template
import numpy as np
from datetime import datetime, timedelta
import logging

logger = logging.getLogger("quant.heatmap")
bp = Blueprint("heatmap", __name__, url_prefix="/heatmap")

SECTOR_MAP = {
    "科技": ["AAPL","MSFT","GOOGL","META","NVDA","AVGO","AMD","INTC","QCOM","TXN",
             "CRM","ADBE","NOW","PANW","CRWD","ADP","ORCL","ANET","AKAM","SNOW"],
    "消费": ["AMZN","TSLA","NFLX","HD","LOW","MCD","SBUX","NKE","TJX","TGT",
             "COST","WMT","EBAY","BKNG","MAR","RCL","CCL","DASH","UBER","ABNB"],
    "金融": ["JPM","GS","AXP","V","MA","BLK","C","BAC","MS","SCHW",
             "SPGI","COF","MET","PRU","AIG","ALL","AFL","MMC","CB"],
    "医疗": ["JNJ","UNH","LLY","MRK","ABBV","PFE","AMGN","ISRG","SYK","VRTX",
             "TMO","DHR","ABT","MDT","BSX","REGN","GILD","BIIB","DXCM","ZTS"],
    "工业": ["CAT","DE","BA","LMT","RTX","GE","HON","MMM","ETN","UPS",
             "FDX","CSX","UNP","CARR","AME","IR","PH","ROK","EMR"],
    "能源": ["XOM","CVX","COP","EOG","SLB","OXY","MPC","PSX","VLO","HAL",
             "BKR","FCX","NEM","APA","DVN","MRO","HES","FANG"],
    "半导体": ["NVDA","AVGO","AMD","INTC","QCOM","TXN","AMAT","KLAC","LRCX","MU","ADI"],
}


def _get_data():
    """获取热图数据（从缓存读取）"""
    from data_prod import load_price_cache
    
    cache = load_price_cache()
    sectors = []
    
    for sector_name, tickers in SECTOR_MAP.items():
        stocks = []
        for t in tickers:
            df = cache.get(t)
            if df is None:
                continue
            row = df.iloc[-1]
            price = row["Close"]
            mom = row.get("Momentum_12M", np.nan)
            rsi = row.get("RSI", np.nan)
            week_change = 0
            if len(df) >= 5:
                week_ago = df["Close"].iloc[-5]
                week_change = (price / week_ago - 1) * 100
            # 综合评分: 动量(40) + 周涨跌(40) + RSI(20)
            mom_score = max(0, min(100, 50 + (float(mom * 100) if not np.isnan(mom) else 0)))
            chg_score = max(0, min(100, 50 + float(week_change) * 2))
            rsi_score = 50.0
            if not np.isnan(rsi):
                rsi_val = float(rsi)
                if rsi_val < 30:
                    rsi_score = 80.0
                elif rsi_val > 70:
                    rsi_score = 30.0
                else:
                    rsi_score = 50.0 + (50.0 - rsi_val) * 0.4
            score = round(mom_score * 0.4 + chg_score * 0.4 + rsi_score * 0.2, 1)
            stocks.append({
                "ticker": t,
                "price": round(float(price), 2),
                "momentum": round(float(mom * 100), 1) if not np.isnan(mom) else 0,
                "rsi": round(float(rsi), 0) if not np.isnan(rsi) else None,
                "weekly_change": round(float(week_change), 2),
                "score": score,
            })
        if stocks:
            avg_score = round(sum(s["score"] for s in stocks) / len(stocks), 1)
            sectors.append({
                "name": sector_name,
                "stocks": stocks[:20],
                "count": len(stocks),
                "avg_score": avg_score,
            })

    total = sum(s["count"] for s in sectors)
    expected = sum(len(v) for v in SECTOR_MAP.values())

    return {
        "sectors": sectors,
        "coverage": f"{total}/{expected}",
    }


@bp.route("/")
def page():
    return render_template("heatmap.html")


@bp.route("/api/data")
def api_data():
    data = _get_data()
    return jsonify(data)
