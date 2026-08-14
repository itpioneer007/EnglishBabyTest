"""
type_detector.py — 从手机 UI 实时识别题型（增强版）

核心目标：不依赖 DOCX 脚本，直接从当前手机页面的 UI 元素/截图
识别"这是一道什么题"，输出结构化题型信息，供审查引擎按题型
执行需求文档第 6 条对应的维度检查。

识别维度:
  - 一级题型 (type_1): 听音选择 / 听音判断 / 听音排序 / 朗读 / 拼写 / 匹配 / 选择 / 填空
  - 二级题型 (type_2): 在一级基础上细分（如 听音选择-词汇 / 听音判断-图片）
  - 结构化信息: 题干文本、选项列表(A/B/C/D)、是否图片题、是否听力题、是否有录音按钮

依据:
  1. UI 文本关键词（题干文字、按钮文字）
  2. UI 结构特征（可点击选项数量、图片 bounds、播放器图标）
  3. 截图 OCR 兜底（文本提取失败时）
"""

from dataclasses import dataclass, field
import re
from typing import List, Optional


# ============================================================
# 题型配置表：关键词 → 题型
# ============================================================

# 一级题型识别规则：按优先级排列（先匹配更具体的）
TYPE1_RULES = [
    # 听音类（听力题）★ 用户约定：带"听录音"的题目叫"听力选择题"
    {"type": "听力选择题", "keywords": ["听一听", "听录音", "听对话", "听短文", "听音", "听句子", "听单词",
                                      "listen", "听下面", "听材料", "听问题"],
     "audio": True, "priority": 90},
    # 听力判断题：特征词必须含"对错/相符/√×/打勾"等明确判断标识（避免"判断"短词误命中）
    {"type": "听力判断题", "keywords": ["对错", "相符", "一致", "√", "×", "正确打", "打勾"],
     "audio": True, "priority": 88},
    {"type": "听力排序题", "keywords": ["排序", "排列", "按顺序", "排成", "给下列", "按听到的顺序"],
     "audio": True, "priority": 85},
    {"type": "听力匹配题", "keywords": ["听录音匹配", "听一听匹配", "听音匹配", "听录音连线", "听音连线"],
     "audio": True, "priority": 83},
    # 朗读类（口语）
    {"type": "朗读", "keywords": ["朗读", "读一读", "跟读", "读单词", "读句子", "大声读", "read", "repeat",
                                   "录音", "跟录音读"],
     "audio": True, "priority": 80},
    # 拼写类
    {"type": "拼写", "keywords": ["拼写", "写出", "写一写", "填空", "填写", "补全", "spell", "write",
                                   "默写", "听写"],
     "audio": False, "priority": 70},
    # 匹配类（文字/图片，非听音）
    {"type": "匹配", "keywords": ["匹配", "配对", "连线", "连接", "对应"],
     "audio": False, "priority": 60},
    # 选择类（默认）
    {"type": "选择", "keywords": ["选择", "选出", "选出不同类", "找出", "圈出", "choose", "select",
                                   "哪个", "哪一项", "下列"],
     "audio": False, "priority": 50},
]

# 二级细分规则（在 type_1 基础上进一步识别对象）
TYPE2_RULES = [
    {"type_2": "词汇", "keywords": ["单词", "词汇", "词语", "词义", "释义"]},
    {"type_2": "句子", "keywords": ["句子", "句型", "语序"]},
    {"type_2": "图片", "keywords": ["图片", "图画", "图", "看图", "照片"]},
    {"type_2": "答语", "keywords": ["答语", "回答", "应答"]},
    {"type_2": "对话", "keywords": ["对话"]},
    {"type_2": "短文", "keywords": ["短文", "文章", "故事"]},
]

# 音频/播放器图标文本（content-desc 或 text）
AUDIO_MARKERS = ["播放", "听", "🔊", "▶", "播放录音", "喇叭", "扬声器", "sound", "play", "audio"]

# 选项前缀：选择题选项通常是 A. B. C. D.
OPTION_PREFIX = re.compile(r'^[A-D][\.、．\s]|^[A-D]$|^[A-D][\)）]')


