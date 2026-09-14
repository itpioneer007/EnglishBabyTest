# -*- coding: utf-8 -*-
"""Mock 验证：解析脚本 docx 的「按关卡分组」

背景（用户反馈）：巧记单词一个单元 6 个关卡，各关题号都从 1 重新开始。
  旧 docx 是平铺列表（只在"位置"行标注关卡），审查员翻起来分不清"第3题"是哪一关的。
  用户要求"要么就把题目按单元+关卡数分类"。

本测试【真实生成一份 docx】（无设备依赖），再读回文档校验：
  1. 标题下出现「分关卡：第1关 X 题 | 第2关 Y 题 ...」明细
  2. 每个关卡恰好一个「━━ 第N关（X 题）━━」分组标题，顺序正确、无重复
  3. 每题「位置」行含 第N关
  4. 无 level 的模块（单元自检）行为完全不变（不出现分组标题/明细）
"""
import sys, os, re, shutil, tempfile

_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_here, "scripts"))
sys.path.insert(0, _here)

from common.gen_script import QuestionCollector

# ★ 打桩：跳过 LLM 知识点生成（每题一次调用，真机上 69 题要跑 ~4 分钟）。
#   本测试只验证 docx 的关卡分组与位置行，与知识点内容无关。
#   ⚠ 这是【类级】打桩，会影响后续所有实例；测试组 C 要验证缓存时会恢复原函数。
_ORIG_LLM_KNOWLEDGE = QuestionCollector._llm_knowledge
QuestionCollector._llm_knowledge = lambda self, q: "（mock 知识点）"

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'✅' if cond else '❌'} {name}" + (f"  ({detail})" if detail else ""))


os.environ.setdefault("PYTHONIOENCODING", "utf-8")

_tmp = tempfile.mkdtemp(prefix="lvgroup_")

# 真实分布参考：六上 U1 各关题数（第1关 0 = 已通关不再出题）
LEVEL_PLAN = [(1, 3), (2, 11), (3, 15), (4, 13), (5, 12), (0, 15)]
_LABEL = {0: "boss关"}

print("=" * 66)
print("测试组 A · 巧记单词 U1（6 关，跨关卡题号从 1 重来）")
print("=" * 66)

coll = QuestionCollector(module="巧记单词", version="湘少版",
                         grade="六年级上册", save_root=_tmp)
_qno = 0
for lv, n in LEVEL_PLAN:
    for k in range(1, n + 1):
        _qno += 1
        coll.add(qno=_qno,
                 stem=f"听录音，选择与录音内容相符的释义。（第{lv}关第{k}题）",
                 options=["A. new", "B. old", "C. long"],
                 answer="A", qtype="巧记单词", unit=1,
                 level=lv, allow_listen=True, speaker_word="new")

docx_path = coll.finish_unit(unit=1)
check("docx 生成成功", bool(docx_path) and os.path.exists(docx_path),
      os.path.basename(docx_path or ""))

# ---- 读回 docx 校验 ----
from docx import Document
doc = Document(docx_path)
lines = [p.text for p in doc.paragraphs]

_detail = next((t for t in lines if t.startswith("分关卡：")), "")
_group_heads = [t for t in lines if t.startswith("━━")]
_loc_lines = [t for t in lines if t.startswith("位置：")]

check("出现「分关卡」明细行", bool(_detail), _detail[:70])
for lv, n in LEVEL_PLAN:
    _label = f"第{lv}关" if lv else "boss关"
    if not n:
        continue
    check(f"  明细含 {_label} {n} 题", f"{_label} {n} 题" in _detail)

_expect_heads = ["boss关" if lv == 0 else f"第{lv}关" for lv, n in LEVEL_PLAN if n]
check(f"关卡分组标题数量 = {len(_expect_heads)}（每关一个）",
      len(_group_heads) == len(_expect_heads), f"实际 {len(_group_heads)} 个")
check("分组标题顺序与关卡顺序一致",
      [re.search(r"(boss关|第\d+关)", h).group(1) for h in _group_heads] == _expect_heads,
      " → ".join(_group_heads))
check("★每个关卡只插一次标题（无重复）",
      len(set(_group_heads)) == len(_group_heads))
