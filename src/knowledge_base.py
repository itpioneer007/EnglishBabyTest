"""
knowledge_base.py — 小学英语教材知识库
===========================================
用途: 存储各版本/各年级/各单元的教材知识点
      用于审查时验证题目内容是否与教材一致

数据组织:
  version → grade → semester → unit → {vocab, patterns, topics, phonics, grammar}

支持的版本:
  - 湘少版 (XiangShao / XS)
  - 湘鲁版 (XiangLu / XL)
  - 人教版 (RenJiao / PEP)

数据来源:
  1. 公司提供的 DOCX 脚本文件（自动解析抽取）
  2. 手动整理的 JSON 补充数据
  3. 逐次审查积累的高频词汇/知识点
"""

import json
import re
import time
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional

# ============================================================
# 数据模型
# ============================================================

@dataclass
class UnitKnowledge:
    """一个单元的教材知识点"""
    unit_num: int = 0                     # 单元号 1-12
    title: str = ""                       # 单元标题
    topic: str = ""                       # 单元话题
    vocab: list = field(default_factory=list)       # 核心词汇
    patterns: list = field(default_factory=list)    # 核心句型
    phonics: list = field(default_factory=list)     # 语音知识点
    grammar: list = field(default_factory=list)     # 语法点
    culture: list = field(default_factory=list)     # 文化背景

    def to_dict(self):
        return asdict(self)

@dataclass
class GradeKnowledge:
    """一个年级的知识（上下册合并）"""
    grade: str = ""                       # "三"/"四"/"五"/"六"
    semester: str = ""                    # "上册"/"下册"
    version: str = ""                     # "湘少版"/"湘鲁版"/"人教版"
    units: dict = field(default_factory=dict)  # {unit_num: UnitKnowledge}

@dataclass
class TextbookKnowledge:
    """完整教材知识库"""
    version: str = ""                     # 教材版本
    grades: dict = field(default_factory=dict)  # {"三上": GradeKnowledge, ...}


# ============================================================
# 知识库管理器
# ============================================================

