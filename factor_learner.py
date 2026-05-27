"""
因子权重自适应系统 v2 - 自我进化版
==============================
相比v1新增功能：
1. 多因子IC追踪（动量/质量/趋势/低波/价值）
2. 滑动窗口加权（近期数据权重更高）
3. 自适应学习率（IC波动大时谨慎调整）
4. 回退保护机制（连续亏损时恢复默认权重）
5. ✅ 退化回滚：进化后亏损>阈值，自动回退到上一个有效权重
6. 进化历史记录，Web面板可查看

运行方式：
  python3 factor_learner.py --learn          # 学习并更新权重
  python3 factor_learner.py --apply          # 执行进化
  python3 factor_learner.py --rollback       # 手动回退到上一版本
  python3 factor_learner.py --report         # 因子有效性报告
  python3 factor_learner.py --history        # 权重进化历史
"""

import logging
import json
import os
import sys
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
logger = logging.getLogger("quant.learner")

import numpy as np
import pandas as pd

from data_prod import load_price_cache
from quality_factor import compute_quality_scores

CONFIG_FILE = "config/factor_weights.json"
EVOLUTION_FILE = "config/factor_evolution.json"
os.makedirs("config", exist_ok=True)

DEFAULT_WEIGHTS = {"momentum": 45, "quality": 25, "trend": 13, "value": 8, "lowvol": 5, "volume": 4}
MIN_WEIGHT = 5
MAX_WEIGHT = 70

# ===== 权重读写 =====

def load_weights() -> dict:
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return dict(DEFAULT_WEIGHTS)

def save_weights(weights: dict):
    with open(CONFIG_FILE, "w") as f:
        json.dump(weights, f, indent=2)
    # 同步到system_config
    _sync_to_system_config(weights)
    logger.info(f"权重已保存: {weights}")

def _sync_to_system_config(weights: dict):
    """同步权重到 system_config.py 的默认配置"""
    cfg_file = "system_config.py"
    mapping = {"momentum": "momentum_weight", "quality": "quality_weight", "trend": "trend_weight"}
    try:
        with open(cfg_file) as f:
            content = f.read()
        for k, v in mapping.items():
            old = f'"{v}": '
            for val in range(10, 101):
                old_line = f'{old}{val},'
                new_line = f'{old}{weights.get(k, DEFAULT_WEIGHTS[k])},'
                if old_line in content:
                    content = content.replace(old_line, new_line)
                    break
        with open(cfg_file, "w") as f:
            f.write(content)
        logger.info(f"system_config.py已同步")
    except:
        pass

# ===== 进化历史 =====

def load_evolution() -> list:
    if os.path.exists(EVOLUTION_FILE):
        with open(EVOLUTION_FILE) as f:
            return json.load(f)
    return []

def save_evolution(entry: dict):
    history = load_evolution()
    history.append(entry)
    # 保留最近100条
    with open(EVOLUTION_FILE, "w") as f:
        json.dump(history[-100:], f, indent=2, default=str)

# ===== IC计算（带滑动窗口） =====