check(f"分组标题带题数（如「━━ 第2关（11 题）━━」）",
      all(re.search(r"（\d+ 题）", h) for h in _group_heads),
      _group_heads[1] if len(_group_heads) > 1 else "")

_total = sum(n for _, n in LEVEL_PLAN)
check(f"题目总数 {_total} 题全部落盘", len(_loc_lines) == _total,
      f"位置行 {len(_loc_lines)} 条")

# 位置行必须带关卡，且按关卡连续出现（验证分组是真实分组而非仅标题）
def _lv_of(ln):
    m = re.search(r"第(\d+)关", ln)
    if m:
        return int(m.group(1))
    return 0 if "boss关" in ln else None

_lvs = [_lv_of(t) for t in _loc_lines]
check("每题「位置」行都带关卡（含 boss关）", all(v is not None for v in _lvs),
      f"缺失 {sum(1 for v in _lvs if v is None)} 条")
from itertools import groupby
_runs = [k for k, _ in groupby(_lvs)]
_expect_runs = [lv for lv, n in LEVEL_PLAN if n]
check("同一关的题连续排布（分组真实生效）", _runs == _expect_runs,
      f"实际顺序 {_runs} / 预期 {_expect_runs}")

print()
print("=" * 66)
print("测试组 B · 无 level 的模块（单元自检）行为不得改变")
print("=" * 66)

_tmp2 = os.path.join(_tmp, "plain")
coll2 = QuestionCollector(module="单元自检", version="湘少版",
                          grade="五年级上册", save_root=_tmp2)
for i in range(1, 6):
    coll2.add(qno=i, stem=f"选出不同类的一项（第{i}题）",
              options=["A. cat", "B. dog", "C. desk"], answer="C",
              qtype="单元自检", unit=1)   # 不传 level

d2 = coll2.finish_unit(unit=1)
doc2 = Document(d2)
l2 = [p.text for p in doc2.paragraphs]
check("无 level → 不出现关卡分组标题", not any(t.startswith("━━") for t in l2))
check("无 level → 不出现「分关卡」明细", not any(t.startswith("分关卡：") for t in l2))
check("无 level → 位置行不含「第N关」",
      not any("关" in t and "第" in t for t in l2 if t.startswith("位置：")),
      next((t for t in l2 if t.startswith("位置：")), ""))
check("无 level → 题目仍全部生成（5 题）",
      len([t for t in l2 if t.startswith("位置：")]) == 5)

shutil.rmtree(_tmp, ignore_errors=True)

print()
print("=" * 66)
print("测试组 C · 知识点缓存（同一题目不得重复触发 LLM，且文案必须一致）")
print("=" * 66)

# ★ 恢复真实 _llm_knowledge（测试组 A/B 用的是类级打桩，会掩盖缓存逻辑）
QuestionCollector._llm_knowledge = _ORIG_LLM_KNOWLEDGE


class FakeLLM:
    """伪 LLM：记录调用次数，返回可预测的文案。"""

    def __init__(self):
        self.calls = 0

    def ask(self, prompt):
        self.calls += 1
        return f"「new」表示“新的”，用来形容刚出现或没见过的事物。（第{self.calls}次调用）"


_c = QuestionCollector(module="巧记单词", version="湘少版",
                       grade="六年级上册", save_root=os.path.join(_tmp, "cache"))
_c._llm = FakeLLM()

# 同一道题（题干+选项+答案相同）在多个关卡反复出现 —— 巧记单词的真实形态
_dup_q = dict(stem="选出发音与 new 相同的单词", options=["A. new", "B. old", "C. long"],
              answer="A", unit=1)
for lv in (1, 2, 3, 4):          # 4 次重复
    _c.add(qno=lv, level=lv, qtype="巧记单词", **_dup_q)
# 换一道不同的题（选项不同 → 不同 key）
_c.add(qno=5, level=5, qtype="巧记单词",
       stem="选出发音与 new 相同的单词", options=["A. new", "B. now", "C. no"],
       answer="A", unit=1)

_k1 = _c._llm_knowledge(_c.questions[0])
_k2 = _c._llm_knowledge(_c.questions[1])
_k3 = _c._llm_knowledge(_c.questions[2])
_k4 = _c._llm_knowledge(_c.questions[3])
_k5 = _c._llm_knowledge(_c.questions[4])

