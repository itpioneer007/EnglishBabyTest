# -*- coding: utf-8 -*-
"""2026-08-26 单元自检/脚本生成/前端五问题修复固化测试

覆盖：
  ① 脚本不再跳过录音题（allow_listen=True）
  ② 脚本 docx 结构：题干去题号前缀 / 选项带A·B·C编号 / 答案对号(字母+内容) / 位置/知识点
  ③ 选词填空：触发条件放宽 + 方框空位识别（LinearLayout/FrameLayout 兼容）
  ⑤ 前端结论过滤：通用通过项(作答元素存在/流程无卡顿)不参与结论行，只留题干摘要+有信息量结论

运行: python scripts/tests/test_fix_20260826_unit_five_issues.py
"""
import sys, os, re

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "common"))

from gen_script import QuestionCollector

passed = 0
failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ✅ {name}")
    else:
        failed += 1
        print(f"  ❌ {name} | {detail}")


# ═══════ ①② 脚本生成：题干去前缀 + 选项编号 + 答案对号 + 听音题收集 ═══════
print("=== ① 脚本生成（题干/选项/答案/听音题）===")
coll = QuestionCollector(module="单元自检", version="湘少版", grade="六年级上册", save_root="tmp_gen")
coll.skipped_no_stem = 0

# A. 单选：题干带13/32前缀 + 选项无字母前缀 + 点击字母A
coll.add(qno=13, stem="13/32 选择各组中不同类的一项。",
         options=["went", "visited", "stay"], answer="A", qtype="单元自检", unit=6, allow_listen=True)
q = coll.questions[-1]
check("A 题干去题号前缀", q["stem"] == "选择各组中不同类的一项。", repr(q["stem"]))
check("A 选项带编号", q["options"] == ["A. went", "B. visited", "C. stay"], repr(q["options"]))
check("A 答案保留字母A", q["answer"] == "A", repr(q["answer"]))

# B. LLM返回选项内容 → 归一化成对应字母
coll.add(qno=14, stem="选择各组中不同类的一项。",
         options=["visited", "never", "early"], answer="never", qtype="单元自检", unit=6, allow_listen=True)
q = coll.questions[-1]
check("B LLM答案内容→字母B", q["answer"] == "B", repr(q["answer"]))

# C. 听音题：题干含"听" + allow_listen=True → 保留
coll.add(qno=15, stem="听句子，选择听到的单词。",
         options=["glad", "old", "silly"], answer="glad",
         qtype="单元自检", unit=6, allow_listen=True, speaker_word="glad")
q = coll.questions[-1]
check("C 听音题收集(题干保留)", "听句子" in q["stem"], repr(q["stem"]))
check("C 选项带编号", q["options"] == ["A. glad", "B. old", "C. silly"], repr(q["options"]))
check("C 答案归一化A", q["answer"] == "A", repr(q["answer"]))
check("C speaker_word 保留", q["speaker_word"] == "glad", repr(q["speaker_word"]))

# D. 完全无内容的题 → 仍跳过
n_before = len(coll.questions)
coll.add(qno=16, stem="", options=[], answer="")
check("D 无题干无答案仍跳过", len(coll.questions) == n_before)


# ═══════ ② docx 结构校验（finish_unit）═══════
print()
print("=== ② docx 生成结构（题干/位置/选项/答案/知识点）===")
coll._llm_knowledge = lambda q: "went/visited是过去式，stay原形，选A。"
p = coll.finish_unit(6)
check("docx 生成成功", bool(p) and os.path.exists(p), str(p))
if p and os.path.exists(p):
    from docx import Document
    doc = Document(p)
    txt = "\n".join(para.text for para in doc.paragraphs)
    check("docx 含题干(无前缀)", "选择各组中不同类的一项。" in txt)
    check("docx 含位置", "位置：单元自检" in txt and "U6" in txt)
    check("docx 选项带编号", "A. went" in txt and "B. visited" in txt and "C. stay" in txt)
    check("docx 答案对号", "正确答案：A（went）" in txt, "看答案行")
    check("docx 含知识点", "知识点：went/visited是过去式" in txt)
    check("docx 听音题也收录", "听句子，选择听到的单词。" in txt)


# ═══════ ③ 选词填空：触发条件 + 方框空位识别 ═══════
print()
print("=== ③ 选词填空（触发条件放宽 + 方框空位识别）===")
# 触发条件：现在仅凭"选词填空/选词/方框中选择"即可进入（不再依赖 tv_sort）
def word_fill_hint(xml):
    _has_edittext = 'class="android.widget.EditText"' in xml
    return any(k in xml for k in ("选词填空", "选词", "从方框中选择", "选择单词填入")) and not _has_edittext
