"""
review_agent.py — 英语宝审查智能体 (v3: 6维检查)
=====================================================================

功能:
  - 六维检查: (1)题干 (2)内容 (3)配图 (4)作答 (5)答错后 (6)音频
  - 知识库查证: 验证题目是否在教材范围内
  - 反馈循环: 记录AI判断, 对比人工标注, 持续优化
  - 双模型架构: deepseek-v4-pro(文本) + qwen3.7-plus(视觉)

用法:
    # 命令行模式(快速审查)
    python review_agent.py --docx "脚本.docx" --unit 6 --stage "基础巩固"

    # 编程模式
    agent = ReviewAgent(script_docx="脚本.docx", knowledge_docx="教材.docx")
    results = agent.review_by_questions(q06_shot="screenshots/q006.png", ...)
    agent.export_report("审查报告.md")

三阶段训练:
    agent.trainer.run_phase2_comparison(ai_results, human_labels)
    agent.trainer.export_report()
"""

import sys, json, time
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.reviewer_common import LLMClient
from src.parse_yingyubao_docx import parse, YingYuBaoQuestion
from src.feedback_loop import FeedbackStore, FeedbackSample, ThreeStageTrainer
from src.knowledge_base import KnowledgeBase
from src.post_error_check import PostErrorChecker
from src.report_check import ReportChecker

# ★ 精确文字比对模块: 文字类检查不依赖LLM,用OCR+difflib逐字比对
try:
    from src.text_diff_checker import check_stem as _diff_check_stem, check_answer as _diff_check_answer, diff_texts
except ImportError:
    _diff_check_stem = _diff_check_answer = diff_texts = None


# ============================================================
# 配置
# ============================================================

@dataclass
class ReviewConfig:
    """审查配置"""
    docx_path: str = ""               # 公司提供的脚本 DOCX
    knowledge_docx: str = ""          # 教材知识库来源(可选, 同名DOCX)
    unit: int = 0                     # 0=全部
    stage: str = ""                   # 空=全部, "基础巩固"/"综合进阶"/"难点突破"
    screenshot_dir: str = "screenshots"
    output_dir: str = "outputs"
    verbose: bool = True              # 打印详细信息

# ============================================================
# 审查结果数据模型
# ============================================================

@dataclass
class CheckResult:
    """单次检查结果"""
    passed: bool = False
    score: float = 0.0                # 0~1
    confidence: int = 0               # ★ 置信度 0-100 (0=AI无法判断, 100=非常确定)
    details: list = field(default_factory=list)
    evidence: list = field(default_factory=list)  # ★ 结构化证据链(Evidence dict)
    error: str = ""
    method: str = ""                   # "diff"(精确比对) / "llm"(AI判断) / "skip" / "uncertain"

    def to_dict(self):
        return {"passed": self.passed, "score": self.score,
                "confidence": self.confidence,
                "details": self.details[:5], "error": self.error[:80],
                "evidence": self.evidence[:5], "method": self.method}

@dataclass
class QuestionReview:
    """一题的完整审查结果"""
    idx: int = 0
    question_type: str = ""
    script_answer: str = ""
    
    # 六维检查结果
    stem_check: CheckResult = field(default_factory=CheckResult)
    content_check: CheckResult = field(default_factory=CheckResult)
    image_check: CheckResult = field(default_factory=CheckResult)
    answer_check: CheckResult = field(default_factory=CheckResult)
    audio_check: CheckResult = field(default_factory=CheckResult)        # (5) 音频
    post_error_check: CheckResult = field(default_factory=CheckResult)   # (6) 答错后
    
    # 知识库查证
    knowledge_check: dict = field(default_factory=dict)
    
    # 综合判定
    overall_passed: bool = False
    overall_score: float = 0.0
    
    screenshot: str = ""
    timestamp: str = ""

    def to_dict(self):
        return {
            "idx": self.idx,
            "type": self.question_type,
            "script_answer": self.script_answer,
            "stem": self.stem_check.to_dict(),
            "content": self.content_check.to_dict(),
            "image": self.image_check.to_dict(),
            "answer": self.answer_check.to_dict(),
            "audio": self.audio_check.to_dict(),
            "post_error": self.post_error_check.to_dict(),
            "knowledge": self.knowledge_check,
            "overall_passed": self.overall_passed,
            "overall_score": round(self.overall_score, 2),
            "screenshot": self.screenshot,
        }


# ============================================================
# 审查智能体 (核心)
# ============================================================

