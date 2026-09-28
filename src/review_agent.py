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

import sys, json, time, re
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
    unit: object = 0                  # 0/None=全部；int=单个(6)；str 支持 "2,4"、"2-4"、"2,4-6"；list=[2,4]
    stage: str = ""                   # 空=全部, "基础巩固"/"综合进阶"/"难点突破"
    screenshot_dir: str = "screenshots"
    output_dir: str = "outputs"
    verbose: bool = True              # 打印详细信息


def normalize_units(u) -> Optional[set]:
    """把 unit 配置归一化成单元集合 set[int]；0/None/""/"NONE" → None(全部)。

    支持: int(6) / str("6") / str("2,4") / str("2-4") / str("2,4-6") / list([2,4])
    """
    if u is None:
        return None
    if isinstance(u, int):
        return {u} if u > 0 else None
    if isinstance(u, (list, tuple, set)):
        nums = {int(x) for x in u if str(x).lstrip("-").isdigit() and int(x) > 0}
        return nums or None
    s = str(u).strip()
    if not s or s.upper() in ("0", "NONE", "全部"):
        return None
    out = set()
    for part in s.split(","):
        part = part.strip()
        mm = re.match(r"^(\d+)(?:\s*[-~]\s*(\d+))?$", part)
        if mm:
            lo = int(mm.group(1))
            hi = int(mm.group(2)) if mm.group(2) else lo
            out.update(range(lo, hi + 1))
    return out or None

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
    suggestion: str = ""               # ★ 针对该维度生成的"建议修改"文本（由 LLM 输出，供实时错题报告展示）

    def to_dict(self):
        return {"passed": self.passed, "score": self.score,
                "confidence": self.confidence,
                "details": self.details[:5], "error": self.error[:80],
                "evidence": self.evidence[:5], "method": self.method,
                "suggestion": self.suggestion}

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

# ★ 让 LLM 在判定"不通过"时顺带给出一句具体修改建议(供实时错题报告展示)
REVIEW_SUGGEST_SUFFIX = (
    "\n\n【修改建议要求】若某维度判定为“不通过”，请在该维度“理由”的同一行末尾，"
    "用「建议修改：」接一句具体的修改方法（例如：图片与脚本不符。建议修改：将配图替换为 cat 的正确图片）。"
    "通过的维度无需写建议修改。"
)

# ============================================================
# ★ 2026-09-17 新增：参考答案 ↔ 关键词 一致性（确定性规则，不依赖 LLM）
# ============================================================
# 背景（用户实测 教科五上U4 第4大题第3小题）：
#   参考答案：They should turn off the lights and take their raincoats.
#   关键词　：turn off the lights, bring their raincoats
#   → 同一表达一处用 take 一处用 bring，学生按关键词作答会被判错。
# 这类"字面不一致"用规则判定比 LLM 更快更准（零网络请求、零成本、100% 可复现）。
_KW_META = ("口语训练", "听力专项", "单元自检", "知识过关", "巧记单词", "语音评测",
            "全脑记词", "单词听写", "新湘少", "新湘鲁", "湘少", "湘鲁",
            "教科", "人教", "PEP", "教研", "年级", "上册", "下册",
            "四上", "四下", "五上", "五下", "六上", "六下", "三上", "三下",
            "适用年级", "编写年份", "技能", "认知目标", "主题")
_KW_SEP = re.compile(r"[,，、;；#|/]+")
_PLACEHOLDER_ANS = ("人工核查", "待人工", "未识别", "未知", "无法确定", "待确认")


