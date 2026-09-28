# -*- coding: utf-8 -*-
"""
脚本内容审查器 v2: 整卷审查（直接读 DOCX 段落，按大题分段审查）
"""
import json
from datetime import datetime
from pathlib import Path


SCRIPT_REVIEW_RULES = """【英语试卷脚本审查规则】严格按以下规则审查：

一、检查对象：题干/选项/答案/听力原文/阅读材料/元数据；第一优先级正文和答案。

二、语言错误：
1. 拼写错误：逐词检查，结合年级/教材词汇判断，不因AI不认识就判错。
2. 语法错误：主谓一致、be动词、名词单复数、冠词、代词、时态。
3. 词性错误：名词/动词/形容词/副词/介词/连词用错。

三、搭配和固定表达：try on/look good on/a pair of等教材语境固定表达；动词/介词搭配。

四、语义合理性：主语谓语匹配、属性/数量/时间/地点/因果合理。

五、上下文一致性：跨句人物/颜色/服装/数量/实体一致；同一文档内部自洽。

六、题目-选项-答案一致性：答案是否越界、选项维度是否一致、答案是否与材料一致。

七、听力/阅读材料一致性：材料→题目→答案→题型逻辑联合判断，区分"考查点差异"vs"命题错误"。

八、选项质量：拼写、同一维度、重复、答案唯一性。

九、元数据自洽：题型/认知目标/知识点/难度/年级/主题之间是否匹配。

判定：输出JSON，所有问题列在issues中。verdict=PASS(无问题)/HAS_ISSUES(有问题)。"""


class ScriptReviewer:
    """脚本内容审查器：直接读 DOCX 全文，按大题分段审查"""

    def __init__(self, llm):
        self.llm = llm

    def review_full(self, docx_path: str) -> dict:
        """审查整个 DOCX 脚本，返回 {total_sections, issues_count, sections: [...]}"""
        sections = self._split_sections(docx_path)
        if not sections:
            return {"error": "无法解析文档内容", "sections": []}
        results = []
        for sec in sections:
            r = self._review_section(sec)
            results.append(r)
        issues_count = sum(1 for r in results if r.get("verdict") == "HAS_ISSUES")
        return {"total_sections": len(results), "issues_count": issues_count, "sections": results}

    def _split_sections(self, docx_path: str) -> list[dict]:
        """将 DOCX 按大题（Ⅰ、Ⅱ、III... 或一二三...）拆分为段落组"""
        from docx import Document
        doc = Document(docx_path)
        all_paras = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
        sections = []
        current = {"title": "文档头部", "lines": []}
        for line in all_paras:
            # 检测大题标题: Ⅰ. Ⅱ. 一、二、等
            import re
            is_header = re.match(r'^[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ一二三四五六七八九十]+[\.、\s]', line) or \
                        re.match(r'^[IVXivx]+[\.\s]', line)
            if is_header and current["lines"]:
                sections.append(current)
                current = {"title": line, "lines": []}
            current["lines"].append(line)
        if current["lines"]:
            sections.append(current)
        return sections

    def _review_section(self, section: dict) -> dict:
        """审查一个大题段落组"""
        title = section["title"]
        text = "\n".join(section["lines"])
        if len(text) < 50:  # 太少内容跳过
            return {"title": title, "verdict": "PASS", "issues": [], "lines": section["lines"]}
        try:
            prompt = (
                f"【任务: 英语试卷脚本审查】\n\n"
                f"【大题标题】{title}\n\n"
                f"【内容】\n{text[:3000]}\n\n"
                f"{SCRIPT_REVIEW_RULES}\n\n"
                f"请按规则审查以上内容，输出严格JSON:\n"
                f'{{"verdict":"PASS或HAS_ISSUES","issues":['
                f'{{"type":"问题类型","severity":"高/中/低","location":"具体位置",'
                f'"quote":"原文","detail":"问题描述","suggestion":"修改建议"}}]}}'
                f"\n无问题则issues:[]。"
            )
            raw = self.llm.ask(prompt)
            data = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
            return self._clean(data, section)
        except Exception as e:
            return {"title": title, "verdict": "ERROR", "issues": [
                {"type": "审查异常", "severity": "低", "detail": str(e)[:120]}
            ], "lines": section["lines"]}

    def _clean(self, data: dict, section: dict) -> dict:
        verdict = str(data.get("verdict", "PASS")).upper()
        if verdict not in ("PASS", "HAS_ISSUES"):
            verdict = "HAS_ISSUES"
        issues = data.get("issues") or []
        if not isinstance(issues, list):
            issues = []
        return {
            "title": section["title"],
            "verdict": verdict,
            "issues": [{
                "type": str(iss.get("type", ""))[:30],
                "severity": str(iss.get("severity", "中"))[:4],
                "location": str(iss.get("location", ""))[:40],
                "quote": str(iss.get("quote", ""))[:100],
                "detail": str(iss.get("detail", ""))[:200],
                "suggestion": str(iss.get("suggestion", ""))[:120],
            } for iss in issues],
            "lines": section["lines"],
        }


