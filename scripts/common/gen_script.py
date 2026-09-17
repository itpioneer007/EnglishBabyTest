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
    from docx.shared import Pt, RGBColor
    from docx.oxml.ns import qn
    _HAS_DOCX = True
except Exception:
    _HAS_DOCX = False

# ⚠ 已废弃（2026-09-10）：旧 `_auto_knowledge` 用它拼"涉及XX相关知识点"——
#   该表达被用户明令禁止，兜底逻辑已改为给出具体答案内容/明确标注待补充。
#   保留常量仅为兼容可能的外部引用，新代码请勿使用。
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

# ★★★ 2026-09-15 题目原文内容检查模板（用户需求）：
#   "检查测试过程中 App 放的题目内容是否存在错误"——例如原文
#   "Tom see lots of people running in the playground yesterday" 里 see 应为 saw。
#   输出刻意用「|」分隔的**单行文本**而不是 JSON：LLM 输出 JSON 经常被 ```json
#   包裹或漏引号，解析极易失败；行式格式容错高、人也能直接读。
CONTENT_CHECK_PROMPT_TEMPLATE = (
    "你是小学英语教材审校老师。下面是{g_grade}英语题目在 App 界面里显示的原文，"
    "请检查其中是否存在英语错误。\n"
    "原文：\n{g_text}\n\n"
    "要求：\n"
    "1. 只检查英语本身的错误：时态、主谓一致、单复数、冠词、介词、拼写、语序、"
    "中式英语等。\n"
    "2. 只报**确定**的错误；拿不准的一律不报（宁可漏报，不可误报）。\n"
    "3. 如果原文只是中文指令、或没有完整英文句子，回复：无错误\n"
    "4. 每行输出一条错误，格式严格为：错误片段|应改为|原因（15字内）\n"
    "   例如：see|saw|yesterday 提示用一般过去时\n"
    "5. 没有任何错误时，只输出三个字：无错误\n"
    "6. 不要输出解释、标题、编号或其它任何内容。"
)


def _parse_content_issues(text: str):
    """解析内容检查返回：每行 "错误片段|应改为|原因"；无错误时返回 []。"""
    if not text:
        return []
    if "无错误" in text and "|" not in text and "｜" not in text:
        return []
    out = []
    for line in str(text).splitlines():
        line = line.strip().strip("-•*　 　")
        if not line or ("|" not in line and "｜" not in line):
            continue
        parts = [p.strip() for p in re.split(r"[|｜]", line)]
        if len(parts) < 2:
            continue
        wrong, correct = parts[0], parts[1]
        reason = parts[2] if len(parts) > 2 else ""
        if not wrong or not correct or wrong == correct:
            continue
        if "无错误" in wrong or "无错误" in correct:
            continue
        out.append({"wrong": wrong[:40], "correct": correct[:40], "reason": reason[:30]})
    return out[:5]


def _unescape_html(s: str) -> str:
    """解码 uiautomator2 dump 残留的 HTML 实体 (&#10; / &amp; 等)
    ★ 2026-08-30 修复：题面 short passage 段含短文+多段换行（如"Xu You is kind.&#10;&#10;　　..."）
       实体渲染到 docx 后会显示成字面 "&#10;"。在所有 _extract_ui_question 入口
       统一解码一次，后续逻辑不再处理。
    """
    try:
        import html as _html
        return _html.unescape(s or "")
    except Exception:
        return s or ""


