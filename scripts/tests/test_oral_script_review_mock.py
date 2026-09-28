# -*- coding: utf-8 -*-
"""口语训练 U6 脚本审查 mock 端到端验证（不连手机）

验证链路（与 web_server._detect_content_dimension 同逻辑）：
  1. parse_oral_paragraphs 解析真实脚本 → U6 应为 20 题（4大题×5小题）
  2. 模拟 App 端记录题卡（idx=小题号, big=大题号, module_qno=小题号）
  3. 按 (unit, big, stage_idx) 匹配脚本题目 → 每题必须唯一命中且题干/答案正确
"""
import os
import re
import sys
import types
import zipfile

# stub python-docx（本环境未装，解析逻辑本身不依赖它）
_d = types.ModuleType("docx")
_d.Document = lambda *a, **k: (_ for _ in ()).throw(NotImplementedError("stub"))
sys.modules["docx"] = _d
sys.path.insert(0, "src")
from parse_yingyubao_docx import parse_oral_paragraphs  # noqa: E402
from review_agent import normalize_units  # noqa: E402

DOCX = "uploads/260513口语训练湘少五上（U6-U10已一测）.docx"

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  ✅ " if cond else "  ❌ ") + name + (f"  —— {detail}" if detail and not cond else ""))


def paras_of(path):
    """zipfile 提取 docx 段落（等价 doc.paragraphs，无需 python-docx）"""
    xml = zipfile.ZipFile(path).read("word/document.xml").decode("utf-8", errors="ignore")
    ps = re.findall(r'<w:p[ >].*?</w:p>', xml, re.S)
    def ptext(p_):
        parts = []
        for m in re.finditer(r'<w:t[^>]*>([^<]*)</w:t>|<w:tab/>|<w:br/>', p_):
            if m.group(1) is not None:
                parts.append(m.group(1))
            elif m.group(0).startswith('<w:tab'):
                parts.append('\t')
        return "".join(parts)
    return [ptext(p_) for p_ in ps]


# ---- 1. 解析脚本 ----
paragraphs = paras_of(DOCX)
qs = parse_oral_paragraphs(paragraphs)
u6 = [q for q in qs if q.unit == 6]
print(f"解析总数={len(qs)}, U6={len(u6)}")
check("U6 解析出 20 题（4大题×5小题）", len(u6) == 20, f"got {len(u6)}")
check("U6 global_idx 连续 1-20", [q.global_idx for q in u6] == list(range(1, 21)))
by_big = {}
for q in u6:
    by_big.setdefault(q.big, []).append(q)
check("每大题 5 小题", all(len(v) == 5 for v in by_big.values()), f"got {[len(v) for v in by_big.values()]}")

# ---- 2. 模拟 App 题卡 + 匹配（与 web_server._detect_content_dimension 一致） ----
_unit_cur = 6
app_cards = []
for big in range(1, 5):
    for sub in range(1, 6):
        app_cards.append({"idx": sub, "big": big, "module_qno": sub})  # 口语训练题卡：idx=小题号

matched = []
for card in app_cards:
    idx = card["idx"]
    _q_big = card.get("big") or 0
    _q_no = card.get("module_qno") or 0
    sqs = []
    if _q_big and _q_no:                                        # 口语题卡：优先 (unit,big,stage_idx)
        sqs = [s for s in u6 if s.unit == _unit_cur and s.big == _q_big and s.stage_idx == _q_no]
    if not sqs:                                                 # 其他：global_idx
        sqs = [s for s in u6 if s.global_idx == idx]
    matched.append((card, sqs[0] if sqs else None))

hit = [m for m in matched if m[1] is not None]
check("20 张 App 题卡全部命中脚本题目", len(hit) == 20, f"命中 {len(hit)}/20")
# 唯一性：每张卡命中不同脚本题
uniq = {id(m[1]) for m in matched}
check("命中的脚本题无重复", len(uniq) == len(hit), f"{len(uniq)} unique / {len(hit)} hits")

# ---- 3. 抽查关键小题的题干/答案对齐 ----
stem_map = {(q.big, q.stage_idx): q.stem for q in u6}
ans_map = {(q.big, q.stage_idx): q.answer for q in u6}
check("第1大题第1小题 = try", stem_map[(1, 1)] == "try", stem_map.get((1, 1)))
check("第1大题第5小题 = little", stem_map[(1, 5)] == "little", stem_map.get((1, 5)))
check("第2大题第1小题 = I have a red car.", stem_map[(2, 1)] == "I have a red car.", stem_map.get((2, 1)))
check("第3大题第1小题 = Which one do you want...", stem_map[(3, 1)].startswith("Which one do you want"), stem_map.get((3, 1)))
check("第3大题第2小题答案 = Can I try the skirt on?", ans_map[(3, 2)].startswith("Can I try the skirt on?"), ans_map.get((3, 2)))
check("第4大题第1小题 = Whose coat is too big?", stem_map[(4, 1)] == "Whose coat is too big?", stem_map.get((4, 1)))
check("第4大题第5小题答案含 because", "because" in ans_map[(4, 5)].lower(), ans_map.get((4, 5)))

# ---- 4. 策略分派 + 听力专项回归（重构后旧解析器行为必须不变） ----
import importlib
P = importlib.import_module("parse_yingyubao_docx")
print("\n== 策略分派 + 听力专项回归 ==")
check("策略注册: 口语/巧记单词/知识过关在前、听力兜底在后",
      [s.name for s in P.STRATEGIES] == ["口语训练", "巧记单词", "知识过关", "听力专项（兜底）"])
check("口语脚本 → OralStrategy.detect=True",
      P.OralStrategy().detect(paragraphs) is True)
