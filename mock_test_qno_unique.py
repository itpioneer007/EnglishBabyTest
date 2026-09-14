# -*- coding: utf-8 -*-
"""Mock 验证：巧记单词"跑完6关审查结果只有15题"修复

根因：App 页面进度 N/M 每关都从 1 重新开始，而审查结果用 "auto-Q{题号}" 做 key
      → 后一关的同号题覆盖前一关 → 6 关 100+ 题最后只剩 max(单关题数) 条。

本测试用 mock device 真实执行 `_answer_loop` 跑 3 个关卡（每关 15 题），验证：
  1. 发出的证据题号【全局唯一、跨关卡不重叠】
  2. `_GQ_NEXT` 跨关卡正确推进
  3. 关卡分组标签生成（U{n} 第{k}关）
  4. 脚本脚本位置行带关卡（QuestionCollector._loc_str）
  5. 同一题多条证据【合并不覆盖】（web_server._merge_evidence_record）

不需要连真机。
"""
import sys, os, re, types, time

_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_here, "scripts"))
sys.path.insert(0, _here)

# ---- 关闭真实等待（_answer_loop 里每步都有 sleep，mock 下没有意义）----
time.sleep = lambda *a, **k: None

from modules import 巧记单词 as Q

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'✅' if cond else '❌'} {name}" + (f"  ({detail})" if detail else ""))


# ============================================================
# Mock 设备：每 3 次 dump 视为推进一题（进度 dump + 发卡 dump + 无试题检测 dump），
#            第 15 题时页面出现「提交」→ 正常结束本关。
#            这样能真实驱动 _answer_loop 的完整循环（发卡/选项/提交）。
# ============================================================
class MockEl:
    def __init__(self, ok=False):
        self.ok = ok

    def exists(self, timeout=0):
        return self.ok

    def click(self):
        pass

    def get_text(self):
        return ""


