# -*- coding: utf-8 -*-
"""★ 2026-09-23 修复回归：「朗读单词/词组」题不得被句子级语法规则判错。

现场（教科版五上 U7 第1大题，清缓存后全量实跑出现的**唯一新假错**）
-------------------------------------------------------------------
    第1大题·第1小题 题干 = "six fox"     ← x 音词对
    第1大题·第2小题 题干 = "box ox"
    第1大题·第3小题 题干 = "yellow yogurt" ← y 音
    第1大题·第4小题 题干 = "you yes"
    第1大题·第5小题 题干 = "zebra zero"    ← z 音
    题型 = "朗读单词。"

这五个题干是**成对的音素词**（共享同一目标音），是 phonics 教学设计。
LLM 却按句子语法判：
    「题干中出现"six fox"，其中"six"数词后名词应用复数形式"foxes"，
      存在单复数不一致的语法错误」→ 题干维度不通过 → 整题假错。

两道防线（本测试逐条锁定）
--------------------------
  ① 提示词（软约束）：题干由 ≤4 个纯字母词构成、且无任何句子级标点
     （. ? ! , ; : 及全角）→ 判定为"词/词组朗读" → 明确写入
     「只检查单词拼写，不得套用句子级语法规则」。
  ② 确定性兜底（硬约束）：即使 LLM 仍给出语法越权意见，只要
     理由**只**涉及句子级语法概念、且**完全没提**拼写/错别字/乱码/截断/缺失
     → 放行该维度（passed=True）并保留 LLM 原文供人工查看。

反向用例保证不洗白真错：
  - 真·拼写错误（"fiox 应为 fox"）必须仍判不通过；
  - 真·句子题（含标点）上的语法意见必须仍判不通过。

运行：python scripts/tests/test_fix_20260923f_word_drill_stem.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from src.review_agent import QuestionReview, ReviewAgent, ReviewConfig  # noqa: E402
from src.parse_yingyubao_docx import YingYuBaoQuestion  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  [OK] " if cond else "  [FAIL] ") + name
          + (("  -> " + str(detail)[:240]) if detail else ""))


DOCX = os.path.join(ROOT, "uploads", "260727口语训练新教科五上U4-7（已二校）.docx")


class _LLMStub:
    """记录每个维度的 prompt；题干维度按注入的 verdict 返回，其余返回通过。"""

    def __init__(self, stem_verdict="[通过 | 置信度:95] | 理由：数据完整。"):
        self.prompts = []
        self.stem_verdict = stem_verdict

    def ask(self, prompt, *a, **kw):
        self.prompts.append(prompt)
        if "【任务: 检查题干" in prompt or "【任务: 检查判断题题干" in prompt:
            return self.stem_verdict
        return "[通过 | 置信度:95] | 理由：数据完整。"

    def stem_prompts(self):
        return [p for p in self.prompts if "【任务: 检查题干" in p]

    def fallback_models(self):
        return []


class _TrainerStub:
    def build_enhanced_prompt(self, body, dim_filter=None, **kw):
        return body


class _KBStub:
    """知识点校验桩：本测试只关心题干维度，知识库返回空结果即可。"""

    def verify_question(self, **kw):
        return {}

    def get_unit_vocab(self, *a, **kw):
        return []

    def get_unit_patterns(self, *a, **kw):
        return []


def make_agent(stem_verdict="[通过 | 置信度:95] | 理由：数据完整。"):
    """只建对象不加载脚本（避免依赖 docx 内容），题干分支不需要 script_questions。"""
    ag = ReviewAgent.__new__(ReviewAgent)
    ag.cfg = ReviewConfig()
    ag.llm = _LLMStub(stem_verdict)
    ag.trainer = _TrainerStub()
    ag.kb = _KBStub()
    ag._build_role_prompt = lambda q: "ROLE"
    ag._build_knowledge_context = lambda q: ""
    return ag


def q_word(stem, type_2="朗读单词。"):
    q = YingYuBaoQuestion(unit=7, big=1, stage_idx=1, stem=stem, answer="")
    q.type_2 = type_2
    q.options = []
    q.keywords = []
    q.sentence_pattern = ""
    q.recording = ""
    q.passage = ""
    return q


def q_sentence(stem):
    return q_word(stem, type_2="朗读句子。")


def stem_of(ag, q):
    r = QuestionReview()
    ag._review_script_llm(r, q)
    return r.stem_check


# ───────────────── ① 提示词守卫 ─────────────────
print("== ① 提示词：词/词组朗读题须显式禁止句子级语法 ==")
ag = make_agent()
sc = stem_of(ag, q_word("six fox"))
_p = ag.llm.stem_prompts()[0]
check("词对题触发「朗读单词/词组」守卫", "不得套用句子级语法规则" in _p, _p[-260:])
check("守卫点名了『数词后名词须用复数』这类越权规则",
      "数词后名词须用复数" in _p)
check("守卫说明该题型考发音、成组单词是教学设计",
      "考的是发音" in _p and "教学设计" in _p)

print("== ① 反向：真句子题不得加该守卫 ==")
ag2 = make_agent()
_p2 = (stem_of(ag2, q_sentence("Next, he will need to cut along the lines.")),
       ag2.llm.stem_prompts()[0])[1]
check("含句末标点的句子题不加守卫",
      "不得套用句子级语法规则" not in _p2, _p2[-200:])

ag3 = make_agent()
stem_of(ag3, q_word("What a wonderful day it is"))   # 5 词 → 超阈值
check("超过 4 个词不加守卫（避免误伤短句）",
      "不得套用句子级语法规则" not in ag3.llm.stem_prompts()[0])

ag4 = make_agent()
stem_of(ag4, q_word("six fox.", type_2="朗读单词。"))  # 带标点 → 视为句子
check("带句末标点即使词少也不加守卫",
      "不得套用句子级语法规则" not in ag4.llm.stem_prompts()[0])

# ───────────────── ② 确定性兜底 ─────────────────
print("== ② 兜底：LLM 仍给语法越权意见 → 放行（并留档原文） ==")
LIVE_VERDICT = (
    "[不通过 | 置信度:80] | 理由：题干中出现\u201csix fox\u201d，"
    "其中\u201csix\u201d数词后名词应用复数形式\u201cfoxes\u201d，存在单复数不一致的语法错误。"
    "建议修改：将题干改为\u201csix foxes\u201d。"
)
ag5 = make_agent(LIVE_VERDICT)
sc5 = stem_of(ag5, q_word("six fox"))
check("现场原文被放行（passed=True）", sc5.passed is True,
      f"passed={sc5.passed} details={sc5.details}")
check("留档了 LLM 原文（检查人员仍能看到）",
      any("单复数" in str(d) for d in (sc5.details or [])), sc5.details)
check("标注了『已忽略』", any("已忽略" in str(d) for d in (sc5.details or [])))
check("清空了 error / suggestion（不再作为错题建议）",
      not (sc5.error or "").strip() and not (sc5.suggestion or "").strip())

print("== ② 反向：真·拼写错误必须仍判不通过 ==")
SPELL_VERDICT = "[不通过 | 置信度:90] | 理由：单词拼写错误，\u201cfiox\u201d应为\u201cfox\u201d。"
ag6 = make_agent(SPELL_VERDICT)
sc6 = stem_of(ag6, q_word("fiox"))
check("拼写错误不被兜底洗白", sc6.passed is False, f"passed={sc6.passed}")
check("未被标『已忽略』",
      not any("已忽略" in str(d) for d in (sc6.details or [])), sc6.details)

print("== ② 反向：真·句子题上的语法意见必须保留 ==")
ag7 = make_agent(LIVE_VERDICT)
sc7 = stem_of(ag7, q_sentence("Next, he will need to cut along the lines."))
check("句子题的语法意见仍判不通过", sc7.passed is False, f"passed={sc7.passed}")

print("== ② 反向：词对题但理由里同时提截断 → 不兜底 ==")
TRUNC_VERDICT = ("[不通过 | 置信度:80] | 理由：题干存在单复数不一致，且文字被截断显示。")
ag8 = make_agent(TRUNC_VERDICT)
sc8 = stem_of(ag8, q_word("six fox"))
check("含真问题关键词（截断）时不兜底", sc8.passed is False, f"passed={sc8.passed}")

print()
print(f"通过 {len(PASS)} / 失败 {len(FAIL)}")
if FAIL:
    for f in FAIL:
        print(f"  - {f}")
    sys.exit(1)
print("✅ 全部通过")
