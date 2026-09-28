# -*- coding: utf-8 -*-
"""2026-09-21 修复回归：大题级「例句」必须参与题干判定 + App 侧拆散例句拼接。

背景（用户检查项四「错误原因和实际错误原因是否一致」被打穿的实例）
------------------------------------------------------------------
教科五上 U4 第3大题「三、仿照例句，说一说。（10分）」：

    脚本 docx 第040段：  例句：I will bring everything inside.
    解析结果：           sentence_pattern='I will bring everything inside.'
                         stem=''（小题题面印在**图片**上，脚本不重复写）

  ① **判定侧**（src/review_agent._review_script_llm）只认 q.stem，
     stem 空 + 题型不含"听音/看图" → 落到 else，让 LLM 判
     "脚本题干是否异常缺失" → 实测输出
     「❌ 脚本题干为空…未提供任何例句文字」+ 建议"请脚本补例句"
     —— 脚本本来就有例句，这是**原因与实际不符** + **反向建议**。

  ② **采集侧**（scripts/modules/口语训练._sub_info）App 把例句渲染成
     多个 TextView（'例句：' │ 'I' │ 'will' │ 'bring' │ …），单节点
     `_extract_sentence_pattern` 只拿到标签、正文全丢 → App 侧永远
     比对不上脚本例句 → 报告只能写"App 只有「例句：」标签"。

本测试全程 mock，不需要设备/网络/LLM。
"""
import os
import re
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  ✔ " if cond else "  ✘ ") + name + (("  → " + str(detail)[:220]) if detail else ""))


# ============================================================
# A 组：口语训练 · _join_split_pattern —— 拼回被拆散的「例句：」
# ============================================================
print("\n[A] _join_split_pattern 拼回被拆散的例句")
import importlib
M = importlib.import_module("modules.口语训练")

# 真机 U4 第3大题实测节点序列（每个词一个 TextView）
SEQ_SPLIT = [
    (30, 900, "例句："),
    (30, 950, "I"), (90, 950, "will"), (160, 950, "bring"),
    (240, 950, "everything"), (350, 950, "inside"), (430, 950, "."),
    (30, 1200, "请结合例句和图片说句子，点击“录音”开始作答。"),
]
got, used = M._join_split_pattern(SEQ_SPLIT)
check("拆散例句拼回完整正文",
      got == "I will bring everything inside.",
      repr(got))
check("句尾标点前不留空格（inside . → inside.）",
      " ." not in got, repr(got))
check("用掉的碎词被标记（供 stems 剔除）",
      {"I", "will", "bring", "everything", "inside", "."} <= used, sorted(used))
check("遇到中文说明即停止（不把 caption 拼进来）",
      "请结合例句" not in got, repr(got))

# 反例：单节点已完整（'1.例句：I travelled to ...'）→ 不该由本函数接手
SEQ_ONE = [(30, 900, "1.例句：I travelled to ...")]
got2, used2 = M._join_split_pattern(SEQ_ONE)
check("单节点完整例句不被重复拼接（返回空，交给原提取器）",
      got2 == "" and not used2, (repr(got2), used2))

# 反例：标签后没有英文 → 返回空
SEQ_BARE = [(30, 900, "例句："), (30, 950, "请结合例句和图片说句子。")]
got3, used3 = M._join_split_pattern(SEQ_BARE)
check("标签后无英文正文 → 返回空（不编造）", got3 == "", repr(got3))

# 反例：空序列
check("空序列安全返回", M._join_split_pattern([]) == ("", set()))

# 反例：普通题面（无例句标签）绝不能被本函数改动
SEQ_PLAIN = [(30, 900, "mum moon"), (30, 950, "1/5")]
check("无「例句」标签的普通题面不受影响",
      M._join_split_pattern(SEQ_PLAIN)[0] == "")


# ============================================================
# B 组：review_agent · 题干判定必须吃 sentence_pattern
# ============================================================
print("\n[B] review_agent._review_script_llm 题干分支")
from src.review_agent import ReviewAgent, ReviewConfig, QuestionReview
from src.parse_yingyubao_docx import YingYuBaoQuestion

DOCX = os.path.join(ROOT, "uploads", "260727口语训练新教科五上U4-7（已二校）.docx")
print("  脚本:", os.path.basename(DOCX), "exists=", os.path.exists(DOCX))


