"""题目解析脚本生成器 — 把答题过程中收集的题目（题干+选项+答案）汇总成脚本 docx

用法（在模块答题循环中）:
    from common.gen_script import QuestionCollector
    coll = QuestionCollector(module="单元自检", version="湘少版", grade="五年级上册")
    # 每题作答时:
    coll.add(qno=q, stem=..., options=[...], answer=opt, qtype=..., unit=6)
    # 单元答完:
    coll.finish_unit(unit=6)   # 写入 docx 脚本文件

生成格式（参考"260707新湘鲁六上听力专项(试编).docx"）:
    1. 题干
    A. xx  B. xx  C. xx
    答案：X
    一级题型：xxx
    二级题型：xxx
    难度：基础
    关键词：模块#版本U单元#...
    知识点：...
    技能：...
    认知目标：识记
    适用年级：xxx
    编写年份：2026年
"""
import os
import re
import sys
import time
from datetime import datetime

try:
    from docx import Document
    from docx.shared import Pt
    _HAS_DOCX = True
except Exception:
    _HAS_DOCX = False

_KNOWLEDGE_KWS = ("语法", "句型", "词汇", "单词", "固定搭配", "时态", "发音",
                  "am/is/are", "can", "like", "want", "what", "where", "who",
                  "When", "How", "Do ", "Does ", "Is ", "Are ")

# ★★★ 固定解析提示词模板（用户要求：规范解析方式与准度，不能乱讲，符合年级要求）
#   解析必须满足：考点准确 + 理由对应正确答案 + 年级适配 + 精简有说服力
#   任何解析生成（前端/后端/批量）都走这个模板，保证一致性。
KNOWLEDGE_PROMPT_TEMPLATE = (
    "你是{g_grade}（{g_version}）英语老师，正在给学生讲解一道错题的考点。\n"
    "题目：{g_stem}\n"
    "选项：{g_options}\n"
    "正确答案：{g_answer}\n\n"
    "请给出本题的知识点解析，必须遵守以下规范：\n"
    "1. 【准确】考点必须是该题真正的语法/词汇/句型点，结合选项和正确答案分析，"
    "不得臆造考点，不得泛泛而谈。\n"
    "2. 【年级适配】解释方式必须符合{g_grade}学生的认知水平"
    "（如be动词、一般现在时、名词复数这类该年级正在学的知识），"
    "不能讲超纲概念（如虚拟语气、定语从句）。\n"
    "3. 【对应答案】必须明确说明为什么{g_answer}是对的，其他选项为什么错/不同类。\n"
    "4. 【精简】30-70字，直接说结论，不要铺垫、不要'首先/其次'。\n"
    "5. 【格式】用中文解释，英文单词保留原文；只输出解析本身，不要标题、编号、前缀。\n"
    "6. 【禁止】禁止'涉及XX相关知识点''本题考查XX'这类模糊套话，禁止编造教材没有的内容。"
)


