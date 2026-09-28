"""★ 2026-09-23 修复回归测试：脚本层 LLM「只报取证不足」不得判不通过。

现场（教科版五上 U7 第3大题第4小题，U7 实跑唯一一条"不通过"）：
    [不通过 | 置信度:70] | 理由：
      - 题干文字检查：通过。…
      - 题目内容检查：通过。…
      - 配图检查：未提供截图，无法核实图片
      建议修改：补充提供该题配图截图以校验图片与句子是否匹配…
三个子项里两个明确通过，唯一"问题"是**没有截图可看** —— 这是取证手段缺失，
不是 App/脚本缺陷。判不通过就是假错（用户反复要求"只判真正影响作答的问题"）。

判定要求（防洗白真错）：
  - 有任一实质问题词（拼写错误/不符/缺失/超纲/应改为…）→ 仍判不通过
  - 建议是"去改内容"而不是"去补截图/人工核对" → 仍判不通过
  - 降级后 method="uncertain" → web_server._cr() 映射为 None（未检），不计不通过

运行：python scripts/tests/test_fix_20260923d_evidence_only_verdict.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from src.review_agent import CheckResult, ReviewAgent  # noqa: E402

PASS = 0
FAIL = []


def chk(name, cond, extra=""):
    global PASS
    if cond:
        PASS += 1
        print(f"  [OK] {name}")
    else:
        FAIL.append(name)
        print(f"  [FAIL] {name}  {extra}")


agent = ReviewAgent.__new__(ReviewAgent)   # 只需要方法，不跑 __init__

# ── 现场原文（U7 第3大题第4小题） ──
LIVE = (
    "不通过 | 置信度:70 | 理由：\n"
    "- **题干文字检查**：通过。题干“根据句型提示，看图说句子”描述完整，无截断无错字，与脚本一致。\n"
    "- **题目内容检查**：通过。答案“I will put food inside.”拼写和语法正确，句型合理。\n"
    "- **配图检查**：未提供截图，无法核实图片 "
    "建议修改：补充提供该题配图截图以校验图片与句子是否匹配，并确认APP端输入框/录音按钮"
    "是否正常显示、能否完整输入答案句子"
)

print("== 判据：只报取证不足 ==")
chk("现场原文 → 认定为取证不足", ReviewAgent._evidence_only_miss(LIVE, "") is True)

chk("有实质拼写错误 → 不降级",
    ReviewAgent._evidence_only_miss(
        "未提供截图，无法核实图片 建议修改：补充提供截图；另外答案拼写错误 “lucas” 应为 “Lucas”",
        "补充提供截图") is False)
chk("内容缺失 → 不降级",
    ReviewAgent._evidence_only_miss(
        "配图未提供截图 建议修改：内容缺失，应改为 “I will make a bird feeder.”",
        "内容缺失，应改为 “I will make a bird feeder.”") is False)
chk("超纲词 → 不降级",
    ReviewAgent._evidence_only_miss(
        "未提供截图，无法核实图片 建议修改：把超纲词 cereal 换成 bread", "把超纲词 cereal 换成 bread") is False)
chk("建议是改内容而非补证 → 不降级",
    ReviewAgent._evidence_only_miss(
        "未提供截图，无法核实图片", "把 App 该处文字改成脚本原文「I will make ...」") is False)
chk("完全没提取证不足 → 不降级",
    ReviewAgent._evidence_only_miss("建议修改：把答案改成脚本原文", "") is False)

print("== _apply_verdict：降级为未判定 ==")
c = CheckResult()
agent._apply_verdict(c, LIVE)
chk('method 变 uncertain（→ _cr 映射 None 未检）', c.method == "uncertain", f"got {c.method!r}")
chk("建议被保留", "补充提供该题配图截图" in (c.suggestion or ""), f"got {c.suggestion!r}")
chk("details 写明未判定原因",
    any("未判定" in d and "取证不足" in d for d in c.details))
chk("details 仍保留 LLM 判断依据",
    any("题干文字检查" in d or "AI判断" in d or "AI理由" in d for d in c.details))

print("== _apply_verdict：真错仍判不通过 ==")
c2 = CheckResult()
agent._apply_verdict(c2, "不通过 | 置信度:95 | 理由：题干拼写错误，"
                         "“quiett” 应为 “quiet”，与脚本不一致 "
                         "建议修改：把 App 题干改成 “The quick queen is quite quiet.”")
chk("真错 method=llm", c2.method == "llm", f"got {c2.method!r}")
chk("真错 passed=False", c2.passed is False)
chk("真错保留建议", "quiet" in (c2.suggestion or ""), f"got {c2.suggestion!r}")

c3 = CheckResult()
agent._apply_verdict(c3, "通过 | 置信度:100 | 理由：题干完整可读，无错别字。")
chk("通过 → passed=True / method=llm", c3.passed is True and c3.method == "llm")

print(f"\n通过 {PASS} / 失败 {len(FAIL)}")
if FAIL:
    print("失败项：")
    for f in FAIL:
        print("  -", f)
    sys.exit(1)
print("✅ 全部通过")
