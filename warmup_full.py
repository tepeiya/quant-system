"""
全量数据预热 — 下载 S&P 500 全部股票
先用新浪（快，回溯至1984），失败回退 Yahoo v8
"""
import logging, os, pickle, time, random, gc
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
logger = logging.getLogger("warmup_full")

CACHE_DIR = "data_cache"
os.makedirs(CACHE_DIR, exist_ok=True)

# S&P 500 完整列表（318只，去重）
SP500 = sorted([
    "A", "AAP", "AAPL", "ABBV", "ABC", "ABNB", "ABT", "ACGL", "ADBE", "ADM", "ADP", "ADSK",
    "AEE", "AEP", "AES", "AFL", "AJG", "ALGN", "ALL", "ALLE", "AMAT", "AMCR", "AMD", "AME",
    "AMGN", "AMP", "AMT", "AMZN", "ANSS", "AON", "APA", "APD", "APO", "AR", "ARES", "ASML",
    "ATO", "AVGO", "AWK", "AXP", "AZO", "BA", "BAC", "BAX", "BDX", "BEN", "BG", "BIIB",
    "BJ", "BK", "BKR", "BLK", "BLL", "BRO", "BSX", "BWXT", "BX", "C", "CAG", "CAH", "CARR",
    "CAT", "CB", "CBOE", "CCI", "CCK", "CDNS", "CE", "CF", "CG", "CHD", "CHTR", "CI", "CL",
    "CLX", "CMA", "CMCSA", "CME", "CMI", "CMS", "CNC", "CNP", "COP", "COST", "CPB", "CRM",
    "CRWD", "CSX", "CTRA", "CTVA", "CVS", "CVX", "CW", "D", "DE", "DG", "DGX", "DHI", "DHR",
    "DIS", "DLTR", "DOV", "DOW", "DTE", "DUK", "DVA", "DVN", "DXCM", "EA", "ECL", "ED",
    "EIX", "EL", "EMN", "EMR", "EOG", "EQIX", "ES", "ETN", "EW", "EXC", "F", "FANG", "FAST",
    "FDX", "FE", "FITB", "FLS", "FMC", "FTNT", "FTV", "GD", "GE", "GILD", "GIS", "GM",
    "GOOGL", "GRMN", "GS", "GWW", "HAL", "HBAN", "HCA", "HD", "HEI", "HES", "HIG", "HII",
    "HON", "HRL", "HSY", "HUM", "ICE", "IDXX", "IEX", "IFF", "ILMN", "INTC", "IP", "IR",
    "ISRG", "ITT", "JCI", "JNJ", "JPM", "K", "KBR", "KDP", "KEY", "KKR", "KLAC", "KMB",
    "KMI", "KO", "KR", "LECO", "LEN", "LH", "LHX", "LIN", "LLY", "LMT", "LNC", "LNG",
    "LNT", "LOW", "LRCX", "MA", "MAS", "MCD", "MCHP", "MCK", "MCO", "MDLZ", "MDT", "MET",
    "META", "MKTX", "MMC", "MMM", "MNST", "MOH", "MRK", "MRO", "MS", "MSA", "MSFT", "MTB",
    "MTDR", "MU", "MUR", "NDAQ", "NEE", "NFLX", "NI", "NKE", "NOC", "NOW", "NRG", "NSC",
    "NTRS", "NVDA", "NVR", "NXPI", "OKE", "OLN", "ORCL", "ORLY", "OSK", "OTIS", "OWL",
    "OXY", "PANW", "PCAR", "PEG", "PEP", "PFE", "PFG", "PG", "PGR", "PH", "PHM", "PKG",
    "PKI", "PLD", "PNC", "PODD", "PPG", "PR", "PRU", "PXD", "QCOM", "RE", "REGN", "RF",
    "RMD", "RNR", "ROK", "ROST", "RPM", "RRC", "RTX", "SBUX", "SCHW", "SEE", "SHW", "SJM",
    "SLB", "SNA", "SNPS", "SO", "SPGI", "SRE", "STI", "STT", "STZ", "SWK", "SWN", "SYK",
    "SYY", "T", "TDG", "TFX", "TGT", "TJX", "TMO", "TOL", "TPG", "TRGP", "TROW", "TRV",
    "TSLA", "TT", "TTC", "TXN", "TXT", "UBER", "UNH", "UNP", "UPS", "V", "VRTX", "VZ",
    "WAT", "WBA", "WEC", "WFC", "WMB", "WMT", "WRK", "WSO", "WST", "WTRG", "WTW", "XOM",
    "XYL", "ZION", "ZTS",
])


def compute_indicators(df):
    import numpy as np
    if df is None or len(df) < 50:
        return df
    df = df.copy()
    close = df["Close"].astype(float)
    for p in [5, 10, 20, 50, 200]:
        df[f"SMA{p}"] = close.rolling(p).mean()
        df[f"EMA{p}"] = close.ewm(span=p, adjust=False).mean()
    for p in [1, 3, 6, 12]:
        df[f"Momentum_{p}M"] = close.pct_change(periods=p * 21)
    df["ATR"] = (df["High"] - df["Low"]).rolling(14).mean()
    df["ATR_Pct"] = (df["ATR"] / close) * 100
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss.replace(0, np.nan)
    df["RSI"] = 100 - (100 / (1 + rs))
    df["Volume_Ratio"] = df["Volume"] / df["Volume"].rolling(20).mean()
    df["BB_Mid"] = df["SMA20"]
    bb_std = close.rolling(20).std()
    df["BB_Up"] = df["BB_Mid"] + 2 * bb_std
    df["BB_Dn"] = df["BB_Mid"] - 2 * bb_std
    return df


def main():
    from data_global import fetch_stock_data

    # 加载已有缓存
    cache_path = f"{CACHE_DIR}/prices.pkl"
    cache = {}
    if os.path.exists(cache_path):
        with open(cache_path, "rb") as f:
            cache = pickle.load(f)
    logger.info(f"已有缓存: {len(cache)} 只")

    total = len(SP500)
    for i, sym in enumerate(SP500):
        if sym in cache and cache[sym] is not None and len(cache[sym]) >= 200:
            continue  # 已有足够数据跳过
        
        try:
            import signal as _sig
            class TimeoutError(Exception): pass
            def _handler(signum, frame): raise TimeoutError()
            _sig.signal(_sig.SIGALRM, _handler)
            _sig.alarm(30)  # 每只最多 30 秒
            try:
                df = fetch_stock_data(sym, days=730)
                if df is not None and len(df) >= 60:
                    df = compute_indicators(df)
                    cache[sym] = df
            except:
                pass
            _sig.alarm(0)
            if (i + 1) % 20 == 0:
                with open(cache_path, "wb") as f:
                    pickle.dump(cache, f)
                logger.info(f"  [{i+1}/{total}] 成功: {len(cache)} 只")
        except Exception as e:
            logger.warning(f"  {sym}: {e}")
            continue
        time.sleep(random.uniform(0.5, 1.0))
        gc.collect()

    with open(cache_path, "wb") as f:
        pickle.dump(cache, f)
    logger.info(f"✅ 完成! 共 {len(cache)} 只股票")


if __name__ == "__main__":
    main()