def _extract_ui_question(xml, answer="", qtype_hint=""):
    """从答题页 XML 提取一道题的（题干/选项/题型），供脚本生成收集。
    - 题干：分级提取——题干节点(question_title_tv/tv_caption/tv_title/tv_stem等)优先，
      兜底长文本（排除按钮/进度/计时器/选项噪音）；多段题干合并（指令+内容）
    - 选项：字母开头项（A. xx）或选项容器（option_cb 等）或纯字母（T/F）
    - 纯听音无题干（题干为空/仅"听录音"指令）→ stem 返回空，上层跳过
    """
    if not xml:
        return {"stem": "", "options": [], "qtype": qtype_hint}

    noise = ("下一题", "上一题", "检查", "提交", "查看报告", "练习报告",
             "恭喜", "回答正确", "回答错误", "很遗憾", "练习结束还剩", "还剩",
             "得分", "用时", "点击录音", "点击结束", "继续答题", "退出训练",
             "答题卡", "单元自检", "口语训练", "听力专项", "知识过关",
             "巧记单词", "语音评测", "全脑记词", "单词听写", "查看解析",
             "正确答案", "错误答案", "本大题", "本小题", "分值", "满分",
             "考前突破", "当前版本", "练习记录", "训练规则说明", "好的",
             "播放", "暂停", "重听", "上一页", "下一页",
             # ★ 2026-09-10 新增：应用锁遮罩提示会被当成题干混进脚本
             #   （真机实测题干出现"听录音，选择与录音内容相符的释义。 / 应用锁保护中"）
             "应用锁保护中", "应用锁", "解锁后继续")

    def _is_noise(t):
        if t in noise or any(n in t for n in noise):
            return True
        if re.match(r"^\d{1,2}:\d{2}$|^\d+(\.\d+)?%?$|^\d+\s*/\s*\d+$|^\d+分$", t):
            return True
        if re.match(r"^[A-F][.、．]\s*", t) or re.match(r"^[TF]\s*$", t):
            return True
        return False

    def _node_parts(_block):
        """从 node 块提取 (text, resource_id) — ★ 同时 html.unescape 防 &#10; 残留"""
        _mt = re.search(r'text="([^"]*)"', _block)
        _mr = re.search(r'resource-id="([^"]*)"', _block)
        return (_unescape_html(_mt.group(1)).strip() if _mt else "",
                _mr.group(1) if _mr else "")

    # ① 题干：优先题干节点（resource-id 含题干语义）——这些一定是题干文字
    stem_nodes = []
    for _nd in re.finditer(r'<node\b[^>]*>', xml):
        _block = _nd.group(0)
        t, rid = _node_parts(_block)
        if not t or len(t) < 2 or len(t) >= 100:
            continue
        if rid and re.search(r'(question_title|tv_caption|tv_title|tv_stem|tv_question|question_content|title_tv)', rid):
            stem_nodes.append(t)
    # ② 兜底：非选项/非噪音长文本（含短题干 ≥2 字符）
    if not stem_nodes:
        for _nd in re.finditer(r'<node\b[^>]*>', xml):
            _block = _nd.group(0)
            t, rid = _node_parts(_block)
            if not t or len(t) < 2 or len(t) >= 100:
                continue
            # 排除选项容器/按钮/交互节点
            if rid and re.search(r'(option_cb|option_iv|radio_btn|check_box|tv_option|btn_|tv_progress|tv_time|tv_index|iv_|img_)', rid):
                continue
            if _is_noise(t):
                continue
            stem_nodes.append(t)
    # ③ 合并：去重 + 去包含（保留完整），最多 3 段
    _merged = []
    for t in stem_nodes:
        t = re.sub(r"[（(]\s*共\d+分\s*[）)]", "", t).strip()  # 清洗分值
        # ★ 2026-08-26 清洗题干前缀题号进度（如 "13/32 选择各组中不同类的一项" →
        #   "选择各组中不同类的一项"）。App 常把题号进度和题干放同一 TextView。
        t = re.sub(r"^\s*\d+\s*[/／]\s*\d+\s*", "", t).strip()
        # ★ 2026-09-10 清洗关卡进度段（巧记单词"第6关 5/15" / "第6关  5"）：
        #   App 把关卡进度与题干放在相邻节点，合并后题干会拖一条" / 第6关 5"杂质
        #   （真机实测），导致脚本题干不干净、与脚本 docx 比对时误判不一致。
        if re.fullmatch(r"第\s*\d+\s*关[\s\d/／]*", t):
            continue  # 整段就是关卡进度 → 丢弃
        t = re.sub(r"^\s*第?\s*\d+\s*关\s*\d+\s*[/／]\s*\d+\s*", "", t).strip()
        if not t:
            continue
        if any(t == s or t in s or s in t for s in _merged):
            continue
        _merged.append(t)
        if len(_merged) >= 3:
            break
    stem = " ".join(_merged).strip()
    # ★ 纯听音指令判定：题干仅为"听录音/听音选X"等指令性文字 → 视为无题干（跳过）
    if stem.strip() and re.fullmatch(
        r"(听录音|听音|听一听|Listen|听录音[，,。 ]?[选判勾][出择].*|"
        r"听对话|听短文|听句子|听单词|听材料|听问题|请听).*",
        stem.strip(), re.IGNORECASE):
        stem = ""
    # ② 选项：字母开头项（A. xx）优先
    opts = []
    for m in re.finditer(r'text="([A-E][.、．]\s*[^"]{1,60})"', xml):
        t = _unescape_html(m.group(1)).strip()
        if t and t not in opts:
            opts.append(t)
    if not opts:
        # ★ 选项是 CheckBox/RadioButton（option_cb 等，文本无字母前缀，如 parrot/notebook）
        #   按出现顺序收集（单元自检等模块的选项就是这种独立单词）
        for m in re.finditer(
                r'<node[^>]*resource-id="[^"]*(?:option_cb|option_iv|radio_btn|check_box)[^"]*"[^>]*text="([^"]{1,40})"|'
                r'<node[^>]*text="([^"]{1,40})"[^>]*resource-id="[^"]*(?:option_cb|option_iv|radio_btn|check_box)[^"]*"', xml):
            t = _unescape_html(m.group(1) or m.group(2) or "").strip()
            if t and t not in opts:
                opts.append(t)
    if not opts:
        # 纯字母（T/F/A-E 判断题）
        for m in re.finditer(r'text="([TFABCDE])"', xml):
            t = m.group(1)
            if t not in opts:
                opts.append(t + ". ")
    return {"stem": stem.strip(), "options": opts[:6], "qtype": qtype_hint}


# ------------------------------------------------------------
# ★ 2026-09-15 图片题截图（统一入口）
#   图片题的题干/选项是图片，XML 里提不到文字 → 答题时把答题页截图存盘，
#   脚本生成阶段（QuestionCollector.finish_unit）用视觉模型识别补全内容。
#   各模块识别到"图片题"时调用本函数，把返回路径传给 add(image_path=...)。
_IMG_DIR_NAME = ("screenshots", "script_imgs")

_MODULE_SLUG = {
    "听力专项": "listen", "听力专项测试": "listen_test",
    "口语训练": "oral", "语音评测": "speech",
    "单元自检": "unitcheck", "巧记单词": "qiaoji", "知识过关": "zhishi",
}


def _module_slug(module: str) -> str:
    """模块名 → 文件名安全短标识（如 '听力专项'→'listen'）"""
    return _MODULE_SLUG.get(module) or re.sub(r"[^\w]", "", module or "mod")[:12] or "mod"


def save_image_shot(d, module: str, qno, tag: str = "img") -> str:
    """图片题截图：存 screenshots/script_imgs/<模块>_<tag><题号>.png，返回路径（失败返回 ""）。

    供各模块答题时对图片题截图；路径传给 QuestionCollector.add(image_path=...)，
    finish_unit() 会用视觉模型识别该截图，补全题干/选项/答案。
    """
    try:
        if d is None:
            return ""
        _root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        _dir = os.path.join(_root, *_IMG_DIR_NAME)
        os.makedirs(_dir, exist_ok=True)
        try:
            _n = int(qno)
        except Exception:
            _n = 0
        _p = os.path.join(_dir, f"{_module_slug(module)}_{tag}{_n:02d}.png")
        for _i in range(3):          # 截图偶发 Errno 22，重试可自愈
            try:
                d.screenshot(_p)
                return _p if os.path.exists(_p) else ""
            except OSError:
                if _i >= 2:
                    return ""
                time.sleep(0.4)
    except Exception:
        pass
    return ""


def is_image_question(xml: str, min_y: int = 400) -> bool:
    """判断当前答题页是否为"图片题"（题干/选项为图片，XML 无文字可解析）。

    判据（从严到宽，命中其一即判为图片题）：
      ① 选项区（y > min_y）有**无文字**的 CheckBox / ImageView 选项容器；
      ② 题干区有 ImageView 且整页几乎无文字。
    ⚠ 判据①刻意要求"无文字"：单元自检等模块的 option_cb 选项是**带文字的**
      CheckBox（如 parrot/notebook），那种是普通文字选择题，不能算图片题。
    仅供模块在答题时决定"是否截图 + 传 image_path"，不做内容判定。
    """
    if not xml:
        return False
    # 有明确的文字选项（A. xx / 单字母）→ 不是图片题
    if re.search(r'text="[A-E][.、．]\s*[^"]{1,60}"', xml) or \
       re.search(r'text="[TFABCDE]"', xml):
        return False
    _txts = [t for t in re.findall(r'text="([^"]*)"', xml) if t and t.strip()]
    _area = re.compile(r'bounds="\[\d+,(\d+)\]\[\d+,(\d+)\]"')
    # ① 选项区有"无文字"的图片/勾选框容器（图片选项的 CheckBox 自身不带文字）
    for _m in re.finditer(r'<node[^>]*>', xml):
        _b = _m.group(0)
        _bm = _area.search(_b)
        if not (_bm and int(_bm.group(1)) > min_y):
            continue
        _tm = re.search(r'text="([^"]*)"', _b)
        if _tm and _tm.group(1).strip():
            continue                      # 该容器带文字 → 是文字选项，跳过
        if 'class="android.widget.CheckBox"' in _b:
            return True
        if 'ImageView' in _b and ('option' in _b or 'pic' in _b or 'iv_' in _b):
            return True
    # ② 题干区有图、且整页几乎无文字（正常题至少有一句题干文字）
    if 'ImageView' in xml and len(" ".join(_txts)) < 12:
        return True
    return False