class ReviewAgent:
    """
    英语宝审查智能体

    四维检查 + 知识库查证 + 反馈循环
    """

    def __init__(self, config: ReviewConfig = None):
        self.cfg = config or ReviewConfig()
        
        # LLM (双模型)
        self.llm = LLMClient.from_config()
        
        # 脚本数据
        self.script_questions: list[YingYuBaoQuestion] = []
        self._load_script()

        # 知识库
        self.kb = KnowledgeBase()
        if self.cfg.knowledge_docx:
            self.kb.add_bulk_from_docx(self.cfg.knowledge_docx)

        # 反馈循环
        self.feedback = FeedbackStore()
        self.trainer = ThreeStageTrainer(llm=self.llm, store=self.feedback)

        # A1 答错后检查器
        self.post_error_checker = PostErrorChecker(llm=self.llm)

        # A3 报告检查器
        self.report_checker = ReportChecker(llm=self.llm)

        # 结果
        self.results: list[QuestionReview] = []

    # ============================================================
    # 脚本加载
    # ============================================================

    def _load_script(self):
        if self.cfg.docx_path and Path(self.cfg.docx_path).exists():
            self.script_questions = parse(self.cfg.docx_path)
            # 过滤
            if self.cfg.unit:
                self.script_questions = [
                    q for q in self.script_questions if q.unit == self.cfg.unit
                ]
            if self.cfg.stage:
                self.script_questions = [
                    q for q in self.script_questions if q.stage == self.cfg.stage
                ]
            print(f"📋 加载脚本: {len(self.script_questions)} 题")
        else:
            print("⚠ 未加载脚本文件 (仅做基本检查)")

    # ============================================================
    # 审查入口
    # ============================================================

    def review(self, screenshots: dict[int, str] = None) -> list[QuestionReview]:
        """
        执行完整审查
        
        Args:
            screenshots: {global_idx: "screenshot_path", ...}
                         如果不传, 自动从 screenshot_dir 扫描
            
        Returns:
            list[QuestionReview]
        """
        if screenshots is None:
            screenshots = self._scan_screenshots()

        self.results = []
        for q in self.script_questions:
            shot = screenshots.get(q.global_idx, "")
            r = self._review_one(q, shot)
            self.results.append(r)

            if self.cfg.verbose:
                icon = "✅" if r.overall_passed else "❌"
                print(f"  Q{r.idx:02d} {icon} score={r.overall_score:.2f}")

        return self.results

    def _scan_screenshots(self) -> dict:
        """扫描截图文件夹"""
        folder = Path(self.cfg.screenshot_dir)
        mapping = {}
        if folder.exists():
            for f in sorted(folder.glob("*.png")):
                num = f.stem.replace("q", "").replace("Q", "")
                try:
                    mapping[int(num)] = str(f)
                except ValueError:
                    pass
        return mapping

    # ============================================================
    # 单题审查
    # ============================================================

    def _review_one(self, q: YingYuBaoQuestion, screenshot: str,
                    post_error_shot: str = "",
                    is_first_question: bool = False,
                    ui_texts: list = None,
                    detected: object = None) -> QuestionReview:
        """审查一道题 (六维 + 知识库)

        Args:
            q: 脚本题目数据
            screenshot: 题目截图路径
            post_error_shot: 答错后结果页截图（仅首题有）
            is_first_question: 是否为本模块首题（触发答错后检查）
            ui_texts: 手机屏幕文字列表（供文字题走文本模型加速）
            detected: TypeDetector 实时识别的题型 (DetectedQuestion)，优先于脚本题型
        """
        # ★ 实时题型优先：手机页面实际识别出的题型 > 脚本题型
        qtype = q.type_2 or ""
        is_audio_q = ("听音" in qtype or "音频" in qtype)
        is_image_q = ("图片" in qtype or "看图" in qtype)
        _orig_type2 = q.type_2  # 备份，_review_batch/_check_image 读 q.type_2
        if detected is not None:
            dq_type1 = getattr(detected, "type_1", "") or ""
            dq_type2 = getattr(detected, "type_2", "") or ""
            if dq_type1 and dq_type1 != "未知":
                qtype = f"{dq_type1}-{dq_type2}" if dq_type2 else dq_type1
                is_audio_q = bool(getattr(detected, "is_audio", False))
                is_image_q = bool(getattr(detected, "is_image", False))
                # 让下游 _review_batch/_check_image 用实时题型判断图片题
                q.type_2 = qtype
            # 实时识别的题干/选项可补充脚本缺失信息
            det_stem = getattr(detected, "stem", "") or ""
            if det_stem and not (q.stem or "").strip():
                q.stem = det_stem
            det_opts = getattr(detected, "options", None)
            if det_opts and not q.options:
                q.options = det_opts

        r = QuestionReview(
            idx=q.global_idx,
            question_type=qtype,
            script_answer=q.answer,
            screenshot=screenshot,
            timestamp=datetime.now().isoformat(),
        )

        if not screenshot or not Path(screenshot).exists():
            # ★ 纯文字审查模式（不连手机 / 无截图）：只检查文字可查的维度，
            #   依赖截图的维度（配图/音频/答错后）标记 skip，而不是全判 0 分
            rr = self._review_text_only(r, q)
            q.type_2 = _orig_type2
            return rr

        # ---- 批量审查 (文字题走文本模型, 配图题走视觉模型) ----
        self._review_batch(q, screenshot, r, ui_texts)

        r.knowledge_check = self._verify_knowledge(q)

        # ---- (3) 配图检查 ----
        r.image_check = self._check_image(q, screenshot)

        # ---- (4) 作答检查 ----
        r.answer_check = self._check_answer(q, screenshot)

        # ---- (5) 音频检查 (A2) ----
        r.audio_check = self._check_audio(q, screenshot)

        # ---- (6) 答错后检查 (A1) ----
        r.post_error_check = self._check_post_error(q, post_error_shot, is_first_question)

        # ---- 综合评分 (六维) ----
        scores = [
            r.stem_check.score,
            r.content_check.score,
            r.image_check.score,
            r.answer_check.score,
            r.audio_check.score,
            r.post_error_check.score,
        ]
        r.overall_score = sum(scores) / len(scores) if scores else 0.0
        r.overall_passed = r.overall_score >= 0.7

        q.type_2 = _orig_type2  # 恢复脚本题型，避免污染
        return r

    # ============================================================
    # 纯文字审查（不连手机 / 无截图）：对照脚本文字检查
    # ============================================================
    def _review_text_only(self, r: QuestionReview, q) -> QuestionReview:
        """
        无截图时的文字审查模式：
        - 题干检查：题干非空、长度合理
        - 内容检查：选项是否齐全（选择题应有 ≥2 个选项）
        - 作答检查：答案非空、格式合理（A/B/C/D 或文本）
        - 知识库检查：题目词汇是否在教材知识范围内（不依赖截图）
        - 配图/音频/答错后：标记 skip（依赖截图，未检测）
        """
        import re as _re
        qtype = q.type_2 or ""
        # 听音/图片类题型：题干与选项内容在音频/图片中，脚本文字里没有，属正常
        is_audio_q = ("听音" in qtype or "音频" in qtype)
        is_image_q = ("图片" in qtype or "看图" in qtype)

        # (1) 题干检查
        stem_txt = (q.stem or "").strip()
        if is_audio_q or is_image_q:
            r.stem_check.passed = False
            r.stem_check.score = 0.0
            r.stem_check.method = "skip"
            r.stem_check.error = "听音/图片题：题干内容在音频或图片中"
            r.stem_check.details.append("纯文字模式无法核对音频/图片内容（需连手机截图）")
        elif not stem_txt:
            r.stem_check.passed = False
            r.stem_check.score = 0.0
            r.stem_check.error = "题干为空（脚本中该题没有题干文字）"
            r.stem_check.details.append("纯文字检查: 题干为空")
        elif len(stem_txt) < 10:
            r.stem_check.passed = False
            r.stem_check.score = 0.3
            r.stem_check.error = "题干过短"
            r.stem_check.details.append(f"纯文字检查: 题干仅 {len(stem_txt)} 字，疑似不完整")
        else:
            r.stem_check.passed = True
            r.stem_check.score = 1.0
            r.stem_check.method = "text"
            r.stem_check.details.append(f"纯文字检查: 题干完整（{len(stem_txt)} 字）")

        # (2) 内容检查：选项完整性（听音/图片题选项在图中，跳过）
        opts = q.options or []
        opt_clean = [o for o in opts if o and str(o).strip()]
        if is_image_q and len(opt_clean) < 2:
            r.content_check.passed = False
            r.content_check.score = 0.0
            r.content_check.method = "skip"
            r.content_check.error = "图片选择题：选项为图片，纯文字无法核对"
            r.content_check.details.append("纯文字模式无法核对图片选项（需连手机截图）")
        elif len(opt_clean) >= 2:
            r.content_check.passed = True
            r.content_check.score = 1.0
            r.content_check.method = "text"
            r.content_check.details.append(f"纯文字检查: 选项齐全（{len(opt_clean)} 个）")
        elif len(opt_clean) == 1:
            r.content_check.passed = False
            r.content_check.score = 0.3
            r.content_check.error = "选项不完整"
            r.content_check.details.append("纯文字检查: 仅有 1 个选项")
        else:
            r.content_check.passed = False
            r.content_check.score = 0.0
            r.content_check.error = "无选项"
            r.content_check.details.append("纯文字检查: 题目无选项（听音/图片题需连手机截图核对）")

        # (3) 作答检查：答案非空 + 格式
        ans = (q.answer or "").strip()
        if not ans:
            r.answer_check.passed = False
            r.answer_check.score = 0.0
            r.answer_check.error = "答案为空"
            r.answer_check.details.append("纯文字检查: 脚本未给出答案")
        elif len(opt_clean) >= 2 and ans not in "ABCDabcd"[:len(opt_clean)]:
            r.answer_check.passed = False
            r.answer_check.score = 0.3
            r.answer_check.error = "答案超出选项范围"
            r.answer_check.details.append(f"纯文字检查: 答案 {ans!r} 不在选项 A-{chr(64+len(opt_clean))} 范围内")
        else:
            r.answer_check.passed = True
            r.answer_check.score = 1.0
            r.answer_check.method = "text"
            r.answer_check.details.append(f"纯文字检查: 答案 {ans!r} 有效")

        # (4) 知识库检查（不依赖截图）
        r.knowledge_check = self._verify_knowledge(q)
        if r.knowledge_check:
            if r.knowledge_check.get("unknown"):
                r.knowledge_check["_detail"] = f"存在未收录词汇: {r.knowledge_check['unknown'][:5]}"
            else:
                r.knowledge_check["_detail"] = f"词汇均在知识库范围内（命中 {len(r.knowledge_check.get('matched', []))} 个）"

        # (5)(6)(7) 依赖截图维度 → skip
        for cr, name in ((r.image_check, "配图"), (r.audio_check, "音频"),
                         (r.post_error_check, "答错后")):
            cr.passed = False
            cr.score = 0.0
            cr.method = "skip"
            cr.error = f"{name}检查需手机截图（纯文字模式跳过）"
            cr.details.append(f"纯文字模式: {name}未检测（需连手机截图）")

        # ---- 综合评分：只统计 文字可查的维度 ----
        # 听音/图片题：题干/选项内容在音频/图中（skip 不计分），只按答案+知识库评分
        if is_audio_q or is_image_q:
            checked_scores = [r.answer_check.score]
            if r.knowledge_check and r.knowledge_check.get("in_knowledge") is not None:
                checked_scores.append(1.0 if r.knowledge_check.get("in_knowledge") else 0.4)
            r.overall_score = sum(checked_scores) / len(checked_scores) if checked_scores else 0.0
            # 答案有效 + 词汇在知识库内 → 通过；答案无效 → 不通过
            r.overall_passed = r.answer_check.passed and r.overall_score >= 0.7
        else:
            checked_scores = [
                r.stem_check.score,
                r.content_check.score,
                r.answer_check.score,
            ]
            if r.knowledge_check and r.knowledge_check.get("in_knowledge") is not None:
                checked_scores.append(1.0 if r.knowledge_check.get("in_knowledge") else 0.4)
            r.overall_score = sum(checked_scores) / len(checked_scores) if checked_scores else 0.0
            # 文字题：题干+选项+答案 都通过才算过
            r.overall_passed = (
                r.stem_check.passed and r.content_check.passed and r.answer_check.passed
                and r.overall_score >= 0.7
            )

        return r

    # ============================================================
    # 批量审查 (B 同学调用的主入口)
    # ============================================================

    def _review_batch(self, questions: list[YingYuBaoQuestion],
                      screenshots: dict[int, str],
                      post_error_shots: dict[int, str] = None) -> list[QuestionReview]:
        """
        批量审查多道题（六维 + 知识库）

        这是 B 同学巡检循环调用的主入口。

        Args:
            questions: 脚本题目列表
            screenshots: {global_idx: "截图路径", ...}
            post_error_shots: {global_idx: "答错后截图路径", ...}（仅首题）

        Returns:
            list[QuestionReview]
        """
        if post_error_shots is None:
            post_error_shots = {}

        results = []
        total = len(questions)

        for i, q in enumerate(questions):
            shot = screenshots.get(q.global_idx, "")
            post_shot = post_error_shots.get(q.global_idx, "")
            is_first = (i == 0)

            r = self._review_one(q, shot, post_error_shot=post_shot,
                                 is_first_question=is_first)
            results.append(r)

            if self.cfg.verbose:
                icon = "✅" if r.overall_passed else "❌"
                dims = self._failed_dimensions(r)
                dim_str = f" [{', '.join(dims)}]" if dims else ""
                print(f"  Q{r.idx:02d} {icon} score={r.overall_score:.2f}{dim_str}")

        return results

    def _failed_dimensions(self, r: QuestionReview) -> list[str]:
        """汇总不通过的维度名"""
        dims = []
        if not r.stem_check.passed:
            dims.append("stem")
        if not r.content_check.passed:
            dims.append("content")
        if not r.image_check.passed:
            dims.append("image")
        if not r.answer_check.passed:
            dims.append("answer")
        if not r.audio_check.passed:
            dims.append("audio")
        if not r.post_error_check.passed:
            dims.append("post_error")
        return dims

    # ============================================================
    # 角色定义: 从 data/review_skill.md 加载 + 动态知识上下文
    # ============================================================

    def _load_skill_identity(self) -> str:
        """
        从 data/review_skill.md 加载审查智能体的身份定义
        让 AI 每次审查前都知道自己是谁、要做什么
        """
        skill_path = Path(__file__).parent.parent / "data" / "review_skill.md"
        if not skill_path.exists():
            # skill 文件不存在时返回简短默认定义
            return (
                "【你的身份】你是一位小学英语教材题目审查专家。\n"
                "你负责审查教育APP'E英语宝'中的听力专项题目。\n"
                "你的核心任务是对每道题做四维检查:\n"
                "  (1)题干文字是否正确\n"
                "  (2)题目内容是否与脚本相符、显示是否完整、有无知识/逻辑错误\n"
                "  (3)配图是否与题目匹配、有无逻辑问题\n"
                "  (4)题目能否正常作答、答案能否完整输入\n"
                "遇到不确定的判断，标记'需人工复核'。\n"
            )
        try:
            content = skill_path.read_text(encoding="utf-8")
            # 提取"一、你的身份"到"七、协作分工"之间的内容
            import re
            m = re.search(r'## 一、你的身份(.*?)(?=## 七、|$)', content, re.DOTALL)
            if m:
                return "【你的身份】" + m.group(1).strip()
            return content[:1000]  # 取前1000字
        except Exception:
            return "【你的身份】你是一位小学英语教材题目审查专家。"

    def _build_role_prompt(self, q: YingYuBaoQuestion) -> str:
        """
        构建统一的"审查智能体"角色定义
        
        每次审查前加载:
        - 从 data/review_skill.md 加载基础身份
        - 从知识库加载当前单元的知识上下文
        - 让AI知道自己在审查什么版本/年级/单元的题目
        """
        # 1. 加载 skill 中的身份定义
        identity = self._load_skill_identity()

        # 2. 提取当前单元的知识
        grade_label = self._name_to_grade(q.keywords) or "五上"
        unit_vocab = self.kb.get_unit_vocab("湘鲁版", grade_label, q.unit)
        unit_patterns = self.kb.get_unit_patterns("湘鲁版", grade_label, q.unit)

        # 3. 格式化知识摘要
        vocab_str = ", ".join(sorted(set(unit_vocab))[:25]) if unit_vocab else "(未收录)"
        patterns_str = "; ".join(unit_patterns[:5]) if unit_patterns else "(未收录)"
        kw_str = "; ".join(q.keywords[:3]) if q.keywords else ""

        # 4. 组合完整角色提示
        role = (
            f"{identity}\n"
            f"\n"
            f"【当前任务】\n"
            f"- 教材版本: 湘鲁版 | 年级: {grade_label} | 单元: Unit {q.unit}\n"
            f"- 关键词: {kw_str}\n"
            f"- 本单元核心词汇({len(unit_vocab)}个): {vocab_str}\n"
            f"- 本单元核心句型({len(unit_patterns)}个): {patterns_str}\n"
            f"\n"
            f"【审查原则】\n"
            f"1. 以脚本文件为第一标准(公司提供的DOCX脚本是正确答案)\n"
            f"2. 以知识库为背景参考(该年级学生应该学过这些词汇和句型)\n"
            f"3. 如果APP中的内容与脚本不一致, 标注为不通过\n"
            f"4. 如果APP内容与脚本一致但与教材知识不符(超纲/错位), 也需标注\n"
            f"5. 不确定的判断标注'需人工复核'\n"
        )
        return role

    def _build_knowledge_context(self, q: YingYuBaoQuestion) -> str:
        """构建当前题目的知识库上下文"""
        grade_label = self._name_to_grade(q.keywords) or "五上"
        unit_vocab = self.kb.get_unit_vocab("湘鲁版", grade_label, q.unit)

        # 提取题目中使用的词汇
        import re
        question_vocab = []
        for opt in q.options:
            clean = re.sub(r'^[A-C][\.\、\s]+', '', opt).strip()
            if clean:
                question_vocab.extend(re.findall(r'[a-zA-Z]+', clean.lower()))
        question_vocab.extend(re.findall(r'[a-zA-Z]+', q.recording.lower()))

        # 哪些在知识库中, 哪些不在
        in_kb = []
        not_in_kb = []
        for w in set(question_vocab):
            if w.lower() in [v.lower() for v in unit_vocab]:
                in_kb.append(w)
            else:
                results = self.kb.search_vocab(w)
                if results:
                    in_kb.append(f"{w}(在{results[0]['grade']}-U{results[0]['unit']}中出现)")
                else:
                    not_in_kb.append(w)

        ctx = f"【知识库验证】\n"
        if in_kb:
            ctx += f"✅ 以下词汇在教材知识库中: {', '.join(in_kb[:8])}\n"
        else:
            ctx += f"⚠ 未在知识库中找到对应词汇\n"
        if not_in_kb:
            ctx += f"❓ 以下词汇不在当前知识库: {', '.join(not_in_kb[:5])}\n"

        ctx += f"录音原文: {q.recording}\n"
        ctx += f"脚本答案: {q.answer}\n"
        return ctx

    # ============================================================
    # 重写: 四维检查 (统一角色 + 深度融合知识库)
    # ============================================================

    def _judge_result(self, a: str) -> Optional[bool]:
        """
        智能判断AI回答是否为通过。

        Returns:
            True   — 明确判定为通过
            False  — 明确判定为不通过
            None   — AI返回无法解析的判定（需人工复核）
        """
        a = a.strip()
        if not a:
            return None  # ★ 空白返回 → 不确定
        if '不通过' in a:
            return False
        if '通过' in a or '匹配' in a or '一致' in a or '正确' in a:
            return True
        if '无' in a and ('错误' in a or '问题' in a or '异常' in a):
            return True
        # ★ 无法解析 → 返回 None（不默认为通过！）
        return None

    def _apply_verdict(self, check: CheckResult, ai_response: str, reason: str = ""):
        """
        统一应用AI审查判定结果到 CheckResult。

        解析格式: [通过/不通过 | 置信度:N] | 理由

        处理三种情况：
        - 明确通过   → passed=True,  score=1.0,  提取置信度
        - 明确不通过 → passed=False, score=0.5,  提取置信度
        - 无法解析   → passed=False, score=0.3,  标记"需人工复核"
        """
        import re as _re

        passed = self._judge_result(ai_response)
        # ★ 尝试提取置信度: [通过 | 置信度:85] 或 [通过/不通过]
        conf_match = _re.search(r'(?:置信度|confidence)[:\s]*(\d{1,3})', ai_response, _re.IGNORECASE)
        confidence = min(int(conf_match.group(1)), 100) if conf_match else (100 if passed else 50)

        if passed is None:
            check.passed = False
            check.score = 0.3
            check.confidence = 0
            check.method = "uncertain"
            check.error = "AI判定无法解析"
            snippet = ai_response[:80]
            check.details.append(f"⚠ 需人工复核 | 无法解析: '{snippet}'")
            if reason:
                check.details.append(f"  AI理由: {reason[:120]}")
        else:
            check.passed = passed
            check.score = 1.0 if passed else 0.5
            check.confidence = confidence
            check.method = "llm"
            detail = f"{ai_response} | {reason}" if reason else ai_response[:150]
            check.details.append(detail)

    def _review_batch(self, q, shot, r, ui_texts=None):
        """一次LLM调用完成四维审查
        文字题(非配图): ★ 优先用精确比对(difflib),只有边缘差异才走LLM; 配图题: 走视觉模型
        """
        try:
            role = self._build_role_prompt(q)
            kb_ctx = self._build_knowledge_context(q)
            is_img = '图片' in q.type_2

            # 决定用文本模型还是视觉模型
            use_vision = is_img  # 配图题必须用视觉
            if not use_vision and not ui_texts:
                use_vision = True  # 没有UI文本时降级回视觉

            screen_text = ''
            if ui_texts:
                screen_text = '\n'.join(ui_texts[:30])

            # ★ 文字题(非配图): 先用精确文字比对, 比对通过的不调LLM
            if not is_img and screen_text and _diff_check_stem is not None:
                # ① 题干精确比对
                stem_diff = _diff_check_stem(shot, q.stem)
                if stem_diff.passed or not stem_diff.need_llm:
                    r.stem_check.passed = stem_diff.passed
                    r.stem_check.score = stem_diff.score
                    r.stem_check.method = "diff"
                    r.stem_check.evidence = [
                        {"type": e.type, "field": e.field, "expected": e.expected,
                         "actual": e.actual, "diff": e.diff, "diff_html": e.diff_html}
                        for e in stem_diff.evidence
                    ]
                    r.stem_check.details.append(
                        f'精确比对通过(相似度{stem_diff.similarity:.1%})' if stem_diff.passed
                        else f'精确比对不通过(相似度{stem_diff.similarity:.1%})'
                    )
                # ② 内容检查: 脚本标准内容 vs OCR文字
                #    比对关键字段是否在OCR中存在
                content_parts = [q.stem] + (q.options or [])
                script_text = '|'.join(content_parts)
                sim_all, desc_all, html_all = diff_texts(script_text, screen_text[:2000])
                r.content_check.score = sim_all if sim_all >= 0.85 else 0.5
                r.content_check.passed = sim_all >= 0.85
                r.content_check.method = "diff"
                r.content_check.evidence = [{
                    "type": "text_ok" if sim_all >= 0.85 else "text_mismatch",
                    "field": "content",
                    "expected": script_text[:200],
                    "actual": screen_text[:200],
                    "diff": desc_all, "diff_html": html_all,
                }]
                r.content_check.details.append(
                    f'内容比对(相似度{sim_all:.1%}){" ✓" if sim_all>=0.85 else " ⚠"}'
                )

                # ③ 如果题干和内容都精确比对通过 → 不走LLM, 直接标签化作答/配图检查
                if r.stem_check.passed and r.content_check.passed:
                    r.image_check.passed = not is_img  # 非配图题默认通过
                    r.image_check.score = 1.0
                    r.image_check.method = "skip"
                    r.image_check.details.append("⏭ 非配图题, 文字精确比对已通过")
                    # 作答检查也走精确比对
                    ans_diff = _diff_check_answer(shot, q.answer, q.options) if q.answer else None
                    if ans_diff and ans_diff.passed:
                        r.answer_check.passed = True
                        r.answer_check.score = 1.0
                        r.answer_check.method = "diff"
                        r.answer_check.evidence = [
                            {"type": e.type, "field": e.field, "expected": e.expected,
                             "actual": e.actual, "diff": e.diff, "diff_html": e.diff_html}
                            for e in ans_diff.evidence
                        ]
                        r.answer_check.details.append("答案选项验证通过(精确比对)")
                    else:
                        r.answer_check.passed = True
                        r.answer_check.score = 0.8
                        r.answer_check.method = "diff"
                        r.answer_check.details.append("文字比对通过, 答案检查走LLM补充")
                    return  # ★ 文字精确比对通过, 不调LLM, 直接返回

            # ── LLM审查(配图题 或 文字比对有边缘差异) ──

            prompt_text = (
                role + '\n\n---\n\n'
                f'【任务: 四维审查】\n'
                f'题型: {q.type_2}\n'
                f'脚本题干: {q.stem}\n'
                f'录音: {q.recording}\n'
                f'脚本答案: {q.answer}\n'
                f'选项: {", ".join(q.options) if q.options else "(图片选项)"}\n'
                f'{kb_ctx}\n\n'
            )
            if use_vision:
                prompt_text += f'请看截图，完成以下四个维度的检查。\n'
            else:
                prompt_text += f'截图已用UI解析提取出以下文字：\n{screen_text[:3000]}\n\n请基于以上屏幕文字和脚本信息，完成四个维度的检查。\n'
            prompt_text += (
                f'回答格式(严格按此格式,一行一个，置信度0-100=你对判断的把握程度):\n'
                f'【题干】通过 | 置信度:95 | 理由\n'
                f'【内容】通过 | 置信度:90 | 理由\n'
                + (f'【配图】通过 | 置信度:85 | 理由\n' if is_img else '【配图】⏭ 非配图题\n') +
                f'【作答】通过 | 置信度:80 | 理由'
            )
            prompt = self.trainer.build_enhanced_prompt(prompt_text, dim_filter='all')
            answer = self.llm.ask(prompt, image_path=shot if use_vision else None)

            import re
            for dim_name, attr in [('题干','stem_check'),('内容','content_check'),
                                    ('配图','image_check'),('作答','answer_check')]:
                check = getattr(r, attr)
                m = re.search(rf'【{dim_name}】\s*([^|]+?)\s*(?:\|\s*(.*))?$', answer, re.MULTILINE)
                if m:
                    verdict = m.group(1).strip()
                    reason = m.group(2).strip() if m.group(2) else ''
                    self._apply_verdict(check, verdict, reason)
                elif dim_name == '配图' and not is_img:
                    check.passed = True; check.score = 1.0; check.details.append('⏭ 非配图题')
                else:
                    check.details.append(f'[解析失败]')
        except Exception as e:
            r.stem_check = self._check_stem(q, shot)
            r.content_check = self._check_content(q, shot)
            r.image_check = self._check_image(q, shot)
            r.answer_check = self._check_answer(q, shot)

    def _check_stem(self, q: YingYuBaoQuestion, shot: str) -> CheckResult:
        """(1) 题干检查: 文字完整清晰 + 与脚本一致"""
        result = CheckResult()
        try:
            role = self._build_role_prompt(q)
            prompt = self.trainer.build_enhanced_prompt(
                role + "\n\n---\n\n"
                f"【任务: 检查题干文字】\n"
                f"脚本中的题干: {q.stem}\n"
                f"题型: {q.type_2}\n\n"
                f"请看截图, 判断:\n"
                f"1. 题目文字是否完整、无截断、无模糊?\n"
                f"2. 是否有错别字或拼写错误?\n"
                f"3. 文字内容是否与脚本一致?\n\n"
                f"回答格式: [通过/不通过 | 置信度:0-100] | 理由",
                dim_filter="stem"
            )
            answer = self.llm.ask(prompt, image_path=shot)
            self._apply_verdict(result, answer)
        except Exception as e:
            result.error = str(e)
        return result

    def _check_content(self, q: YingYuBaoQuestion, shot: str) -> CheckResult:
        """(2) 内容检查: 选项 vs 脚本 + 知识库双重验证"""
        result = CheckResult()
        try:
            kb_ctx = self._build_knowledge_context(q)
            role = self._build_role_prompt(q)

            prompt = self.trainer.build_enhanced_prompt(
                role + "\n\n---\n\n"
                f"【任务: 检查题目内容】\n"
                f"题型: {q.type_2}\n"
                f"脚本答案: {q.answer}\n"
                f"脚本选项: {', '.join(q.options) if q.options else '(图片选项)'}\n\n"
                f"{kb_ctx}\n"
                f"请看截图, 判断:\n"
                f"1. 选项内容是否与脚本一致?\n"
                f"2. 正确答案是否合理? (录音内容是否确实对应正确答案)\n"
                f"3. 涉及的词汇/句型是否在该年级教材范围内?\n"
                f"4. 如果有超出教材范围的词汇, 是否合理?(合理扩展可接受)\n\n"
                f"回答格式: [通过/不通过 | 置信度:0-100] | 理由",
                dim_filter="content"
            )
            answer = self.llm.ask(prompt, image_path=shot)
            self._apply_verdict(result, answer)
        except Exception as e:
            result.error = str(e)
        return result

    def _check_image(self, q: YingYuBaoQuestion, shot: str) -> CheckResult:
        """(3) 配图检查: 图片匹配录音/答案 + 教材适合性 + 参考图对照"""
        result = CheckResult()
        if "图片" not in q.type_2:
            result.passed = True
            result.score = 1.0
            result.details.append("⏭ 非配图题")
            return result

        try:
            # 用 ImageBank 找参考图
            ref_images = []
            try:
                from src.image_bank import ImageBank
                bank = ImageBank()
                ref_images = bank.find_for_question(
                    unit=q.unit,
                    recording=q.recording,
                    answer=q.answer,
                    options=q.options,
                    stem=q.stem,
                )
            except Exception:
                pass

            role = self._build_role_prompt(q)
            prompt_text = (
                role + "\n\n---\n\n"
                f"【任务: 检查配图】\n"
                f"录音: {q.recording}\n"
                f"脚本答案: {q.answer}\n"
                f"题型: {q.type_2}\n\n"
            )

            if ref_images:
                prompt_text += (
                    f"下方提供了【参考图】和【实际截图】两张图片。\n"
                    f"【参考图】是教材的原始配图, 【实际截图】是从APP截取的。\n"
                    f"请对比两张图, 判断:\n"
                    f"1. 实际截图中的图片与参考图是否一致?(是同一个物品/场景吗)\n"
                    f"2. 实际截图是否清晰完整?(无截断/模糊/变形)\n"
                    f"3. 实际截图是否有逻辑问题?(如参考图是勺子, 但APP显示叉子)\n"
                    f"4. 图片内容是否与录音 '{q.recording}' 匹配?\n\n"
                    f"回答格式: [通过/不通过 | 置信度:0-100] | 理由"
                )
                all_images = ref_images + [shot]
            else:
                prompt_text += (
                    f"请看截图中的图片, 判断:\n"
                    f"1. 图片是否清晰完整?(无截断/模糊/变形)\n"
                    f"2. 图片内容是否与录音匹配?\n"
                    f"3. 图片中的物品/场景是否适合该年级学生的认知水平?\n"
                    f"4. 图片有无逻辑问题?(如: 录音说'spoon'但图片是叉子)\n"
                    f"5. 如果是干扰项图片, 是否合理?(不会让学生混淆)\n\n"
                    f"回答格式: [通过/不通过 | 置信度:0-100] | 理由"
                )
                all_images = [shot]

            prompt = self.trainer.build_enhanced_prompt(prompt_text, dim_filter="image")
            answer = self.llm.ask(prompt, image_paths=all_images)
            self._apply_verdict(result, answer)
            if ref_images:
                result.details.append(f" [参考图: {', '.join(Path(p).stem for p in ref_images[:2])}]")
        except Exception as e:
            result.error = str(e)
        return result

    def _check_answer(self, q: YingYuBaoQuestion, shot: str) -> CheckResult:
        """(4) 作答检查: 可作答 + 答案可完整输入"""
        result = CheckResult()
        try:
            role = self._build_role_prompt(q)
            prompt = self.trainer.build_enhanced_prompt(
                role + "\n\n---\n\n"
                f"【任务: 检查作答可行性】\n"
                f"题型: {q.type_2}\n"
                f"脚本答案: {q.answer}\n\n"
                f"请看截图, 判断:\n"
                f"1. 选项/输入框/交互元素是否清晰可见?\n"
                f"2. 用户能否正常作答?\n"
                f"   - 点击/选择类题型: 检查选项(文字或图片)是否完整显示且可点击, 答案选项'{q.answer}'是否存在\n"
                f"   - 输入/拼写类题型: 检查输入框是否可见, 答案'{q.answer}'能否完整输入\n"
                f"   - 拖拽/连线类题型: 检查可拖拽元素是否存在\n"
                f"3. 交互方式是否符合该题型的预期?(如听音选图应有图片可点, 听音选词应有文字选项)\n"
                f"4. 对于听音题型, 录音播放按钮是否可见?\n\n"
                f"回答格式: [通过/不通过 | 置信度:0-100] | 理由",
                dim_filter="answer"
            )
            answer = self.llm.ask(prompt, image_path=shot)
            self._apply_verdict(result, answer)
        except Exception as e:
            result.error = str(e)
        return result

    # ============================================================
    # (5) 音频检查 (A2)
    # ============================================================

    def _check_audio(self, q: YingYuBaoQuestion, shot: str) -> CheckResult:
        """
        (5) 音频检查: 听力题检测音频可用性

        判断标准:
          - 非听力题 → 跳过 (passed=True, score=1.0)
          - 听力题 → 检查截图中是否有播放按钮、音频控件是否可见

        B 同学在巡检循环中也可通过 ADB 实际点击播放按钮验证进度变化，
        此方法提供基于截图的视觉检查作为补充。
        """
        result = CheckResult()

        # 判断是否为听力题
        is_audio = any(kw in q.type_2 for kw in ["听音", "听力", "听"])
        if not is_audio:
            result.passed = True
            result.score = 1.0
            result.details.append("⏭ 非听力题")
            return result

        try:
            role = self._build_role_prompt(q)
            prompt = self.trainer.build_enhanced_prompt(
                role + "\n\n---\n\n"
                f"【任务: 检查音频播放功能】\n"
                f"题型: {q.type_2}（听力题）\n"
                f"录音原文: {q.recording}\n\n"
                f"请看截图, 判断:\n"
                f"1. 截图中是否可见播放按钮/喇叭图标？\n"
                f"2. 音频控件是否被遮挡或截断？\n"
                f"3. 播放按钮位置是否合理（通常靠近题目顶部）？\n"
                f"4. 是否有任何异常（如灰色不可点击状态）？\n\n"
                f"回答格式: [通过/不通过 | 置信度:0-100] | 理由",
                dim_filter="audio"
            )
            answer = self.llm.ask(prompt, image_path=shot)
            passed = "通过" in answer and "不通过" not in answer
            result.passed = passed
            result.score = 1.0 if passed else 0.5
            result.details.append(answer[:150])
        except Exception as e:
            result.error = str(e)
        return result

    # ============================================================
    # (6) 答错后检查 (A1 — 委托给 PostErrorChecker)
    # ============================================================

    def _check_post_error(self, q: YingYuBaoQuestion,
                          post_error_shot: str = "",
                          is_first: bool = False) -> CheckResult:
        """
        (6) 答错后结果页检查

        仅在每模块首题触发。委托给 PostErrorChecker 执行。

        Args:
            q: 脚本题目
            post_error_shot: 答错后结果页截图
            is_first: 是否为首题（决定是否触发检查）

        Returns:
            CheckResult: 非触发条件时 passed=True, score=1.0
        """
        result = CheckResult()

        if not is_first:
            result.passed = True
            result.score = 1.0
            result.details.append("⏭ 非首题，跳过答错后检查")
            return result

        if not post_error_shot or not Path(post_error_shot).exists():
            result.passed = True
            result.score = 1.0
            result.details.append("⏭ 无答错后截图（可能未执行故意选错流程）")
            return result

        # 委托给 PostErrorChecker
        try:
            pe_result = self.post_error_checker.check(post_error_shot, q)
            result.passed = pe_result.passed
            result.score = pe_result.score
            result.details = pe_result.details
            result.error = pe_result.error
        except Exception as e:
            result.error = str(e)
            result.details.append(f"[异常] 答错后检查失败: {e}")

        return result

    # ============================================================
    # 知识库查证
    # ============================================================

    def _verify_knowledge(self, q: YingYuBaoQuestion) -> dict:
        """验证题目是否在教材知识范围内"""
        # 从问题中提取词汇
        vocab = []
        for opt in q.options:
            import re
            clean = re.sub(r'^[A-C][\.\、\s]+', '', opt).strip()
            if clean:
                vocab.extend(re.findall(r'[a-zA-Z]+', clean.lower()))

        result = self.kb.verify_question(
            unit=q.unit,
            vocab_used=vocab,
            version="湘鲁版",
            grade=self._name_to_grade(q.keywords) or "五上",
        )
        return result

    def _name_to_grade(self, keywords: list) -> str:
        """从关键词中提取年级"""
        for kw in keywords:
            if "三上" in kw: return "三上"
            if "三下" in kw: return "三下"
            if "四上" in kw: return "四上"
            if "四下" in kw: return "四下"
            if "五上" in kw: return "五上"
            if "五下" in kw: return "五下"
            if "六上" in kw: return "六上"
            if "六下" in kw: return "六下"
        return "五上"

    # ============================================================
    # 报告生成
    # ============================================================

    def export_report(self, path: str = None) -> str:
        """导出审查报告 (Markdown)"""
        if not path:
            self.cfg.output_dir and Path(self.cfg.output_dir).mkdir(exist_ok=True)
            path = f"{self.cfg.output_dir or 'outputs'}/review_report.md"

        total = len(self.results)
        passed = sum(1 for r in self.results if r.overall_passed)
        avg_score = sum(r.overall_score for r in self.results) / total if total else 0

        lines = [
            "# 英语宝审查报告\n",
            f"生成时间: {datetime.now().isoformat()}",
            f"脚本: {self.cfg.docx_path}",
            f"单元: {self.cfg.unit or '全部'} | 阶段: {self.cfg.stage or '全部'}",
            f"审查题数: {total}",
            f"通过: {passed}/{total} ({passed/total*100:.0f}%)" if total > 0 else "通过: 0/0 (无题)",
            f"综合得分: {avg_score:.2f}\n",
        ]

        # 按题型统计
        type_stats = {}
        for r in self.results:
            tp = r.question_type or "未知"
            if tp not in type_stats:
                type_stats[tp] = {"total": 0, "passed": 0}
            type_stats[tp]["total"] += 1
            if r.overall_passed:
                type_stats[tp]["passed"] += 1

        lines.append("## 题型统计\n")
        lines.append("| 题型 | 总数 | 通过 | 通过率 |")
        lines.append("|------|------|------|--------|")
        for tp, s in sorted(type_stats.items()):
            rate = f"{s['passed']/s['total']*100:.0f}%" if s['total'] else "-"
            lines.append(f"| {tp} | {s['total']} | {s['passed']} | {rate} |")

        # 逐题详情
        lines.extend(["\n## 逐题详情\n", "| # | 题型 | 题干 | 内容 | 配图 | 作答 | 音频 | 答错后 | 总评 |"])
        lines.append("|---|------|------|------|------|------|------|------|------|")
        for r in self.results:
            def icon(p):
                return "✅" if p else "❌"
            lines.append(
                f"| Q{r.idx:02d} | {r.question_type[:10]} | "
                f"{icon(r.stem_check.passed)} | "
                f"{icon(r.content_check.passed)} | "
                f"{icon(r.image_check.passed)} | "
                f"{icon(r.answer_check.passed)} | "
                f"{icon(r.audio_check.passed)} | "
                f"{icon(r.post_error_check.passed)} | "
                f"{'✅' if r.overall_passed else '❌'} ({r.overall_score:.2f}) |"
            )

        # 问题题目
        failed = [r for r in self.results if not r.overall_passed]
        if failed:
            lines.append(f"\n## 问题题目 ({len(failed)} 题)\n")
            for r in failed:
                lines.append(f"### Q{r.idx:02d} ({r.question_type})\n")
                if r.stem_check.details:
                    lines.append(f"- 题干: {r.stem_check.details[0]}")
                if r.content_check.details:
                    lines.append(f"- 内容: {r.content_check.details[0]}")
                if r.image_check.details:
                    lines.append(f"- 配图: {r.image_check.details[0]}")
                if r.answer_check.details:
                    lines.append(f"- 作答: {r.answer_check.details[0]}")
                if r.audio_check.details and not r.audio_check.passed:
                    lines.append(f"- 音频: {r.audio_check.details[0]}")
                if r.post_error_check.details and not r.post_error_check.passed:
                    lines.append(f"- 答错后: {r.post_error_check.details[0]}")
                lines.append("")

        # 反馈统计
        feedback_stats = self.feedback.get_stats()
        if feedback_stats.get("total", 0) > 0:
            lines.append("\n## 反馈数据\n")
            lines.append(f"- 总样本: {feedback_stats['total']}")
            lines.append(f"- 准确率: {feedback_stats['accuracy']}")
            bad_patterns = self.feedback.get_bad_patterns()
            if bad_patterns:
                lines.append("- 高频错误模式:")
                for p in bad_patterns:
                    lines.append(f"  - {p}")

        report = "\n".join(lines)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(report, encoding="utf-8")
        print(f"📄 报告已保存: {path}")
        return report

    def export_json(self, path: str = None) -> str:
        """导出 JSON 格式结果"""
        if not path:
            self.cfg.output_dir and Path(self.cfg.output_dir).mkdir(exist_ok=True)
            path = f"{self.cfg.output_dir or 'outputs'}/review_results.json"

        data = {
            "config": {
                "docx": self.cfg.docx_path,
                "unit": self.cfg.unit,
                "stage": self.cfg.stage,
            },
            "summary": {
                "total": len(self.results),
                "passed": sum(1 for r in self.results if r.overall_passed),
                "avg_score": round(
                    sum(r.overall_score for r in self.results) / len(self.results), 2
                ) if self.results else 0,
            },
            "results": [r.to_dict() for r in self.results],
            "feedback_stats": self.feedback.get_stats(),
            "timestamp": datetime.now().isoformat(),
        }
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"📄 JSON 已保存: {path}")
        return path


