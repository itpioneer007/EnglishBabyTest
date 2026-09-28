# -*- coding: utf-8 -*-
"""口语训练模块 mock 端到端验证（不连手机，用真机快照回归）

数据来源（真机 dump）：
  - _archive/debug_files/cur_home.xml  「朗读句子」大题2/4、请阅读题目7S 倒计时中（无麦克风）
  - _archive/debug_files/oral_q3.xml   「看图回答」大题3/4、小题已作答态（无麦克风）
  - mock：cur_home + 注入 record_btn（真实坐标 [425,1371][655,1652]，落在第2个 ll_container）

验证点：
  1. _find_active_sub_question：tv_sort "1/5" 解析小题号/总数；朗读句子题题干=speech_content；
     图片题题干="图片题"；已作答/分值不再污染题干
  2. collect_ui_evidence：题干=大题介绍(tv_caption)；口语题不把小题句子混进题干；
     有 record_btn 时 作答/麦克风 检测通过
  3. _answer_big_question 的"大题完成"按钮列表不再包含"下一题"（防提前切大题）
  4. _get_big_progress：正确读取 tv_question_sort "2/4"
"""
import os
import re
import sys
import types

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS = os.path.join(BASE, "scripts")
sys.path.insert(0, SCRIPTS)

# 不连手机：stub uiautomator2，模块内部 d 不会被真正调用
_u2 = types.ModuleType("uiautomator2")
sys.modules["uiautomator2"] = _u2

from common.evidence import collect_ui_evidence  # noqa: E402
from modules import 口语训练 as m                # noqa: E402


def load(name):
    with open(os.path.join(BASE, name), encoding="utf-8", errors="ignore") as f:
        return f.read()


def ev_line(e):
    return f"      [{e['field']}] {e['type']} actual={e.get('actual','')!r} diff={e.get('diff','')!r}"


PASS = []
FAIL = []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  ✅ " if cond else "  ❌ ") + name + (f"  —— {detail}" if detail and not cond else ""))


# ================= Test 1: cur_home（朗读句子 · 倒计时中 · 无麦克风） =================
print("\n== T1 cur_home.xml（朗读句子 2/4，倒计时中，无 record_btn） ==")
xml = load("_archive/debug_files/cur_home.xml")

sub_no, total, stem, box = m._find_active_sub_question(None, xml)
print(f"  _find_active_sub_question → sub_no={sub_no} total={total} stem={stem!r} box={box}")
check("T1.1 小题号解析 tv_sort '1/5' → sub_no=1", sub_no == 1, f"got {sub_no}")
check("T1.2 小题总数 total=5", total == 5, f"got {total}")
check("T1.3 小题题干 = speech_content 句子", stem == "I see a bee flying in the tree.", f"got {stem!r}")

ev = collect_ui_evidence(xml, qtype="口语训练")
for e in ev:
    print(ev_line(e))
cap = next((e["actual"] for e in ev if e["field"] == "题干"), "")
check("T1.4 题干 = 大题介绍(tv_caption)", "请大声朗读你看到的句子" in cap and "共15分" not in cap, f"got {cap!r}")
check("T1.5 题干不含小题句子", "I see a bee" not in cap, f"got {cap!r}")
no_ans = next((e for e in ev if e["field"] == "作答"), None)
check("T1.6 倒计时中未检测到麦克风（属正常，不算误报）", no_ans is not None and "未检测到麦克风" in no_ans.get("diff", ""), f"got {no_ans}")

# ================= Test 2: oral_q3（看图回答 · 已作答态 · 无麦克风） =================
print("\n== T2 oral_q3.xml（看图回答 3/4，已作答态，无 record_btn） ==")
xml2 = load("_archive/debug_files/oral_q3.xml")
sub_no2, total2, stem2, box2 = m._find_active_sub_question(None, xml2)
print(f"  _find_active_sub_question → sub_no={sub_no2} total={total2} stem={stem2!r} box={box2}")
check("T2.1 小题号解析 '1.' → sub_no=1", sub_no2 == 1, f"got {sub_no2}")
check("T2.2 图片题题干 = 图片题", stem2 == "图片题", f"got {stem2!r}")
check("T2.3 已作答/分值未污染题干", "已作答" not in stem2 and "分" not in stem2, f"got {stem2!r}")