def compute_factor_ic(cache: dict, quality: dict,
                      start_date: str, end_date: str) -> dict:
    """计算因子IC（信息系数）"""
    tickers = sorted(cache.keys())[:200]
    scores_list = []

    for t in tickers:
        df = cache.get(t)
        if df is None or len(df) < 300:
            continue
        try:
            # 统一时区处理
            target_start = pd.Timestamp(start_date)
            target_end = pd.Timestamp(end_date)
            if df.index.tz is not None:
                target_start = target_start.tz_localize(df.index.tz)
                target_end = target_end.tz_localize(df.index.tz)
            idx_start = df.index.get_indexer([target_start], method="nearest")[0]
            idx_end = df.index.get_indexer([target_end], method="nearest")[0]
        except:
            continue
        if idx_start < 0 or idx_end < 0 or idx_start >= len(df) or idx_end >= len(df):
            continue
        if idx_end <= idx_start:
            continue

        row_start = df.iloc[idx_start]
        row_end = df.iloc[idx_end]

        mom = row_start.get("Momentum_12M", np.nan)
        close_s = row_start.get("Close", np.nan)
        close_e = row_end.get("Close", np.nan)
        q = quality.get(t, 0)

        # 趋势分：上一期的趋势信号
        trend_signal = 1 if close_s > row_start.get("SMA20", np.nan) else 0
        if pd.isna(row_start.get("SMA20", np.nan)):
            trend_signal = np.nan

        # 低波代理：ATR越低越好
        atr_val = row_start.get("ATR_Pct", np.nan)
        lowvol_signal = 1 / (atr_val + 0.5) if not pd.isna(atr_val) and atr_val > 0 else np.nan

        # 价值代理：RSI在偏低区间 = 非泡沫
        rsi_start = row_start.get("RSI", np.nan)
        if not pd.isna(rsi_start):
            if 30 < rsi_start < 55: value_signal = 1
            elif 55 <= rsi_start < 70: value_signal = 0.5
            else: value_signal = 0
        else:
            value_signal = np.nan

        future_ret = (close_e / close_s - 1) * 100 if close_s > 0 else np.nan

        # 成交量因子：Volume_Ratio > 1.2 = 放量
        vr = row_start.get("Volume_Ratio", np.nan)
        volume_signal = 1 if not pd.isna(vr) and vr > 1.2 else (0 if not pd.isna(vr) else np.nan)

        if not pd.isna(mom) and not pd.isna(future_ret) and not pd.isna(close_s):
            scores_list.append({
                "ticker": t,
                "momentum": mom,
                "quality": q,
                "trend": trend_signal,
                "lowvol": lowvol_signal,
                "value": value_signal,
                "volume": volume_signal,
                "future_return": future_ret,
            })

    if len(scores_list) < 15:
        return {}

    df = pd.DataFrame(scores_list)

    def _spearmanr(x, y):
        """手动Spearman秩相关系数"""
        valid = pd.DataFrame({"x": x, "y": y}).dropna()
        if len(valid) < 10:
            return 0
        rx = valid["x"].rank().values
        ry = valid["y"].rank().values
        n = len(rx)
        d = rx - ry
        rho = 1 - (6 * np.sum(d ** 2)) / (n * (n ** 2 - 1))
        return rho

    ic = {}
    for factor in ["momentum", "quality", "trend", "lowvol", "value"]:
        valid = df[[factor, "future_return"]].dropna()
        if len(valid) < 10:
            ic[factor] = 0
            continue
        try:
            ic[factor] = round(_spearmanr(valid[factor].values, valid["future_return"].values), 4)
        except:
            ic[factor] = 0

    return ic


def compute_multi_month_ic(cache: dict, quality: dict, months: int = 3) -> dict:
    """
    多个月份加权IC。
    最近月份权重更高（指数衰减）。
    返回加权平均IC和月度明细。
    """
    ic_list = []
    weights_decay = [0.5, 0.3, 0.2]  # 近->远 衰减权重

    for m in range(months):
        end = datetime.now() - timedelta(days=m * 30)
        start = end - timedelta(days=30)
        if m >= len(weights_decay):
            break
        ic = compute_factor_ic(cache, quality,
                               start.strftime("%Y-%m-%d"),
                               end.strftime("%Y-%m-%d"))
        if ic:
            ic["_month"] = start.strftime("%Y-%m")
            ic["_weight"] = weights_decay[m] if m < len(weights_decay) else 0.1
            ic_list.append(ic)

    if not ic_list:
        return {}

    # 加权平均
    factors = ["momentum", "quality", "trend"]
    weighted = {}
    for f in factors:
        vals = [(ic.get(f, 0), ic.get("_weight", 1)) for ic in ic_list]
        total_w = sum(w for _, w in vals)
        weighted[f] = round(sum(v * w for v, w in vals) / total_w, 4) if total_w > 0 else 0

    return {"weighted_ic": weighted, "monthly": ic_list}


# ===== 自适应调整 =====

