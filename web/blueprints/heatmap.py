"""
股票热图 - Blueprint (实时版)
"""
from flask import Blueprint, jsonify, render_template
import numpy as np
import pandas as pd
from datetime import datetime

bp = Blueprint("heatmap", __name__, url_prefix="/heatmap")

SECTOR_MAP = {
    "科技": ["AAPL","MSFT","GOOGL","META","NVDA","AVGO","AMD","INTC","QCOM","TXN",
             "CRM","ADBE","NOW","PANW","CRWD","ADP","ORCL","ANET","AKAM","SNOW"],
    "消费": ["AMZN","TSLA","NFLX","HD","LOW","MCD","SBUX","NKE","TJX","TGT",
             "COST","WMT","EBAY","BKNG","MAR","RCL","CCL","DASH","UBER","ABNB"],
    "金融": ["JPM","GS","BK","AXP","V","MA","BLK","C","BAC","MS","SCHW",
             "SPGI","COF","MET","PRU","AIG","ALL","AFL","MMC","CB"],
    "医疗": ["JNJ","UNH","LLY","MRK","ABBV","PFE","AMGN","ISRG","SYK","VRTX",
             "TMO","DHR","ABT","MDT","BSX","REGN","GILD","BIIB","DXCM","ZTS"],
    "工业": ["CAT","DE","BA","LMT","RTX","GE","HON","MMM","ETN","TDG",
             "UPS","FDX","CSX","UNP","CARR","AME","IR","PH","ROK","EMR"],
    "能源": ["XOM","CVX","COP","EOG","SLB","OXY","MPC","PSX","VLO","HAL",
             "BKR","FCX","NEM","APA","DVN","MRO","HES","FANG","WBD","CTRA"],
    "半导体": ["NVDA","AVGO","AMD","INTC","QCOM","TXN","AMAT","KLAC","LRCX","MU","ADI"],
}


def _get_data():
    """获取热图数据（实时从 Tiingo/Alpaca 拉取）"""
    from data_prod import load_price_cache
    from quality_factor import compute_quality_scores
    
    cache = load_price_cache()
    
    # 从缓存获取已有数据
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
            
            if len(df) >= 5:
                week_ago = df["Close"].iloc[-5]
                week_change = (price / week_ago - 1) * 100
            else:
                week_change = 0

            stocks.append({
                "ticker": t,
                "price": round(float(price), 2),
                "momentum": round(float(mom * 100), 1) if not np.isnan(mom) else 0,
                "rsi": round(float(rsi), 0) if not np.isnan(rsi) else None,
                "weekly_change": round(float(week_change), 2),
                "score": 0,
            })
        
        if stocks:
            sectors.append({
                "name": sector_name,
                "stocks": stocks[:15],
                "count": len(stocks),
            })
    
    return {"sectors": sectors}


@bp.route("/")
def page():
    return render_template("heatmap.html")


@bp.route("/api/data")
def api_data():
    data = _get_data()
    return jsonify(data)