# ============================================================
# 数据结构
# ============================================================

@dataclass
class DetectedQuestion:
    """识别出的一道题的题型与结构化信息"""
    type_1: str = "未知"                # 一级题型
    type_2: str = ""                    # 二级细分
    full_type: str = ""                 # 组合："听音选择-词汇"
    is_audio: bool = False              # 是否听力/音频题
    is_image: bool = False              # 是否图片题
    stem: str = ""                      # 题干文本
    options: List[str] = field(default_factory=list)   # 选项 ["A. xxx", ...]
    has_option_buttons: bool = False    # UI 是否有可点击选项按钮
    audio_buttons: List[str] = field(default_factory=list)  # 音频按钮文本
    image_bounds: List[tuple] = field(default_factory=list) # 图片区域 (x1,y1,x2,y2)
    raw_texts: List[str] = field(default_factory=list)      # 全部 UI 文本（调试用）
    confidence: float = 0.0             # 识别置信度 0~1

    def describe(self) -> str:
        """一行描述，用于日志"""
        parts = [self.full_type or self.type_1]
        if self.is_audio: parts.append("听力")
        if self.is_image: parts.append("图片")
        if self.options: parts.append(f"{len(self.options)}选项")
        if self.stem: parts.append(f"题干{len(self.stem)}字")
        return " · ".join(parts)


# ============================================================
# 核心识别器
# ============================================================

