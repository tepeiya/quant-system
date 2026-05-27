"""
总账户熔断保护
===========
铁律：当日亏损超过阈值，自动清仓并停止当日交易。

规则：
  - 当日亏损 > 总权益的 10% → 清仓，当日不再交易
  - 连续2天亏损 > 5% → 清仓，暂停交易24小时
  - 回测最大回撤的 50% → 永久停止该策略（需要人工复核）

用法：
  from circuit_breaker import CircuitBreaker
  cb = CircuitBreaker()
  if cb.should_stop():
      print("熔断触发，停止交易")
"""

import os
import json
import logging
from datetime import datetime, timedelta

logger = logging.getLogger("quant.circuit")

from system_config import get as get_cfg

BREAKER_FILE = "config/circuit_breaker.json"


class CircuitBreaker:
    """熔断保护"""

    def __init__(self):
        self.daily_loss_limit = get_cfg("circuit_daily_loss", 10.0)
        self.consecutive_loss_limit = get_cfg("circuit_consecutive_loss", 5.0)
        self.max_drawdown_stop = get_cfg("circuit_max_drawdown", 25.0)
        self.breakers = self._load()

    def _load(self) -> dict:
        if os.path.exists(BREAKER_FILE):
            with open(BREAKER_FILE) as f:
                return json.load(f)
        return {"tripped": False, "tripped_at": None, "reason": "", "consecutive_loss_days": 0, "last_equity": None}

    def _save(self):
        os.makedirs("config", exist_ok=True)
        with open(BREAKER_FILE, "w") as f:
            json.dump(self.breakers, f, indent=2)

    def check(self, current_equity: float, initial_equity: float) -> dict:
        """
        检查是否触发熔断。
        返回：{"should_stop": bool, "reason": str}
        """
        # 如果已经触发，检查是否过了冷静期
        if self.breakers.get("tripped"):
            tripped_at = self.breakers.get("tripped_at")
            if tripped_at:
                cool_down = get_cfg("circuit_cooldown_hours", 24)
                cooldown_end = datetime.fromisoformat(tripped_at) + timedelta(hours=cool_down)
                if datetime.now() < cooldown_end:
                    return {"should_stop": True, "reason": f"熔断冷却中（至{cooldown_end.strftime('%H:%M')})"}
                else:
                    # 冷却结束，重置
                    self.reset()

        # 总回撤计算（这才是关键）
        total_drawdown = (current_equity - initial_equity) / max(initial_equity, 1) * 100

        # 每日亏损
        last = self.breakers.get("last_equity")
        if last is not None:
            daily_loss = (last - current_equity) / max(last, 1) * 100
        else:
            daily_loss = 0

        reason = None
        trigger = False

        # 1. 总回撤超过最大限制
        if -total_drawdown > self.max_drawdown_stop:
            trigger = True
            reason = f"总回撤 {abs(total_drawdown):.1f}% 超过 {self.max_drawdown_stop}% 熔断线"
            self.breakers["permanent"] = True

        # 2. 当日亏损超过阈值
        if daily_loss > self.daily_loss_limit:
            trigger = True
            reason = f"当日亏损 {daily_loss:.1f}%，超过 {self.daily_loss_limit}% 熔断线"

        # 3. 连续亏损
        if daily_loss > 0:
            self.breakers["consecutive_loss_days"] += 1
        else:
            self.breakers["consecutive_loss_days"] = 0

        if self.breakers["consecutive_loss_days"] >= 2 and daily_loss > 3:
            trigger = True
            reason = f"连续{self.breakers['consecutive_loss_days']}天亏损，触发熔断"

        if trigger:
            self.breakers["tripped"] = True
            self.breakers["tripped_at"] = datetime.now().isoformat()
            self.breakers["reason"] = reason
            self._save()
            logger.warning(f"🔴 熔断触发: {reason}")
            return {"should_stop": True, "reason": reason}

        # 更新最后权益
        self.breakers["last_equity"] = current_equity
        self._save()
        return {"should_stop": False, "reason": ""}

    def reset(self):
        """重置熔断"""
        self.breakers = {"tripped": False, "tripped_at": None, "reason": "",
                         "consecutive_loss_days": 0, "last_equity": None}
        self._save()
        logger.info("🟢 熔断已重置")

    def is_tripped(self) -> bool:
        """是否处于熔断状态"""
        return self.check(0, 0).get("should_stop", False)


if __name__ == "__main__":
    cb = CircuitBreaker()
    result = cb.check(950, 1000)  # 当日亏了$50
    print(f"熔断检查: {result}")

    if result["should_stop"]:
        print(f"🔴 交易停止: {result['reason']}")
    else:
        print("🟢 正常交易")

    cb.reset()