check("★同一题目只调 1 次 LLM（4 道重复题）", _c._llm.calls == 2,
      f"LLM 调用 {_c._llm.calls} 次（重复题 1 次 + 不同题 1 次）")
check("★同一题目的知识点文案完全一致（确定性）",
      _k1 == _k2 == _k3 == _k4, f"4 份文案是否全等: {len({_k1, _k2, _k3, _k4}) == 1}")
check("不同题目各自独立生成（不误合并）", _k5 != _k1)
check("缓存命中计数正确", _c._knowledge_cache_hits == 3,
      f"命中 {_c._knowledge_cache_hits}（4 重复题 - 1 次实调）")
check("_knowledge_key 只由内容决定（与关卡/单元无关）",
      _c._knowledge_key(_c.questions[0]) == _c._knowledge_key(_c.questions[3]))

# finish_unit 里重复题也应复用（不新增 LLM 调用）
_d3 = _c.finish_unit(unit=1)
check("finish_unit 生成成功", bool(_d3))
check("finish_unit 期间未新增 LLM 调用（缓存生效）", _c._llm.calls == 2,
      f"总调用 {_c._llm.calls} 次")

shutil.rmtree(_tmp, ignore_errors=True)

print()
print("=" * 66)
print("测试组 D · LLM 不可用时的降级行为（402 快速失败 / 熔断 / 兜底文案）")
print("=" * 66)

from src.reviewer_common import is_fatal_llm_error, LLMClient  # noqa: E402

# --- D1：不可重试错误识别 ---
check("402 Payment Required → 判为不可重试",
      is_fatal_llm_error("HTTP Error 402: Payment Required"))
check("401 Unauthorized → 判为不可重试",
      is_fatal_llm_error("HTTP Error 401: Unauthorized"))
check("余额/额度字样 → 判为不可重试", is_fatal_llm_error("账户余额不足"))
check("网络超时 → 不判为不可重试（应重试）",
      not is_fatal_llm_error("Read timed out"))

# --- D2：LLMClient.ask 遇到 402 必须快速失败（不重试、不退避） ---
_calls = {"n": 0}
_orig_call_api = LLMClient._call_api


def _fail_api(self, *a, **k):
    _calls["n"] += 1
    raise RuntimeError("HTTP Error 402: Payment Required")


import time as _time_mod  # noqa: E402
_slept = {"n": 0}
_orig_sleep = _time_mod.sleep
_time_mod.sleep = lambda *a, **k: _slept.__setitem__("n", _slept["n"] + 1)
LLMClient._call_api = _fail_api
try:
    _cli = LLMClient(api_key="sk-test")
    _r = _cli.ask("测试")
finally:
    LLMClient._call_api = _orig_call_api
    _time_mod.sleep = _orig_sleep

check("★402 只尝试 1 次（不重试）", _calls["n"] == 1, f"尝试 {_calls['n']} 次")
check("★402 不退避等待（旧行为白等 9 秒）", _slept["n"] == 0, f"sleep {_slept['n']} 次")
check("返回体标明调用失败", "LLM 调用失败" in _r, _r[:60])

# --- D3：收集器熔断（LLM 持续 402 → 不逐题空转） ---
QuestionCollector._llm_knowledge = _ORIG_LLM_KNOWLEDGE


class DeadLLM:
    """始终返回 402 失败体的伪 LLM。"""

    def __init__(self):
        self.calls = 0

    def ask(self, prompt):
        self.calls += 1
        return "[LLM 调用失败] HTTP Error 402: Payment Required（第1次尝试）"


_c2 = QuestionCollector(module="巧记单词", version="湘少版",
                        grade="六年级上册", save_root=os.path.join(_tmp, "dead"))
_c2._llm = DeadLLM()
for i in range(1, 11):
    _c2.add(qno=i, level=i, qtype="巧记单词", stem=f"听录音，选出第{i}题的正确释义。",
            options=["A. new", "B. old"], answer="A", unit=1, allow_listen=True)