def _extract_ui_question(xml, answer="", qtype_hint=""):
    """从答题页 XML 提取一道题的（题干/选项/题型），供脚本生成收集。
    - 题干：优先 question_title_tv 节点；兜底长文本（排除按钮/进度/计时器噪音）
    - 选项：字母开头项（A. xx / B. xx）或纯字母项（T/F/A-E 判断题无文字选项）
    - 纯听音无题干（题干为空/仅"听录音"指令）→ stem 返回空，上层跳过
    """
    if not xml:
        return {"stem": "", "options": [], "qtype": qtype_hint}
    # ① 题干：question_title_tv 优先，其次 tv_caption（单元自检等用 tv_caption）
    #   ★ XML 属性顺序不固定（text 可能在 resource-id 前）→ 用非贪婪匹配任一顺序
    stem = ""
    for _rid in ("question_title_tv", "tv_caption"):
        if stem:
            break
        for m in re.finditer(
                rf'<node[^>]*resource-id="[^"]*{_rid}[^"]*"[^>]*text="([^"]+)"|'
                rf'<node[^>]*text="([^"]+)"[^>]*resource-id="[^"]*{_rid}[^"]*"', xml):
            t = (m.group(1) or m.group(2) or "").strip()
            if t and len(t) < 80:
                stem = t
                break
    # ★ 清洗题干里的分值噪音："选择各组中不同类的一项。 (共1分)" → 去掉"(共N分)"
    stem = re.sub(r"[（(]\s*共\d+分\s*[）)]", "", stem).strip()
    if not stem:
        # 兜底：长文本（排除噪音）
        noise = ("下一题", "上一题", "检查", "提交", "查看报告", "练习报告",
                 "恭喜", "回答正确", "回答错误", "很遗憾", "练习结束还剩", "还剩",
                 "得分", "用时", "点击录音", "点击结束", "继续答题", "退出训练",
                 "答题卡", "单元自检", "口语训练", "听力专项", "知识过关",
                 "巧记单词", "语音评测", "全脑记词", "单词听写", "查看解析",
                 "正确答案", "错误答案", "本大题", "本小题", "分值", "满分",
                 "考前突破", "当前版本", "练习记录", "训练规则说明", "好的")
        for m in re.finditer(r'text="([^"]{4,})"', xml):
            t = m.group(1).strip()
            if not t or t in noise or len(t) >= 80:
                continue
            if any(n in t for n in noise):
                continue
            # ★ 排除选项/字母项（A. bus / B. 图片 / T/ F）——否则纯听音题
            #   会把"听录音"过滤后剩下的第一个选项误当题干！
            if re.match(r"^[A-F][.、．]\s*", t) or re.match(r"^[TF]\s*$", t):
                continue
            if re.match(r"^\d{1,2}:\d{2}$|^\d+(\.\d+)?%?$|^\d+\s*/\s*\d+$|^\d+分$", t):
                continue
            stem = t
            break
    # ★ 纯听音指令判定：题干仅为"听录音/听音选X"等指令性文字 → 视为无题干（跳过）
    #   （听力题的实质内容在音频里，脚本里没有可解析的题干文字）
    if stem.strip() and re.fullmatch(
        r"(听录音|听音|听一听|Listen|听录音[，,。 ]?[选判勾][出择].*|"
        r"听对话|听短文|听句子|听单词|听材料|听问题).*",
        stem.strip(), re.IGNORECASE):
        stem = ""
    # ② 选项：字母开头项（A. xx）优先
    opts = []
    for m in re.finditer(r'text="([A-E][.、．]\s*[^"]{1,60})"', xml):
        t = m.group(1).strip()
        if t and t not in opts:
            opts.append(t)
    if not opts:
        # ★ 选项是 CheckBox/RadioButton（option_cb 等，文本无字母前缀，如 parrot/notebook）
        #   按出现顺序收集（单元自检等模块的选项就是这种独立单词）
        for m in re.finditer(
                r'<node[^>]*resource-id="[^"]*(?:option_cb|option_iv|radio_btn|check_box)[^"]*"[^>]*text="([^"]{1,40})"|'
                r'<node[^>]*text="([^"]{1,40})"[^>]*resource-id="[^"]*(?:option_cb|option_iv|radio_btn|check_box)[^"]*"', xml):
            t = (m.group(1) or m.group(2) or "").strip()
            if t and t not in opts:
                opts.append(t)
    if not opts:
        # 纯字母（T/F/A-E 判断题）
        for m in re.finditer(r'text="([TFABCDE])"', xml):
            t = m.group(1)
            if t not in opts:
                opts.append(t + ". ")
    return {"stem": stem.strip(), "options": opts[:6], "qtype": qtype_hint}