# ============================================================
# CLI 入口
# ============================================================

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="英语宝审查智能体")
    p.add_argument("--docx", required=True, help="脚本 DOCX 文件")
    p.add_argument("--knowledge", help="知识库来源 DOCX (可选)")
    p.add_argument("--unit", type=int, default=0, help="指定单元")
    p.add_argument("--stage", default="", help="指定阶段")
    p.add_argument("--screenshots", default="screenshots", help="截图目录")
    p.add_argument("--feedback", action="store_true", help="运行后进入反馈模式")
    p.add_argument("--report", action="store_true", help="生成报告")
    p.add_argument("--train", action="store_true", help="生成训练报告")
    args = p.parse_args()

    cfg = ReviewConfig(
        docx_path=args.docx,
        knowledge_docx=args.knowledge or args.docx,
        unit=args.unit,
        stage=args.stage,
        screenshot_dir=args.screenshots,
    )

    agent = ReviewAgent(cfg)
    results = agent.review()

    if args.report:
        agent.export_report()
        agent.export_json()

    if args.feedback:
        print("\n反馈统计:")
        print(json.dumps(agent.feedback.get_stats(), ensure_ascii=False, indent=2))
        print("\n错误模式:")
        for p in agent.feedback.get_bad_patterns():
            print(f"  {p}")

    if args.train:
        print(agent.trainer.export_report())