class _LLMStub:
    """记录**全部** prompt（题干/内容/答案…每个维度一次），固定返回"通过"。

    ⚠ 只留"最后一次"会读错维度：`_review_script_llm` 依次问 题干→内容→答案…，
    最后一次是答案维度，断言必然落空（本测试第一版就踩了这个坑）。
    """
    def __init__(self):
        self.prompts = []

    def ask(self, prompt, *a, **kw):
        self.prompts.append(prompt)
        return "[通过 | 置信度:95] | 理由：数据完整，无缺失。"

    def stem_prompts(self):
        """只看**题干维度**的 prompt。

        ⚠ 不能用 `"题干" in p` 过滤：「内容/选项」维度的任务串里也写着
        "不要判断『选项内容与录音/题干是否语义匹配』" → 会把它们一起捞进来
        （本测试第二版踩过这个坑）。任务串格式见 `_review_script_llm._llm_dim`：
            f"【任务: {task}】\n…"
        题干维度的 task 只有三种开头：检查题干… / 检查判断题题干… / 检查题干是否缺失…
        """
        return [p for p in self.prompts
                if "【任务: 检查题干" in p or "【任务: 检查判断题题干" in p]

    def fallback_models(self):
        return []


class _TrainerStub:
    def build_enhanced_prompt(self, body, dim_filter=None, **kw):
        return body


def _make_agent():
    ag = ReviewAgent(ReviewConfig(docx_path=DOCX, screenshot_dir=os.path.join(ROOT, "screenshots"),
                                  unit="4", verbose=False))
    ag.llm = _LLMStub()
    ag.trainer = _TrainerStub()
    ag._build_role_prompt = lambda q: "ROLE"
    ag._build_knowledge_context = lambda q: ""
    ag._apply_verdict = lambda chk, ans: (setattr(chk, "passed", True),
                                          setattr(chk, "method", "llm"))
    return ag


ag = _make_agent()
# 取脚本里 big=3 的第1小题（就是被误判的那道）
q3 = next(q for q in ag.script_questions if getattr(q, "big", 0) == 3)
print("  取到题：unit=%s big=%s stem=%r sentence_pattern=%r"
      % (q3.unit, q3.big, q3.stem, getattr(q3, "sentence_pattern", "")))
check("前提：该题 stem 为空但 sentence_pattern 非空",
      (not (q3.stem or "").strip()) and bool(getattr(q3, "sentence_pattern", "").strip()))

r = QuestionReview()
ag._review_script_llm(r, q3)
_ps = ag.llm.stem_prompts()
check("题干维度确实被问了一次", len(_ps) == 1, "n=%d" % len(_ps))
_p = _ps[0] if _ps else ""
check("题干 prompt 带上了大题级例句",
      "I will bring everything inside." in _p, _p[:300])
check("不再走『脚本题干是否异常缺失』这条误判路径",
      "脚本题干是否异常缺失" not in _p)
check("明确禁止因『没单独写小题题面』判不通过",
      "绝不能因『脚本没有单独写小题题面』" in _p, _p[-300:])
check("stem_check.actual 记录的是例句原文（报告可展示）",
      "I will bring everything inside." in (r.stem_check.actual or ""),
      repr(r.stem_check.actual))


# 反例：stem 与 sentence_pattern 都空 → 必须仍然报"缺题干"（不能把真缺失也放过）
print("\n[B2] 反向：真·缺题干仍要被判出来")
q_empty = YingYuBaoQuestion(unit=4, big=3, stage_idx=1, stem="", answer="I will turn off the lights.")
q_empty.type_2 = "仿照例句，说一说。"
ag.llm.prompts.clear()
r2 = QuestionReview()
ag._review_script_llm(r2, q_empty)
_ps2 = ag.llm.stem_prompts()
check("无 stem 且无 sentence_pattern → 仍走『脚本题干是否异常缺失』",
      any("脚本题干是否异常缺失" in x for x in _ps2),
      (_ps2[0][:200] if _ps2 else "(无题干 prompt)"))

# 反例：已有 stem 的普通题 → prompt 不含例句强约束（不应被新逻辑干扰）
q_normal = next(q for q in ag.script_questions if (q.stem or "").strip())
ag.llm.prompts.clear()
r3 = QuestionReview()
ag._review_script_llm(r3, q_normal)
_ps3 = ag.llm.stem_prompts()
_p3 = _ps3[0] if _ps3 else ""
check("有 stem 的普通朗读题：题干 prompt 仍是常规检查",
      "脚本题干是否异常缺失" not in _p3
      and "绝不能因『脚本没有单独写小题题面』" not in _p3,
      _p3[:200])
check("有 stem 的普通朗读题：题干内容正确传入",
      (q_normal.stem or "")[:20] in _p3, _p3[:200])


# ============================================================
print("\n" + "=" * 60)
print("通过 %d 项，失败 %d 项" % (len(PASS), len(FAIL)))
if FAIL:
    print("失败清单:")
    for f in FAIL:
        print("  -", f)
    sys.exit(1)
print("全部通过 ✅")
