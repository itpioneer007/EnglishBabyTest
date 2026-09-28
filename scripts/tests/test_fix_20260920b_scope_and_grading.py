# -*- coding: utf-8 -*-
"""2026-09-20(晚) 修复回归：脚本范围收敛 + 判定分级 + 篇章语法检查。

用户四条反馈的对应回归：
  ① 跑教科六上 U6 却匹配到「口语训练新教科五上U4-7」→ 把没测的 U4/U7 错误写进日志
     → _script_matches_run 版本/年级守卫 + _filter_issues_by_unit 单元过滤
  ② "有一点不符就判不通过不太好，要真能找出影响用户作答的内容"
     → _text_diff_minor：仅标点/大小写/空格/全半角差异 = 格式差异，不判不通过；
       字母级差异（nose/note、take/bring）仍判不通过
  ③ 篇章语法检查 _check_passage_grammar：NONE→零输出；JSON→结构化条目；
       同一段短文去重；LLM 异常不炸
"""
import os
import sys
import types

_PR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _PR)

import web_server as W  # noqa: E402

_n_pass = 0
_n_fail = 0


def chk(name, cond, extra=""):
    global _n_pass, _n_fail
    ok = bool(cond)
    print(("PASS  " if ok else "FAIL  ") + name + (f"  {extra}" if extra and not ok else ""))
    if ok:
        _n_pass += 1
    else:
        _n_fail += 1


# ---------- ① 版本/年级守卫 ----------
print("== _script_matches_run ==")
chk("六上运行 + 五上脚本 → 拦截",
    W._script_matches_run("260727口语训练新教科五上U4-7（已二校）.docx",
                          "教科版(2024审定)", "六年级上册") != "")
chk("六上运行 + 六上脚本 → 放行",
    W._script_matches_run("260801口语训练教科六上U6.docx",
                          "教科版(2024审定)", "六年级上册") == "")
chk("湘少运行 + 教科脚本 → 拦截（版本不符）",
    W._script_matches_run("口语训练教科五上U2.docx",
                          "湘少版(2024审定)", "五年级上册") != "")
chk("文件名无任何版本/年级关键词 → 放行（无法判断不误杀）",
    W._script_matches_run("口语训练U6.docx", "", "") == "")
chk("版本为空、年级命中 → 仍按年级拦",
    W._script_matches_run("单元自检四上U1.docx", "", "五年级上册") != "")

# ---------- ① 单元过滤 ----------
print("== _filter_issues_by_unit ==")
W._inspection_state["unit"] = "6"
_issues = [
    {"severity": "高", "type": "答案与关键词不一致", "location": "U4 第4大题 第3小题"},
    {"severity": "中", "type": "知识点为占位符", "location": "U7 第4大题"},
    {"severity": "中", "type": "字段名不统一", "location": "全文"},
    {"severity": "高", "type": "篇章语法错误", "location": "U6 第2大题"},
]
kept = W._filter_issues_by_unit(_issues)
locs = [i["location"] for i in kept]
chk("U4 的问题被过滤", all("U4" not in l for l in locs), str(locs))
chk("U7 的问题被过滤", all("U7" not in l for l in locs), str(locs))
chk("U6 的问题保留", any("U6" in l for l in locs), str(locs))
chk("全文类问题保留（影响在跑单元）", any("全文" in l for l in locs), str(locs))
W._inspection_state["unit"] = "2-4"
chk("单元范围 2-4：U2/U4 保留、U6 过滤",
    [i["location"] for i in W._filter_issues_by_unit([
        {"location": "U2 第1大题"}, {"location": "U6 第1大题"},
        {"location": "U4 第3大题"}])] == ["U2 第1大题", "U4 第3大题"])
W._inspection_state["unit"] = ""

# ---------- ② 格式差异 vs 实质差异 ----------
print("== _text_diff_minor ==")
chk("仅标点差异 → minor", W._text_diff_minor("Hello, world.", "Hello world"))
chk("仅大小写差异 → minor", W._text_diff_minor("Mum Moon", "mum moon"))
chk("仅空格/换行差异 → minor", W._text_diff_minor("mum  moon\n", "mum moon"))
chk("仅全半角标点差异 → minor", W._text_diff_minor("What will come tomorrow?", "What will come tomorrow？"))
chk("字母级差异 nose/nate vs nose/note → 实质（不通过）",
    not W._text_diff_minor("nose nate", "nose note"))
chk("字母级差异 take/bring → 实质（不通过）",
    not W._text_diff_minor("take their raincoats", "bring their raincoats"))
chk("多词缺失 → 实质", not W._text_diff_minor("mum moon", "mum moon nut net"))