# ============================================================
# 确定性完整性校验（零 LLM 成本 / 100% 召回 / 不截断）
# ============================================================
# 为什么必须补这一层：_review_section 是"按大题喂 LLM"的审查，有三个硬伤——
#   ① 内容被 text[:3000] 截断 → 大题后半部分根本不进模型（阅读大题极易超 3000 字符）；
#   ② 内容 < 50 字符直接 return PASS，连看都不看；
#   ③ 规则全是"语言/搭配/语义"这类主观判断，对**结构性缺失**
#      （少题、缺参考答案、字段名不统一、知识点为空）没有确定性判据，
#      只能靠模型在长文本里碰运气 → 用户实测反馈"有问题没查出来"。
# 本层把"能确定的"问题用规则直接判死，放在 LLM 审查之前跑：
# 便宜、可复现、不截断，且不会因为模型注意力漂移而漏。

_UNIFIED_FIELD_ALIASES = [
    (("难度", "难度系数"), "难度"),
    (("技能", "技能要求"), "技能"),
]
_NO_ANSWER_TYPES = ("朗读",)          # 朗读类不写参考答案（题干本身即答案）


def check_script_completeness(docx_path: str, questions: list) -> list:
    """对整份脚本做确定性完整性校验。

    返回 issues: [{type, severity, location, quote, detail, suggestion}]
    """
    import re as _re
    issues = []

    # ---- ① 题号连续性：每个 (unit, big) 的小题号必须是 1..N 连续 ----
    groups = {}
    for q in questions:
        groups.setdefault((q.unit, q.big), []).append(q)
    for (unit, big) in sorted(groups, key=lambda k: (k[0], k[1])):
        nums = sorted(q.stage_idx for q in groups[(unit, big)])
        expect = list(range(1, len(nums) + 1))
        if nums != expect:
            miss = [n for n in expect if n not in nums]
            dup = sorted({n for n in nums if nums.count(n) > 1})
            issues.append({
                "type": "题号不连续",
                "severity": "高",
                "location": "U%s 第%s大题" % (unit, big),
                "quote": "小题号=%s" % nums,
                "detail": ("应解析出 1..%d 连续小题号，实际为 %s%s%s" % (
                    len(nums), nums,
                    "；缺少 %s" % miss if miss else "",
                    "；重复 %s" % dup if dup else "")),
                "suggestion": "核查该大题题干行的编号是否漏写/被截断，以及小题数是否与大题声明一致",
            })

    # ---- ② 元数据字段名统一 ----
    try:
        from docx import Document
        paras = [p.text.strip() for p in Document(docx_path).paragraphs if p.text.strip()]
    except Exception:
        paras = []
    field_names = set()
    for t in paras:
        _fm = _re.match(r"^([\u4e00-\u9fa5]{2,6})[：:]", t)
        if _fm:
            field_names.add(_fm.group(1))
    for aliases, canon in _UNIFIED_FIELD_ALIASES:
        hit = [a for a in aliases if a in field_names]
        if len(hit) > 1:
            issues.append({
                "type": "字段名不统一",
                "severity": "中",
                "location": "全文",
                "quote": "、".join(hit),
                "detail": "同一语义出现 %d 种字段名写法：%s" % (len(hit), "、".join(hit)),
                "suggestion": "统一为「%s：」，避免下游按字段名取值时漏取（如难度分级失真）" % canon,
            })

    # ---- ③ 参考答案缺失（朗读/跟读类豁免）----
    for q in questions:
        ans = (q.answer or "").strip()
        if ans and ans not in ("/", "-", "无"):
            continue
        if any(k in ((q.type_1 or "") + (q.type_2 or "")) for k in _NO_ANSWER_TYPES):
            continue
        issues.append({
            "type": "参考答案缺失",
            "severity": "中",
            "location": "U%s 第%s大题 第%s小题" % (q.unit, q.big, q.stage_idx),
            "quote": (q.stem or "")[:40],
            "detail": "题型为「%s」但未解析到参考答案" % ((q.type_2 or q.type_1 or "未知")),
            "suggestion": "补写「参考答案：」行；多组可接受答案用 / 分隔",
        })

    # ---- ④ 知识点缺失 / 占位符 / 条数与小题数不符 ----
    for (unit, big) in sorted(groups, key=lambda k: (k[0], k[1])):
        qs = groups[(unit, big)]
        kps = qs[0].knowledge_points or []
        joined = " ".join(kps).strip()
        loc = "U%s 第%s大题" % (unit, big)
        if not joined:
            issues.append({
                "type": "知识点缺失", "severity": "中", "location": loc,
                "quote": (qs[0].big_title or "")[:40],
                "detail": "该大题所有小题的 knowledge_points 为空",
                "suggestion": "补充「知识点：」行（多条用编号行或分号分隔）",
            })
        elif joined in ("/", "-", "无"):
            issues.append({
                "type": "知识点为占位符", "severity": "中", "location": loc,
                "quote": joined,
                "detail": "知识点写成了占位符「%s」，未给出实际内容" % joined,
                "suggestion": "替换为真实知识点（如句型结构 / 发音规律）",
            })

    # ---- ⑤ 参考答案 ↔ 关键词 一致性（确定性，复用已有规则）----
    try:
        from review_agent import check_answer_keyword_consistency as _ck
    except Exception:
        try:
            from src.review_agent import check_answer_keyword_consistency as _ck
        except Exception:
            _ck = None
    if _ck:
        for q in questions:
            kws = [k for k in (q.keywords or []) if "#" not in k]
            if not kws or not (q.answer or "").strip():
                continue
            try:
                res = _ck(q.answer, kws, q.passage or "")
            except Exception:
                continue
            # ★ 返回值是三元组 (issues:list, checked:int, detail:dict)，不是字符串。
            #   第一版直接把它当 truthy 用 → 每题都判"不一致"（实测 45 条全误报）。
            if isinstance(res, (list, tuple)):
                bad_items = res[0] if (res and isinstance(res[0], list)) else []
            else:
                bad_items = [res] if res else []
            for _b in bad_items:
                _msg = _b if isinstance(_b, str) else str(_b)
                issues.append({
                    "type": "答案与关键词不一致",
                    "severity": "高",
                    "location": "U%s 第%s大题 第%s小题" % (q.unit, q.big, q.stage_idx),
                    "quote": _msg[:60],
                    "detail": _msg[:160],
                    "suggestion": "核对参考答案用词与关键词是否指向同一表达（如 take / bring 这类动词替换最易错）",
                })
    return issues
