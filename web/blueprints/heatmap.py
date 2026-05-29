"""
股票热图 - Blueprint
"""
from flask import Blueprint, jsonify, render_template
import numpy as np

bp = Blueprint("heatmap", __name__, url_prefix="/heatmap")

# 行业映射（S&P 500常用分类）
SECTOR_MAP = {
    "科技": ["AAPL","MSFT","GOOGL","META","NVDA","AVGO","AMD","INTC","QCOM","TXN",
             "CRM","ADBE","NOW","PANW","CRWD","ADP","ORCL","IBM","CSCO","ANET",
             "AMAT","KLAC","LRCX","MU","ADI","AKAM","DDOG","SNOW","PLTR","ARM"],
    "半导体": ["NVDA","AVGO","AMD","INTC","QCOM","TXN","AMAT","KLAC","LRCX","MU","ADI"],
    "消费": ["AMZN","TSLA","NFLX","UBER","ABNB","HD","LOW","MCD","SBUX","NKE",
             "TJX","TGT","COST","WMT","EBAY","BKNG","MAR","RCL","CCL","DASH"],
    "金融": ["JPM","GS","BK","AXP","V","MA","BLK","C","BAC","MS","SCHW",
             "SPGI","COF","MET","PRU","AIG","ALL","AFL","TRV","MMC"],
    "医疗": ["JNJ","UNH","LLY","MRK","ABBV","PFE","AMGN","ISRG","SYK","VRTX",
             "TMO","DHR","ABT","MDT","BSX","REGN","GILD","BIIB","DXCM","ZTS"],
    "工业": ["CAT","DE","BA","LMT","RTX","GE","HON","MMM","ETN","TDG",
             "UPS","FDX","CSX","UNP","CARR","AME","IR","PH","ROK","EMR"],
    "能源": ["XOM","CVX","COP","EOG","SLB","OXY","MPC","PSX","VLO","HAL",
             "BKR","FCX","NEM","APA","DVN","MRO","OXY","HES","FANG","CTRA"],
    "通信": ["T","VZ","CMCSA","DIS","CHTR","TMUS","WBD","PARA","LYV","FOXA"],
    "消费必需品": ["PG","KO","PEP","CL","KMB","MDLZ","SYY","GIS","KHC","HSY",
                 "WMT","COST","TGT","SJM","CAG","CPB","K","MKC","SYY","ADM"],
    "公用事业": ["NEE","DUK","SO","D","AEP","SRE","ED","EXC","PEG","XEL",
                "ES","EIX","AWK","WTRG","ATO","SRE","AEE","FE","CMS","PNW"],
    "房地产": ["PLD","AMT","CCI","EQIX","SPG","WELL","O","AVB","EQR","DLR",
              "PSA","BXP","ARE","INVH","MAA","ESS","UDR","WY","PEAK","FRT"],
}


def _get_data():
    """获取热图数据"""
    from data_prod import load_price_cache
    from quality_factor import compute_quality_scores
    
    cache = load_price_cache()
    quality = compute_quality_scores(cache)
    
    # 构建行业-股票数据
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
            
            # 一周涨跌幅
            if len(df) >= 5:
                week_ago = df["Close"].iloc[-5]
                week_change = (price / week_ago - 1) * 100
            else:
                week_change = 0
            
            q = quality.get(t, 0)
            
            stocks.append({
                "ticker": t,
                "price": round(float(price), 2),
                "score": round(float(q), 1),
                "momentum": round(float(mom * 100), 1) if not np.isnan(mom) else 0,
                "rsi": round(float(rsi), 0) if not np.isnan(rsi) else None,
                "weekly_change": round(float(week_change), 2),
                "market_cap": 0,  # 暂缺
            })
        
        if stocks:
            # 按评分排序
            stocks.sort(key=lambda x: -x["score"])
            avg_score = sum(s["score"] for s in stocks) / len(stocks) if stocks else 0
            sectors.append({
                "name": sector_name,
                "stocks": stocks[:15],  # 每行业最多显示15只
                "count": len(stocks),
                "avg_score": round(avg_score, 1),
            })
    
    # 按平均评分排序
    sectors.sort(key=lambda x: -x["avg_score"])
    return {"sectors": sectors}


@bp.route("/")
def page():
    return render_template("heatmap.html")


@bp.route("/api/data")
def api_data():
    data = _get_data()
    return jsonify(data)