class TypeDetector:
    """从 UI 元素列表识别当前题目题型"""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose

    def detect(self, elements: list, screenshot_path: str = "") -> DetectedQuestion:
        """
        识别当前页面题型

        Args:
            elements: adb.dump_ui() 返回的 UIElement 列表（有 .text/.bounds/.clickable）
            screenshot_path: 截图路径（可选，用于图片题检测兜底）

        Returns:
            DetectedQuestion
        """
        dq = DetectedQuestion()
        if not elements:
            return dq

        # ---- 收集全部文本与结构特征 ----
        texts = []
        clickable_texts = []
        image_areas = []
        for e in elements:
            t = (e.text or "").strip()
            if t:
                texts.append(t)
                if getattr(e, "clickable", False):
                    clickable_texts.append(t)
            # 图片区域（ImageView 类）
            cls = (e.class_name or "")
            if "Image" in cls:
                b = e.bounds
                if b and b[2] - b[0] > 40 and b[3] - b[1] > 40:
                    image_areas.append((b[0], b[1], b[2], b[3]))
        dq.raw_texts = texts

        full_text = "\n".join(texts)
        full_text_lower = full_text.lower()

        # ---- 一级题型识别（关键词优先级） ----
        best_type1, best_score = "", 0
        for rule in TYPE1_RULES:
            hit = 0
            for kw in rule["keywords"]:
                if kw in full_text or kw.lower() in full_text_lower:
                    hit += 1
            if hit > 0:
                score = rule["priority"] + hit * 5
                if score > best_score:
                    best_score = score
                    best_type1 = rule["type"]
                    dq.is_audio = rule["audio"]

        if best_type1:
            dq.type_1 = best_type1
        else:
            # 无明确关键词 → 用结构特征推断
            dq.type_1 = self._infer_by_structure(dq, texts, clickable_texts, elements)
            dq.is_audio = self._detect_audio_marker(texts, clickable_texts)

        # ---- 二级细分 ----
        for rule in TYPE2_RULES:
            for kw in rule["keywords"]:
                if kw in full_text:
                    dq.type_2 = rule["type_2"]
                    if kw == "图片" or kw == "看图" or kw == "图":
                        dq.is_image = True
                    break
            if dq.type_2:
                break

        # ---- 题干：取最长的文本（通常是题干） ----
        # 过滤掉选项/按钮/进度文本
        noise = set()
        for t in texts:
            if re.match(r'^\d+/\d+$', t.strip()): noise.add(t)          # 1/40 进度
            if t.strip() in ("下一题", "上一题", "检查", "提交", "开始答题", "重听"): noise.add(t)
            if OPTION_PREFIX.match(t.strip()): noise.add(t)              # 选项
        candidates = [t for t in texts if t not in noise and len(t) >= 4]
        if candidates:
            dq.stem = max(candidates, key=len)

        # ---- 选项识别 ----
        dq.options = self._extract_options(texts)
        dq.has_option_buttons = len([t for t in clickable_texts if OPTION_PREFIX.match(t.strip())]) >= 2

        # ---- 音频按钮 ----
        for t in clickable_texts:
            if any(m in t for m in AUDIO_MARKERS) or t.strip() in ("▶", "🔊"):
                dq.audio_buttons.append(t)

        dq.image_bounds = image_areas
        if image_areas:
            dq.is_image = True

        # ---- 组合题型 ----
        dq.full_type = f"{dq.type_1}" + (f"-{dq.type_2}" if dq.type_2 else "")

        # ---- 置信度 ----
        conf = 0.3
        if dq.type_1 != "未知": conf += 0.3
        if dq.type_2: conf += 0.15
        if dq.stem: conf += 0.1
        if dq.options or dq.has_option_buttons: conf += 0.15
        if dq.audio_buttons: conf += 0.05
        dq.confidence = min(conf, 1.0)

        if self.verbose:
            print(f"  [TypeDetector] {dq.describe()} (conf={dq.confidence:.0%})")
        return dq

    # ============================================================
    # 辅助方法
    # ============================================================

    def _infer_by_structure(self, dq, texts, clickable_texts, elements) -> str:
        """无关键词时，按 UI 结构推断题型"""
        # 有可点击选项按钮 (A/B/C/D) → 选择题
        opt_btns = [t for t in clickable_texts if OPTION_PREFIX.match(t.strip())]
        if len(opt_btns) >= 2:
            return "选择"
        # 有图片区域 → 看图/图片题
        if dq.image_bounds:
            return "看图选择" if len(opt_btns) >= 2 else "看图"
        # 有输入框 → 填空/拼写
        for e in elements:
            if "EditText" in (e.class_name or ""):
                return "填空"
        return "未知"

    def _detect_audio_marker(self, texts, clickable_texts) -> bool:
        """检测音频标记"""
        all_t = texts + clickable_texts
        return any(any(m in t for m in AUDIO_MARKERS) for t in all_t)

    def _extract_options(self, texts) -> List[str]:
        """提取 A/B/C/D 选项"""
        opts = []
        for t in texts:
            ts = t.strip()
            if OPTION_PREFIX.match(ts):
                opts.append(ts)
        # 按 A/B/C/D 排序
        def key_fn(o):
            m = re.match(r'^([A-D])', o)
            return m.group(1) if m else "Z"
        opts.sort(key=key_fn)
        return opts


# ============================================================
# 便捷函数
# ============================================================

def detect_question_type(elements: list, screenshot_path: str = "",
                         verbose: bool = False) -> DetectedQuestion:
    """便捷入口"""
    return TypeDetector(verbose=verbose).detect(elements, screenshot_path)


def text_fingerprint(dq: DetectedQuestion) -> str:
    """题型指纹：用于与脚本题型对照/显示"""
    return dq.full_type or dq.type_1


if __name__ == "__main__":
    # 自测
    class FakeEl:
        def __init__(self, text, clickable=False, cls="TextView", bounds=(0,0,100,40)):
            self.text = text
            self.clickable = clickable
            self.class_name = cls
            self.bounds = bounds

    demo = [
        FakeEl("1/40"),
        FakeEl("听录音，选出你所听到的单词", clickable=False),
        FakeEl("A. apple", clickable=True),
        FakeEl("B. banana", clickable=True),
        FakeEl("C. orange", clickable=True),
        FakeEl("▶ 播放", clickable=True),
        FakeEl("下一题", clickable=True),
    ]
    dq = detect_question_type(demo, verbose=True)
    print("题干:", dq.stem)
    print("选项:", dq.options)
    print("听力:", dq.is_audio, "| 图片:", dq.is_image, "| 音频按钮:", dq.audio_buttons)