class QuestionCollector:
    """答题过程中的题目收集器（每道有题干的题收集一条，单元答完汇总写脚本）"""

    def __init__(self, module="单元自检", version="", grade="", save_root=None):
        self.module = module
        self.version = version or "湘少版"
        self.grade = grade or "五年级上册"
        # 保存目录：项目根/gen_scripts（默认）；可传 save_root 覆盖
        self.save_root = save_root or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gen_scripts")
        os.makedirs(self.save_root, exist_ok=True)
        self.questions = []       # 当前单元收集的题（含题干可解析的）
        self.skipped_no_stem = 0  # 无题干跳过的题数（纯听音等）

    # ------------------------------------------------------------
    def add(self, qno, stem="", options=None, answer="", qtype="",
            unit=0, recording="", knowledge="", big=None):
        """收集一道题。仅当有题干（非纯听音）才保留，否则跳过。

        Args:
            qno: 题号（单元内序号）
            stem: 题干文字（空 = 纯听音/无题干 → 跳过）
            options: 选项列表 ['A. xx', 'B. xx', ...]
            answer: 答案（点击的选项，如 'B'）
            qtype: 题型（如 '单选', '判断'）
            unit: 单元号
            recording: 录音原文（听力题可能有）
            knowledge: 知识点（可选，LLM 生成或留空）
            big: 大题号（口语训练等"第N大题"定位用）
        """
        stem = (stem or "").strip()
        if not stem or stem in ("(无题干文字)", "(无)", "听录音", "听录音，选择正确答案"):
            self.skipped_no_stem += 1
            return
        # 过滤纯听音指令类题干（"听录音，选出你听到的单词" 无实际内容 → 跳）
        if re.fullmatch(r"(听录音|听音|听一听|Listen)[，,。. ]*(选择|选出|判断|勾选|选出你听到的).*", stem, re.IGNORECASE):
            self.skipped_no_stem += 1
            return
        opts = [str(o).strip() for o in (options or []) if str(o).strip()]
        # 清洗选项：去掉多余空白（"A.  sport" → "A. sport"）
        opts = [re.sub(r"\s+", " ", o) for o in opts]
        self.questions.append({
            "qno": int(qno) if str(qno).isdigit() else qno,
            "stem": stem, "options": opts, "answer": str(answer).strip(),
            "qtype": qtype or "", "unit": int(unit) if str(unit).isdigit() else unit,
            "recording": (recording or "").strip(),
            "knowledge": (knowledge or "").strip(),
            "big": big,
            "time": datetime.now().strftime("%H:%M:%S"),
        })

    # ------------------------------------------------------------
    def _llm_knowledge(self, q):
        """用大模型生成知识点解析：符合该版本年级的知识水平，精简有说服力。
        像"为什么1+1=2"要用小学方法解释——不模糊、直接给出该年级该懂的结论。
        """
        try:
            sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
            from src.reviewer_common import LLMClient
            llm = LLMClient.from_config()
            opt_str = " ".join(q["options"]) if q["options"] else "（无文字选项）"
            # ★ 固定模板（KNOWLEDGE_PROMPT_TEMPLATE），保证解析规范一致
            prompt = KNOWLEDGE_PROMPT_TEMPLATE.format(
                g_grade=self.grade, g_version=self.version,
                g_stem=q["stem"], g_options=opt_str, g_answer=q["answer"])
            ans = ""
            for _try in range(2):  # 不合格重试一次
                ans = (llm.ask(prompt) or "").strip()
                if ans and len(ans) > 5 and "LLM 调用失败" not in ans and self._check_knowledge_ok(ans):
                    break
                ans = ""  # 不合格 → 重试
            if ans:
                return ans[:120]
        except Exception as _e:
            print(f"  ⚠ 知识点 LLM 生成失败: {_e}")
        return self._auto_knowledge(q)

    # ------------------------------------------------------------
    @staticmethod
    def _check_knowledge_ok(ans):
        """解析质量校验：模糊套话/超纲词 → 不合格（防'乱讲'）"""
        fuzzy = ("涉及", "相关知识点", "本题考查", "本道题考查", "一般考查", "基础知识点")
        if any(f in ans for f in fuzzy):
            return False
        # 超纲概念（五年级不应出现）
        over = ("虚拟语气", "定语从句", "现在完成时", "过去完成时", "被动语态", "非谓语")
        if any(o in ans for o in over):
            return False
        return True

    # ------------------------------------------------------------
    def finish_unit(self, unit):
        """单元答完：把收集到的题写成脚本 docx（模板格式）。
        返回生成的文件路径；无题可写返回 None。
        """
        if not self.questions:
            print(f"  ⚠ 单元 {unit} 无可生成解析的题目（{self.skipped_no_stem} 题无题干跳过）")
            return None
        if not _HAS_DOCX:
            print("  ❌ python-docx 不可用，无法生成脚本")
            return None
        # ★ 知识点用大模型生成（每题一次调用，串行；该年级知识点有说服力）
        print(f"  🧠 正在为 {len(self.questions)} 题生成知识点解析（LLM）…")
        for q in self.questions:
            if not q.get("knowledge"):
                q["knowledge"] = self._llm_knowledge(q)
        _u = f"U{unit}"
        fname = f"{datetime.now().strftime('%y%m%d')}_{self.module}_{self.grade.replace('年级', '')}{_u}_生成脚本.docx"
        path = os.path.join(self.save_root, fname)
        doc = Document()
        doc.add_heading(f"{self.module} · {self.grade} {_u} · 题目解析脚本", level=0)
        doc.add_paragraph(f"版本：{self.version}　|　单元：{_u}　|　生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}")
        doc.add_paragraph(f"共 {len(self.questions)} 题（无题干/纯听音 {self.skipped_no_stem} 题跳过）")
        for i, q in enumerate(self.questions, 1):
            # ★ 简化格式：位置 / 题干 / 选项 / 答案 / 知识点（用户要求，不搞严谨字段）
            doc.add_heading(f"{i}. {q['stem']}", level=1)
            _p = doc.add_paragraph()
            _p.add_run("位置：").bold = True
            _p.add_run(self._loc_str(q))
            _p = doc.add_paragraph()
            _p.add_run("选项：").bold = True
            _p.add_run("　　".join(q["options"]) if q["options"] else "（无文字选项）")
            _p = doc.add_paragraph()
            _p.add_run("正确答案：").bold = True
            _p.add_run(q["answer"])
            _p = doc.add_paragraph()
            _p.add_run("知识点：").bold = True
            _p.add_run(q["knowledge"] or self._auto_knowledge(q))
            doc.add_paragraph()
        doc.save(path)
        print(f"  ✅ 生成脚本: {path}（{len(self.questions)} 题，跳过无题干 {self.skipped_no_stem}）")
        return path

    # ------------------------------------------------------------
    def _loc_str(self, q):
        """App 位置描述：模块 · 单元 · 第N题（含大题时带大题号）"""
        _parts = [self.module]
        if q.get("unit"):
            _parts.append(f"U{q['unit']}")
        if q.get("big"):
            _parts.append(f"第{q['big']}大题")
        if q.get("qno"):
            _parts.append(f"第{q['qno']}题")
        return " · ".join(_parts)

    # ------------------------------------------------------------
    @staticmethod
    def _auto_knowledge(q):
        """从题干/答案自动推断知识点（简单启发式；复杂可后续接 LLM）"""
        txt = f"{q['stem']} {q['answer']} {' '.join(q['options'])}"
        for kw in _KNOWLEDGE_KWS:
            if kw in txt:
                return f"涉及{kw}相关知识点"
        return "基础知识点"

    # ------------------------------------------------------------
    def summary(self, unit):
        return {
            "unit": unit,
            "generated": len(self.questions),
            "skipped": self.skipped_no_stem,
        }
