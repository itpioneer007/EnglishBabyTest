# -*- coding: utf-8 -*-
"""生成「巧记单词」解析脚本样例 docx（含关卡分组），用于查看新格式。

数据来源：uploads/260413巧记单词闯关部分新湘少五上（已一校）.doc 的真实题目内容，
按巧记单词的真实形态（一个单元 6 关：1~5 数字关 + boss 关）分配关卡，
知识点走真实 LLM（走 gen_script 自带的知识点缓存）。

产出：gen_scripts/样例_巧记单词关卡分组_U1.docx
"""
import os
import sys

_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_here, "scripts"))
sys.path.insert(0, _here)

os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from scripts.common.gen_script import QuestionCollector  # noqa: E402

DOC = os.path.join(_here, "uploads", "260413巧记单词闯关部分新湘少五上（已一校）.doc")

# ---- 1. 从真实脚本解析出 U1 的题目 ----
sys.path.insert(0, os.path.join(_here, "src"))
from src.parse_yingyubao_docx import parse  # noqa: E402

qs = parse(DOC)
u1 = [q for q in qs if q.unit == 1]
print(f"真实脚本 U1 解析到 {len(u1)} 题")
for q in u1[:6]:
    print(f"   type2={q.type_2!r} stem={(q.stem or '')[:44]!r} ans={q.answer!r}")

# ---- 2. 取前 18 题，按真实形态分配关卡（每关 3 题，含 boss 关） ----
SAMPLE = 18
_selected = u1[:SAMPLE]
# 关卡分配：1,2,3,4,5,boss —— 每关 3 题
_lv_seq = [1] * 3 + [2] * 3 + [3] * 3 + [4] * 3 + [5] * 3 + [0] * 3

coll = QuestionCollector(
    module="巧记单词",
    version="湘少版",
    grade="五年级上册",
    save_root=os.path.join(_here, "gen_scripts"),
)

for i, (q, lv) in enumerate(zip(_selected, _lv_seq), 1):
    coll.add(
        qno=i,
        stem=(q.stem or "").strip(),
        options=[str(o).strip() for o in (q.options or [])],
        answer=(q.answer or "").strip(),
        qtype="巧记单词",
        unit=1,
        level=lv,
        allow_listen=True,
        speaker_word=(getattr(q, "speaker_word", "") or "").strip(),
    )

print(f"\n收集 {len(coll.questions)} 题，开始生成 docx（知识点走真实 LLM，有缓存）…")
path = coll.finish_unit(unit=1)
print(f"\n✅ 样例脚本: {path}")

# ---- 3. 顺便把文件改名成一眼能认出的"样例" ----
if path and os.path.exists(path):
    _new = os.path.join(os.path.dirname(path), "样例_巧记单词_关卡分组U1.docx")
    if os.path.exists(_new):
        os.remove(_new)
    os.rename(path, _new)
    print(f"✅ 已改名: {_new}")

    # 打印前若干行，便于命令行直接核对分组结构
    from docx import Document
    print("\n--- 文档前 24 行 ---")
    for t in [p.text for p in Document(_new).paragraphs][:24]:
        print("   ", t[:78])
