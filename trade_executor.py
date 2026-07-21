"""
统一执行器 (Unified Executor)
==============================
从信号总线读取信号 → 风控检查 → 统一券商接口下单
所有策略共用同一个执行管道，不再各自调 Alpaca API

设计原则：
- 独立进程运行，可随时启停
- 只从总线读，不关心信号来源
- 下单前统一过 risk_manager
- 走 broker_manager 统一券商接口
- 写成交回报到总线，记录到 trade_log
"""

import json
import logging
import os
import sys
import time
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s [EXECUTOR] %(message)s")
logger = logging.getLogger("quant.executor")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import signal_bus
import order_manager as om
from broker_manager import BrokerManager
from risk_manager import RiskManager

_circuit_breaker_loaded = False
try:
    from circuit_breaker import CircuitBreaker
    _circuit_breaker_loaded = True
except Exception:
    pass


# ============================================================
# 执行策略
# ============================================================

class TradeExecutor:
    """统一交易执行器"""

    def __init__(self, broker_id: str = None):
        from broker_manager import get_default_broker_id
        self.bm = BrokerManager()
        self.broker_id = broker_id or get_default_broker_id()
        self.risk = None
        self._client = None
        self._circuit_breaker = CircuitBreaker() if _circuit_breaker_loaded else None

    def get_client(self):
        """获取当前券商的交易客户端 (BrokerInterface)"""
        if self._client is None:
            try:
                self._client = self.bm.use(self.broker_id)
            except Exception as e:
                logger.warning(f"券商 {self.broker_id} 使用失败: {e}，尝试默认券商")
                self._client = self.bm.get_current()
        return self._client

    def set_broker(self, broker_id: str):
        """切换券商"""
        self.broker_id = broker_id
        self._client = None
        logger.info(f"切换到券商: {broker_id}")

    # -------------------------------------------------------
    # 信号 → 订单
    # -------------------------------------------------------

    def process_signal(self, msg: dict) -> list[dict]:
        """
        处理一条 signal 消息，返回待执行的交易意图
        只做计算、不下单
        """
        payload = msg["payload"]
        strategy = msg["strategy"]
        buy_list = payload.get("buy_list", [])
        sell_list = payload.get("sell_list", [])
        candidates = payload.get("candidates", [])
        market = payload.get("market", {})

        if not buy_list and not sell_list:
            logger.debug(f"[{strategy}] 无买卖列表")
            return []

        logger.info(f"[{strategy}] 处理信号: 买入{buy_list[:5]} 卖出{sell_list[:5]}")

        # 根据策略选择对应的券商
        try:
            from strategy_broker import get_broker_for_strategy
            target_broker = get_broker_for_strategy(strategy)
            if target_broker and target_broker != self.broker_id:
                self.set_broker(target_broker)
        except Exception as e:
            logger.debug(f"策略券商映射读取失败(使用默认): {e}")

        client = self.get_client()
        if not client:
            logger.warning(f"[{strategy}] 券商未连接")
            return []

        # 获取当前持仓
        positions = self._get_positions(client)
        held_symbols = set(p.get("symbol", p.get("ticker", "")) for p in positions)

        intents = []

        # 卖出信号
        for ticker in sell_list:
            if ticker in held_symbols:
                pos_info = next((p for p in positions if p.get("symbol", p.get("ticker", "")) == ticker), None)
                if pos_info:
                    qty = abs(int(pos_info.get("qty", pos_info.get("qty_available", 0))))
                    if qty > 0:
                        intents.append({
                            "ticker": ticker, "side": "sell", "qty": qty,
                            "reason": "signal", "source_strategy": strategy,
                            "price": pos_info.get("current_price", 0),
                        })

        # 买入信号
        for ticker in buy_list:
            if ticker not in held_symbols:
                # 从candidates获取推荐价格
                price = 0
                for c in candidates:
                    if c.get("ticker") == ticker:
                        price = c.get("price", 0)
                        break

                # 计算买入数量（由sizer决定）
                qty = self._calc_buy_qty(ticker, price, strategy)
                if qty > 0:
                    intents.append({
                        "ticker": ticker, "side": "buy", "qty": qty,
                        "reason": "signal", "source_strategy": strategy,
                        "price": price,
                    })

        # 写入订单意图到总线（但不执行）
        for intent in intents:
            signal_bus.write_order(
                ticker=intent["ticker"],
                side=intent["side"],
                qty=intent["qty"],
                price=intent.get("price", 0),
                reason=intent["reason"],
                source_strategy=intent["source_strategy"],
            )

        logger.info(f"[{strategy}] 生成 {len(intents)} 个交易意图")
        return intents

    # -------------------------------------------------------
    # 执行交易意图
    # -------------------------------------------------------

    def execute_intents(self, intents: list[dict], dry_run: bool = False) -> list[dict]:
        """
        执行交易意图列表。
        dry_run=True 只模拟不下单
        返回成交结果列表
        """
        if not self.risk:
            self.risk = RiskManager()

        client = self.get_client()
        if not client:
            logger.error("券商未连接，无法执行")
            return []

        results = []
        for intent in intents:
            ticker = intent["ticker"]
            side = intent["side"]
            qty = intent["qty"]
            price = intent.get("price", 0)
            reason = intent.get("reason", "signal")
            strategy = intent.get("source_strategy", "unknown")

            # ===== 风控检查 =====
            signal_info = {"symbol": ticker, "side": side, "qty": qty, "price": price}
            ok_risk, risk_msg = self.risk.check_signal(signal_info, {})
            if not ok_risk:
                logger.warning(f"  ⛔ [{ticker}] 风控拦截: {risk_msg}")
                # 记录被拦截的订单
                om.new_intent(ticker, side, qty, reason=reason, strategy=strategy,
                              broker=self.broker_id, price=price)
                results.append({
                    "ticker": ticker, "side": side, "qty": qty,
                    "status": "rejected", "reason": risk_msg,
                    "source_strategy": strategy,
                })
                continue

            if dry_run:
                logger.info(f"  [模拟] {side.upper()} {ticker} x{qty} @ ${price}")
                om.new_intent(ticker, side, qty, reason=reason, strategy=strategy,
                              broker=self.broker_id, price=price)
                results.append({
                    "ticker": ticker, "side": side, "qty": qty,
                    "status": "dry_run", "reason": reason,
                    "source_strategy": strategy,
                })
                continue

            # ===== 执行下单 =====
            try:
                # 先创建订单意图
                intent = om.new_intent(ticker, side, qty, reason=reason,
                                       strategy=strategy, broker=self.broker_id,
                                       price=price)
                order = self._place_order(client, ticker, side, qty)
                if order:
                    order_id = order.get("order_id", str(order))
                    om.mark_submitted(intent["intent_id"], broker_order_id=order_id)
                    logger.info(f"  ✅ {side.upper()} {ticker} x{qty} → 订单#{order_id}")

                    # 写入成交回报到总线
                    signal_bus.write_order(
                        ticker=ticker, side=side, qty=qty,
                        price=price, reason=reason,
                        source_strategy=strategy,
                        order_id=order_id,
                        filled_qty=qty,
                    )

                    # 写入交易日志（trade_log.json）和数据库
                    try:
                        from portfolio_tracker import record_trade
                        record_trade(
                            symbol=ticker, side=side, qty=qty,
                            price=price, order_id=order_id,
                        )
                    except Exception as e:
                        logger.debug(f"写入trade_log失败: {e}")

                    try:
                        from database import get_session, Trade, User
                        session = get_session()
                        try:
                            default_user = session.query(User).first()
                            if default_user:
                                trade = Trade(
                                    user_id=default_user.id,
                                    ticker=ticker,
                                    side=side.upper(),
                                    quantity=qty,
                                    price=price,
                                    amount=qty * price,
                                    strategy=strategy,
                                    source="executor",
                                    notes=f"order_id={order_id}; reason={reason}",
                                )
                                session.add(trade)
                                session.commit()
                        finally:
                            session.close()
                    except Exception as e:
                        logger.debug(f"写入数据库trades表失败: {e}")

                    results.append({
                        "ticker": ticker, "side": side, "qty": qty,
                        "status": "submitted", "order_id": order_id,
                        "reason": reason, "source_strategy": strategy,
                    })
                else:
                    logger.warning(f"  ⚠️ {side.upper()} {ticker} 下单返回空")
                    results.append({
                        "ticker": ticker, "side": side, "qty": qty,
                        "status": "empty_response", "source_strategy": strategy,
                    })
            except Exception as e:
                logger.error(f"  ❌ {side.upper()} {ticker} 失败: {e}")
                results.append({
                    "ticker": ticker, "side": side, "qty": qty,
                    "status": "error", "error": str(e)[:100],
                    "source_strategy": strategy,
                })

        return results

    # -------------------------------------------------------
    # 轮询总线 + 自动执行
    # -------------------------------------------------------

    def run_once(self, dry_run: bool = False):
        """单次执行：读总线 → 处理信号 → 执行"""
        if self._circuit_breaker:
            try:
                client = self.get_client()
                if client:
                    acct = client.get_account()
                    current_equity = float(acct.get("equity", acct.get("portfolio_value", 0)))
                    last_equity = float(acct.get("last_equity", current_equity))
                    if current_equity <= 0:
                        logger.debug("熔断检查跳过: 当前权益为0")
                    elif last_equity <= 0:
                        logger.debug("熔断检查跳过: 上次权益为0")
                    else:
                        cb_result = self._circuit_breaker.check(current_equity, last_equity)
                        if cb_result.get("should_stop"):
                            logger.warning(f"⛔ 熔断触发: {cb_result.get('reason')}，停止本次执行")
                            return [{"status": "circuit_breaker", "reason": cb_result["reason"]}]
            except Exception as e:
                logger.debug(f"熔断检查跳过: {e}")

        msgs = signal_bus.read_pending_messages(consumer="executor", limit=20)

        all_intents = []
        for msg in msgs:
            if msg["msg_type"] == "signal":
                intents = self.process_signal(msg)
                all_intents.extend(intents)
                signal_bus.mark_consumed(msg["msg_id"])
            elif msg["msg_type"] == "order":
                # order 类型消息直接执行（直接从总线来的订单意图）
                payload = msg["payload"]
                intent = {
                    "ticker": payload.get("ticker", ""),
                    "side": payload.get("side", "buy"),
                    "qty": payload.get("qty", 0),
                    "price": payload.get("price", 0),
                    "reason": payload.get("reason", "manual"),
                    "source_strategy": payload.get("source_strategy", msg.get("strategy", "unknown")),
                }
                all_intents.append(intent)
                signal_bus.mark_consumed(msg["msg_id"])

        if all_intents:
            results = self.execute_intents(all_intents, dry_run=dry_run)
            logger.info(f"本轮执行完成: {len(results)}笔, "
                        f"成功={sum(1 for r in results if r['status']=='submitted')}笔")
            return results
        else:
            logger.debug("无待处理消息")
            return []

    def run_loop(self, interval: int = 60, dry_run: bool = False):
        """持续轮询（用于独立进程模式）"""
        logger.info(f"🚀 执行器启动, 轮询间隔={interval}s, dry_run={dry_run}")
        while True:
            try:
                self.run_once(dry_run=dry_run)
            except Exception as e:
                logger.error(f"轮询异常: {e}")
            time.sleep(interval)

    # -------------------------------------------------------
    # 内部辅助方法
    # -------------------------------------------------------

    def _get_positions(self, client) -> list[dict]:
        """获取当前持仓（适配 BrokerInterface）"""
        try:
            positions = client.get_positions()
            return positions if isinstance(positions, list) else []
        except Exception as e:
            logger.debug(f"get_positions失败: {e}")
            return []

    def _calc_buy_qty(self, ticker: str, price: float, strategy: str) -> int:
        """计算买入数量（简化版，后续接入sizer模块）"""
        if price <= 0:
            return 0
        try:
            client = self.get_client()
            if client:
                acct = client.get_account()
                cash = float(acct.get("cash", 0))
                # 保守/激进 各分配50%，日内单独分配
                if strategy == "intraday":
                    ratio = 0.20
                elif strategy == "momentum":
                    ratio = 0.30
                else:
                    ratio = 0.30
                max_positions = 5
                per_target = (cash * ratio) / max_positions
                qty = int(per_target / price)
                return max(qty, 1)
        except Exception as e:
            logger.debug(f"计算买入量失败: {e}")
        return 0

    def _place_order(self, client, ticker: str, side: str, qty: int):
        """统一下单接口（适配 BrokerInterface）"""
        return client.submit_order(ticker, qty, side.upper(), order_type="market")


# ============================================================
# CLI 入口
# ============================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="统一交易执行器")
    parser.add_argument("--broker", default=None, help="券商ID")
    parser.add_argument("--dry-run", action="store_true", help="模拟运行，不下单")
    parser.add_argument("--interval", type=int, default=60, help="轮询间隔(秒)")
    parser.add_argument("--once", action="store_true", help="只执行一次，不循环")
    parser.add_argument("--broker-id", default=None, help="券商ID (同上)")

    args = parser.parse_args()

    broker = args.broker or args.broker_id
    executor = TradeExecutor(broker_id=broker)

    if args.once:
        results = executor.run_once(dry_run=args.dry_run)
        print(f"\n执行完成: {len(results)}笔交易意图")
        for r in results[:10]:
            print(f"  [{r['status']}] {r.get('side','')} {r.get('ticker','')} x{r.get('qty',0)}")
    else:
        executor.run_loop(interval=args.interval, dry_run=args.dry_run)
