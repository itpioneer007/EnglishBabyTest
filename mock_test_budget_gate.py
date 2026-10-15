# -*- coding: utf-8 -*-
"""
mock 端到端测试：每日 LLM 预算阀门（llm_budget.py + reviewer_common.LLMClient）

覆盖场景：
    A. 记账：record_usage 累计金额、写入台账、明细追加
    B. 阀门：当日消费 ≥ 上限时 check_budget 抛 BudgetExceededError
    C. E2E-放行：mock 掉网络后 LLMClient 正常调用且真实 usage 被记账
    D. E2E-拦截：超限后 _call_api 不发网络请求直接抛预算异常
    E. ask() 短路：预算耗尽时 ask() 立即返回"[预算阀门]"文本，不重试、不发请求
    F. 跨天重置：台账日期非今日时自动清零

运行：python mock_test_budget_gate.py
注意：测试会临时改写 data/llm_budget.json（自动备份并在结束后还原）。
"""

import json
import os
import sys
from io import StringIO
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

import llm_budget
from llm_budget import BudgetExceededError, check_budget, record_usage, budget_status

LEDGER = llm_budget.LEDGER_PATH

_pass, _fail = 0, 0


def check(name, cond, detail=""):
    global _pass, _fail
    if cond:
        _pass += 1
        print(f"  [PASS] {name}")
    else:
        _fail += 1
        print(f"  [FAIL] {name}  {detail}")


def fake_openai_response(prompt_tokens=1000, completion_tokens=500, content="ok"):
    """构造 OpenAI 兼容 HTTP 响应（urlopen 返回值）"""
    body = json.dumps({
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
    }).encode("utf-8")

    class _Resp:
        def read(self):
            return body
    return _Resp()


def main():
    # ── 备份真实台账 + 固定预算上限 ──
    backup = LEDGER.read_bytes() if LEDGER.exists() else None
    os.environ["LLM_DAILY_BUDGET_YUAN"] = "1.0"   # 测试用 1 元上限，便于触发
    try:
        print("\n== A. 记账 ==")
        if LEDGER.exists():
            LEDGER.unlink()
        r = record_usage("deepseek-v4.1-flash", {"prompt_tokens": 1_000_000, "completion_tokens": 500_000})
        # 单价 (1.0, 4.0) 元/1M → 1.0*1 + 4.0*0.5 = 3.0 元
        check("单笔折算金额", abs(r["cost_yuan"] - 3.0) < 1e-6, f"got {r['cost_yuan']}")
        st = budget_status()
        check("台账累计金额", abs(st["spent_yuan"] - 3.0) < 1e-4, f"got {st['spent_yuan']}")
        check("明细条数", st["calls_today"] == 1, f"got {st['calls_today']}")
        r2 = record_usage("qwen3.8-27b", {"prompt_tokens": 100_000, "completion_tokens": 0})
        check("模型单价表子串匹配(qwen3.8-27b→2元/1M)", abs(r2["cost_yuan"] - 0.2) < 1e-6, f"got {r2['cost_yuan']}")
        r3 = record_usage("unknown-model-xyz", {"prompt_tokens": 1_000_000, "completion_tokens": 0})
        check("未知模型走默认单价(2元/1M)", abs(r3["cost_yuan"] - 2.0) < 1e-6, f"got {r3['cost_yuan']}")

        print("\n== B. 阈值拦截（上限 1 元，已花 5.2 元）==")
        try:
            check_budget("deepseek-v4.1-flash")
            check("超限应抛 BudgetExceededError", False, "未抛异常")
        except BudgetExceededError as e:
            check("超限应抛 BudgetExceededError", True)
            check("异常文案含[预算阀门]", "[预算阀门]" in str(e), str(e)[:60])

        print("\n== F. 跨天重置 ==")
        data = json.loads(LEDGER.read_text(encoding="utf-8"))
        data["date"] = "2026-01-01"   # 伪造昨天
        LEDGER.write_text(json.dumps(data), encoding="utf-8")
        st = budget_status()
        check("跨天后清零", st["spent_yuan"] == 0.0 and st["calls_today"] == 0, f"got {st}")

        print("\n== C. E2E-放行：mock 网络，LLMClient 正常调用并记账 ==")
        from reviewer_common import LLMClient
        client = LLMClient(api_key="sk-mock", model="deepseek-v4.1-flash",
                           base_url="https://mock.invalid/v1")
        with mock.patch("urllib.request.urlopen", return_value=fake_openai_response(2000, 1000, "hello")) as m_urlopen:
            out = client.ask("测试提问", image_path=None)
        check("返回模型内容", out == "hello", f"got {out!r}")
        check("网络请求发出 1 次", m_urlopen.call_count == 1, f"got {m_urlopen.call_count}")
        st = budget_status()
        # 2000*1.0/1M + 1000*4.0/1M = 0.002 + 0.004 = 0.006 元
        check("真实 usage 已记账", abs(st["spent_yuan"] - 0.006) < 1e-6, f"got {st['spent_yuan']}")
        last = st["recent_calls"][-1]
        check("记账明细含模型名", last["model"] == "deepseek-v4.1-flash", f"got {last}")

        print("\n== D+E. E2E-拦截：超限后不发网络请求，ask() 短路返回 ==")
        # 伪造台账：已花 100 元 >> 1 元上限
        data = json.loads(LEDGER.read_text(encoding="utf-8"))
        data["spent_yuan"] = 100.0
        LEDGER.write_text(json.dumps(data), encoding="utf-8")
        with mock.patch("urllib.request.urlopen") as m_urlopen:
            out = client.ask("测试提问", image_path=None)
            check("ask() 返回预算文案", "[预算阀门]" in out, f"got {out!r}")
            check("未发出任何网络请求", m_urlopen.call_count == 0, f"got {m_urlopen.call_count}")

        with mock.patch("urllib.request.urlopen") as m_urlopen2:
            try:
                client._call_api("直连测试")
                check("_call_api 超限抛异常", False, "未抛异常")
            except BudgetExceededError:
                check("_call_api 超限抛异常", True)
            check("_call_api 同样未发请求", m_urlopen2.call_count == 0, f"got {m_urlopen2.call_count}")

        print("\n== 视觉分支拦截 ==")
        client_v = LLMClient(api_key="sk-mock", model="deepseek-v4.1-flash",
                             base_url="https://mock.invalid/v1",
                             vision_api_key="sk-mock", vision_model="qwen3.8-27b",
                             vision_base_url="https://mock.invalid/v1")
        out = client_v.ask("看图题", image_paths=["nonexistent.png"])
        check("视觉调用超限同样被拦", "[预算阀门]" in out, f"got {out!r}")

    finally:
        # ── 还原真实台账 ──
        if backup is not None:
            LEDGER.write_bytes(backup)
        elif LEDGER.exists():
            LEDGER.unlink()
        os.environ.pop("LLM_DAILY_BUDGET_YUAN", None)

    print(f"\n===== 结果: {_pass} 通过 / {_fail} 失败 =====")
    sys.exit(1 if _fail else 0)


if __name__ == "__main__":
    main()