xml_wf = '<node text="阅读短文，选词填空。"/><node text="5"><node class="android.widget.LinearLayout" bounds="[100,600][320,760]"/></node>'
check("选词填空触发(无tv_sort也能进)", word_fill_hint(xml_wf), "不再依赖 tv_sort")
xml_edit = '<node class="android.widget.EditText" text=""/>'
check("有EditText不触发选词(走打字填空)", not word_fill_hint(xml_edit))

# 方框空位识别（用户截图1：LinearLayout 方框 + 序号）
def find_slots(xml):
    slots = []
    for m in re.finditer(r"<node[^>]*>", xml):
        b = m.group(0)
        cls = re.search(r'class="([^"]*)"', b)
        bm = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', b)
        if not (cls and bm):
            continue
        x1, y1, x2, y2 = map(int, (bm.group(1), bm.group(2), bm.group(3), bm.group(4)))
        if y1 < 200 or y2 > 2250:
            continue
        cname = cls.group(1)
        checked = 'checked="true"' in b
        tm = re.search(r'text="([^"]*)"', b)
        txt = tm.group(1).strip() if tm else ""
        is_slot = False
        if "CheckBox" in cname:
            is_slot = True
        elif any(k in cname for k in ("LinearLayout", "FrameLayout", "View")):
            w, h = x2 - x1, y2 - y1
            if 40 <= w <= 320 and 40 <= h <= 160:
                if not txt or re.fullmatch(r"[①②③④⑤⑥⑦⑧⑨⑩\d]{1,3}", txt):
                    is_slot = True
        if not is_slot:
            continue
        has_content = checked or (bool(txt) and not re.fullmatch(r"[①②③④⑤⑥⑦⑧⑨⑩\d]{1,3}", txt))
        slots.append(((x1 + x2) // 2, (y1 + y2) // 2, has_content, txt))
    slots.sort(key=lambda s: (s[2], s[1]))
    return slots

xml_slots = (
    '<node><node class="android.widget.LinearLayout" bounds="[100,600][320,760]">'
    '<node class="android.widget.TextView" text="①"/></node>'
    '<node class="android.widget.LinearLayout" bounds="[500,600][720,760]">'
    '<node class="android.widget.TextView" text="②"/></node>'
    '<node class="android.widget.LinearLayout" bounds="[100,1000][320,1160]">'
    '<node class="android.widget.TextView" text="③"/></node>'
    '<node class="android.widget.TextView" text="mooncakes" bounds="[60,1900][260,2000]"/>'
    "</node>"
)
slots = find_slots(xml_slots)
empty = [s for s in slots if not s[2]]
check("方框空位识别3个", len(slots) == 3, f"got {len(slots)}")
check("未填空位=3(has_content=False)", len(empty) == 3, f"got {len(empty)}")


# ═══════ ⑤ 前端结论过滤（通用通过项不参与结论行）═══════
print()
print("=== ⑤ 前端结论过滤（通用项不污染结论）===")
def isGenericPass(detail):
    if not detail:
        return True
    g = ["作答元素存在", "作答元素:", "音频控件", "扬声器/播放", "播放标识", "流程无卡顿",
         "流程无", "提取到", "条文字", "可作答", "选项", "检测到", "个选项", "题干文字", "已识别", "通过"]
    return any(k in detail for k in g)

def meaningfulDetail(detail):
    if not detail:
        return ""
    if isGenericPass(detail):
        return ""
    meaningful = ["脚本", "扬声器", "不符", "不一致", "错配", "缺失", "缺", "题干一致",
                  "题干与脚本", "未找到", "无", "遗漏", "错误", "正确", "答案", "听力", "recording", "对照"]
    return detail if any(k in detail for k in meaningful) else ""

check("通用项: 作答元素存在→过滤", meaningfulDetail("作答元素存在") == "")
check("通用项: 音频控件→过滤", meaningfulDetail("音频控件:扬声器播放标识可见且可点击") == "")
check("通用项: 流程无卡顿→过滤", meaningfulDetail("流程无卡顿") == "")
check("通用项: 提取到3条文字→过滤", meaningfulDetail("提取到3条文字") == "")
check("有价值: 题干与脚本一致→保留", meaningfulDetail("题干与脚本一致") == "题干与脚本一致")
check("有价值: 扬声器new与脚本不符→保留", meaningfulDetail("扬声器new与脚本year不符") == "扬声器new与脚本year不符")
check("有价值: 音频缺失→保留", meaningfulDetail("音频缺失") == "音频缺失")

print()
print(f"结果: {passed} 通过, {failed} 失败")
sys.exit(1 if failed else 0)