ev2 = collect_ui_evidence(xml2, qtype="口语训练")
for e in ev2:
    print(ev_line(e))
cap2 = next((e["actual"] for e in ev2 if e["field"] == "题干"), "")
check("T2.4 题干 = 大题介绍(看图回答)", "看图回答" in cap2, f"got {cap2!r}")

# ================= Test 3: mock 倒计时结束 + record_btn（落在第2个小题） =================
print("\n== T3 mock：cur_home + 注入 record_btn [425,1371][655,1652]（第2小题作答中） ==")
mock = xml.replace('text="请阅读题目7S"', 'text=""')
record_node = ('<node index="9" text="" resource-id="com.dinoenglish.yyb:id/record_btn" '
               'class="android.widget.FrameLayout" package="com.dinoenglish.yyb" content-desc="" '
               'checkable="false" checked="false" clickable="true" enabled="true" focusable="false" '
               'focused="false" scrollable="false" long-clickable="false" password="false" '
               'selected="false" visible-to-user="true" bounds="[425,1371][655,1652]" drawing-order="2"/>')
mock = re.sub(r'<node[^>]*resource-id="com\.dinoenglish\.yyb:id/btn_box"[^>]*>',
              record_node + "\n" + r"\g<0>", mock, count=1)

pos = m._find_record_btn(None, mock)
check("T3.1 _find_record_btn 找到麦克风", pos is not None, f"got {pos}")
if pos:
    check("T3.2 麦克风中心坐标正确", pos == (540, 1511), f"got {pos}")

sub_no3, total3, stem3, box3 = m._find_active_sub_question(None, mock)
print(f"  _find_active_sub_question → sub_no={sub_no3} total={total3} stem={stem3!r} box={box3}")
check("T3.3 按 record_btn 位置选中第2小题 sub_no=2", sub_no3 == 2, f"got {sub_no3}")
check("T3.4 第2小题题干正确", stem3 == "I hurt my knee when I run fast.", f"got {stem3!r}")

ev3 = collect_ui_evidence(mock, qtype="口语训练")
for e in ev3:
    print(ev_line(e))
ans = next((e for e in ev3 if e["field"] == "作答"), None)
check("T3.5 有麦克风时作答检测通过", ans is not None and ans["type"] == "text_ok", f"got {ans}")
mic = next((e for e in ev3 if e["field"] == "作答" and "麦克风" in e.get("diff", "")), None)
if mic:
    check("T3.6 麦克风可点击", "可点击" in mic.get("diff", ""), f"got {mic}")

# ================= Test 4: 大题进度读取 =================
cur_big, tot_big = m._get_big_progress(xml)
print(f"\n== T4 _get_big_progress → current={cur_big} total={tot_big}")
check("T4.1 大题进度 2/4", (cur_big, tot_big) == (2, 4), f"got {cur_big}/{tot_big}")

# ================= Test 5: 大题完成按钮列表不含"下一题" =================
src = open(os.path.join(SCRIPTS, "modules", "口语训练.py"), encoding="utf-8").read()
big_done_line = re.search(r'for _btxt in \(([^)]*)\)', src)
if big_done_line:
    items = [x.strip().strip('"') for x in big_done_line.group(1).split(",")]
    print(f"\n== T5 大题完成按钮列表 = {items}")
    check("T5.1 不含'下一题'（防提前切大题）", "下一题" not in items, f"got {items}")
    # ★ 2026-08-24 重构：交卷从列表移除，改为"无录音按钮后"独立检测 + 点击后必须等"确定交卷"确认框
    #   （真机第4大题"交卷"按钮常驻，若放列表 → 答完1小题就点 → 被 Toast 拒绝 → 交卷不生效界面停住）
    check("T5.2 交卷独立分支+确认框验证",
          "交卷" not in items and 'd(text="交卷").exists(timeout=0.2)' in src
          and 'd(text="确定交卷")' in src,
          f"got {items}")

print("\n" + "=" * 40)
print(f"结果: {len(PASS)} 通过, {len(FAIL)} 失败")
if FAIL:
    print("失败项:")
    for f in FAIL:
        print("  -", f)
    sys.exit(1)
print("全部通过 ✅")
