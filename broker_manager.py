"""
券商接口管理器
============
支持多券商接入，统一交易接口。

当前支持的券商：
- Alpaca（纸交易/美国用户实盘）
- IBKR（盈透证券，中国用户推荐）

用法：
  from broker_manager import BrokerManager
  bm = BrokerManager()
  bm.use("ibkr")
  bm.get_positions()
"""

import os
import json
import logging
from datetime import datetime

logger = logging.getLogger("quant.broker")

BROKER_CONFIG_FILE = "config/broker_config.json"


# ===== 券商配置 =====

DEFAULT_CONFIG = {
    "alpaca_paper": {
        "name": "Alpaca 纸交易",
        "enabled": True,
        "type": "alpaca",
        "paper": True,
        "env_key_id": "ALPACA_API_KEY_ID",
        "env_secret": "ALPACA_SECRET_KEY",
        "base_url": "https://paper-api.alpaca.markets",
        "data_url": "https://data.alpaca.markets",
        "strategies": ["conservative", "momentum", "intraday"],  # 关联的策略
    },
    "alpaca_paper_intraday": {
        "name": "Alpaca 日内专用",
        "enabled": False,
        "type": "alpaca",
        "paper": True,
        "env_key_id": "ALPACA_INTRADAY_KEY_ID",
        "env_secret": "ALPACA_INTRADAY_SECRET",
        "base_url": "https://paper-api.alpaca.markets",
        "data_url": "https://data.alpaca.markets",
        "strategies": ["intraday"],
    },
    "ibkr": {
        "name": "盈透证券 (实盘)",
        "enabled": False,
        "type": "ibkr",
        "env_key_id": "IBKR_ACCOUNT_ID",
        "env_secret": "IBKR_TOKEN",
        "host": "localhost",
        "port": 7496,       # TWS实盘
        "client_id": 1,
    },
    "ibkr_paper": {
        "name": "盈透证券 (模拟)",
        "enabled": False,
        "type": "ibkr",
        "env_key_id": "IBKR_ACCOUNT_ID",
        "env_secret": "IBKR_TOKEN",
        "host": "localhost",
        "port": 7497,       # TWS模拟
        "client_id": 2,
    },
    "ibkr_gateway": {
        "name": "盈透证券 (IB Gateway)",
        "enabled": False,
        "type": "ibkr",
        "env_key_id": "IBKR_ACCOUNT_ID",
        "env_secret": "IBKR_TOKEN",
        "host": "localhost",
        "port": 4001,       # IB Gateway
        "client_id": 3,
    },
    "longbridge": {
        "name": "长桥证券",
        "enabled": False,
        "type": "longbridge",
        "env_key_id": "LONGBRIDGE_APP_KEY",
        "env_secret": "LONGBRIDGE_APP_SECRET",
    },
}


def load_config() -> dict:
    """加载券商配置"""
    os.makedirs("config", exist_ok=True)
    if os.path.exists(BROKER_CONFIG_FILE):
        with open(BROKER_CONFIG_FILE) as f:
            return json.load(f)
    # 首次使用默认配置
    save_config(dict(DEFAULT_CONFIG))
    return dict(DEFAULT_CONFIG)


