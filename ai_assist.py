"""
AI 选股辅助模块 — 全自动分析候选股票
====================================
支持:
  - Gemini API (免费)
  - 开关控制 (启用/禁用)
  - 每日信号生成时自动调用

用法:
  from ai_assist import ai_filter_candidates
  filtered = ai_filter_candidates(candidates, market_context)
"""

import os
import json
import logging
from datetime import datetime

logger = logging.getLogger("quant.ai")

AI_CONFIG_FILE = "config/ai_config.json"

DEFAULT_CONFIG = {
    "enabled": False,
    "provider": "gemini",
    "api_key": "",
    "model": "gemini-2.0-flash-lite",
    "api_base": "",
    "prompt_template": "",
}


def load_config() -> dict:
    """加载 AI 配置"""
    if os.path.exists(AI_CONFIG_FILE):
        try:
            with open(AI_CONFIG_FILE) as f:
                cfg = json.load(f)
            for k, v in DEFAULT_CONFIG.items():
                cfg.setdefault(k, v)
            return cfg
        except:
            pass
    return dict(DEFAULT_CONFIG)


def save_config(cfg: dict):
    """保存 AI 配置"""
    os.makedirs("config", exist_ok=True)
    with open(AI_CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)
    logger.info(f"AI配置已保存: enabled={cfg.get('enabled')}, provider={cfg.get('provider')}")


def ai_filter_candidates(candidates: list, market_context: dict = None) -> list:
    """
    用 AI 分析和筛选候选股票

    参数:
        candidates: 候选股票列表 [{ticker, score, price, ...}]
        market_context: 大盘上下文 {trend, spy_price, rsi}

    返回:
        filtered: 筛选后的候选列表（AI 推荐买的不动，不推荐的移除）
    """
    cfg = load_config()
    if not cfg.get("enabled") or not cfg.get("api_key"):
        logger.info("AI辅助未启用或未配置Key，跳过")
        return candidates

    if not candidates:
        return candidates

    provider = cfg.get("provider", "gemini")
    api_key = cfg.get("api_key", "")

    if provider == "gemini":
        return _filter_with_gemini(candidates, market_context, api_key, cfg)
    elif provider == "openai":
        return _filter_with_openai(candidates, market_context, api_key, cfg)
    else:
        logger.warning(f"不支持的AI提供商: {provider}")
        return candidates


def _filter_with_gemini(candidates: list, market_context: dict,
                        api_key: str, cfg: dict) -> list:
    """用 Gemini API 分析"""
    try:
        import google.generativeai as genai

        genai.configure(api_key=api_key)
        model_name = cfg.get("model", "gemini-2.0-flash-lite")

        # 构建提示词
        prompt = _build_prompt(candidates, market_context)

        model = genai.GenerativeModel(model_name)
        resp = model.generate_content(prompt, generation_config={
            "temperature": 0.3,
            "max_output_tokens": 500,
        })

        result = _parse_ai_response(resp.text, candidates)
        logger.info(f"AI分析完成: {len(candidates)}→{len(result)}只")
        return result

    except ImportError:
        logger.warning("google-generativeai 未安装，跳过AI分析")
        logger.warning("  pip install google-generativeai")
        return candidates
    except Exception as e:
        logger.error(f"AI分析失败: {e}")
        return candidates


def _filter_with_openai(candidates: list, market_context: dict,
                        api_key: str, cfg: dict) -> list:
    """用 OpenAI 兼容 API 分析（直接 requests，不需要 openai 库）"""
    import requests as _requests
    import json as _json

    api_base = cfg.get("api_base", "").strip().rstrip("/")
    model_name = cfg.get("model", "gpt-4o-mini")
    prompt = _build_prompt(candidates, market_context)

    try:
        resp = _requests.post(
            f"{api_base}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model_name,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
                "max_tokens": 500,
            },
            timeout=15,
        )

        if resp.status_code != 200:
            logger.error(f"AI API 返回 {resp.status_code}: {resp.text[:100]}")
            return candidates

        data = resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        if not content:
            logger.warning("AI 返回空内容")
            return candidates

        result = _parse_ai_response(content, candidates)
        logger.info(f"AI分析完成: {len(candidates)}→{len(result)}只")
        return result

    except Exception as e:
        logger.error(f"AI分析失败: {e}")
        return candidates


def _build_prompt(candidates: list, market_context: dict) -> str:
    """构建 AI 提示词"""
    context_str = ""
    if market_context:
        context_str = (
            f"大盘环境: SPY=${market_context.get('spy_price', '?')}, "
            f"RSI={market_context.get('rsi', '?')}, "
            f"趋势={market_context.get('trend', '?')}\n"
        )

    stocks_str = "\n".join([
        f"  {c.get('ticker','?'):6s} 评分{c.get('score',0):.1f} "
        f"价格${c.get('price',0):.2f} 动量{c.get('mom',0):+.1f}% "
        f"RSI={c.get('rsi','?')}"
        for c in candidates
    ])

    prompt = f"""你是一个专业的美国股票分析师。请分析以下候选股票。

{context_str}
候选股票:
{stocks_str}

对每只股票，综合考虑:
1. 技术面：动量趋势、RSI是否过热、价格位置
2. 基本面：这家公司是做什么的、近期表现
3. 风险：有没有明显的问题或不确定性

输出 JSON 格式（不要其他文字）:
[
  {{
    "ticker": "AAPL",
    "verdict": "BUY",           // BUY=建议买入, SKIP=建议跳过
    "reason": "一句话说明理由",  // 比如"动量强劲且RSI适中，苹果服务收入增长稳健"
    "confidence": "medium"       // high/medium/low
  }},
  ...
]"""

    return prompt


def _parse_ai_response(text: str, candidates: list) -> list:
    """解析 AI 返回的 JSON 结果"""
    import re, json

    # 提取 JSON
    json_match = re.search(r'\[.*?\]', text, re.DOTALL)
    if not json_match:
        logger.warning("AI返回中没有找到JSON")
        return candidates

    try:
        ai_results = json.loads(json_match.group(0))
    except json.JSONDecodeError:
        logger.warning("AI返回的JSON格式错误")
        return candidates

    if not isinstance(ai_results, list):
        return candidates

    # 构建 ticker -> verdict 映射
    verdicts = {}
    for r in ai_results:
        ticker = r.get("ticker", "")
        verdict = r.get("verdict", "SKIP").upper()
        if ticker and verdict in ("BUY", "SELL", "SKIP"):
            verdicts[ticker] = {
                "verdict": verdict,
                "reason": r.get("reason", ""),
                "confidence": r.get("confidence", "medium"),
            }

    # 应用筛选：AI 说 SKIP 的移除
    filtered = []
    skipped = []
    for c in candidates:
        t = c.get("ticker", "")
        if t in verdicts:
            v = verdicts[t]
            if v["verdict"] == "SKIP":
                skipped.append(t)
                logger.info(f"  AI跳过: {t} ({v['reason']})")
                continue
            c["ai_verdict"] = v["verdict"]
            c["ai_reason"] = v["reason"]
            c["ai_confidence"] = v["confidence"]
        filtered.append(c)

    if skipped:
        logger.info(f"AI过滤掉 {len(skipped)} 只: {', '.join(skipped)}")

    return filtered
