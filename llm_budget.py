# -*- coding: utf-8 -*-
"""
每日 LLM 预算阀门（Budget Gate）

背景（2026-10-03 事故）：
    DeepSeek key「LLM审查」连续多日被打满（10-02 单日 ¥20.05）。
    为避免再次出现"事后对账才发现烧钱"，本项目所有 LLM 调用
    （LLMClient._call_api 统一入口）在发出请求前必须过本阀门。

工作方式：
    1. 每次调用前 check_budget()：当日累计消费 ≥ 上限 → 抛 BudgetExceededError，
       当天剩余所有 LLM 调用被拒绝（审查流程会拿到明确的预算报错文本，而非静默烧钱）。
    2. 每次调用后 record_usage()：从响应的 usage 字段读取真实 token 数，
       按内置单价表折算金额，追加进台账 data/llm_budget.json。
    3. 台账按"自然日"自动重置（跨零点后第一次调用时清零）。
    4. 阀门自身出错时选择"放行并大声打印警告"（fail-open），
       避免台账 IO 故障把整个审查工具变砖——但会在日志里留下明显痕迹。

配置：
    .env 中 LLM_DAILY_BUDGET_YUAN=10   （每日预算上限，单位：元，默认 10）

人工查询：
    python llm_budget.py                # 命令行直接查看今日台账
    GET /api/budget                     # web_server 暴露的 JSON 接口
"""

import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path

# ------------------------------------------------------------
# 路径与常量
# ------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent
LEDGER_PATH = _PROJECT_ROOT / "data" / "llm_budget.json"

# 默认每日预算（元）。可被 .env 的 LLM_DAILY_BUDGET_YUAN 覆盖。
DEFAULT_DAILY_LIMIT_YUAN = 10.0

# 台账中保留的单日调用明细条数上限（防止文件无限膨胀）
_MAX_CALL_RECORDS = 500

# ------------------------------------------------------------
# 单价表（元 / 1M tokens）：(input, output)
#   - 按子串匹配模型名，命中第一个为止；都不命中用 _DEFAULT_PRICE
#   - 数值为估算口径，宁可略高估（阀门宁可早触发不可晚触发）
#   - 缓存命中 tokens 按全价 input 计（简化处理，略高估更安全）
#   - 如需精确，可在此处按阿里云百炼/DeepSeek 官方价目表更新
# ------------------------------------------------------------

_PRICING = {
    "deepseek-v4.1-flash": (1.0, 4.0),
    "deepseek-v4-flash": (0.5, 2.0),
    "deepseek-v4-pro": (4.0, 16.0),
    "deepseek-v3.2": (2.0, 8.0),
    "deepseek-chat": (2.0, 8.0),
    "qwen3.8-27b": (2.0, 8.0),
    "qwen3.8-max": (2.4, 9.6),
    "qwen3.8-flash": (0.3, 1.2),
    "qwen3.7-flash": (0.3, 1.2),
}
_DEFAULT_PRICE = (2.0, 8.0)

_lock = threading.Lock()


class BudgetExceededError(RuntimeError):
    """当日 LLM 预算已耗尽。attrs: spent / limit / date"""

    def __init__(self, spent: float, limit: float, date: str):
        self.spent = spent
        self.limit = limit
        self.date = date
        super().__init__(
            f"[预算阀门] 今日({date}) LLM 消费已 达 {spent:.2f} 元 / 上限 {limit:.2f} 元，"
            f"剩余调用已拒绝。可调高 .env 的 LLM_DAILY_BUDGET_YUAN 或等明天自动重置。"
        )


# ------------------------------------------------------------
# 内部工具
# ------------------------------------------------------------

def _load_dotenv_if_needed() -> None:
    """复用 reviewer_common 的 .env 逻辑太重，这里独立做一次轻量加载（幂等）。"""
    env_path = _PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())
    except Exception:
        pass


def daily_limit() -> float:
    """每日预算上限（元）"""
    _load_dotenv_if_needed()
    raw = os.environ.get("LLM_DAILY_BUDGET_YUAN", "").strip()
    try:
        v = float(raw) if raw else DEFAULT_DAILY_LIMIT_YUAN
        return v if v > 0 else DEFAULT_DAILY_LIMIT_YUAN
    except ValueError:
        return DEFAULT_DAILY_LIMIT_YUAN


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _price_for(model: str) -> tuple:
    m = (model or "").lower()
    for key, price in _PRICING.items():
        if key in m:
            return price
    return _DEFAULT_PRICE


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """按单价表折算一次调用的金额（元）"""
    p_in, p_out = _price_for(model)
    return (prompt_tokens * p_in + completion_tokens * p_out) / 1_000_000.0


