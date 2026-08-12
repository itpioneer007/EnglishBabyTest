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