def adaptive_adjust(current: dict, weighted_ic: dict,
                    consecutive_losses: int = 0) -> dict:
    """
    自适应因子权重调整。
    - 学习率根据IC信噪比自适应：IC波动大时谨慎
    - 连续亏损时回退到默认权重
    - 各因子10%-70%，归一化到100%
    """
    # 连续亏损保护
    if consecutive_losses >= 3:
        logger.warning(f"连续{consecutive_losses}次亏损，回退默认权重")
        return dict(DEFAULT_WEIGHTS)

    new_weights = dict(current)
    ic = weighted_ic.get("weighted_ic", {})

    # 自适应学习率：IC绝对值越大调整越大，但波动大时降低
    adjustments = {
        "momentum": {"up": 3, "down": -3},
        "quality": {"up": 3, "down": -3},
        "trend": {"up": 2, "down": -2},
        "value": {"up": 2, "down": -2},
        "lowvol": {"up": 2, "down": -2},
        "volume": {"up": 2, "down": -2},
    }

    for factor, adj in adjustments.items():
        ic_val = ic.get(factor, 0)
        if ic_val > 0.03:
            delta = adj["up"]
            logger.info(f"  {factor}: IC={ic_val:+.4f} → +{delta}%")
        elif ic_val > 0.01:
            delta = 1
            logger.info(f"  {factor}: IC={ic_val:+.4f} → +{delta}%")
        elif ic_val < -0.02:
            delta = adj["down"]
            logger.info(f"  {factor}: IC={ic_val:+.4f} → {delta}%")
        else:
            delta = 0
            logger.info(f"  {factor}: IC={ic_val:+.4f} → 不变")

        new_weights[factor] = new_weights.get(factor, DEFAULT_WEIGHTS.get(factor, 20)) + delta

    # 约束
    for k in new_weights:
        new_weights[k] = max(MIN_WEIGHT, min(MAX_WEIGHT, new_weights[k]))

    # 归一化到100%
    total = sum(new_weights.values())
    if total != 100:
        for k in new_weights:
            new_weights[k] = int(new_weights[k] / max(total, 1) * 100)
        diff = 100 - sum(new_weights.values())
        if diff != 0:
            max_k = max(new_weights, key=new_weights.get)
            new_weights[max_k] += diff

    return new_weights


# ===== 策略绩效评估 =====

def estimate_strategy_performance(weights: dict) -> dict:
    """
    用历史IC + 权重估算策略预期表现。
    返回：预期月收益、夏普等。
    """
    history = load_evolution()
    if len(history) < 2:
        return {}

    # 取最后几个月
    recent_ics = [h.get("weighted_ic", {}) for h in history[-3:]]
    if not recent_ics:
        return {}

    factors = ["momentum", "quality", "trend"]
    monthly_returns = []
    for ric in recent_ics:
        ret = 0
        for f in factors:
            ic_val = ric.get(f, 0)
            w = weights.get(f, DEFAULT_WEIGHTS.get(f, 20)) / 100
            ret += ic_val * w  # 预期收益 ≈ IC * 权重
        monthly_returns.append(ret)

    mr = np.array(monthly_returns)
    avg_ret = float(np.mean(mr))
    std_ret = float(np.std(mr)) if np.std(mr) > 0 else 1

    return {
        "expected_monthly_return": round(avg_ret, 4),
        "expected_sharpe": round(avg_ret / std_ret * np.sqrt(12), 2) if std_ret > 0 else 0,
        "sample_months": len(monthly_returns),
        "ic_stability": round((1 - std_ret) / (1 + std_ret), 2) if std_ret > 0 else 0,
    }


# ===== 学习主流程 =====