def _trim_knowledge(text: str, limit: int = 120) -> str:
    """知识点截断：优先在句末/分句标点处断开。

    ★ 2026-09-15 修复：原实现 `ans[:120]` 硬截断会切断词语——
      实测六年级上册口语训练U1 第2题被截成「…符合“形容词 + 名」（缺半截），
      审查员看到的是残句。改为在最近的句读标点处断开，实在没有才用省略号。
    """
    t = (text or "").strip()
    if len(t) <= limit:
        return t
    head = t[:limit]
    for p in ("。", "！", "？", "；", ".", "!", "?", ";"):
        i = head.rfind(p)
        if i >= int(limit * 0.6):
            return head[:i + 1]
    for p in ("，", ",", "、", "："):
        i = head.rfind(p)
        if i >= int(limit * 0.6):
            return head[:i] + "…"
    return head.rstrip() + "…"


class QuestionCollector:
    """答题过程中的题目收集器（每道有题干的题收集一条，单元答完汇总写脚本）"""

    def __init__(self, module="单元自检", version="", grade="", save_root=None):
        self.module = module
        self.version = version or "湘少版"
        self.grade = grade or "五年级上册"
        # ★ 改造方案：取消白名单，所有模块都生成脚本。
        #   听音题用 ASR 补 recording，图片题用视觉模型补内容，跟读题用 speaker_word + recording。
        self.gen_allowed = True
        # 保存目录：项目根/gen_scripts（默认，scripts/common/gen_script.py 上三级）；可传 save_root 覆盖
        self.save_root = save_root or os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "gen_scripts")
        os.makedirs(self.save_root, exist_ok=True)
        self.questions = []          # 当前单元收集的题（含题干可解析的）
        self.skipped_no_stem = 0     # 无题干跳过的题数（纯听音等）
        # ★ 2026-09-15 无「明确答案」跳过的题数（口语跟读 / 看图说句等）——
        #   用户明确：这类题在 App 里没有标准答案，不算"题目"，不做解析也不进脚本
        self.skipped_no_answer = 0
        # ★ 2026-09-15 题目原文错误检查缓存（原文 → 错误列表）：同一原文只查一次 LLM
        self._content_cache = {}
        # ★ 2026-09-10 知识点缓存（题目内容 → 解析文案）与 LLM 客户端复用，
        #   避免同一道题重复触发 LLM（用户明确要求知识点生成具备确定性）
        self._knowledge_cache = {}
        self._knowledge_cache_hits = 0
        self._llm = None
        # ★ 2026-09-10 熔断状态：LLM 额度/密钥不可用时置 True，剩余题目不再调用 LLM
        self._llm_disabled = False
        self._llm_fail_streak = 0

    # ------------------------------------------------------------
    def add(self, qno, stem="", options=None, answer="", qtype="",
            unit=0, recording="", knowledge="", big=None, image_path="",
            allow_listen=False, speaker_word="", level=None):
        """收集一道题。只有「有明确答案」且能解析出内容的题才保留，否则跳过。

        ★ 2026-09-15 准入规则（用户明确）：脚本解析只针对**明确有答案**的题目；
          口语跟读 / 看图说句这类在 App 里没有标准答案的，不算"题目"，一律跳过。
          判据见方法内 `_has_answer`：有选项 / 有实义答案 / 有图片题截图。

        Args:
            qno: 题号（全局/单元内序号）
            stem: 题干文字（空 = 纯听音/无题干 → 跳过）
            options: 选项列表 ['A. xx', 'B. xx', ...]
            answer: 答案（点击的选项，如 'B'）
            qtype: 题型（如 '单选', '判断'）
            unit: 单元号
            recording: 录音原文（听力题可能有）
            knowledge: 知识点（可选，LLM 生成或留空）
            big: 大题号（口语训练等"第N大题"定位用）
            image_path: 图片题截图路径（★ 选项为空但有截图时，finish_unit 用视觉模型识别补全）
            allow_listen: ★ 2026-08-26 是否允许收集听音题（巧记单词传 True——
              听音选释义题题干+扬声器识别词+选项都应进解析脚本；听力专项/口语训练仍 False）
            speaker_word: ★ 2026-08-26 扬声器播放的单词（ASR 识别，听音题用，放题干后展示）
            level: ★ 2026-09-10 关卡号（巧记单词"第N关"，位置行/分组显示用）。
              **None = 该模块无关卡概念**（单元自检等，行为与旧版完全一致）；
              **0 = boss 关**（巧记单词最后一关，App 里显示为"第6关"）。
              ⚠ 不能用 0 当"无关卡"默认值——否则 boss 关会被静默丢掉分组标签。
        """
        stem = (stem or "").strip()
        answer = (answer or "").strip()
        recording = (recording or "").strip()
        # ★ 2026-08-26 题干兜底清洗：去掉题号进度前缀（"13/32 选择..." → "选择..."）。
        #   _extract_ui_question 已处理，这里兜底（防其它来源传入带前缀题干）。
        stem = re.sub(r"^\s*\d+\s*[/／]\s*\d+\s*", "", stem).strip()
        _has_img = bool(image_path) and os.path.exists(image_path)
        # ★ 改造方案：放宽跳过条件——只有题干、答案、录音原文都为空才跳过。
        #   听音题有 recording 即可收集，跟读题有 speaker_word 可收集，图片题有截图可补选项。
        if not stem and not answer and not recording:
            # 图片题：无题干但有截图 → 仍然记录（finish_unit 用视觉模型识别补全）
            if image_path and os.path.exists(image_path):
                self.questions.append({
                    "qno": int(qno) if str(qno).isdigit() else qno,
                    "stem": stem, "options": [], "answer": str(answer).strip(),
                    "qtype": qtype or "", "unit": int(unit) if str(unit).isdigit() else unit,
                    "level": level,
                    "recording": recording,
                    "speaker_word": (speaker_word or "").strip(),
                    "knowledge": "", "big": big,
                    "image_path": image_path,
                    "time": datetime.now().strftime("%H:%M:%S"),
                })
                return
            self.skipped_no_stem += 1
            return
        # ★ 听音题判定（用户明确要求）：题干含"听"字即跳过——
        #   "听词汇/听句子/听对话/听录音" 全是听力题，题目实质在音频里，
        #   脚本里没有可解析的题干文字，跳过不做脚本审查
        #   （保留含"听"的非听音词：如"听说读写"等极少数情况由下方白名单保护）
        # ★ 2026-08-26 allow_listen=True（巧记单词）：听音题也收集——
        #   题干 + 选项 + 扬声器识别词(speaker_word) + recording 一并进解析脚本，
        #   这样听音选释义题也能生成脚本且能核对扬声器内容
        _LISTEN_WHITELIST = ("听说读写", "听力理解能力", "听说")
        _is_listen = ("听" in stem and not any(w in stem for w in _LISTEN_WHITELIST)) or \
            bool(re.match(r"^\s*(Listen|listen|Listening)\b", stem))
        # ★ 2026-09-15 图片题放行：图片题题干常为"听录音，选择与录音内容相符的图片"，
        #   会被下面的听音判定拦掉——但图片题的内容在截图里（image_path），
        #   视觉模型可识别补全，不属于"音频里、脚本无法解析"的纯听音题。
        if _is_listen and not allow_listen and not _has_img:
            self.skipped_no_stem += 1
            return
        opts = [str(o).strip() for o in (options or []) if str(o).strip()]
        # ★★★★★ 2026-09-15 准入收紧（用户明确要求）——放在最后一道闸：
        #   "脚本解析不是所有题目都需要，是指**明确有答案**的题目。
        #    口语跟读 / 看图说句这类没有明确答案的，都不算是题目。"
        #   判据（命中其一即可，从严到宽）：
        #     ① 有选项 → 选择题/判断题一定有标准答案（即使本次没读到答案字母，
        #        App 里也是确定的，不能因为解析失败就把整道题丢掉）；
        #     ② 有实义答案值（排除"人工核查（图片题）"这类占位串）；
        #     ③ 有图片题截图 → 正确答案由 App 判定，内容由视觉补全。
        #   口语训练传的是 options=[] / answer="" / 无截图 → 落空被跳过，属预期：
        #   视觉识别出的画面描述只用于让学生跟读，不作为解析脚本内容。
        #   ⚠ 刻意排在听音判定**之后**：纯听音题仍归入"无题干/纯听音"口径，
        #     保持既有统计语义不变，本规则只做最后的净增过滤。
        _ans_s = (answer or "").strip()
        _has_answer = bool(opts) or (
            bool(_ans_s) and not any(p in _ans_s for p in
                                    ("人工核查", "待人工", "未识别", "未知", "无法确定")))
        if not _has_answer and not _has_img:
            self.skipped_no_answer += 1
            return
        # 清洗选项：去掉多余空白（"A.  sport" → "A. sport"）
        opts = [re.sub(r"\s+", " ", o) for o in opts]
        # ★ 2026-08-26 选项自动补字母编号：若选项无字母前缀（如 ["went","visited","stay"]）
        #   补成 ["A. went","B. visited","C. stay"]，这样答案字母(A/B/C)才能与选项对号。
        #   否则脚本显示"选项：went visited stay / 正确答案：A"完全对不上。
        _opts_normalized = []
        for _i, _o in enumerate(opts):
            if re.match(r"^[A-F][.、．]\s*", _o):
                _opts_normalized.append(_o)
            else:
                _opts_normalized.append(f"{chr(65+_i)}. {_o}")
        opts = _opts_normalized
        # ★ 答案归一化：answer 若是选项内容（如 "went"）而非字母(A/B/C)，转成对应字母
        #   （LLM 判定时返回的可能是选项内容；点击字母时已是字母，保留原样）
        _ans_clean = (answer or "").strip()
        if _ans_clean and len(_ans_clean) <= 40 and not re.match(r"^[A-F]$", _ans_clean.upper()):
            for _i, _o in enumerate(opts):
                _text = re.sub(r"^[A-F][.、．]\s*", "", _o).strip()
                if _ans_clean.lower() in _text.lower() or _text.lower() in _ans_clean.lower():
                    _ans_clean = chr(65 + _i)
                    break
            # 未匹配到明确字母 → 保留原答案（可能是拼音/单词内容），不强行改
        self.questions.append({
            "qno": int(qno) if str(qno).isdigit() else qno,
            "stem": stem, "options": opts, "answer": _ans_clean,
            "qtype": qtype or "", "unit": int(unit) if str(unit).isdigit() else unit,
            "recording": (recording or "").strip(),
            "speaker_word": (speaker_word or "").strip(),  # ★ 扬声器识别词（听音题）
            "knowledge": (knowledge or "").strip(),
            "big": big,
            "level": level,  # ★ 2026-09-10 关卡号（巧记单词"第N关"）
            # ★ 2026-09-15 图片题截图：即使题干/答案非空也要保留——
            #   图片题的选项是图片，XML 提不到文字（只有一个字母占位），
            #   finish_unit 靠这个路径做视觉识别补全。
            "image_path": image_path,
            "time": datetime.now().strftime("%H:%M:%S"),
        })

    # ------------------------------------------------------------
    def _llm_knowledge(self, q):
        """用大模型生成知识点解析：符合该版本年级的知识水平，精简有说服力。
        像"为什么1+1=2"要用小学方法解释——不模糊、直接给出该年级该懂的结论。

        ★ 2026-09-10 两处优化（用户要求"知识点生成需具备确定性，避免同一题重复触发 LLM"）：
          1. **题目内容级缓存**：key = 题干 + 选项 + 答案（不含关卡/单元）——
             巧记单词整单元 101 题里有大量重复词（同一单词在多个关卡反复出现），
             缓存后同一题只调一次 LLM，既省时间（实测可省 50%+ 调用）又保证
             同一道题的解析文案**逐字一致**（确定性）。
          2. **复用 LLMClient**：原来每题都 `LLMClient.from_config()` 重建客户端，
             整单元 101 题就是 101 次初始化；改为实例内复用。
        """
        # ★ 2026-09-15 纯音频/跟读题守卫：题干只是页面指令（如"听音频跟读"），
        #   且**没有任何可解析内容**（无选项、无答案、无图片描述）→ LLM 只会吐套话
        #   （实测一个大题 5 题答案逐字雷同，违反"知识点要有说服力"的要求）。
        #   改为固定提示，既避免误导也不耗额度。
        #   ⚠ 判据必须同时要求"无可解析内容"：图片题的题干也常是纯中文指令
        #     （如"听录音，选择与录音内容相符的图片"），但它的选项由视觉模型补全，
        #     内容在选项里 → 必须照常走 LLM。只看"题干无英文"会误伤这类题。
        _stem_raw = (q.get("stem") or "").strip()
        _has_en = bool(re.search(r"[A-Za-z]{2,}", _stem_raw)) or \
            any(re.search(r"[A-Za-z]{2,}", str(o)) for o in (q.get("options") or []))
        _has_content = bool(q.get("options")) or bool(q.get("answer")) \
            or bool(q.get("image_desc"))
        if not _has_en and not _has_content and \
                re.search(r"听|跟读|口语", _stem_raw + " " + (q.get("qtype") or "")):
            return "（音频/跟读题·题干无文字内容，需对照录音核对发音与语调）"
        _key = self._knowledge_key(q)
        _hit = self._knowledge_cache.get(_key)
        if _hit:
            self._knowledge_cache_hits += 1
            return _hit
        # ★ 2026-09-10 熔断：LLM 已判定不可用（额度耗尽/密钥失效）→ 不再逐题重试。
        #   否则整单元 101 题 × 每题 2 次尝试 × ~10s = 半小时纯空转（用户以为卡死）。
        if self._llm_disabled:
            return self._auto_knowledge(q)
        _last_raw = ""
        try:
            sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
            from src.reviewer_common import LLMClient, is_fatal_llm_error
            if self._llm is None:
                self._llm = LLMClient.from_config()
            llm = self._llm
            opt_str = " ".join(q["options"]) if q["options"] else "（无文字选项）"
            # ★ 固定模板（KNOWLEDGE_PROMPT_TEMPLATE），保证解析规范一致
            prompt = KNOWLEDGE_PROMPT_TEMPLATE.format(
                g_grade=self.grade, g_version=self.version,
                g_stem=q["stem"], g_options=opt_str, g_answer=q["answer"])
            # ★ 2026-09-15 原文已查出错误时，必须让解析**指出错误**：
            #   否则 LLM 会把错误用法当正确内容讲解（如把 "Tom see" 讲成"用原形"），
            #   等于用错误解析去"印证"错误题目，比不解析更糟。
            _errs = q.get("content_issues") or []
            if _errs:
                _hint = "；".join(f"{_e['wrong']} 应为 {_e['correct']}（{_e['reason']}）"
                                 for _e in _errs)
                prompt += ("\n\n⚠ 已知本题原文存在疑似错误：" + _hint +
                           "。请在解析中**明确指出这个错误并给出正确形式**，"
                           "绝对不要把错误用法当作正确内容来讲解。")
            ans = ""
            for _try in range(2):  # 不合格重试一次
                ans = (llm.ask(prompt) or "").strip()
                _last_raw = ans
                if ans and len(ans) > 5 and "LLM 调用失败" not in ans and self._check_knowledge_ok(ans):
                    _ans = _trim_knowledge(ans, 120)
                    self._knowledge_cache[_key] = _ans
                    self._llm_fail_streak = 0
                    return _ans
                if is_fatal_llm_error(ans):   # 额度/密钥问题 → 重试无意义
                    break
                ans = ""  # 不合格 → 重试
            # 走到这里说明本次生成失败：判定是否致命 → 熔断并**大声**提示（只提示一次）
            self._llm_fail_streak += 1
            if is_fatal_llm_error(_last_raw) or self._llm_fail_streak >= 3:
                self._llm_disabled = True
                _why = _last_raw[:110] if _last_raw else "连续多次生成不合格"
                print(f"  ⚠ 知识点 LLM 已停用（{_why}）"
                      f"→ 本单元剩余 {len(self.questions)} 题改用兜底解析，"
                      f"请检查 LLM 额度/密钥后重新生成脚本")
                try:
                    from common.logger import log_msg
                    log_msg(f"⚠ 知识点 LLM 不可用（{_why}）→ 已熔断，剩余题目改用兜底解析；"
                            f"请检查 DeepSeek 余额/密钥（额度耗尽会返回 402 Payment Required）",
                            "warning")
                except Exception:
                    pass
        except Exception as _e:
            print(f"  ⚠ 知识点 LLM 生成失败: {_e}")
        return self._auto_knowledge(q)

    # ------------------------------------------------------------
    @staticmethod
    def _knowledge_key(q):
        """知识点缓存 key：仅由题目内容决定（题干+答案+选项），与关卡/单元无关。

        ★ 用内容做 key 是刻意的：同一道题无论出现在第几关第几单元，
          知识点文案必须完全一致（确定性），不能"同一个词两种解释"。
        """
        return "|".join([
            (q.get("stem") or "").strip(),
            (q.get("answer") or "").strip(),
            "~".join(q.get("options") or []),
        ])

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
    def _llm_content_check(self, q):
        """检查 App 显示的题目原文是否存在英语错误（语法/用词/拼写）。

        用户需求（2026-09-15）：测试过程中要能发现"App 放的题目本身写错了"。
        例：原文 "Tom see lots of people running in the playground yesterday"
            中 see 应为过去式 saw（有 yesterday 这个过去时间标志）。

        返回 [{'wrong':..., 'correct':..., 'reason':...}, ...]；无错误返回 []。

        ★ 只检查**来自 App 界面的英文**（题干 / 听力原文）。视觉模型生成的
          画面描述（qtype 含"看图"）是我们自己的输出，查它没有意义 → 跳过。
        ★ 英文词少于 3 个直接跳过：中文指令题（"听录音，选择…"）没有句子可审，
          检查只会白花额度。
        """
        if "看图" in (q.get("qtype") or ""):
            return []
        _text = " ".join(x for x in [(q.get("stem") or "").strip(),
                                     (q.get("recording") or "").strip()] if x)
        # 选项本身是完整句时（如 "A. He go to school by bus every day."）也纳入检查；
        # 单词/短语选项（"A. see"）不查——片段不成句，查了只会误报。
        for _o in (q.get("options") or []):
            _o = re.sub(r"^[A-F][.、．]\s*", "", str(_o)).strip()
            if len(re.findall(r"[A-Za-z]{2,}", _o)) >= 4:
                _text += " " + _o
        if len(re.findall(r"[A-Za-z]{2,}", _text)) < 3:
            return []
        if _text in self._content_cache:
            return self._content_cache[_text]
        if self._llm_disabled:          # 额度/密钥不可用 → 不再逐题重试
            return []
        _issues = []
        try:
            sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
            from src.reviewer_common import LLMClient, is_fatal_llm_error
            if self._llm is None:
                self._llm = LLMClient.from_config()
            ans = (self._llm.ask(CONTENT_CHECK_PROMPT_TEMPLATE.format(
                g_grade=self.grade, g_text=_text)) or "").strip()
            if is_fatal_llm_error(ans):
                self._llm_disabled = True
            else:
                _issues = _parse_content_issues(ans)
        except Exception as _e:
            print(f"  ⚠ 题目原文内容检查失败（不影响脚本生成）: {_e}")
        self._content_cache[_text] = _issues
        return _issues

    # ------------------------------------------------------------
    def finish_unit(self, unit):
        """单元答完：把收集到的题写成脚本 docx（模板格式）。
        返回生成的文件路径；无题可写返回 None。
        """
        # ★ 改造方案：取消白名单拦截，所有模块都生成脚本
        #   （听音题用 ASR 补 recording，图片题用视觉模型补内容，跟读题扬声器识别）
        if not self.questions:
            # ★ 2026-09-15 说明"为什么没有脚本"：口语跟读/看图说句这类题在 App 里
            #   没有标准答案，按新规则不算"题目"，因此整个单元不产出解析脚本。
            #   （用户明确：这些题没必要做解析，视觉识别只用于让学生跟读。）
            _why = []
            if self.skipped_no_answer:
                _why.append(f"{self.skipped_no_answer} 题无明确答案（口语/跟读类，不做解析）")
            if self.skipped_no_stem:
                _why.append(f"{self.skipped_no_stem} 题无题干（纯听音类）")
            _msg = f"单元 {unit} 未生成解析脚本：{'；'.join(_why) or '无有效题目'}"
            print(f"  ℹ {_msg}")
            try:
                from common.logger import log_msg
                log_msg(f"ℹ U{unit} {_msg}（按规则只对有明确答案的题目生成解析）", "info")
            except Exception:
                pass
            self.skipped_no_stem = 0
            self.skipped_no_answer = 0
            return None
        if not _HAS_DOCX:
            print("  ❌ python-docx 不可用，无法生成脚本")
            return None
        # ★ 2026-09-15 图片题识别补全（**必须排在知识点生成之前**）
        #   图片题的选项是图片，XML 只能提到字母占位 → 先用视觉模型识别截图补全
        #   options / answer / stem，再让 LLM 基于"补全后的完整题目"生成知识点。
        #   ⚠ 此前这段排在知识点生成之后，导致两个真问题：
        #     ① 图片题生成解析时题干/选项仍是空的 → 等于拿空题目问 LLM，解析无意义；
        #     ② "图片内容描述"拼接依赖 knowledge 为空，而此时已非空 → 永远不生效（死代码）。
        _need_vision = []
        for _q in self.questions:
            _p = _q.get("image_path")
            if not _p or not os.path.exists(_p):
                continue
            _opts = _q.get("options") or []
            # 无选项，或选项只是字母占位（"A. " / "B. "）→ 内容在图片里，需视觉识别
            if not _opts or all(re.fullmatch(r"[A-F][.、．]?\s*", str(o or "")) for o in _opts):
                _need_vision.append(_q)
        if _need_vision:
            print(f"  🖼 正在识别 {len(_need_vision)} 道图片题的截图（视觉模型）…")
            try:
                from common.logger import log_msg
                log_msg(f"🖼 图片题解析：正在用视觉模型识别 {len(_need_vision)} 道图片题的截图内容…", "info")
            except Exception:
                pass
            for q in _need_vision:
                try:
                    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                    from common.vision_fill import recognize_image_question
                    res = recognize_image_question(
                        q.get("image_path", ""),
                        question_hint=q.get("qtype", ""),
                        known_options=None,
                        answer_hint=q.get("answer", ""),
                    )
                    # ★ 无论识别成功与否都标记 image_src：脚本里要提示"内容来自视觉识别"
                    q["image_src"] = True
                    if res.get("ok"):
                        if res.get("options"):
                            q["options"] = res["options"]
                        if res.get("answer"):
                            q["answer"] = res["answer"]
                        if res.get("stem"):
                            q["stem"] = res["stem"]
                        q["image_desc"] = (res.get("description") or "").strip()
                        print(f"    ✅ Q{q.get('qno')} 图片识别完成: {q['image_desc'][:30]}")
                    else:
                        q["image_desc"] = ""
                        print(f"    ⚠ Q{q.get('qno')} 图片识别失败: {res.get('error', '')[:60]}")
                except Exception as e:
                    q["image_src"] = True
                    q["image_desc"] = ""
                    print(f"    ⚠ Q{q.get('qno')} 图片识别异常: {e}")
        # ★★★★★ 2026-09-15 题目原文错误检查（**必须排在知识点生成之前**）
        #   用户需求："检查测试过程中 App 放的题目内容是否存在错误"。
        #   例：原文 "Tom see lots of people running in the playground yesterday"
        #       → see 应为 saw（yesterday 是过去时间标志）。
        #   ⚠ 顺序至关重要：若原文本身有错而先做知识点，LLM 会把错误用法当正确讲，
        #     等于用错误解析"印证"错误题目 —— 比不解析更糟。
        #     因此这里先查错 → 日志标出 → 结果存进 q["content_issues"]，
        #     再由 _llm_knowledge / 脚本渲染使用。
        _err_total = 0
        for q in self.questions:
            q["content_issues"] = self._llm_content_check(q)
            for _it in q["content_issues"]:
                _err_total += 1
                _warn = (f"⚠ {self._loc_str(q)} 题目原文疑似错误："
                         f"{_it['wrong']} → {_it['correct']}（{_it['reason']}）")
                print(f"  {_warn}")
                try:
                    from common.logger import log_msg
                    log_msg(_warn, "warning")
                except Exception:
                    pass
        if self.questions:
            print(f"  🔍 已检查 {len(self.questions)} 道题的原文内容，"
                  f"发现 {_err_total} 处疑似错误")
        # ★ 知识点用大模型生成（题目内容去重后调用；该年级知识点有说服力）
        _total_q = len(self.questions)
        _need = sum(1 for q in self.questions
                    if not q.get("knowledge")
                    and self._knowledge_key(q) not in self._knowledge_cache)
        _dup = _total_q - _need - sum(1 for q in self.questions if q.get("knowledge"))
        print(f"  🧠 正在为 {_total_q} 题生成知识点解析（LLM）…"
              + (f"（去重后可省 {_dup} 次重复调用）" if _dup > 0 else ""))
        for _gi, q in enumerate(self.questions, 1):
            if not q.get("knowledge"):
                q["knowledge"] = self._llm_knowledge(q)
            # ★ 进度心跳：逐题调 LLM 耗时久，定期提示避免误以为卡死
            if _total_q >= 10 and (_gi == 1 or _gi % 10 == 0 or _gi == _total_q):
                try:
                    from common.logger import log_msg
                    log_msg(f"⏳ 脚本生成进行中 {_gi}/{_total_q}…", "info")
                except Exception:
                    print(f"  ⏳ 脚本生成进行中 {_gi}/{_total_q}…")
        if self._knowledge_cache_hits:
            print(f"  ♻ 知识点命中缓存 {self._knowledge_cache_hits} 题（同一题目复用解析，保证文案一致）")
        _u = f"U{unit}"
        # ★ 规范文件名：日期+版本缩写+年级缩写+模块[+单元]，如
        #   "260817湘少五上单元自检U6.docx"（参考官方脚本"260714新湘鲁六上听力专项"格式）
        fname = f"{datetime.now().strftime('%y%m%d')}{self._short_version()}{self._short_grade()}{self.module}{_u}.docx"
        path = os.path.join(self.save_root, fname)
        doc = Document()
        # ★ 统一字体：不用内置 Heading/Title 样式（会随主题变蓝色Calibri→
        #   与正文字体颜色/大小/粗细不一致，用户反馈"同一个标题里不一致"）
        #   全部用 Normal + 手动设置：中文黑体、英文Arial、黑色、固定大小
        _normal = doc.styles["Normal"]
        _normal.font.name = "Arial"
        _normal.font.size = Pt(11)
        _normal.font.color.rgb = RGBColor(0x33, 0x33, 0x33)
        _normal.font.bold = False
        try:
            _normal.element.rPr.rFonts.set(qn("w:eastAsia"), "黑体")
        except Exception:
            pass

        def _add_line(text="", bold=False, size=11, space_after=4):
            """统一行：Normal 样式 + 指定加粗/字号（全文档一致，黑体Arial）"""
            _p = doc.add_paragraph()
            _p.paragraph_format.space_after = Pt(space_after)
            _r = _p.add_run(text)
            _r.font.name = "Arial"
            try:
                _r.element.rPr.rFonts.set(qn("w:eastAsia"), "黑体")
            except Exception:
                pass
            _r.font.size = Pt(size)
            _r.font.bold = bold
            _r.font.color.rgb = RGBColor(0x33, 0x33, 0x33)
            return _p

        # 文档标题（大号黑色加粗，不用 Title 样式）
        _add_line(f"{self.module} · {self.grade} {_u} · 题目解析脚本", bold=True, size=16, space_after=6)
        _add_line(f"版本：{self.version}　|　单元：{_u}　|　生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}", size=10, space_after=2)
        # ★ 2026-09-15 表头只写真正发生了的跳过类别（都为 0 时保持简洁）
        _skip_bits = []
        if self.skipped_no_answer:
            _skip_bits.append(f"无明确答案（口语/跟读类）{self.skipped_no_answer} 题")
        if self.skipped_no_stem:
            _skip_bits.append(f"无题干/纯听音 {self.skipped_no_stem} 题")
        _skip_txt = f"（{'、'.join(_skip_bits)}已跳过）" if _skip_bits else ""
        _add_line(f"共 {len(self.questions)} 题{_skip_txt}", size=10, space_after=6)
        # ★ 2026-09-15 题目原文错误汇总（逐题详情见各题下方）
        _err_n = sum(len(q.get("content_issues") or []) for q in self.questions)
        if _err_n:
            _add_line(f"⚠ 本次共发现 {_err_n} 处题目原文疑似错误（详见各题「原文疑似错误」行）",
                      size=10, space_after=6)
        # ★ 2026-09-10：按【关卡】分组列出（巧记单词一个单元 6 关，各关题号都从 1 重来，
        #   平铺列表会让审查员分不清"第3题"是哪一关的）——有关卡时插入关卡分组标题，
        #   并在"共 N 题"下方给出每关题数明细；无 level（None）的模块（单元自检等）行为完全不变。
        #   ⚠ level=0 是 boss 关（真关卡），必须用 `is not None` 判断，不能当"无关卡"。
        _lv_counts = {}
        for _q in self.questions:
            if _q.get("level") is not None:
                _lv_counts[_q["level"]] = _lv_counts.get(_q["level"], 0) + 1
        if _lv_counts:
            _detail = "　|　".join(
                f"{self._level_label(k)} {v} 题" for k, v in sorted(_lv_counts.items()))
            _add_line(f"分关卡：{_detail}", size=10, space_after=10)
        else:
            _add_line("", size=10, space_after=4)
        _last_lv = "__none__"
        for i, q in enumerate(self.questions, 1):
            # ★ 关卡分组标题（level 变化时插入，只插一次）
            _lv = q.get("level")
            if _lv is not None and _lv != _last_lv:
                _add_line(f"━━ {self._level_label(_lv)}（{_lv_counts.get(_lv, 0)} 题）━━",
                          bold=True, size=14, space_after=4)
                _last_lv = _lv
            # 题号（标题，简洁）
            _add_line(f"第{i}题", bold=True, size=13, space_after=2)
            # 题干（完整内容：指令+具体内容，如"请找出与下面选项不符的一项"）
            # ★ 2026-09-15 图片题：题干/选项来自视觉模型识别（概率性结论），
            #   显式标注来源，审查员一眼知道哪些字段需要人工复核。
            _stem_show = q['stem'] or "（图片题：题干未识别）"
            # ★ 2026-09-15 视觉来源标注：图片题（image_src）与口语训练"看图说句"
            #   （qtype 含"看图"）的题干来自视觉模型识别，属概率性结论，
            #   显式标注让审查员知道哪些字段需要人工复核（避免伪装成确定结论）。
            if q.get("image_src") or "看图" in (q.get("qtype") or ""):
                _stem_show += "　［内容由视觉识别·需人工复核］"
            _add_line(f"题干：{_stem_show}", size=11, space_after=2)
            _add_line(f"位置：{self._loc_str(q)}", size=11, space_after=2)
            # ★ 2026-09-15 空选项文案按题型区分：口语题本来就没有选项，
            #   若沿用"内容见题目图片"，审查员会以为有图可查（图片目录实际为空）。
            if q['options']:
                _opt_show = '　　'.join(q['options'])
            elif q.get("image_src") or q.get("image_desc"):
                _opt_show = '（无文字选项·内容见题目图片）'
            elif "口语" in (q.get("qtype") or ""):
                _opt_show = '（口语题·无选项）'
            else:
                _opt_show = '（无文字选项）'
            _add_line(f"选项：{_opt_show}", size=11, space_after=2)
            # ★ 图片题：单独给出画面内容描述（选项描述之外的整体画面）
            if q.get("image_desc"):
                _add_line(f"图片内容：{q['image_desc']}", size=11, space_after=2)
            # ★ 答案：优先给出字母 + 对应选项内容（让检查人一眼对上）
            _ans = (q['answer'] or "").strip()
            _ans_opt = ""
            if _ans and re.match(r"^[A-F]$", _ans.upper()):
                _idx = ord(_ans.upper()) - 65
                if 0 <= _idx < len(q['options']):
                    _ans_opt = re.sub(r"^[A-F][.、．]\s*", "", q['options'][_idx]).strip()
            _ans_line = f"正确答案：{_ans}"
            if _ans_opt:
                _ans_line += f"（{_ans_opt}）"
            _add_line(_ans_line, size=11, space_after=2)
            # ★ 2026-09-15 题目原文疑似错误：App 界面显示的英文本身写错了
            #   （用户需求：测试过程中要能发现题目内容有误，这里在脚本里标出；
            #    同一条也会以 ⚠ 级别打进运行日志）
            for _it in (q.get("content_issues") or []):
                _add_line(f"⚠ 题目原文疑似错误：{_it['wrong']} → {_it['correct']}"
                          f"（{_it['reason']}）", size=11, space_after=2)
            _add_line(f"知识点：{q['knowledge'] or self._auto_knowledge(q)}", size=11, space_after=10)
        doc.save(path)
        print(f"  ✅ 生成脚本: {path}（{len(self.questions)} 题，跳过无题干 {self.skipped_no_stem}）")
        # ★ 2026-09-15 写出后清空已收集题目：收集器在模块内跨单元复用
        #   （U1 写完接着收 U2），不清空会导致第二个单元的脚本把第一个单元的
        #   题目整批重复包含一遍。知识点缓存（_knowledge_cache）刻意保留——
        #   跨单元复用可保证同一道题的解析文案逐字一致。
        self.questions = []
        self.skipped_no_stem = 0
        self.skipped_no_answer = 0
        return path

    # ------------------------------------------------------------
    @staticmethod
    def _level_label(lv):
        """关卡显示名：0 = boss关，其余 = 第N关。

        ★ 巧记单词一个单元 6 关（1~5 数字关 + boss 关），App 里 boss 关也显示成"第6关"，
          这里统一用"boss关"标识，避免与数字关号混淆。
        """
        return "boss关" if not lv else f"第{lv}关"

    # ------------------------------------------------------------
    def _loc_str(self, q):
        """App 位置描述：模块 · 单元 · 第N关 · 第N题（含大题时带大题号）

        ★ 2026-09-10：补"第N关"——巧记单词一个单元有 6 个关卡，各关题号都从 1 开始，
          不带关卡时"第3题"无法定位到是哪一关的第3题。
        """
        _parts = [self.module]
        if q.get("unit"):
            _parts.append(f"U{q['unit']}")
        if q.get("level") is not None:   # ⚠ 0 = boss关，必须 is not None
            _parts.append(self._level_label(q["level"]))
        if q.get("big"):
            _parts.append(f"第{q['big']}大题")
        if q.get("qno"):
            _parts.append(f"第{q['qno']}题")
        return " · ".join(_parts)

    # ------------------------------------------------------------
    def _short_version(self):
        """版本缩写：湘少版→湘少；新湘鲁版→新湘鲁；其余原样（去'版'字）"""
        v = (self.version or "").strip()
        v = v.replace("（", "").replace("）", "").replace("(", "").replace(")", "")
        for k in ("新湘鲁", "湘鲁", "湘少", "人教", "外研", "译林"):
            if k in v:
                return k
        return v.replace("版", "") or "通用"

    def _short_grade(self):
        """年级缩写：五年级上册→五上；六年级下册→六下；其余压缩"""
        g = (self.grade or "").strip()
        m = re.match(r"([一二三四五六七八九])\s*年级\s*(上|下)\s*册", g)
        if m:
            return f"{m.group(1)}{m.group(2)}"
        # 兜底：去掉"年级/册"字
        return g.replace("年级", "").replace("册", "") or ""

    # ------------------------------------------------------------
    @staticmethod
    def _auto_knowledge(q):
        """LLM 不可用时的兜底解析。

        ★ 2026-09-10 修正（用户明令禁止含糊表达）：
          旧兜底返回 "涉及{关键词}相关知识点" / "基础知识点" —— 这恰恰是用户禁止的
          "涉及 XX 相关知识点"式套话，且会被 `_check_knowledge_ok` 判为不合格（自相矛盾）。
          现改为：① 能给出具体信息的就具体给出（正确答案内容 / 听到的单词）；
                  ② 实在无法生成时，明确标注"待补充 + 原因"，让审查员一眼看出需人工补，
                     而不是拿一句套话充数。
        """
        _parts = []
        _ans = (q.get("answer") or "").strip()
        _opts = q.get("options") or []
        _ans_txt = ""
        if _ans and re.match(r"^[A-F]$", _ans.upper()):
            _i = ord(_ans.upper()) - 65
            if 0 <= _i < len(_opts):
                _ans_txt = re.sub(r"^[A-F][.、．]\s*", "", str(_opts[_i])).strip()
        elif _ans:
            _ans_txt = _ans
        _spk = (q.get("speaker_word") or "").strip()
        # ★ 听音选释义：把"听到的词"和"正确释义"组合成真正有用的知识点
        #   （例：扬声器 "new" + 正确项 "新的" → 「new」的意思是「新的」）
        #   这比只写"正确答案是「新的」"更有解释力，仍是本地可得、无需 LLM。
        if _spk and _ans_txt and _spk not in _ans_txt and not re.match(r"^[A-F]$", _ans_txt):
            _parts.append(f"「{_spk}」的意思是「{_ans_txt}」")
        elif _ans_txt:
            _parts.append(f"正确答案是「{_ans_txt}」")
        elif _spk:
            _parts.append(f"录音中读到的词是「{_spk}」")
        if _parts:
            return "；".join(_parts) + "。"
        return "（知识点待人工补充：本次未生成，请检查 LLM 额度/密钥后重新生成脚本）"

    # ------------------------------------------------------------
    def summary(self, unit):
        return {
            "unit": unit,
            "generated": len(self.questions),
            "skipped": self.skipped_no_stem,
        }