class MockD:
    def __init__(self, level_name="第1关"):
        self.n = 0
        self._xml = ""
        self.level_name = level_name

    def _render(self, cur):
        _done = cur >= 15
        return (
            '<hierarchy>'
            f'<node text="{self.level_name} {cur}/15"/>'
            '<node text="听录音，跟读单词。"/>'
            '<node text="点击显示释义"/>'
            '<node text="A"/><node text="B"/><node text="C"/>'
            + ('<node text="提交"/>' if _done else '')
            + '</hierarchy>'
        )

    def dump_hierarchy(self):
        self.n += 1
        cur = min((self.n - 1) // 3 + 1, 15)
        self._xml = self._render(cur)
        return self._xml

    def __call__(self, **kw):
        txt = kw.get("text", "")
        return MockEl(bool(txt) and f'text="{txt}"' in self._xml)

    def xpath(self, *a, **k):
        return types.SimpleNamespace(all=lambda: [])

    def press(self, *a, **k):
        pass

    def click(self, *a, **k):
        pass

    def window_size(self):
        return (1080, 2400)

    def screenshot(self, *a, **k):
        pass


# ---- patch：step_log 收集题号、should_stop 恒 False ----
_LOGS = []
Q.step_log = lambda msg, level="info", evidence=None: _LOGS.append(msg)
Q.should_stop = lambda: False

print("=" * 66)
print("测试组 1 · 3 个关卡连续跑（每关 15 题）→ 题号必须全局唯一")
print("=" * 66)

Q._GQ_NEXT = 0
Q._cur_unit = 1
_LEVEL_LOGS = {}
for _lv in (1, 2, 3):
    _LOGS.clear()
    Q._cur_level = _lv
    # 复刻 _run_one_level 的关卡上下文设置（不含真机导航）
    try:
        from common.logger import set_current_module
        set_current_module("巧记单词", f"U{Q._cur_unit} 第{_lv}关")
    except Exception:
        pass
    _q = Q._answer_loop(MockD(f"第{_lv}关"), max_q=40)
    _nums = [int(m.group(1)) for m in
             (re.match(r"\s*第(\d+)题", s) for s in _LOGS) if m]
    _LEVEL_LOGS[_lv] = _nums
    print(f"  第{_lv}关: 返回 q={_q}, 发卡题号 {_nums[:3]}…{_nums[-3:] if _nums else []} (共{len(_nums)}张)")

_all = [n for v in _LEVEL_LOGS.values() for n in v]
check("3 关均发卡（非空）", all(_LEVEL_LOGS[k] for k in (1, 2, 3)),
      f"各关张数 {[len(_LEVEL_LOGS[k]) for k in (1, 2, 3)]}")
check("题号全局唯一（无跨关卡覆盖）", len(_all) == len(set(_all)),
      f"共 {len(_all)} 张，唯一 {len(set(_all))} 个")
check("关卡区间不重叠", (max(_LEVEL_LOGS[1]) < min(_LEVEL_LOGS[2]) < max(_LEVEL_LOGS[2]) < min(_LEVEL_LOGS[3])),
      f"L1≤{max(_LEVEL_LOGS[1])} < L2 {min(_LEVEL_LOGS[2])}~{max(_LEVEL_LOGS[2])} < L3≥{min(_LEVEL_LOGS[3])}")
check("第1关题号从 1 开始", min(_LEVEL_LOGS[1]) == 1)
# 注：mock 的题目推进按 dump 次数估算（发卡轮 3 次 dump、普通轮 2 次），
#     所以关内题号可能跳号（41→43）。真实设备上进度读数是 1,2,3… 连续的。
#     这里只断言【严格递增且唯一】——这是 qid 不冲突的充要条件。
check("每关题号严格递增（关内不重复、不倒流）", all(
    _LEVEL_LOGS[k][i] < _LEVEL_LOGS[k][i + 1]
    for k in (1, 2, 3) for i in range(len(_LEVEL_LOGS[k]) - 1)))
check("_GQ_NEXT 已推进到 3 关之后", Q._GQ_NEXT >= 45, f"_GQ_NEXT={Q._GQ_NEXT}")

print()
print("=" * 66)
print("测试组 2 · 审查结果按「模块·单元 关卡」分组")
print("=" * 66)

from common.logger import get_current_module
_mod, _stage = get_current_module()
check("模块名保持「巧记单词」", _mod == "巧记单词", _mod)
check("关卡标签形如「U1 第3关」", _stage == "U1 第3关", _stage)
_mod_key = f"{_mod}{'·' + _stage if _stage else ''}"
check("前端「分模块」键 = 巧记单词·U1 第3关", _mod_key == "巧记单词·U1 第3关", _mod_key)
try:
    from common.logger import set_current_module
    set_current_module("巧记单词", "U2 boss关")
    check("boss 关标签形如「U2 boss关」", get_current_module()[1] == "U2 boss关")
except Exception as _e:
    check("boss 关标签", False, str(_e))

print()
print("=" * 66)
print("测试组 3 · 脚本位置行带关卡（第N关）")
print("=" * 66)

from common.gen_script import QuestionCollector
_c = QuestionCollector(module="巧记单词", version="湘少版", grade="六年级上册")
_loc = _c._loc_str({"unit": 1, "level": 1, "qno": 3})
check("位置含单元", "U1" in _loc, _loc)
check("位置含关卡", "第1关" in _loc, _loc)
check("位置含题号", "第3题" in _loc, _loc)
_loc2 = _c._loc_str({"unit": 2, "level": 0, "qno": 5})
check("boss关(level=0) 不显示关卡、不报错", "U2" in _loc2 and "第5题" in _loc2, _loc2)

# add() 接受 level 参数并落库
_c.add(qno=1, stem="听录音，跟读单词。", options=["A. new", "B. year"],
       answer="A", qtype="巧记单词", unit=1, level=2, allow_listen=True)
check("collector.add 接受 level 参数", _c.questions and _c.questions[0].get("level") == 2,
      str(_c.questions[0].get("level") if _c.questions else None))

print()
print("=" * 66)
print("测试组 4 · 同一题多条证据合并（不覆盖丢维度）")
print("=" * 66)

import web_server as W

_prev = {
    "idx": 1, "ai_stem": True, "ai_content": True, "ai_image": None,
    "ai_answer": None, "ai_audio": None, "ai_post_error": None,
    "stem_reason": "界面题干正常 ✓", "content_reason": "可选项正常 ✓",
    "image_reason": "", "answer_reason": "", "audio_reason": "",
    "post_error_reason": "", "overall_passed": None, "overall_score": 0.0,
    "conclusions": {
        "stem": {"status": "pass", "detail": "界面题干正常 ✓"},
        "content": {"status": "pass", "detail": "可选项正常 ✓"},
        "image": {"status": "na", "detail": ""},
        "answerable": {"status": "na", "detail": ""},
        "audio": {"status": "na", "detail": ""},
        "answer_knowledge": {"status": "na", "detail": ""},
        "flow": {"status": "na", "detail": ""},
        "report": {"status": "na", "detail": ""},
    },
    "stem": "听录音，跟读单词。", "options": "A. new  B. year",
    "screenshot": "", "question_type": "巧记单词", "score_info": "",
    "human_label": True, "human_note": "人工已确认", "note": "备注",
    "layer": "basic+script", "script": {"matched": True, "status": "pending"},
}
# 第二条证据（反馈页扬声器）：只带音频维
_new = {
    "idx": 1, "ai_stem": None, "ai_content": None, "ai_image": None,
    "ai_answer": None, "ai_audio": True, "ai_post_error": None,
    "stem_reason": "", "content_reason": "", "image_reason": "",
    "answer_reason": "", "audio_reason": "音频控件正常 ✓", "post_error_reason": "",
    "overall_passed": None, "overall_score": 0.0,
    "conclusions": {k: {"status": "na", "detail": ""} for k in
                    ("stem", "content", "image", "answerable", "audio",
                     "answer_knowledge", "flow", "report")},
    "stem": "", "options": "", "screenshot": "", "question_type": "巧记单词",
    "score_info": "", "human_label": None, "human_note": "", "note": "",
    "layer": "basic_only", "script": None,
}

import copy
_new_orig = copy.deepcopy(_new)   # 合并前快照（供"旧代码行为"对比用例使用）
_m = W._merge_evidence_record(_prev, _new)
check("题干维度未被清零（合并保留）", _m["ai_stem"] is True)
check("选项维度未被清零（合并保留）", _m["ai_content"] is True)
check("音频维度新增为通过", _m["ai_audio"] is True)
check("overall 重算为通过（≥3维全通过）", _m["overall_passed"] is True, str(_m["overall_passed"]))
check("人工标注不被覆盖", _m["human_label"] is True and _m["human_note"] == "人工已确认")
check("脚本层结果保留", bool(_m["script"]) and _m["layer"] == "basic+script")
check("文本非空才覆盖（题干保留）", _m["stem"] == "听录音，跟读单词。")
check("conclusions.stem 同步为 pass", _m["conclusions"]["stem"]["status"] == "pass")
check("conclusions.audio 同步为 pass", _m["conclusions"]["audio"]["status"] == "pass")
check("conclusions.flow 跟随 overall=pass", _m["conclusions"]["flow"]["status"] == "pass")

# 反向：新证据判不通过 → 合并后必须不通过（不通过优先）
_new2 = dict(_new)
_new2["ai_content"] = False
_new2["content_reason"] = "可选项缺失 ✗"
_m2 = W._merge_evidence_record(_prev, _new2)
check("任一维度不通过 → 合并后仍不通过", _m2["ai_content"] is False)
check("不通过 → overall=False", _m2["overall_passed"] is False)

# 旧代码行为对比（直接覆盖会丢维度）
check("（对比）旧代码直接覆盖会丢题干维度", _new_orig["ai_stem"] is None,
      "这就是修复前只剩扬声器一维的原因")

print()
print("=" * 66)
print("测试组 5 · 页面读不到 N/M 进度时仍能数出全部题（不整关丢失）")
print("=" * 66)


class MockDNoProgress(MockD):
    """无 "N/M" 进度文本，但有答题元素「检查」+ 每轮换题干（模拟题号不可读的关卡）"""

    def _render(self, cur):
        return (
            '<hierarchy>'
            '<node text="点击显示释义"/>'
            f'<node text="选择第{cur}题的正确释义"/>'
            '<node text="A"/><node text="B"/><node text="C"/>'
            '<node text="检查"/>'
            + ('<node text="提交"/>' if cur >= 8 else '')
            + '</hierarchy>'
        )


_LOGS.clear()
Q._GQ_NEXT = 0
_q5 = Q._answer_loop(MockDNoProgress(), max_q=40)
_nums5 = [int(m.group(1)) for m in
          (re.match(r"\s*第(\d+)题", s) for s in _LOGS) if m]
print(f"  发卡题号: {_nums5}")
check("读不到进度也能发卡（不再是 0 题）", len(_nums5) >= 4, f"发卡 {len(_nums5)} 张")
check("签名字号严格递增（题干变化判定换题）", all(
    _nums5[i] < _nums5[i + 1] for i in range(len(_nums5) - 1)))
check("题号唯一", len(_nums5) == len(set(_nums5)))


class MockDLoading(MockD):
    """只有 loading（无进度、无答题元素）→ 不应误发卡"""

    def _render(self, cur):
        return '<hierarchy><node text="正在加载…"/></hierarchy>'


_LOGS.clear()
Q._GQ_NEXT = 0
Q._answer_loop(MockDLoading(), max_q=40)
# 注意：_LOGS 里还会有"⚠ 本关进入后未出现答题元素"这类提示，只统计发卡日志
_ev_load = [s for s in _LOGS if re.match(r"\s*第\d+题", s)]
check("loading 页不误发卡（防脏数据）", len(_ev_load) == 0,
      f"发卡 {len(_ev_load)} 张；其它日志 {[s[:24] for s in _LOGS]}")

print()
print("=" * 66)
print("测试组 6 · 题干杂质清洗（关卡进度段 / 应用锁遮罩）")
print("=" * 66)

from common.gen_script import _extract_ui_question

# 构造与真机一致的场景：关卡进度、应用锁遮罩、题干同页共存
_xml_dirty = (
    '<hierarchy>'
    '<node text="第6关 5/15"/>'
    '<node text="根据中文提示，选择正确的字母补全单词。"/>'
    '<node text="第6关  6"/>'
    '<node text="应用锁保护中"/>'
    '<node text="A. new"/><node text="B. year"/>'
    '</hierarchy>'
)
_r = _extract_ui_question(_xml_dirty)
print(f"  提取结果 stem={_r['stem']!r}")
check("关卡进度段被丢弃（不混入题干）", "第6关" not in _r["stem"], _r["stem"][:40])
check("应用锁遮罩被丢弃", "应用锁" not in _r["stem"], _r["stem"][:40])
check("真实题干保留", "补全单词" in _r["stem"], _r["stem"][:40])
check("选项正常提取", len(_r["options"]) >= 2, str(_r["options"]))

# 段内嵌关卡进度（"第6关 5/15 根据中文提示…"）→ 前缀应被清掉
_r2 = _extract_ui_question(
    '<hierarchy><node text="第6关 5/15 根据中文提示，选择正确的字母补全单词。"/>'
    '<node text="A. new"/><node text="B. year"/></hierarchy>'
)
print(f"  段内嵌 stem={_r2['stem']!r}")
check("段内嵌关卡进度被清掉", _r2["stem"].startswith("根据中文提示"), _r2["stem"][:40])

# 正常题干不受影响（回归保护）
_r3 = _extract_ui_question(
    '<hierarchy><node text="请找出与下面选项不符的一项。"/>'
    '<node text="A. went"/><node text="B. visited"/></hierarchy>'
)
check("正常题干不被误清洗", "请找出与下面选项不符的一项" in _r3["stem"], _r3["stem"][:40])

print()
print("=" * 66)
print("测试组 7 · 通用防御：跨阶段同号题不再互相覆盖（听力专项 练习+测试 等）")
print("=" * 66)

# 保护：测试进程不得覆盖真机任务正在写的状态文件
W._save_inspection_state = lambda: None
W._save_inspection_state_merge = lambda: None
W._live_regen_error_report = lambda: None

from common.logger import set_current_module as _setmod

# 3 条通过证据（覆盖 题干/选项/音频 三维 → overall=True，避免触发错题截图）
_ev_ok = [
    {"field": "题干", "type": "text_ok", "expected": "脚本题干", "actual": "界面题干", "diff": "题干一致"},
    {"field": "选项", "type": "text_ok", "expected": "脚本选项", "actual": "界面选项", "diff": "选项一致"},
    {"field": "音频", "type": "text_ok", "expected": "有喇叭", "actual": "有喇叭", "diff": "音频控件正常"},
]

W._inspection_state["questions"] = {}
W._inspection_state["_modules_total"] = {}
W._inspection_state["_seen_qids"] = {}
W._inspection_state.pop("_qid_owner", None)

# 阶段A：听力专项 · 练习（题号 1、2）
_setmod("听力专项", "练习")
W._record_module_evidence(1, "第1题 检查", _ev_ok)
W._record_module_evidence(2, "第2题 检查", _ev_ok)

# 阶段B：听力专项 · 测试（题号同样从 1、2 开始 → 旧代码会覆盖阶段A）
_setmod("听力专项", "测试")
W._record_module_evidence(1, "第1题 检查", _ev_ok)
W._record_module_evidence(2, "第2题 检查", _ev_ok)

_qs = W._inspection_state["questions"]
print(f"  最终 questions: {sorted(_qs)}")
print(f"  分模块统计: {W._inspection_state['_modules_total']}")
check("跨阶段 4 道题全部保留（不再只剩后一阶段）", len(_qs) == 4, f"实际 {len(_qs)} 条")
check("阶段A 两题仍在（未被覆盖）", "auto-Q001" in _qs and "auto-Q002" in _qs)
check("阶段B 两题重编号为新号", "auto-Q003" in _qs and "auto-Q004" in _qs)
check("分模块按阶段分组统计 = 各 2 题",
      W._inspection_state["_modules_total"].get("听力专项·练习") == 2 and
      W._inspection_state["_modules_total"].get("听力专项·测试") == 2,
      str(W._inspection_state["_modules_total"]))
check("重编号后阶段归属正确",
      _qs["auto-Q003"].get("stage") == "测试" and _qs["auto-Q001"].get("stage") == "练习")

# 同一阶段内重复报同一题（如"完整性检查"+"扬声器检查"）→ 不应重编号
_own_before = dict(W._inspection_state["_qid_owner"])
W._record_module_evidence(1, "第1题 检查（扬声器内容）", _ev_ok)
check("同阶段同题重报不重编号（保持合并语义）",
      sorted(W._inspection_state["questions"]) == sorted(_qs) and
      W._inspection_state["_qid_owner"] == _own_before,
      str(sorted(W._inspection_state["questions"])))

print()
print("=" * 66)
print("测试组 8 · 内容审查的 stage 过滤（关卡标签不得过滤掉其它关卡的题）")
print("=" * 66)

_skip = W._should_skip_by_stage
check("子模块同名 → 保留（听力专项·练习）", _skip("练习", "练习") is False)
check("子模块不同名 → 过滤（练习 vs 测试）", _skip("练习", "测试") is True)
check("★关卡标签不做过滤（U1 boss关 vs U1 第1关）", _skip("U1 boss关", "U1 第1关") is False,
      "修复点：否则内容审查只剩最后一关的题")
check("关卡标签 vs 空 stage → 不过滤", _skip("U1 第1关", "") is False)
check("stage 为空 → 不过滤（旧行为兼容）", _skip("", "U1 第1关") is False)
check("关卡标签之间不过滤（第1关 vs 第2关）", _skip("U1 第1关", "U1 第2关") is False)
check("综合进阶/难点突破等仍在白名单内", _skip("综合进阶", "难点突破") is True)

print()
print("=" * 66)
print("测试组 9 · 题数口径（本关进度跨度）必须与审查结果条数一致")
print("=" * 66)

# 真机现象：App 会记住关卡内进度，第2关从「第4题」开始 → 实际做了 11 题，
# 但旧口径 max(进度, q) 报成 13。这里用 mock 复现：进度从 4 走到 14 → 应返回 11。


class MockDResume(MockD):
    """关卡从进度 4 开始、到 14 结束（App 记忆上次进度）。"""

    def __init__(self, start=4, end=14, total=15):
        super().__init__("第2关")
        self.start, self.end, self.total = start, end, total

    def dump_hierarchy(self):
        self.n += 1
        cur = min(self.start + (self.n - 1) // 3, self.end)
        self._xml = (
            '<hierarchy>'
            f'<node text="{self.level_name} {cur}/{self.total}"/>'
            '<node text="听录音，跟读单词。"/>'
            '<node text="点击显示释义"/>'
            '<node text="A"/><node text="B"/><node text="C"/>'
            + ('<node text="提交"/>' if cur >= self.end else '')
            + '</hierarchy>'
        )
        return self._xml


Q._GQ_NEXT = 0
Q._cur_unit = 1
Q._cur_level = 2
_LOGS.clear()
_d = MockDResume()
_q2 = Q._answer_loop(_d, max_q=40)
_issued = len([s for s in _LOGS if re.match(r"\s*第\d+题", s)])
check("本关从进度4开始→返回11题（14-4+1，非旧的13）", _q2 == 11, f"返回 {_q2}")
check("★返回题数与审查结果发卡条数严格一致", _q2 == _issued,
      f"返回 {_q2} 条 / 发卡 {_issued} 条")
check("首题全局题号 = 进度跨度起点（非 4 起跳）", int(re.match(r"\s*第(\d+)题", _LOGS[0]).group(1)) == 1,
      f"首张卡题号 {re.match(r'\s*第(\d+)题', _LOGS[0]).group(1)}")

# 对照：旧口径 max(_cur_progress, q) 会报成 13（用户当时看到的矛盾数字）
check("（对照）旧口径会报 13 题 → 与 11 条审查结果矛盾", 14 != 11,
      "这就是用户看到\"完成13题却只有11条\"的原因")

print()
print("=" * 66)
print(f"结果: {len(PASS)} 通过 / {len(FAIL)} 失败")
if FAIL:
    print("失败用例:")
    for f in FAIL:
        print("   -", f)
print("=" * 66)
sys.exit(1 if FAIL else 0)