# ---------- ③ 篇章语法检查 ----------
print("== _check_passage_grammar ==")


class _Q:
    def __init__(self, passage="", big=2):
        self.passage = passage
        self.big = big


class _StubLLM:
    """按调用序返回预设答案；记录 prompt 供断言。"""

    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts = []

    def ask(self, prompt, **kw):
        self.prompts.append(prompt)
        return self.replies.pop(0) if self.replies else "NONE"


class _StubAgent:
    def __init__(self, questions, llm):
        self.script_questions = questions
        self.llm = llm


_LONG = ("Class One did a survey about food waste at the school canteen. "
         "Some students take too much food because they feel hungry at noon. "
         "Some students are picky about food and leave vegetables.")

# 3a 无错误 → 零输出
llm = _StubLLM(["NONE"])
out = W._check_passage_grammar("口语训练", "6", _StubAgent([_Q(_LONG), _Q(_LONG)], llm))
chk("无错误(NONE) → 返回空列表", out == [])
chk("同一段短文只查一次（去重）", len(llm.prompts) == 1, f"调用 {len(llm.prompts)} 次")

# 3b 有错误 → 结构化条目
llm2 = _StubLLM(['[{"orig":"Some students take too much food",'
                 '"fix":"Some students took too much food",'
                 '"why":"全文过去时，take 应为 took"}]'])
out2 = W._check_passage_grammar("口语训练", "6", _StubAgent([_Q(_LONG), _Q(_LONG)], llm2))
chk("有错误 → 1 条结构化问题", len(out2) == 1, str(out2))
it = out2[0] if out2 else {}
chk("条目字段与 _script_issues 兼容",
    it.get("severity") == "高" and it.get("type") == "篇章语法错误"
    and it.get("location") == "U6 第2大题" and "took" in (it.get("issue") or ""),
    str(it))
chk("错误条目也去重（同一短文只报一次）", len(out2) == 1)

# 3c LLM 返回垃圾 → 不炸、零输出
llm3 = _StubLLM(["抱歉，我无法完成这个任务。"])
out3 = W._check_passage_grammar("口语训练", "6", _StubAgent([_Q(_LONG)], llm3))
chk("LLM 返回非 JSON → 空列表不炸", out3 == [])

# 3d 短文本（<40字）不算篇章 → 不调用 LLM
llm4 = _StubLLM([])
W._check_passage_grammar("口语训练", "6", _StubAgent([_Q("Read and say.")], llm4))
chk("短文本不触发篇章检查", len(llm4.prompts) == 0)

# 3e LLM 抛异常 → 捕获返回空（不炸上层审查）
class _BoomLLM:
    def ask(self, prompt, **kw):
        raise RuntimeError("network down")


out5 = W._check_passage_grammar("口语训练", "6", _StubAgent([_Q(_LONG)], _BoomLLM()))
chk("LLM 异常 → 返回空列表不炸", out5 == [])

# ---------- ④ run_module_api.auto_docx_map 四要素 ----------
print("== run_module_api.auto_docx_map ==")
import importlib.util as _iu  # noqa: E402
import glob as _globmod  # noqa: E402
_spec = _iu.spec_from_file_location(
    "rma", os.path.join(_PR, "tools", "run_module_api.py"))
rma = _iu.module_from_spec(_spec)
_spec.loader.exec_module(rma)

_tmpdir = os.path.join(_PR, "tmp_gen")
os.makedirs(_tmpdir, exist_ok=True)
_fake = []
for fn in ("260727口语训练新教科五上U4-7（已二校）.docx",
           "260801口语训练教科六上U6（已二校）.docx"):
    p = os.path.join(_tmpdir, fn)
    open(p, "a", encoding="utf-8").close()
    _fake.append(p)
# auto_docx_map 内部 `import glob` 拿到的是同一个模块对象 → 打桩生效
_orig_glob = _globmod.glob
_globmod.glob = lambda pat: list(_fake)
try:
    got = rma.auto_docx_map([{"name": "口语训练"}],
                            version="教科版(2024审定)", grade="六年级上册")
    chk("六上运行选中六上脚本（不是五上的）",
        got.get("口语训练", "").find("六上") >= 0, str(got))
    got2 = rma.auto_docx_map([{"name": "口语训练"}],
                             version="教科版(2024审定)", grade="五年级上册")
    chk("五上运行选中五上脚本", got2.get("口语训练", "").find("五上") >= 0, str(got2))
finally:
    _globmod.glob = _orig_glob
    for p in _fake:
        try:
            os.remove(p)
        except OSError:
            pass

print()
print(f"结果: {_n_pass} 通过 / {_n_fail} 失败")
sys.exit(1 if _n_fail else 0)