class KnowledgeBase:
    """
    教材知识库 — 增删查改
    
    用法:
        kb = KnowledgeBase()
        kb.load("data/english_textbook.json")
        
        # 查询某个知识点属于哪个年级单元
        matches = kb.search_vocab("sport")
        
        # 验证题目是否符合教材范围
        check = kb.verify_question(unit=6, vocab_used=["sport", "fun"])
    """

    def __init__(self, path: str = "data/knowledge_base.json"):
        self.path = Path(path)
        self.data: dict = {}  # {"湘少版:五上": {...}, ...}
        self._load()

    # ============================================================
    # 加载/保存
    # ============================================================

    def _load(self):
        if self.path.exists():
            with open(self.path, "r", encoding="utf-8") as f:
                self.data = json.load(f)
        else:
            self.data = {}

    @staticmethod
    def _try_convert_doc(doc_path: str) -> Optional[str]:
        """用 Word COM 把 .doc 转成 .docx，返回转换后路径"""
        import time as _time
        docx_path = doc_path.rsplit('.', 1)[0] + '_converted.docx'
        if Path(docx_path).exists() and Path(docx_path).stat().st_mtime >= Path(doc_path).stat().st_mtime:
            return docx_path
        try:
            import win32com.client
            word = win32com.client.Dispatch('Word.Application')
            word.Visible = False
            try:
                doc = word.Documents.Open(str(Path(doc_path).resolve()))
                doc.SaveAs2(str(Path(docx_path).resolve()), FileFormat=16)
                doc.Close()
            finally:
                word.Quit()
                _time.sleep(0.5)
            return docx_path
        except Exception as e:
            print(f"[知识库] .doc→.docx 转换失败: {e}")
            return None

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
        print(f"✅ 知识库已保存: {self.path} ({self._count_entries()} 条知识点)")

    def _count_entries(self) -> int:
        """统计总知识点数"""
        count = 0
        for key, grade in self.data.items():
            for unum, unit in grade.get("units", {}).items():
                count += len(unit.get("vocab", []))
                count += len(unit.get("patterns", []))
        return count

    # ============================================================
    # 添加/更新
    # ============================================================

    def add_unit(self, version: str, grade_label: str, unit: UnitKnowledge):
        """
        添加一个单元的知识点
        
        Args:
            version: "湘少版" / "湘鲁版" / "人教版"
            grade_label: "三上" / "三下" / "四上" / ...
            unit: UnitKnowledge 对象
        """
        key = f"{version}:{grade_label}"
        if key not in self.data:
            self.data[key] = {"version": version, "grade": grade_label, "units": {}}
        self.data[key]["units"][str(unit.unit_num)] = unit.to_dict()

    def add_bulk_from_docx(self, docx_path: str):
        """
        从公司的 DOCX/DOC 脚本批量导入知识点
        自动解析脚本中的录音原文、选项词汇、知识点说明
        """
        from src.parse_yingyubao_docx import parse

        # .doc → .docx 自动转换
        final_path = docx_path
        if docx_path.lower().endswith('.doc') and not docx_path.lower().endswith('.docx'):
            final_path = self._try_convert_doc(docx_path)
            if not final_path:
                print(f"[知识库] 无法转换 .doc 文件, 跳过: {docx_path}")
                return {"vocab": 0, "patterns": 0, "questions": 0}

        questions = parse(final_path)
        stats = {"vocab": 0, "patterns": 0, "questions": len(questions)}

        # 整个文档只猜一次年级+版本
        grade_label = self._guess_grade_label(docx_path, questions)
        version = self._guess_version(docx_path)

        for q in questions:
            # 提取词汇 (从选项和录音中)
            vocab_words = []
            for opt in q.options:
                clean = re.sub(r'^[A-C][\.\、\s]+', '', opt).strip()
                if clean:
                    vocab_words.append(clean.lower())
            # 录音中的关键词
            rec_words = re.findall(r'[a-zA-Z]+', q.recording.lower())
            vocab_words.extend(rec_words)

            # 提取句型/知识点
            patterns_list = []
            for kp in q.knowledge_points:
                if kp:
                    patterns_list.append(kp)

            # 创建单元知识点
            unit_num = q.unit
            uk = UnitKnowledge(
                unit_num=unit_num,
                topic=self._extract_topic(q),
                vocab=list(set(vocab_words)),
                patterns=list(set(patterns_list)),
            )

            # 合并到已有单元
            existing = None
            key = f"{version}:{grade_label}"
            if key in self.data and str(unit_num) in self.data[key]["units"]:
                existing = self.data[key]["units"][str(unit_num)]
                existing["vocab"] = list(set(existing.get("vocab", []) + uk.vocab))
                existing["patterns"] = list(set(existing.get("patterns", []) + uk.patterns))
                if q.type_2 and q.type_2 not in existing.get("exam_types", []):
                    existing.setdefault("exam_types", []).append(q.type_2)
            else:
                d = uk.to_dict()
                d["exam_types"] = [q.type_2] if q.type_2 else []
                self.add_unit(version, grade_label, uk)
                if existing:
                    self.data[key]["units"][str(unit_num)] = existing

            stats["vocab"] += len(vocab_words)
            stats["patterns"] += len(patterns_list)

        self.save()
        print(f"  解析 {stats['questions']} 题 → 词汇 {stats['vocab']} 条, 句型 {stats['patterns']} 条")
        return stats

    # ============================================================
    # 查询/验证
    # ============================================================

    def search_vocab(self, word: str) -> list[dict]:
        """
        查询一个单词出现在哪些年级/单元
        
        Returns:
            [{"version": "湘少版", "grade": "五上", "unit": 6, "title": "..."}, ...]
        """
        results = []
        w = word.lower().strip()
        for key, grade in self.data.items():
            for unum, unit in grade.get("units", {}).items():
                if w in [v.lower() for v in unit.get("vocab", [])]:
                    results.append({
                        "version": grade["version"],
                        "grade": grade["grade"],
                        "unit": int(unum),
                        "title": unit.get("title", ""),
                    })
        return results

    def verify_question(self, unit: int, vocab_used: list[str] = None,
                        patterns_used: list[str] = None,
                        version: str = "", grade: str = "") -> dict:
        """
        验证题目是否在教材知识范围内
        
        Returns:
            {"in_knowledge": True/False, "matched": [...], "unknown": [...]}
        """
        if vocab_used is None:
            vocab_used = []
        if patterns_used is None:
            patterns_used = []

        # 查找目标单元
        target_key = f"{version}:{grade}" if version and grade else None
        target_unit = None
        if target_key and target_key in self.data:
            target_unit = self.data[target_key]["units"].get(str(unit))

        matched_vocab = []
        unknown_vocab = []

        for w in vocab_used:
            wl = w.lower().strip()
            found = False
            for key, g in self.data.items():
                for unum, u in g.get("units", {}).items():
                    if wl in [v.lower() for v in u.get("vocab", [])]:
                        matched_vocab.append({"word": w, "unit": f"{g['grade']}-U{unum}"})
                        found = True
                        break
                if found:
                    break
            if not found:
                unknown_vocab.append(w)

        return {
            "in_knowledge": len(unknown_vocab) == 0,
            "matched": matched_vocab,
            "unknown": unknown_vocab,
            "target_unit_vocab": target_unit.get("vocab", []) if target_unit else [],
        }

    def get_unit_vocab(self, version: str, grade: str, unit: int) -> list:
        """获取某个单元的核心词汇"""
        key = f"{version}:{grade}"
        if key in self.data:
            u = self.data[key]["units"].get(str(unit), {})
            return u.get("vocab", [])
        return []

    def get_unit_patterns(self, version: str, grade: str, unit: int) -> list:
        """获取某个单元的核心句型"""
        key = f"{version}:{grade}"
        if key in self.data:
            u = self.data[key]["units"].get(str(unit), {})
            return u.get("patterns", [])
        return []

    # ============================================================
    # 统计分析
    # ============================================================

    def summary(self) -> list[dict]:
        """知识库概览"""
        rows = []
        for key, grade in sorted(self.data.items()):
            units = grade.get("units", {})
            total_v = sum(len(u.get("vocab", [])) for u in units.values())
            total_p = sum(len(u.get("patterns", [])) for u in units.values())
            rows.append({
                "key": key,
                "version": grade["version"],
                "grade": grade["grade"],
                "units": len(units),
                "vocab": total_v,
                "patterns": total_p,
            })
        return rows

    # ============================================================
    # 内部工具
    # ============================================================

    def _guess_grade_label(self, docx_path: str, questions: list = None) -> str:
        """
        从文件路径+文档内容推断年级
        
        优先级: 文件名 > 文档内容中的"标题行" > 试题单元号反推
        """
        path = str(docx_path).lower()

        # 1. 从文件名提取
        grade_labels = ["一上","一下","二上","二下","三上","三下","四上","四下","五上","五下","六上","六下"]
        for lbl in grade_labels:
            if lbl in path:
                return lbl

        # 2. 从文档标题提取 (如"五年级上册听力专项")
        grade_map = {
            '一年级上册':'一上','一年级下册':'一下','二年级上册':'二上','二年级下册':'二下',
            '三年级上册':'三上','三年级下册':'三下','四年级上册':'四上','四年级下册':'四下',
            '五年级上册':'五上','五年级下册':'五下','六年级上册':'六上','六年级下册':'六下',
        }
        if questions:
            for q in questions[:5]:  # 查前5题的stem/keywords
                text = (q.stem + ' '.join(q.keywords)).lower()
                for full, short in grade_map.items():
                    if full in text:
                        return short

        # 3. 从题目数量反推 (听力专项U6-9是五上/六上特征)
        if questions:
            units = set(q.unit for q in questions if q.unit > 0)
            # U6-U9 多为五上或六上
            if units and min(units) >= 6 and max(units) <= 9:
                # 检查文件名含"六"→六上, 含"五"→五上
                if '六' in path: return '六上'
                if '五' in path: return '五上'

        return "未知"

    def _guess_version(self, docx_path: str) -> str:
        """从文件路径猜测版本"""
        path = str(docx_path).lower()
        if "湘鲁" in path or "xl" in path:
            return "湘鲁版"
        elif "湘少" in path or "xs" in path:
            return "湘少版"
        elif "人教" in path:
            return "人教版"
        # 从文件名提取
        m = re.search(r'新湘鲁|湘鲁|湘少|人教|PEP', path)
        return m.group(0) + "版" if m else "湘鲁版"

    def _extract_topic(self, q) -> str:
        """从题目中提取话题"""
        if q.knowledge_points:
            return q.knowledge_points[0]
        return q.stem[:30] if q.stem else q.type_2


# ============================================================
# 快速使用入口
# ============================================================

def build_from_docx(docx_paths: list[str] = None):
    """
    从 DOCX 文件构建知识库
    
    Args:
        docx_paths: DOCX 文件路径列表（为空则自动搜索）
    """
    kb = KnowledgeBase()

    if not docx_paths:
        # 默认搜索常见路径
        base = r"D:\压缩包存储"
        if Path(base).exists():
            docx_paths = [str(p) for p in Path(base).rglob("*.docx")]

    if not docx_paths:
        print("⚠ 未找到 DOCX 文件")
        return kb

    print(f"📚 导入 {len(docx_paths)} 个 DOCX 文件到知识库...")
    for p in docx_paths:
        print(f"  📄 {Path(p).name}")
        try:
            kb.add_bulk_from_docx(p)
        except Exception as e:
            print(f"    ⚠ 解析失败: {e}")

    return kb


if __name__ == "__main__":
    # 直接从 DOCX 构建知识库
    kb = build_from_docx()
    for row in kb.summary():
        print(f"  {row['key']}: {row['units']}单元, {row['vocab']}词汇, {row['patterns']}句型")