check("听力脚本 → OralStrategy.detect=False（走兜底）",
      P.OralStrategy().detect(paras_of("uploads/260508听力专项英语五年级上册湘少版U6（二校）.docx")) is False)
lp = paras_of("uploads/260508听力专项英语五年级上册湘少版U6（二校）.docx")
lq = P.ListeningStrategy().parse(lp)
check("听力专项(旧解析器路径)仍可解析", len(lq) > 0, f"{len(lq)} 题")
if lq:
    u6l = [q for q in lq if q.unit == 6]
    check("听力专项 U6 单元识别正确", len(u6l) == len(lq))
    check("听力专项选项/答案解析", any(q.options for q in lq) and any(q.answer for q in lq))
    print(f"  听力专项: {len(lq)} 题, 阶段分布="
          f"{sorted({q.stage for q in lq})}")

# ---- 5. 知识过关（KnowledgeStrategy）----
print("\n== 知识过关 ==")
kp = paras_of("uploads/260513知识过关新湘少五上U6-10（已二校）.docx")
check("知识过关 detect 正确", P.KnowledgeStrategy().detect(kp) is True)
kq = P.KnowledgeStrategy().parse(kp)
kunits = {}
for q in kq: kunits.setdefault(q.unit, []).append(q)
check("知识过关 48 题", len(kq) == 48, f"got {len(kq)}")
check("知识过关 U6=11 题（第11题不串单元）", len(kunits.get(6, [])) == 11, f"got {len(kunits.get(6, []))}")
check("知识过关 unit=0 空题 = 0", 0 not in kunits, f"got {sorted(kunits)}")
u6k = [q for q in kq if q.unit == 6]
check("知识过关 题型字段写入 type_2", all(q.type_2 for q in u6k), [q.type_2 for q in u6k[:3]])
check("U6 末题 = 连词成句(Can I have a new dress?)",
      u6k[-1].stem.startswith("连词成句") and "new dress" in u6k[-1].answer, u6k[-1].answer[:40])
print(f"  知识过关: {len(kq)} 题, 单元={sorted(kunits)}")

# ---- 6. 巧记单词（.doc 老格式 + QiaojiStrategy）----
print("\n== 巧记单词 .doc ==")
QJ_DOC = "D:/腾讯电脑管家软件搬家/xwechat_files/wxid_4bxb6ihw9mmv22_8af8/msg/file/2026-07/260413巧记单词闯关部分新湘少五上（已一校）.doc"
if os.path.exists(QJ_DOC):
    qj = P.parse(QJ_DOC)
    qjunits = {}
    for q in qj: qjunits.setdefault(q.unit, []).append(q)
    check("巧记单词 总 930 题", len(qj) == 930, f"got {len(qj)}")
    check("巧记单词 U1=108 题（App 10/108 对应）", len(qjunits.get(1, [])) == 108, f"got {len(qjunits.get(1, []))}")
    u1 = [q for q in qj if q.unit == 1]
    check("U1 首题=听录音跟读单词", u1[0].stem == "听录音，跟读单词。", u1[0].stem if u1 else "")
    check("U1 第2题=听音选释义(答案B)",
          u1[1].stem.startswith("听录音，选择与录音内容相符") and u1[1].answer == "B",
          f"{u1[1].stem if len(u1)>1 else ''}|{u1[1].answer if len(u1)>1 else ''}")
    check("U1 第3题=字母补全(答案ew)",
          u1[2].stem.startswith("根据中文提示") and u1[2].answer == "ew",
          f"{u1[2].stem if len(u1)>2 else ''}|{u1[2].answer if len(u1)>2 else ''}")
    print(f"  巧记单词: {len(qj)} 题, 单元={sorted(qjunits)}")
else:
    print("  ⚠ 巧记单词 .doc 不在本机（跳过，需用户提供）")

# ---- 7. 多单元脚本过滤（2026-08-25 用户核心需求：脚本覆盖所选单元才审查）----
print("\n== 多单元脚本过滤（normalize_units + 单元提取）==")
_nu_cases = [
    ("6", {6}), ("2,4", {2, 4}), ("2-4", {2, 3, 4}), ("2,4-6", {2, 4, 5, 6}),
    (6, {6}), ([2, 4], {2, 4}), (0, None), ("0", None), ("NONE", None), ("", None),
]
for _inp, _exp in _nu_cases:
    _got = normalize_units(_inp)
    check(f"normalize_units({_inp!r})={_got}", _got == _exp, f"got {_got}")
# 真实脚本多单元提取（U6-U10 全单元脚本）
_allqs = parse_oral_paragraphs(paras_of(DOCX))
check("全单元脚本解析 100 题", len(_allqs) == 100, f"got {len(_allqs)}")
_sel68 = [q for q in _allqs if q.unit in normalize_units("6,8")]
check("选U6,U8 → 提取40题(各20)", len(_sel68) == 40 and sorted({q.unit for q in _sel68}) == [6, 8],
      f"got {len(_sel68)} {sorted({q.unit for q in _sel68})}")
_sel2 = [q for q in _allqs if q.unit in normalize_units("2")]
check("选U2(脚本无U2) → 0题静默跳过", len(_sel2) == 0, f"got {len(_sel2)}")
_sel7 = [q for q in _allqs if q.unit in normalize_units("7")]
check("选U7 → 提取20题", len(_sel7) == 20, f"got {len(_sel7)}")

print("\n" + "=" * 46)
print(f"结果: {len(PASS)} 通过, {len(FAIL)} 失败")
if FAIL:
    for f in FAIL:
        print("  -", f)
    sys.exit(1)
print("全部通过 ✅")