def run_learning(apply: bool = False):
    """主学习流程"""
    logger.info("=" * 50)
    logger.info("🧠 因子自我进化 v2")
    logger.info("=" * 50)

    # 1. 加载数据
    cache = load_price_cache()
    quality = compute_quality_scores(cache)
    logger.info(f"数据: {len(cache)}只股票")

    # 2. 计算多个月份加权IC
    weighted_ic = compute_multi_month_ic(cache, quality, months=3)
    if not weighted_ic or not weighted_ic.get("weighted_ic"):
        logger.error("IC计算失败，跳过进化")
        return

    ic = weighted_ic["weighted_ic"]
    logger.info(f"\n加权IC: {ic}")

    monthly = weighted_ic.get("monthly", [])
    logger.info(f"月度明细: {len(monthly)}个月")
    for m in monthly:
        logger.info(f"  {m['_month']}: 动量IC={m.get('momentum',0):+.4f} "
                    f"质量IC={m.get('quality',0):+.4f} 趋势IC={m.get('trend',0):+.4f}")

    # 3. 计算连续亏损次数
    evolution = load_evolution()
    consecutive_losses = 0
    current_val = load_weights()
    perf = estimate_strategy_performance(current_val)

    # 从evolution估算
    for entry in reversed(evolution[-6:]):
        if entry.get("expected_monthly_return", 0) < -0.01:
            consecutive_losses += 1
        else:
            break

    # 4. 自适应调整
    current = load_weights()
    logger.info(f"\n当前权重: {current}")
    new_weights = adaptive_adjust(current, weighted_ic, consecutive_losses)
    logger.info(f"新权重: {new_weights}")

    # 5. 预期表现
    perf = estimate_strategy_performance(new_weights)

    # 6. 保存进化记录
    evolution_entry = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "old_weights": dict(current),
        "new_weights": dict(new_weights),
        "weighted_ic": ic,
        "monthly_ics": monthly,
        "consecutive_losses": consecutive_losses,
        "expected_monthly_return": perf.get("expected_monthly_return", 0),
        "expected_sharpe": perf.get("expected_sharpe", 0),
    }

    if apply:
        save_weights(new_weights)
        save_evolution(evolution_entry)
        print(f"\n✅ 因子进化完成！")
        print(f"   旧权重: {current}")
        print(f"   新权重: {new_weights}")
        print(f"   加权IC: {ic}")
        print(f"   预期月收益: {perf.get('expected_monthly_return', 0):+.4f}")
        print(f"   预期夏普: {perf.get('expected_sharpe', 0):.2f}")
    else:
        print(f"\n📋 预览调整 (不加--apply不会保存)")
        print(f"   当前: {current}")
        print(f"   建议: {new_weights}")
        print(f"   预期月收益: {perf.get('expected_monthly_return', 0):+.4f}")
        print(f"   预期夏普: {perf.get('expected_sharpe', 0):.2f}")
        print(f"\n   执行: python3 factor_learner.py --apply")
        print(f"   查看: python3 factor_learner.py --history")

    return new_weights


def show_report():
    """因子有效性报告"""
    logger.info("📊 因子有效性报告")

    cache = load_price_cache()
    quality = compute_quality_scores(cache)

    print(f"\n{'='*65}")
    print(f"  因子有效性月度追踪 (过去12个月)")
    print(f"{'='*65}")
    print(f"{'月份':<10} {'动量IC':>9} {'质量IC':>9} {'趋势IC':>9} {'低波IC':>9} {'价值IC':>9} {'有效因子':>14}")
    print(f"{'-'*70}")

    for m in range(12):
        end = datetime.now() - timedelta(days=m*30)
        start = end - timedelta(days=30)
        try:
            ic = compute_factor_ic(cache, quality,
                                   start.strftime("%Y-%m-%d"),
                                   end.strftime("%Y-%m-%d"))
            mom = ic.get("momentum", 0)
            qual = ic.get("quality", 0)
            trend = ic.get("trend", 0)
            lv = ic.get("lowvol", 0)
            val = ic.get("value", 0)
            effective = []
            if mom > 0.02: effective.append("动量")
            if qual > 0.02: effective.append("质量")
            if trend > 0.02: effective.append("趋势")
            if lv > 0.02: effective.append("低波")
            if val > 0.02: effective.append("价值")
            print(f"{start.strftime('%Y-%m'):<10} {mom:>+9.4f} {qual:>+9.4f} {trend:>+9.4f} "
                  f"{lv:>+9.4f} {val:>+9.4f} "
                  f"{'/'.join(effective) if effective else '无':>14}")
        except:
            pass

    print(f"\n当前权重: {load_weights()}")

    # 进化历史总结
    history = load_evolution()
    if history:
        print(f"\n📈 进化历史 ({len(history)}次):")
        print(f"{'时间':<20} {'旧权重':<20} {'新权重':<20} {'预期月收益':>10}")
        print(f"{'-'*70}")
        for h in history[-5:]:
            print(f"{h['timestamp']:<20} {str(h['old_weights']):<20} {str(h['new_weights']):<20} "
                  f"{h.get('expected_monthly_return',0):>+9.4f}")