check("D3 前置：10 题都已收集（听音题需 allow_listen=True）",
      len(_c2.questions) == 10, f"实际 {len(_c2.questions)} 题")
for _q in _c2.questions:
    _q["knowledge"] = _c2._llm_knowledge(_q)

check("★LLM 绝不可用 → 触发熔断（不逐题空转）", _c2._llm_disabled)
check("★10 题只调用有限次（熔断生效，非 10×2=20 次）", _c2._llm.calls <= 8,
      f"实际调用 {_c2._llm.calls} 次")
check("熔断后仍能给每题兜底知识点（不留空）",
      all((q.get("knowledge") or "").strip() for q in _c2.questions))

# --- D4：兜底文案不得出现被禁的含糊表达 ---
_banned = ("涉及", "相关知识点", "基础知识点")
_k_with_ans = _c2._auto_knowledge(
    {"stem": "选释义", "options": ["A. new", "B. old"], "answer": "A"})
check("★兜底不再输出『涉及XX相关知识点』套话",
      not any(b in _k_with_ans for b in _banned), _k_with_ans[:60])
check("能确定答案时给出具体内容", "new" in _k_with_ans, _k_with_ans[:60])
_k_no_ans = _c2._auto_knowledge({"stem": "听录音，跟读单词。", "options": [], "answer": ""})
check("★无法生成时明确标注『待人工补充』（不拿套话充数）",
      "待人工补充" in _k_no_ans, _k_no_ans[:70])
check("待补充提示含原因/处理方式（便于排查）",
      "LLM" in _k_no_ans, _k_no_ans[:70])

# ★ 听音选释义：应把"听到的词"和"正确释义"组合成有用知识点
_k_spk = _c2._auto_knowledge(
    {"stem": "听录音，选择与录音内容相符的释义。", "options": ["A. 漂亮的"],
     "answer": "A", "speaker_word": "new"})
check("★听音题兜底组合出『词 → 释义』（比只给答案更有解释力）",
      "new" in _k_spk and "漂亮的" in _k_spk, _k_spk[:70])
_k_letter = _c2._auto_knowledge(
    {"stem": "选字母补全", "options": [], "answer": "ew"})
check("答案非字母选项时原样给出", "ew" in _k_letter, _k_letter[:60])

print()
print("=" * 66)
print("测试组 E · 两供应商同时不可用：ask() 不得抛异常")
print("=" * 66)


def _fail_all(self, *a, **k):
    raise RuntimeError("HTTP Error 402: Payment Required")


LLMClient._call_api = _fail_all
try:
    _cli2 = LLMClient(api_key="sk-a", vision_api_key="sk-b", vision_model="qwen-x")
    # 视觉路径 + 全失败（旧代码：末次降级裸调用 → 抛 HTTPError）
    try:
        _rv = _cli2.ask("描述截图", image_path="whatever.png")
        _raised = None
    except Exception as _ex:  # noqa: BLE001
        _rv, _raised = "", _ex
    # 纯文本路径 + 全失败
    try:
        _rt = _cli2.ask("纯文本")
        _raised_t = None
    except Exception as _ex:  # noqa: BLE001
        _rt, _raised_t = "", _ex
finally:
    LLMClient._call_api = _orig_call_api

check("★视觉路径全失败 → 不抛异常（旧行为会抛 HTTPError 崩调用方）", _raised is None,
      f"异常: {type(_raised).__name__}" if _raised else "")
check("★返回体带 [LLM 不可用] 标记（上层可识别为模型故障而非核查结论）",
      "[LLM 不可用]" in str(_rv), str(_rv)[:80])
check("提示同时给出两个供应商的错误（便于定位）",
      "视觉模型" in str(_rv) and "文本模型" in str(_rv))
check("★纯文本路径全失败 → 不抛异常", _raised_t is None)
check("纯文本失败体标明调用失败", "LLM" in str(_rt), str(_rt)[:60])

shutil.rmtree(_tmp, ignore_errors=True)

print()
print("=" * 66)
print(f"结果: {len(PASS)} 通过 / {len(FAIL)} 失败")
if FAIL:
    print("失败用例:")
    for f in FAIL:
        print("   -", f)
print("=" * 66)
sys.exit(1 if FAIL else 0)