def _norm_en(s: str) -> str:
    """英文归一化：小写、统一撇号、展开 (s)/(es) 复数标记、去标点、压空格。"""
    s = str(s or "").lower().replace("’", "'").replace("‘", "'")
    s = re.sub(r"\((?:s|es|s\)|es\))\)?", "s", s)   # window(s) / window(es) → windows
    s = re.sub(r"[^a-z0-9' ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def split_content_keywords(keywords) -> list:
    """把脚本「关键词」字段拆成英文内容短语，剔除模块名/单元号等元信息。

    脚本里 "关键词：口语训练#新教科五上U4"（元信息）与
    "关键词：turn off the lights, bring their raincoats"（内容）是同一字段，
    必须靠"是否含英文实词"区分，否则会把单元号当成待核对短语。
    """
    out = []
    for raw in (keywords or []):
        for part in _KW_SEP.split(str(raw)):
            p = part.strip()
            if len(p) < 2 or not re.search(r"[A-Za-z]", p):
                continue                                   # 纯中文 → 元信息
            if any(m in p for m in _KW_META):
                continue                                   # 含模块名/版本名 → 元信息
            if re.match(r"^[A-Za-z]\s*\d", p):              # U4 / U10
                continue
            out.append(p)
    seen, uniq = set(), []
    for p in out:
        k = _norm_en(p)
        if k and k not in seen:
            seen.add(k)
            uniq.append(p)
    return uniq


def _align_substitute(phrase: str, answer: str):
    """在答案里找与关键词短语最像的片段，返回 (替换对, 答案片段)。

    SequenceMatcher 的 'replace' 段正好给出"同位置换词"（bring → take），
    这正是要让 App/脚本方看到的那一处差异。
    """
    import difflib as _dl
    pw = _norm_en(phrase).split()
    aw = _norm_en(answer).split()
    if not pw or not aw:
        return [], ""
    n = len(pw)
    best_r, best_pairs, best_seg = 0.0, [], ""
    for i in range(0, max(1, len(aw) - n + 1)):
        win = aw[i:i + n] or aw[i:]
        sm = _dl.SequenceMatcher(None, pw, win)
        pairs = []
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "replace":
                pairs.append((pw[i1:i2], win[j1:j2]))
        if sm.ratio() > best_r:
            best_r, best_pairs, best_seg = sm.ratio(), pairs, " ".join(win)
    return best_pairs, best_seg


def check_answer_keyword_consistency(answer: str, keywords, passage: str = ""):
    """核对「参考答案」与「关键词」是否指向同一表达。

    返回 (problems, checked_count, sources)
      problems      : list[str]，每条是一句可直接写进错题卡的结论（空 = 一致）
      checked_count : 实际比对的关键词短语数；0 表示无可比对内容（调用方应标「未检」，
                      绝不能不吭声地跳过——用户明确要求"没有检查出来也要有检查"）
      sources       : {短语: [出现位置, ...]}，供报告展示佐证
    """
    _ans = str(answer or "").strip()
    if not _ans or any(p in _ans for p in _PLACEHOLDER_ANS):
        return [], 0, {}
    kws = split_content_keywords(keywords)
    if not kws:
        return [], 0, {}
    ans_n = _norm_en(_ans)
    psg_n = _norm_en(passage)
    problems, sources = [], {}
    for kw in kws:
        kw_n = _norm_en(kw)
        if not kw_n:
            continue
        where = []
        if re.search(rf"(?<![a-z]){re.escape(kw_n)}(?![a-z])", ans_n):
            where.append("参考答案")
        if psg_n and re.search(rf"(?<![a-z]){re.escape(kw_n)}(?![a-z])", psg_n):
            where.append("短文/听力材料")
        sources[kw] = where
        if "参考答案" in where:
            continue                                    # 命中 → 一致
        pairs, seg = _align_substitute(kw, _ans)
        if pairs:
            _detail = "；".join(
                f"{' '.join(a)} → {' '.join(b)}" for a, b in pairs if a and b)
            problems.append(
                f"关键词「{kw}」与参考答案不一致：答案里是「{seg}」"
                + (f"（{_detail}）" if _detail else "")
                + "，学生按关键词作答会被判错")
        elif not where:
            problems.append(
                f"关键词「{kw}」在参考答案《{_ans}》与短文/听力材料中均未出现 → 疑为关键词写错")
        else:
            problems.append(
                f"关键词「{kw}」只出现在{'/'.join(where)}中，参考答案用的是其它表达 → 前后用词不统一")
    return problems, len(kws), sources


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
        self.script_units: set = set()  # ★ 脚本实际包含的单元集合（供"单元不匹配"提示）
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
            # ★ 脚本实际单元分布（含单元=0 表示解析不到单元号）
            self.script_units = {q.unit for q in self.script_questions}
            # ★ 过滤：支持多单元（"2,4" / "2-4" / [2,4]），脚本覆盖所选任一单元即保留
            #   （2026-08-25 用户需求：脚本"口语训练湘少五上U2"只审U2；全单元脚本
            #   提取所选 U2/U4 题目审查；不含所选单元的脚本自动跳过，不报错）
            _units = normalize_units(self.cfg.unit)
            if _units:
                self.script_questions = [
                    q for q in self.script_questions if q.unit in _units
                ]
                # 单元不匹配提示：脚本不含所选单元（静默跳过审查=用户预期，
                #   print 一行供命令行排查即可，不上抛不告警）
                if not self.script_questions:
                    _units_sorted = sorted(u for u in self.script_units if u > 0)
                    _u0 = 0 in self.script_units
                    print(f"ℹ 脚本不含所选单元 {sorted(_units)}！脚本实际单元: "
                          f"{_units_sorted if _units_sorted else '无(未解析到)'}"
                          f"{' + 未标注单元' if _u0 else ''}")
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
        _total = len(self.script_questions)
        for _i, q in enumerate(self.script_questions, 1):
            shot = screenshots.get(q.global_idx, "")
            r = self._review_one(q, shot)
            self.results.append(r)

            # ★ 进度心跳：让用户知道仍在进行，不是卡死
            if _total >= 10 and (_i == 1 or _i % 10 == 0 or _i == _total):
                try:
                    from common.logger import log_msg
                    log_msg(f"⏳ 脚本审查进行中 {_i}/{_total}…", "info")
                except Exception:
                    print(f"  ⏳ 脚本审查进行中 {_i}/{_total}…")

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
        is_audio_q = ("听音" in qtype or "听力" in qtype or "音频" in qtype)
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
            # ★ LLM 脚本审查：无截图时也用大模型基于脚本信息逐维判定，
            #   理由具体有说服力；配图/音频/答错后标 skip（需截图）
            rr = self._review_script_llm(r, q)
            rr.content_check = self._check_content(q, "")
            q.type_2 = _orig_type2
            return rr

        # ---- 批量审查 (文字题走文本模型, 配图题走视觉模型) ----
        self._review_batch(q, screenshot, r, ui_texts)

        r.knowledge_check = self._verify_knowledge(q)

        # ★ 内容维度: 联合检查覆盖(知识性+脚本语言质量)
        r.content_check = self._check_content(q, screenshot)

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
        # 听音/听力/图片类题型：题干与选项内容在音频/图片中，脚本文字里没有，属正常
        is_audio_q = ("听音" in qtype or "听力" in qtype or "音频" in qtype)
        is_image_q = ("图片" in qtype or "看图" in qtype)
        # ★ 口语类题型（朗读/跟读/口语/发音）：作答方式是"点麦克风录音"，本就没有选项，
        #   AI 不应按选择题判"无ABC选项"（用户实测：麦克风可点却被判答案维度不过）
        is_speak_q = any(k in qtype for k in ("朗读", "跟读", "口语", "发音", "读一读", "读单词", "读句子"))

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

        # (2) 内容检查：选项完整性（听音/图片题选项在图中，跳过；口语题无选项，跳过）
        opts = q.options or []
        opt_clean = [o for o in opts if o and str(o).strip()]
        if is_image_q and len(opt_clean) < 2:
            r.content_check.passed = False
            r.content_check.score = 0.0
            r.content_check.method = "skip"
            r.content_check.error = "图片选择题：选项为图片，纯文字无法核对"
            r.content_check.details.append("纯文字模式无法核对图片选项（需连手机截图）")
        elif is_speak_q:
            # ★ 口语题（录音作答）：无选项属正常，跳过（不再误判"无选项"）
            r.content_check.passed = True
            r.content_check.score = 1.0
            r.content_check.method = "skip"
            r.content_check.details.append("口语题：作答方式为录音（点麦克风），无选项属正常")
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
        if is_speak_q:
            # ★ 口语题：作答=录音（点麦克风说），脚本无文字答案属正常，跳过
            r.answer_check.passed = True
            r.answer_check.score = 1.0
            r.answer_check.method = "skip"
            r.answer_check.details.append("口语题：作答方式为录音（点麦克风），脚本无文字答案属正常")
        elif not ans:
            r.answer_check.passed = False
            r.answer_check.score = 0.0
            r.answer_check.error = "答案为空"
            r.answer_check.details.append("纯文字检查: 脚本未给出答案")
        else:
            ans_up = ans.upper()
            # ★ 判断题答案 T/F、匹配题映射答案（含 - 或数字）不套用 A/B/C 范围校验
            is_judge = ans_up in ("T", "F", "TRUE", "FALSE")
            is_map = ("-" in ans or any(c.isdigit() for c in ans))
            if len(opt_clean) >= 2 and not is_judge and not is_map and ans_up not in "ABCD"[:len(opt_clean)]:
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
    # ★ LLM 脚本审查（无截图时也调用大模型，理由有说服力）
    # ============================================================
    def _review_script_llm(self, r: QuestionReview, q) -> QuestionReview:
        """
        把脚本完整信息（题型/题干/选项/答案/录音/知识点）交给 LLM 逐维判断，
        理由由 LLM 给出（具体、说明依据）；不通过时 LLM 附带「建议修改：」。
        依赖截图的维度（配图/音频/答错后）标记 skip（未检，不计入不通过）。
        """
        def _llm_dim(task, payload, dim_filter):
            chk = CheckResult()
            try:
                role = self._build_role_prompt(q)
                kb = self._build_knowledge_context(q)
                prompt = self.trainer.build_enhanced_prompt(
                    role + "\n\n---\n\n"
                    f"【任务: {task}】\n题型: {q.type_2 or '未知'}\n{payload}\n{kb}\n"
                    f"请依据以上脚本信息判断（无需截图），理由要具体说明判断依据：\n"
                    f"回答格式: [通过/不通过 | 置信度:0-100] | 理由" + REVIEW_SUGGEST_SUFFIX,
                    dim_filter=dim_filter
                )
                answer = self.llm.ask(prompt)
                # ★ LLM 调用失败（key 无效/401/欠费等）→ 标未检，不误判不通过
                if ('LLM 调用失败' in answer or '401' in str(answer)[:80]
                        or 'Unauthorized' in str(answer)):
                    chk.method = "skip"
                    chk.details.append(f"LLM 调用失败（请检查 .env 的 LLM_API_KEY/VISION_API_KEY）：{str(answer)[:90]}")
                    return chk
                self._apply_verdict(chk, answer)
            except Exception as e:
                chk.error = str(e)
                chk.method = "skip"   # LLM 调用失败 → 未检，不误判不通过
                chk.details.append(f"LLM 调用失败: {e}")
            return chk

        qtype = q.type_2 or ""
        is_audio_q = ("听音" in qtype or "听力" in qtype or "音频" in qtype)
        is_image_q = ("图片" in qtype or "看图" in qtype)
        is_judge_q = ("判断" in qtype)            # ★ 听音判断图片/信息/正误：T/F 判断题
        is_match_q = ("匹配" in qtype)            # ★ 听音匹配图片：答案映射格式 1-5 C E D A B
        is_speak_q = ("朗读" in qtype or "跟读" in qtype or "口语" in qtype
                      or "发音" in qtype or "读一读" in qtype
                      or "读单词" in qtype or "读句子" in qtype)  # ★ 2026-08-25：口语训练答案非唯一，App 录音评分
        stem_txt = (q.stem or "").strip()
        # ★ 2026-09-21：大题级「例句 / 句型」= sentence_pattern，**也是题干的一部分**。
        #   根因（实测 U4 第3大题）：「仿照例句，说一说」这类题的小题题面印在 **图片** 上，
        #   脚本不在小题里重复写题面，只在大题下写一行 `例句：I will bring everything inside.`
        #   作为仿写基准。旧逻辑只看 q.stem → stem 为空 → 落到后面的 else 分支
        #   `_llm_dim("检查题干是否缺失或过短（脚本题干为空）")` → 误判
        #   「脚本题干为空、未提供任何例句文字」，并给出**方向相反**的建议
        #   （"请在题干区域补充仿照的例句文本"——可脚本本来就有例句）。
        #   用户检查项「错误原因和实际错误原因是否一致」被这一条直接打穿。
        #   解析侧早已就绪（parse_yingyubao_docx 把例句挂到大题下每个小题），
        #   只有判定侧漏用了它。
        _pat_txt = (getattr(q, "sentence_pattern", "") or "").strip()
        _stem_from_pattern = bool(_pat_txt) and not stem_txt
        _eff_stem = stem_txt or (f"例句：{_pat_txt}" if _pat_txt else "")
        opt_str = ", ".join(q.options) if q.options else "(脚本未列出选项/图片选项)"

        # (1) 题干：脚本有题干（或大题级例句）→ LLM 审文字质量；
        #     两者都无 → 听音/图片题标 skip（题干在音频/图中），其余才判"缺题干"
        if _eff_stem:
            if is_judge_q:
                # ★ 判断题机制：题干是「待判断的陈述句」，与录音不一致是正常出题（学生听录音判断对错）
                r.stem_check = _llm_dim(
                    "检查判断题题干是否完整可读、有无明显错别字。注意：判断题题干是待判断的陈述句，"
                    "与录音原文不一致属于正常出题机制（学生需听录音判断该陈述对错），"
                    "绝不能因『题干与录音不一致/相矛盾』判不通过；题干存在且可读即判通过。",
                    f"题干: {_eff_stem}\n题型: {qtype}（判断题，答案格式为 T/F）", "stem")
                r.stem_check.actual = _eff_stem[:200]
            else:
                _stem_task = (
                    "检查题干数据是否完整：是否缺失、是否短到无法理解、是否有明显错别字。"
                    "不要对题干措辞风格/出题设计作价值判断（如'与题型不匹配'这类主观批评不算问题）；"
                    "题干存在且可读即判通过。"
                )
                # ★ 2026-09-23 新增：朗读单词/音素词对题**不得套用句子级语法规则**。
                #   现场（教科版五上 U7 第1大题，实跑唯一的新假错）：
                #     题干 "six fox" 被 LLM 判「数词后名词应用复数 foxes，存在单复数不一致」
                #     → 题干维度不通过 → 整题不通过。
                #   但该大题是**发音练习**："six fox"(x音) / "box ox" / "yellow yogurt"(y音) /
                #   "you yes" / "zebra zero"(z音) —— 成对单词共享同一目标音素，
                #   是教学设计，不是名词短语，谈不上单复数。
                #   判据：题干由 ≤4 个纯字母词构成、且不含任何句子级标点（. ? ! , ; :）
                #   → 属于"词/词组朗读"而非句子 → 只查拼写，不查语法。
                _nl_tokens = _eff_stem.replace("　", " ").split()
                _looks_word_drill = (
                    bool(_nl_tokens) and len(_nl_tokens) <= 4
                    and not re.search(r"[.?!,;:，。？！；：]", _eff_stem)
                    and all(re.fullmatch(r"[A-Za-z][A-Za-z'\-]*", t) for t in _nl_tokens)
                )
                if _looks_word_drill:
                    _stem_task += (
                        "★ 本题为「朗读单词/词组」（题干由若干独立单词构成、无句子结构）："
                        "**只检查单词拼写是否正确，不得套用句子级语法规则**"
                        "（如『数词后名词须用复数』『缺少冠词』『主谓一致』『缺少谓语』等一律不算问题）"
                        "—— 该类题目考的是发音，成对/成组出现的单词是**教学设计**，不是句子。"
                        "单词拼写正确即判通过。"
                    )
                if _stem_from_pattern:
                    # ★ 关键：明确告诉 LLM「题面在图片上，例句就是作答指引」，
                    #   否则它会按"没有小题题面"判缺失（这正是误判的机理）。
                    _stem_task += (
                        "★ 本题为「仿照例句，说一说」：小题题面（配图）在 App 界面上，"
                        "脚本以『例句：…』给出仿写基准，**该例句即本题的作答指引**。"
                        "只要例句非空、可读、无错别字即判通过；"
                        "**绝不能因『脚本没有单独写小题题面』或『没有别的例句提示』判不通过**。"
                    )
                r.stem_check = _llm_dim(_stem_task, f"题干: {_eff_stem}", "stem")
                r.stem_check.actual = _eff_stem[:200]
                # ★ 2026-09-23 确定性兜底：提示词是"软约束"，LLM 仍可能忍不住套句子语法。
                #   实测它给出「six → foxes，单复数不一致」并判不通过 → 整题假错。
                #   判据（两条同时成立才放行，避免把真错误洗白）：
                #     ① 该题干是「朗读单词/词组」题（_looks_word_drill）
                #     ② 不通过理由**只**涉及句子级语法概念，且**完全没提**拼写/错别字/
                #        乱码/截断/缺失/多写少写这些"真问题"关键词
                #   放行方式：passed=True + 保留 LLM 原文（检查人员仍能看到它的意见）。
                if _looks_word_drill and r.stem_check.passed is False \
                        and r.stem_check.method not in ("skip",):
                    _sc_txt = " ".join(
                        [r.stem_check.error or ""]
                        + [str(d) for d in (r.stem_check.details or [])]
                        + [r.stem_check.suggestion or ""])
                    _GRAM_OVERREACH = ("单复数", "复数形式", "冠词", "主谓一致", "谓语",
                                       "时态", "句子结构", "句子不完整", "不成句", "语法错误",
                                       "语序")
                    _REAL_PROBLEM = ("拼写", "错别字", "乱码", "截断", "缺失", "空白",
                                     "多写", "少写", "拼错")
                    if any(k in _sc_txt for k in _GRAM_OVERREACH) \
                            and not any(k in _sc_txt for k in _REAL_PROBLEM):
                        _orig = " ".join(str(d) for d in (r.stem_check.details or []))[:300]
                        r.stem_check.passed = True
                        r.stem_check.error = ""
                        r.stem_check.details = list(r.stem_check.details or []) + [
                            "⚠ 已忽略「朗读单词/词组」题上的句子级语法意见"
                            "（该题型考发音与拼写，成对/成组单词是教学设计、不是句子）："
                            f"{_orig[:160]}"
                        ]
                        r.stem_check.suggestion = ""
        elif is_audio_q or is_image_q:
            r.stem_check = CheckResult(passed=False, score=0.0, method="skip",
                                       error="脚本未提供题干文字（听音/图片题题干在音频或图中）",
                                       details=["脚本未提供题干：听音/图片题题干在音频/图中，需连手机核对"])
        else:
            r.stem_check = _llm_dim("检查题干是否缺失或过短（脚本题干为空）",
                                    "题干: (空) 请判断脚本题干是否异常缺失", "stem")

        # (2) 内容/选项
        # ★ 判断题：无 A/B/C 文字选项（T/F 作答）是正常格式 → skip 无法文字核对
        if is_judge_q:
            r.content_check = CheckResult(passed=False, score=0.0, method="skip",
                                          error="判断题以 T/F 作答、无文字选项，跳过内容核对",
                                          details=["判断题无 A/B/C 文字选项（T/F 作答），内容维度无需文字核对"])
        else:
            # ★ 图片题：脚本里图片选项只有占位（"A."/"B." 无文字或空），图片在 App 中，
            #   无法文字核对 → 标 skip（未检）而非不通过
            _opt_clean = [str(o).strip().rstrip('.') for o in (q.options or [])]
            _is_placeholder = (not _opt_clean) or all(
                o in ("A", "B", "C", "D", "E", "F") for o in _opt_clean)
            if is_image_q and _is_placeholder:
                r.content_check = CheckResult(passed=False, score=0.0, method="skip",
                                              error="图片题选项为占位（A./B. 无文字），需连手机截图核对",
                                              details=["图片题选项是图片占位（A./B.），脚本无法提供图片描述，需连手机截图核对"])
            else:
                r.content_check = _llm_dim(
                    "检查选项数据是否完整自洽（只做数据层面检查）：选项是否缺失/为空、数量是否明显异常"
                    "（选择题应有2-4个选项）、答案是否在选项范围内。"
                    "★ 不要判断『选项内容与录音/题干是否语义匹配』——听音题录音在音频中，纯文字无法核对语义，"
                    "且答语题选项为完整句子、判断题无选项等都是正常格式；"
                    "不要对超纲词汇、出题难度、题干措辞作价值判断（那是教研职责）。"
                    "选项齐全且答案在范围内即判通过。",
                    f"题型: {qtype or '未知'}\n选项: {opt_str}\n答案: {q.answer or '(未给出)'}", "content")

        # (3) 作答
        if is_speak_q:
            # ★ 2026-08-25 口语训练：答案非唯一，App 根据录音评分，脚本答案仅作评分参考
            #   旧逻辑：LLM 拿"选项+答案+录音"判断 → 口语题答案常是"朗读 try"等描述性内容，
            #   LLM 不认为是有效答案 → 误报"脚本未提供答案"（用户实测第45题66分误判）
            #   改：口语题作答维度直接 skip（不作为错题判定），同时把脚本答案+关键词
            #   作为评分参考信息保留（供报告展示）
            r.answer_check = CheckResult(
                passed=True, score=1.0, method="skip",
                details=[f"口语训练：作答方式=录音（点麦克风说），App 根据录音评分，"
                         f"答案非唯一。脚本答案「{q.answer or '(无)'}」+关键词「{','.join(q.keywords or []) or '(无)'}」"
                         f"仅作评分参考，不作为错题判定依据。"]
            )
        elif q.answer:
            if is_judge_q:
                # ★ 判断题答案固定 T/F，用规则判定（更快更准，不依赖 LLM）
                _ans = str(q.answer).strip().upper()
                if _ans in ("T", "F", "TRUE", "FALSE", "对", "错", "√", "×"):
                    r.answer_check = CheckResult(passed=True, score=1.0, method="text",
                                                 details=[f"判断题答案 {_ans} 有效（T/F 格式）"])
                else:
                    r.answer_check = CheckResult(passed=False, score=0.0, method="text",
                                                 error="判断题答案应为 T/F",
                                                 details=[f"判断题答案异常: {q.answer}（应为 T/F）"])
            elif is_match_q:
                # ★ 匹配题答案映射格式（如 1-5 C E D A B）：规则判定（更快更准，不依赖 LLM）
                _am = re.match(r'^(\d+)-(\d+)\s+([A-Za-z][\sA-Za-z]*)$', str(q.answer).strip())
                if _am:
                    _letters = [x for x in _am.group(3).split() if x]
                    _n_q = int(_am.group(2))
                    _ok = len(_letters) == _n_q and all(len(x) == 1 and x.isalpha() for x in _letters)
                    if _ok:
                        r.answer_check = CheckResult(passed=True, score=1.0, method="text",
                                                     details=[f"匹配题答案映射 {q.answer} 有效（{_n_q}小题 ↔ {_n_q}字母）"])
                    else:
                        r.answer_check = CheckResult(passed=False, score=0.0, method="text",
                                                     error="匹配题答案映射异常",
                                                     details=[f"匹配题答案 {q.answer}：映射字母数与小题数不一致或格式异常"])
                else:
                    r.answer_check = _llm_dim(
                        "检查匹配题答案映射是否有效：答案格式如『1-5 C E D A B』（小题号-字母序列），"
                        "匹配题无 A/B/C 常规文字选项属于正常格式（选项是图片）；"
                        "只需检查映射字母数是否与小题数一致、字母是否在合理范围内（A-D等），格式规范即判通过；"
                        "不要因『无文字选项』判不通过。",
                        f"题型: {qtype}\n答案: {q.answer}\n录音: {q.recording or '(未提供)'}", "answer")
            else:
                r.answer_check = _llm_dim(
                    "检查答案数据是否有效：答案是否为空、是否在选项范围内、格式是否与题型匹配"
                    "（选择题应在A-D内）。仅做数据层面检查，不做超纲/难度等价值判断；"
                    "答案存在且格式合理即判通过。",
                    f"题型: {qtype or '未知'}\n选项: {opt_str}\n答案: {q.answer}\n录音: {q.recording or '(未提供)'}", "answer")
        else:
            r.answer_check = CheckResult(passed=False, score=0.0, method="text",
                                         error="脚本未给出答案", details=["脚本未提供答案"])

        # ★ 2026-09-17 新增：参考答案 ↔ 关键词 一致性（确定性规则，覆盖 LLM 结论）
        #   为什么放在这里而不是并进 LLM 调用：
        #   ① LLM 对"答案有效/格式合理"判通过，会**掩盖**关键词与答案用词不一致
        #      （用户实测：LLM 判通过，但答案用 take、关键词用 bring）；
        #   ② 规则判定零成本、可复现，还能给出"bring → take"这种可直接改的结论。
        #   checked>0 且无问题 → 追加一条"已核对"证据，避免该检查项被静默跳过。
        try:
            _kw_problems, _kw_n, _kw_src = check_answer_keyword_consistency(
                q.answer, q.keywords, getattr(q, "passage", "") or q.recording)
            if _kw_problems:
                _sug = "统一「参考答案」与「关键词」的用词（学生按关键词作答会被判错）"
                for _p in _kw_problems:
                    _m2 = re.search(r"：答案里是「([^」]+)」（(.+?)）", _p)
                    if _m2:
                        _sug += f"；例如把关键词改为与答案一致的表达「{_m2.group(1)}」"
                        break
                r.answer_check = CheckResult(
                    passed=False, score=0.0, method="text",
                    error="关键词与参考答案不一致",
                    details=[f"❌ {_p}" for _p in _kw_problems],
                    suggestion=_sug,
                )
            elif _kw_n:
                r.answer_check.details = list(r.answer_check.details) + [
                    f"✅ 关键词与参考答案一致（已核对 {_kw_n} 个短语："
                    f"{'、'.join(list(_kw_src)[:4])}）"
                ]
        except Exception as _e:
            # 该规则异常绝不能影响主流程 → 记一条"未检"痕迹即可
            r.answer_check.details = list(r.answer_check.details) + [
                f"⚠ 关键词一致性检查未执行: {_e}"
            ]

        # (4)(5)(6) 配图/音频/答错后：无截图 → skip（未检）
        for cr, name in ((r.image_check, "配图"), (r.audio_check, "音频"),
                         (r.post_error_check, "答错后")):
            cr.passed = False
            cr.score = 0.0
            cr.method = "skip"
            cr.error = f"{name}检查需手机截图（脚本审查跳过）"
            cr.details.append(f"脚本审查: {name}未检测（需连手机截图）")

        # 知识库检查
        r.knowledge_check = self._verify_knowledge(q)

        # overall：与 _qreview_to_state 判定一致（有 False → 不通过；checked 全 True → 通过；否则 None）
        # ★ 2026-08-25 修复：uncertain（REVIEW/待审）与 skip 一样不计入 checked，
        #   否则"朗读单词"这类无选项题 LLM 合理 REVIEW → passed=False → 整体误判不通过
        checked = [c for c in (r.stem_check, r.content_check, r.answer_check)
                   if c.method not in ("skip", "uncertain")]
        if checked:
            if any(c.passed is False for c in checked):
                r.overall_passed = False
            elif all(c.passed for c in checked):
                r.overall_passed = True
            else:
                r.overall_passed = None
        else:
            r.overall_passed = None   # 全未检（如 LLM 不可用）→ 未审，不误判不通过
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
        a = (a or "").strip()
        if not a:
            return None  # ★ 空白返回 → 不确定
        # ★ 修复：LLM 解释里可能引用"不通过"（如"无需因…判不通过"），不能全文包含判断。
        #   ① 优先解析格式标记 [通过 | 置信度:96] / [不通过 | 置信度:xx]
        _m = re.search(r'\[(通过|不通过)\s*[|｜，,、\]]', a)
        if _m:
            return _m.group(1) == '通过'
        # ② 找"不通过"与"独立通过"（(?<!不) 排除"不通过"里的"通过"子串）的位置
        _ff = a.find('不通过')
        _fp_m = re.search(r'(?<!不)通过', a)
        _fp = _fp_m.start() if _fp_m else -1
        if _fp >= 0 and _ff >= 0:
            return _fp < _ff          # 独立"通过"在前 → True
        if _fp >= 0:
            return True
        if _ff >= 0:
            # "不通过"前有"无需/不应/不要"等否定 → 实际含义是"通过"
            if re.search(r'(?:无需|不应|不要|不会|不能|不是|不必)[^，。；、]{0,12}不通过', a):
                return True
            return False
        # ③ 其他积极词兜底
        if '匹配' in a or '一致' in a or '正确' in a:
            return True
        # ★ 无法解析 → 返回 None（不默认为通过！）
        return None

    # ★ 2026-09-23 新增："只报取证不足"的判据（详见 _evidence_only_miss）
    _EVIDENCE_MISS_KW = (
        "未提供截图", "没提供截图", "没有截图", "无截图", "缺截图",
        "未提供配图", "未提供图片", "未提供该题配图截图",
        "无法核实", "无法检查", "无法查看", "无法判断", "看不到图", "未见配图",
    )
    _HARD_ISSUE_KW = (
        "拼写错误", "语法错误", "不符", "不一致", "缺失", "有误", "不正确",
        "超纲", "应改为", "写错", "拼错", "不匹配", "未显示", "遗漏", "多余",
    )

    @classmethod
    def _evidence_only_miss(cls, text: str, sugg: str) -> bool:
        """LLM 判"不通过"但理由**只是取证不足**（如没给配图截图）→ 不是缺陷。

        现场（教科版五上 U7 第3大题第4小题，脚本层审查输出）：
            [不通过 | 置信度:70] | 理由：
              - 题干文字检查：通过。…
              - 题目内容检查：通过。…
              - 配图检查：未提供截图，无法核实图片
              建议修改：补充提供该题配图截图以校验图片与句子是否匹配…
        三个子项里两个明确通过，唯一"问题"是**没有截图可用** —— 这属于取证手段
        缺失，不是 App / 脚本的缺陷。判"不通过"就是假错（用户反复要求"只判真正
        影响学生作答的问题"）。这里只做**单向**放宽：命中判据 → 降级为"未判定"，
        绝不把真错洗白（有任一实质问题词命中就不降级）。
        """
        if not any(k in text for k in cls._EVIDENCE_MISS_KW):
            return False
        if any(k in text for k in cls._HARD_ISSUE_KW):
            return False
        if sugg and not any(k in sugg for k in ("截图", "人工核对", "人工确认",
                                                "连手机", "补充提供", "补证")):
            return False
        return True

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

        # ★ 2026-09-23：把「建议修改」的抽取提前到判定之前 —— 判"是否只是取证不足"
        #   需要看 LLM 给的建议是"去补截图/人工核对"还是"去改内容"。
        _combined = f"{ai_response}\n{reason}"
        _m_sugg = _re.search(r'建议修改[:：]\s*([^\n]{4,200})', _combined)
        _sugg_txt = _m_sugg.group(1).strip().rstrip('。.').strip() if _m_sugg else ""

        # ★ 2026-09-23：LLM 把"取证不足"当成"不通过" → 假错，降级为「未判定」。
        #   标 method="uncertain" 后，_qreview_to_state._cr() 会映射成 None（未检），
        #   且 overall 计算里 uncertain 与 skip 一样不计入 checked → 不会误判不通过。
        if passed is False and self._evidence_only_miss(_combined, _sugg_txt):
            check.passed = False
            check.score = 0.0
            check.confidence = confidence
            check.method = "uncertain"
            check.error = "取证不足，未判不通过"
            check.suggestion = _sugg_txt
            check.details.append(
                "⏸ 未判定：脚本审查只报了「取证不足」（如缺配图截图 / 无法核实），"
                "未发现实质内容问题 → 不计不通过，请人工补证")
            if ai_response:
                check.details.append(f"  AI判断: {ai_response[:150]}")
            if reason:
                check.details.append(f"  AI理由: {reason[:120]}")
            return

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

        # ★ 抽出"建议修改"并嵌入 detail（供实时错题报告展示绿色"修改建议"框）
        #   （正则抽取已在函数开头做过，这里复用 _sugg_txt）
        if _sugg_txt and not check.passed:
            check.suggestion = _sugg_txt
            if not any('建议修改' in d for d in check.details):
                check.details[-1] = f"{check.details[-1]} 建议修改：{check.suggestion}"

    def _create_empty_review(self) -> QuestionReview:
        """创建一个空的审查结果对象"""
        return QuestionReview()

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
            prompt_text += REVIEW_SUGGEST_SUFFIX
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
                f"回答格式: [通过/不通过 | 置信度:0-100] | 理由" + REVIEW_SUGGEST_SUFFIX,
                dim_filter="stem"
            )
            answer = self.llm.ask(prompt, image_path=shot)
            self._apply_verdict(result, answer)
        except Exception as e:
            result.error = str(e)
        return result

    def _check_content(self, q, shot: str) -> CheckResult:
        """(2) 内容检查: 有脚本→知识性+语言联合检查; 无脚本→跳过"""
        result = CheckResult()
        has_script = bool((getattr(q, "stem", "") or "").strip()) or bool(q.options) or bool((getattr(q, "answer", "") or "").strip())
        if not has_script:
            result.passed = True
            result.score = 1.0
            result.details = ["无脚本, 跳过知识性检查"]
            return result
        try:
            role = self._build_role_prompt(q)
            stem = (getattr(q, "stem", "") or "").strip()
            options = "; ".join([o for o in (q.options or []) if o]) or "(无)"
            answer = (getattr(q, "answer", "") or "").strip() or "(无)"
            qtype = (getattr(q, "type_2", "") or "").strip() or "未知"
            rec = (getattr(q, "recording", "") or "").strip()
            payload = f"【题型】{qtype}\n【脚本材料】{stem or '(无)'}\n【选项】{options}\n【答案】{answer}"
            if rec:
                payload += f"\n【录音稿】{rec[:400]}"
            rules = ("【审查规则】有脚本时联合检查(不连手机):\n"
                     "一、知识性(PASS/REVIEW/REJECT): 有明确依据才判错, 三问(错误在哪/为什么/正确是什么)齐全才REJECT, 证据不足→REVIEW。\n"
                     "二、脚本语言质量:\n"
                     "1.拼写: 逐词检查, 结合教材年级词汇\n2.语法: 主谓一致/be动词/单复数/冠词/代词/时态/词性\n"
                     "3.选项: 拼写/同一维度/重复/答案越界/数量不匹配\n"
                     "4.搭配: 固定短语/动词介词搭配\n5.语义: 合理性, 上下文一致性\n\n"
                     '输出JSON: {"verdict":"PASS/REVIEW/REJECT","issue_type":"","location":"","quote":"",'
                     '"basis":"","correct":"","severity":"","confidence":0,'
                     '"lang_issues":[{"type":"拼写/语法/选项/搭配/语义","severity":"高/中/低",'
                     '"location":"","quote":"","detail":"","suggestion":""}]}')
            prompt_text = (role + "\n\n---\n\n"
                           f"【任务: 内容审查】\n{payload}\n\n{rules}\n"
                           "按规则联合检查(有脚本:知识+语言, 无脚本只知识判定)，只输出JSON。")
            prompt = self.trainer.build_enhanced_prompt(prompt_text, dim_filter="content")
            raw = self.llm.ask(prompt)
            data = json.loads(raw[raw.find("{"):raw.rfind("}")+1])
            verdict = str(data.get("verdict", "REVIEW")).upper()
            if verdict not in ("PASS", "REVIEW", "REJECT"):
                verdict = "REVIEW"
            parts = []
            if verdict == "REJECT":
                parts.append(f"\u274c REJECT[{data.get('issue_type','')}@{data.get('location','')}] {data.get('basis','')[:120]}")
            elif verdict == "REVIEW":
                parts.append(f"\u26a0 REVIEW: {data.get('basis','')[:120]}")
            else:
                parts.append(f"\u2705 PASS: {data.get('basis','')[:120]}")
            lang = data.get("lang_issues") or []
            for li in (lang or [])[:6]:
                parts.append(f"[{li.get('type','')}] {li.get('detail','')[:100]}")
            result.details = parts[:10]
            result.passed = (verdict == "PASS" and len(lang) == 0)
            result.score = 0.3 if (verdict == "REJECT" or len(lang) > 3) else (0.7 if (verdict == "REVIEW" or len(lang) > 0) else 1.0)
            # ★ 2026-08-25 修复：REVIEW=信息不足（如朗读单词题只有单词无选项，LLM
            #   合理无法核对）→ 标 uncertain（未检），下游 _cr 转 None，不误判不通过。
            #   原实现 method 为空串，_qreview_to_state._cr 无法识别 → 当 False 处理，
            #   导致"题干/选项都过、得分100"却综合判定不通过。
            if verdict == "REVIEW":
                result.method = "uncertain"
        except Exception as e:
            result.passed = True
            result.score = 0.7
            result.details = [f"内容检查异常: {str(e)[:80]}"]
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
                    f"回答格式: [通过/不通过 | 置信度:0-100] | 理由" + REVIEW_SUGGEST_SUFFIX
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
                    f"回答格式: [通过/不通过 | 置信度:0-100] | 理由" + REVIEW_SUGGEST_SUFFIX
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
                f"回答格式: [通过/不通过 | 置信度:0-100] | 理由" + REVIEW_SUGGEST_SUFFIX,
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
                f"回答格式: [通过/不通过 | 置信度:0-100] | 理由" + REVIEW_SUGGEST_SUFFIX,
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