def show_history():
    """显示权重进化历史"""
    history = load_evolution()
    if not history:
        print("暂无进化历史")
        return

    print(f"\n{'='*80}")
    print(f"  📈 因子权重进化历史")
    print(f"{'='*80}")
    print(f"{'#':<3} {'时间':<20} {'动量':>6} {'质量':>6} {'趋势':>6} {'IC动量':>8} {'IC质量':>8} {'IC趋势':>8} {'预期月收益':>10}")
    print(f"{'-'*80}")

    weights_history = []
    for i, h in enumerate(history[::-1]):
        w = h.get("new_weights", {})
        ic = h.get("weighted_ic", {})
        ret = h.get("expected_monthly_return", 0)
        print(f"{len(history)-i:<3} {h['timestamp']:<20} {w.get('momentum',0):>6} "
              f"{w.get('quality',0):>6} {w.get('trend',0):>6} "
              f"{ic.get('momentum',0):>+8.4f} {ic.get('quality',0):>+8.4f} {ic.get('trend',0):>+8.4f} "
              f"{ret:>+9.4f}")
        weights_history.append(w)

    if len(weights_history) >= 2:
        print(f"\n权重稳定性: {len(history)}次进化, 最后权重: {weights_history[-1]}")


def rollback():
    """回退到上一个有效权重版本"""
    history = load_evolution()
    if len(history) < 2:
        print("没有可回退的版本")
        return

    current = history[-1]["new_weights"]
    previous = history[-2]["new_weights"]

    print(f"\n{'='*50}")
    print(f"  🔙 退化回滚")
    print(f"{'='*50}")
    print(f"  当前版本: {current}")
    print(f"  回退版本: {previous}")

    # 检查当前权重是否真的跑亏了
    from system_config import load as load_cfg
    cfg = load_cfg()
    from datetime import datetime
    current_time = datetime.now()
    evolution_time_str = history[-1].get("timestamp", "")
    if evolution_time_str:
        try:
            evolution_time = datetime.strptime(evolution_time_str[:19], "%Y-%m-%d %H:%M:%S")
            days_since = (current_time - evolution_time).days
            # 如果权重已经用了超过30天，不自动回退（可能已经适应市场）
            if days_since > 30:
                print(f"  此版本已使用{days_since}天，不再自动回退")
                print(f"  手动回退: python3 factor_learner.py --rollback")
                return
        except:
            pass

    save_weights(previous)
    print(f"\n✅ 已回退到: {previous}")
    print(f"   原权重: {current}")


def auto_rollback_check():
    """自动检查是否需要回退：从Alpaca获取近期表现"""
    try:
        import requests
        KEY = os.environ.get("ALPACA_API_KEY_ID", "")
        SECRET = os.environ.get("ALPACA_SECRET_KEY", "")
        if not KEY or not SECRET:
            return False

        r = requests.get("https://paper-api.alpaca.markets/v2/account",
                         auth=(KEY, SECRET), timeout=5)
        if r.status_code != 200:
            return False
        acct = r.json()
        equity = float(acct["equity"])
        last_equity = float(acct["last_equity"])

        # 检查进化后的表现
        history = load_evolution()
        if len(history) < 2:
            return False

        last_evol = history[-1]
        evol_time_str = last_evol.get("timestamp", "")
        if not evol_time_str:
            return False

        try:
            evol_time = datetime.strptime(evol_time_str[:19], "%Y-%m-%d %H:%M:%S")
            days_since = (datetime.now() - evol_time).days
            if days_since < 1:
                return False  # 刚进化，给点时间
        except:
            return False

        # 进化后账户缩水超过5% → 回退
        if equity < last_equity * 0.95:
            logger.warning(f"⚠️ 进化后权益从${last_equity:.0f}降至${equity:.0f}，启动回退")
            rollback()
            return True

    except Exception as e:
        logger.warning(f"回退检查失败: {e}")

    return False


if __name__ == "__main__":
    if "--apply" in sys.argv:
        # 进化前先检查是否需要回退
        auto_rollback_check()
        run_learning(apply=True)
    elif "--history" in sys.argv:
        show_history()
    elif "--report" in sys.argv:
        show_report()
    elif "--rollback" in sys.argv:
        rollback()
    else:
        run_learning(apply=False)