def _read_ledger() -> dict:
    """读台账；跨天自动重置；文件损坏视为今日 0 消费（自愈）"""
    today = _today()
    if not LEDGER_PATH.exists():
        return {"date": today, "spent_yuan": 0.0, "calls": []}
    try:
        with open(LEDGER_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"[预算阀门] ⚠ 台账文件损坏，已重置（原文件错误：{e}）")
        return {"date": today, "spent_yuan": 0.0, "calls": []}

    if data.get("date") != today:
        # 跨零点：清零重开
        return {"date": today, "spent_yuan": 0.0, "calls": []}
    data.setdefault("spent_yuan", 0.0)
    data.setdefault("calls", [])
    return data


def _write_ledger(data: dict) -> None:
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = LEDGER_PATH.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(LEDGER_PATH)  # 原子替换，避免并发写坏


# ------------------------------------------------------------
# 对外 API（供 LLMClient 调用）
# ------------------------------------------------------------

def check_budget(model: str = "") -> dict:
    """
    调用前检查。超限抛 BudgetExceededError；正常返回当前状态 dict。
    阀门自身故障时 fail-open（打印警告并放行）。
    """
    try:
        with _lock:
            data = _read_ledger()
        spent, limit = data["spent_yuan"], daily_limit()
        if spent >= limit:
            raise BudgetExceededError(spent, limit, data["date"])
        return {"date": data["date"], "spent_yuan": spent, "limit_yuan": limit,
                "remaining_yuan": round(limit - spent, 4)}
    except BudgetExceededError:
        raise  # 这是阀门的正常业务异常，不能被 fail-open 吞掉
    except Exception as e:
        print(f"[预算阀门] ⚠ 检查失败，本次放行（fail-open）：{e}")
        return {"date": _today(), "spent_yuan": None, "limit_yuan": daily_limit(),
                "remaining_yuan": None, "fail_open": True}


def record_usage(model: str, usage: dict) -> dict:
    """
    调用后记账。usage 为 OpenAI 兼容格式的 usage 字段：
        {"prompt_tokens": int, "completion_tokens": int, ...}
    返回本次记账明细。
    """
    p = int(usage.get("prompt_tokens") or 0)
    c = int(usage.get("completion_tokens") or 0)
    cost = estimate_cost(model, p, c)
    record = {
        "time": datetime.now().strftime("%H:%M:%S"),
        "model": model,
        "prompt_tokens": p,
        "completion_tokens": c,
        "cost_yuan": round(cost, 6),
    }
    try:
        with _lock:
            data = _read_ledger()
            data["spent_yuan"] = round(data["spent_yuan"] + cost, 6)
            data["calls"].append(record)
            if len(data["calls"]) > _MAX_CALL_RECORDS:
                data["calls"] = data["calls"][-_MAX_CALL_RECORDS:]
            _write_ledger(data)
    except Exception as e:
        # 记账失败不影响本次调用结果，但必须留痕
        print(f"[预算阀门] ⚠ 记账失败（本笔 {cost:.4f} 元未入账）：{e}")
    return record


def budget_status() -> dict:
    """供 /api/budget 与命令行使用的状态快照"""
    with _lock:
        data = _read_ledger()
    limit = daily_limit()
    return {
        "date": data["date"],
        "limit_yuan": limit,
        "spent_yuan": round(data["spent_yuan"], 4),
        "remaining_yuan": round(max(0.0, limit - data["spent_yuan"]), 4),
        "exhausted": data["spent_yuan"] >= limit,
        "calls_today": len(data["calls"]),
        "recent_calls": data["calls"][-20:],
    }


# ------------------------------------------------------------
# 命令行：python llm_budget.py
# ------------------------------------------------------------

if __name__ == "__main__":
    st = budget_status()
    print(f"日期       : {st['date']}")
    print(f"今日消费   : ¥{st['spent_yuan']:.4f} / 上限 ¥{st['limit_yuan']:.2f}"
          f"（剩余 ¥{st['remaining_yuan']:.2f}）")
    print(f"调用次数   : {st['calls_today']}")
    print(f"阀门状态   : {'已耗尽（拒绝新调用）' if st['exhausted'] else '放行中'}")
    if st["recent_calls"]:
        print("最近调用：")
        for r in st["recent_calls"][-10:]:
            print(f"  {r['time']}  {r['model']:<28} "
                  f"in={r['prompt_tokens']:<7} out={r['completion_tokens']:<6} "
                  f"¥{r['cost_yuan']:.4f}")