def save_config(config: dict):
    """保存券商配置"""
    os.makedirs("config", exist_ok=True)
    with open(BROKER_CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


def list_brokers() -> list[dict]:
    """列出所有券商（包括未启用的）"""
    config = load_config()
    # 读取 .env 文件中的 Key 值
    env_values = {}
    env_file = ".env"
    if os.path.exists(env_file):
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    env_values[k.strip()] = v.strip()

    brokers = []
    for bid, bc in config.items():
        key_id = bc.get("env_key_id", "")
        secret = bc.get("env_secret", "")
        key_set = bool(env_values.get(key_id, ""))
        secret_set = bool(env_values.get(secret, ""))
        brokers.append({
            "id": bid,
            "name": bc.get("name", bid),
            "type": bc.get("type", "unknown"),
            "paper": bc.get("paper", False),
            "enabled": bc.get("enabled", False),
            "ready": bc.get("enabled", False) and key_set and secret_set,
            "strategies": bc.get("strategies", []),
        })
    return brokers


# ===== 统一交易接口 =====

class BrokerInterface:
    """所有券商必须实现这个接口"""
    
    def get_account(self) -> dict:
        raise NotImplementedError
    
    def get_positions(self) -> list[dict]:
        raise NotImplementedError
    
    def submit_order(self, symbol: str, qty: int, side: str, order_type="market") -> dict:
        raise NotImplementedError
    
    def cancel_order(self, order_id: str) -> bool:
        raise NotImplementedError
    
    def get_orders(self, limit=10, status="all") -> list[dict]:
        raise NotImplementedError


class AlpacaBroker(BrokerInterface):
    """Alpaca 券商实现（纸交易+实盘）"""
    
    def __init__(self, config: dict):
        import requests
        self._requests = requests
        self.base = config.get("base_url", "https://paper-api.alpaca.markets")
        self.key = os.environ.get(config.get("env_key_id", "ALPACA_API_KEY_ID"), "")
        self.secret = os.environ.get(config.get("env_secret", "ALPACA_SECRET_KEY"), "")
        self._auth = (self.key, self.secret)
    
    def _get(self, path):
        return self._requests.get(f"{self.base}{path}", auth=self._auth, timeout=10)
    
    def _post(self, path, data):
        return self._requests.post(f"{self.base}{path}", json=data, auth=self._auth, timeout=10)
    
    def _delete(self, path):
        return self._requests.delete(f"{self.base}{path}", auth=self._auth, timeout=10)
    
    def get_account(self) -> dict:
        r = self._get("/v2/account")
        if r.status_code == 200:
            a = r.json()
            return {
                "id": a["account_number"],
                "cash": float(a["cash"]),
                "equity": float(a["equity"]),
                "buying_power": float(a["buying_power"]),
                "status": a["status"],
            }
        return {"error": str(r.status_code)}
    
    def get_positions(self) -> list[dict]:
        r = self._get("/v2/positions")
        if r.status_code == 200:
            positions = []
            for p in r.json():
                cost = float(p.get("cost_basis", 0))
                mv = float(p["market_value"])
                positions.append({
                    "symbol": p["symbol"],
                    "qty": int(p["qty"]),
                    "avg_entry": float(p.get("avg_entry_price", 0)),
                    "current_price": float(p["current_price"]),
                    "market_value": mv,
                    "cost_basis": cost,
                    "pnl": round(mv - cost, 2),
                    "pnl_pct": round((mv - cost) / max(cost, 1) * 100, 2) if cost > 0 else 0,
                })
            return positions
        return []
    
    def submit_order(self, symbol: str, qty: int, side: str, order_type="market") -> dict:
        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.trading.requests import MarketOrderRequest
        from alpaca.trading.client import TradingClient
        
        client = TradingClient(self.key, self.secret, paper="paper" in self.base)
        side_enum = OrderSide.BUY if side.upper() == "BUY" else OrderSide.SELL
        
        try:
            order = client.submit_order(MarketOrderRequest(
                symbol=symbol, qty=qty, side=side_enum,
                time_in_force=TimeInForce.DAY,
            ))
            return {"order_id": str(order.id), "status": order.status, "symbol": symbol, "qty": qty}
        except Exception as e:
            return {"error": str(e)}
    
    def get_orders(self, limit=10, status="all") -> list[dict]:
        r = self._get(f"/v2/orders?limit={limit}&status={status}")
        if r.status_code == 200:
            return [{
                "id": o["id"], "symbol": o["symbol"], "side": o["side"],
                "qty": o["qty"], "status": o["status"],
                "filled_price": o.get("filled_avg_price"),
                "time": o.get("filled_at", o.get("submitted_at")),
            } for o in r.json()]
        return []


class IBBroker(BrokerInterface):
    """IBKR 券商接口 v2 —— 完整实现
    支持：TWS(7496) / IB Gateway(4001) / 模拟(7497)
    功能：账户查询、持仓、下单、订单管理、期权
    """

    def __init__(self, config: dict):
        self.host = config.get("host", "127.0.0.1")
        self.port = config.get("port", 7497)
        self.client_id = config.get("client_id", int(datetime.now().timestamp() % 1000))
        self.account_id = os.environ.get(config.get("env_key_id", "IBKR_ACCOUNT_ID"), "")
        self._ib = None
        self._connected = False
        self._next_order_id = -1
        logger.info(f"IBKR接口初始化: {self.host}:{self.port} clientId={self.client_id}")

    def _connect(self):
        if self._connected and self._ib and self._ib.isConnected():
            return True
        try:
            from ib_insync import IB, util
            util.patchAll()
            self._ib = IB()
            self._ib.connect(self.host, self.port, clientId=self.client_id,
                            account=self.account_id if self.account_id else None)
            self._ib.reqMarketDataType(1)  # 1=实时, 2=冻结, 3=延迟
            self._connected = True
            self._next_order_id = self._ib.client.getReqId()
            logger.info(f"✅ IBKR已连接: {self.host}:{self.port} (账户: {self.account_id or '默认'})")
            return True
        except Exception as e:
            self._connected = False
            logger.error(f"❌ IBKR连接失败: {e}")
            return False

    def _disconnect(self):
        try:
            if self._ib and self._ib.isConnected():
                self._ib.disconnect()
        except:
            pass
        self._connected = False

    def get_account(self) -> dict:
        if not self._connect():
            return {"error": "IBKR未连接", "note": "请确保TWS/Gateway已运行（端口7496/7497/4001）"}

        try:
            summary = self._ib.accountSummary()
            acct = {}
            for a in summary:
                acct[a.tag] = float(a.value) if a.currency == "BASE" else acct.get(a.tag, 0)

            return {
                "equity": round(acct.get("NetLiquidation", 0), 2),
                "cash": round(acct.get("TotalCashValue", 0), 2),
                "buying_power": round(acct.get("BuyingPower", 0), 2),
                "gross_pnl": round(acct.get("GrossPnL", 0), 2),
                "init_margin": round(acct.get("InitMarginReq", 0), 2),
                "maint_margin": round(acct.get("MaintMarginReq", 0), 2),
                "available_funds": round(acct.get("AvailableFunds", 0), 2),
                "connected": True,
                "broker": "IBKR",
            }
        except Exception as e:
            return {"error": f"IBKR查询失败: {e}", "connected": False}

    def get_positions(self) -> list[dict]:
        if not self._connect():
            return []

        try:
            positions = self._ib.positions()
            result = []
            total_pnl = 0

            for p in positions:
                contract = p.contract
                sec_type = contract.secType  # STK=股票, OPT=期权, FUT=期货
                symbol = contract.symbol
                if sec_type == "OPT":
                    symbol = f"{contract.symbol} {contract.lastTradeDateOrContractMonth} {contract.strike} {contract.right}"

                # 获取当前价格
                current_price = 0.0
                try:
                    ticker = self._ib.reqMktData(contract, "", False, False)
                    self._ib.sleep(0.5)
                    current_price = ticker.marketPrice() or 0.0
                except:
                    current_price = float(p.marketValue) / float(p.position) if float(p.position) != 0 else 0

                market_value = float(p.marketValue)
                avg_cost = float(p.avgCost)
                cost_basis = abs(avg_cost * float(p.position))
                pnl = round(market_value - cost_basis, 2)
                pnl_pct = round((market_value / cost_basis - 1) * 100, 2) if cost_basis > 0 else 0.0
                total_pnl += pnl

                result.append({
                    "symbol": symbol,
                    "sec_type": sec_type,
                    "qty": int(p.position),
                    "avg_entry_price": round(abs(float(p.avgCost)), 2),
                    "current_price": round(current_price, 2),
                    "cost_basis": round(cost_basis, 2),
                    "market_value": round(market_value, 2),
                    "pnl_amount": pnl,
                    "pnl_pct": pnl_pct,
                })

            return result
        except Exception as e:
            logger.error(f"IBKR持仓查询失败: {e}")
            return []

    def submit_order(self, symbol: str, qty: int, side: str,
                     order_type="market", limit_price=None,
                     sec_type="STK", exchange="SMART",
                     good_until=None, **kwargs) -> dict:
        """
        提交订单到IBKR。
        
        参数:
            symbol:      股票代码
            qty:         数量
            side:        "buy" 或 "sell"
            order_type:  "market" / "limit" / "stop" / "stoplimit"
            limit_price: 限价单价格
            sec_type:    "STK" 股票 / "OPT" 期权
            exchange:    "SMART" 智能路由 / "NYSE" / "NASDAQ"
            good_until:  GTC到期日 (datetime) 或 "day" (当日有效)
        """
        if not self._connect():
            return {"error": "IBKR未连接"}

        try:
            from ib_insync import Stock, Option, MarketOrder, LimitOrder, StopOrder, StopLimitOrder
            from ib_insync import Contract, Trade

            # 构建合约
            if sec_type == "OPT":
                # 期权合约需要额外参数
                contract = Option(symbol, exchange=exchange,
                                 lastTradeDateOrContractMonth=kwargs.get("expiry", ""),
                                 strike=kwargs.get("strike", 0),
                                 right=kwargs.get("right", "C"),
                                 currency="USD")
            else:
                contract = Stock(symbol, exchange, "USD")

            self._ib.qualifyContracts(contract)

            # 订单类型
            side_enum = "BUY" if side.upper() == "BUY" else "SELL"

            if order_type == "market":
                order = MarketOrder(side_enum, qty)
            elif order_type == "limit":
                if limit_price is None:
                    return {"error": "限价单需要limit_price"}
                order = LimitOrder(side_enum, qty, limit_price)
            elif order_type == "stop":
                stop_price = kwargs.get("stop_price", limit_price)
                if stop_price is None:
                    return {"error": "止损单需要stop_price"}
                order = StopOrder(side_enum, qty, stop_price)
            elif order_type == "stoplimit":
                stop_price = kwargs.get("stop_price", limit_price)
                if stop_price is None or limit_price is None:
                    return {"error": "止损限价单需要stop_price和limit_price"}
                order = StopLimitOrder(side_enum, qty, stop_price, limit_price)
            else:
                return {"error": f"不支持的订单类型: {order_type}"}

            # 有效期
            if good_until and good_until != "day":
                order.goodAfterTime = good_until.strftime("%Y%m%d %H:%M:%S")
                order.goodTillDate = (good_until + timedelta(days=30)).strftime("%Y%m%d %H:%M:%S")
                order.tif = "GTC"
            else:
                order.tif = "DAY"

            # 提交订单
            trade = self._ib.placeOrder(contract, order)

            return {
                "order_id": str(trade.order.orderId),
                "status": trade.orderStatus.status,
                "symbol": symbol,
                "qty": qty,
                "side": side,
                "order_type": order_type,
                "limit_price": limit_price,
                "filled_qty": trade.orderStatus.filled,
                "avg_fill_price": trade.orderStatus.avgFillPrice,
                "time": str(datetime.now()),
            }

        except Exception as e:
            logger.error(f"IBKR下单失败 {symbol}: {e}")
            return {"error": str(e), "symbol": symbol}

    def cancel_order(self, order_id: str) -> bool:
        if not self._connect():
            return False
        try:
            order = self._ib.getOrder(int(order_id))
            if order:
                self._ib.cancelOrder(order)
                return True
        except Exception as e:
            logger.error(f"IBKR撤单失败 {order_id}: {e}")
        return False

    def get_orders(self, limit=10, status="all") -> list[dict]:
        """查询订单列表"""
        if not self._connect():
            return []

        try:
            trades = self._ib.trades()
            filtered = []

            for t in trades:
                if status != "all" and t.orderStatus.status != status.upper():
                    continue
                filtered.append({
                    "order_id": str(t.order.orderId),
                    "symbol": t.contract.symbol,
                    "side": t.order.action,
                    "qty": t.order.totalQuantity,
                    "filled_qty": t.orderStatus.filled,
                    "avg_fill_price": t.orderStatus.avgFillPrice,
                    "status": t.orderStatus.status,
                    "order_type": t.order.orderType,
                    "time": str(t.order.lastModifiedTime or t.log[-1].time) if t.log else "",
                })

            return filtered[:limit]

        except Exception as e:
            logger.error(f"IBKR订单查询失败: {e}")
            return []

    def get_open_orders(self) -> list[dict]:
        """查询未成交订单"""
        return self.get_orders(status="submitted")

    def get_portfolio_summary(self) -> dict:
        """获取完整的投资组合摘要"""
        acct = self.get_account()
        positions = self.get_positions()

        total_mv = sum(p.get("market_value", 0) for p in positions)
        total_cost = sum(p.get("cost_basis", 0) for p in positions)
        total_pnl = sum(p.get("pnl_amount", 0) for p in positions)
        total_pnl_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0

        return {
            **acct,
            "positions": positions,
            "position_count": len(positions),
            "total_market_value": round(total_mv, 2),
            "total_cost_basis": round(total_cost, 2),
            "total_pnl": round(total_pnl, 2),
            "total_pnl_pct": round(total_pnl_pct, 2),
            "exposure_pct": round(total_mv / acct.get("equity", 1) * 100, 1) if acct.get("equity", 0) > 0 else 0,
        }


class LongBridgeBroker(BrokerInterface):
    """长桥证券接口（预留）"""
    def __init__(self, config: dict):
        pass
    
    def get_account(self) -> dict:
        return {"note": "长桥接口待实现"}
    
    def get_positions(self) -> list[dict]:
        return []
    
    def submit_order(self, symbol: str, qty: int, side: str, order_type="market") -> dict:
        return {"note": "长桥接口待实现"}
    
    def get_orders(self, limit=10, status="all") -> list[dict]:
        return []


# ===== 管理器 =====

BROKER_CLASSES = {
    "alpaca": AlpacaBroker,
    "ibkr": IBBroker,
    "longbridge": LongBridgeBroker,
}


def get_default_broker_id() -> str:
    path = "config/default_broker.txt"
    if os.path.exists(path):
        try:
            with open(path) as f:
                return f.read().strip()
        except:
            pass
    return "alpaca_paper"


class BrokerManager:
    """券商管理器 — 支持多用户账户隔离"""
    
    def __init__(self, username: str = None):
        self.config = load_config()
        self._current = None
        self._current_id = None
        self.username = username
    
    def _get_user_env(self) -> dict:
        """获取用户专属的券商Key（覆盖环境变量）"""
        if not self.username:
            return {}
        from web.blueprints.auth import get_user_broker_keys
        try:
            keys = get_user_broker_keys(self.username)
            env = {}
            if keys.get("ALPACA_API_KEY_ID"):
                env["ALPACA_API_KEY_ID"] = keys["ALPACA_API_KEY_ID"]
            if keys.get("ALPACA_SECRET_KEY"):
                env["ALPACA_SECRET_KEY"] = keys["ALPACA_SECRET_KEY"]
            if keys.get("IBKR_ACCOUNT_ID"):
                env["IBKR_ACCOUNT_ID"] = keys["IBKR_ACCOUNT_ID"]
            if keys.get("IBKR_TOKEN"):
                env["IBKR_TOKEN"] = keys["IBKR_TOKEN"]
            return env
        except:
            return {}
    
    def list_available(self) -> list[dict]:
        """列出可用的券商"""
        return list_brokers()
    
    def use(self, broker_id: str) -> BrokerInterface:
        """切换到指定券商（支持用户隔离）"""
        bc = self.config.get(broker_id)
        if not bc:
            raise ValueError(f"未知券商: {broker_id}")
        
        # 合并用户Key到环境变量
        user_env = self._get_user_env()
        for k, v in user_env.items():
            os.environ[k] = v
        
        broker_class = BROKER_CLASSES.get(bc["type"])
        if not broker_class:
            raise ValueError(f"未实现的券商类型: {bc['type']}")
        
        self._current = broker_class(bc)
        self._current_id = broker_id
        logger.info(f"已切换到: {bc['name']} {'[' + self.username + ']' if self.username else ''}")
        return self._current
    
    def get_current(self) -> BrokerInterface:
        if self._current is None:
            available = self.list_available()
            if not available:
                raise RuntimeError("没有可用的券商")

            # 优先使用默认券商（若已启用）
            default_id = get_default_broker_id()
            ids = [b["id"] for b in available]
            if default_id in ids:
                self.use(default_id)
            else:
                self.use(available[0]["id"])
        return self._current
    
    def get_for_strategy(self, strategy: str) -> "BrokerInterface":
        """获取指定策略绑定的券商"""
        for bid, bc in self.config.items():
            if not bc.get("enabled"):
                continue
            strategies = bc.get("strategies", [])
            if strategy in strategies:
                return self.use(bid)
        # 回退到默认
        return self.get_current()

    def get_strategy_broker_id(self, strategy: str) -> str:
        """获取指定策略绑定的券商ID"""
        for bid, bc in self.config.items():
            if not bc.get("enabled"):
                continue
            strategies = bc.get("strategies", [])
            if strategy in strategies:
                return bid
        return get_default_broker_id()

    def enable(self, broker_id: str, enabled: bool = True):
        """启用/禁用券商"""
        if broker_id in self.config:
            self.config[broker_id]["enabled"] = enabled
            save_config(self.config)
    
    def add(self, broker_id: str, config: dict):
        """添加新券商"""
        self.config[broker_id] = config
        save_config(self.config)


# ===== 快捷函数 =====

def check_alpaca():
    """检测Alpaca是否可用"""
    key = os.environ.get("ALPACA_API_KEY_ID", "")
    secret = os.environ.get("ALPACA_SECRET_KEY", "")
    if not key or not secret:
        return False
    import requests
    try:
        r = requests.get("https://paper-api.alpaca.markets/v2/account",
                         auth=(key, secret), timeout=5)
        return r.status_code == 200
    except:
        return False


if __name__ == "__main__":
    bm = BrokerManager()
    print("可用券商:")
    for b in bm.list_available():
        status = "✅ 就绪" if b["ready"] else "❌ 未配置Key"
        print(f"  {b['name']:20s} ({b['type']}) {status}")
    
    # 测试Alpaca
    if check_alpaca():
        alpaca = bm.use("alpaca_paper")
        acct = alpaca.get_account()
        print(f"\nAlpaca 账户: {acct.get('id','?')}")
        print(f"权益: ${acct.get('equity',0):.2f}")
        positions = alpaca.get_positions()
        print(f"持仓: {len(positions)}只")
        for p in positions:
            print(f"  {p['symbol']} x{p['qty']} @ ${p['current_price']} PnL:{p['pnl_pct']:+.2f}%")
