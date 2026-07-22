"""
英语宝模块检测 - OCR 文字提取引擎

支持多种 OCR 后端，按优先级自动降级：
  1. PaddleOCR（中文识别最佳，需安装 paddleocr）
  2. EasyOCR（开箱即用，无需额外依赖）
  3. uiautomator dump（从 Android UI 层级直接读文字，无需截图OCR）

使用方式:
    engine = OCREngine(backend="auto")      # 自动选择可用后端
    blocks = engine.extract("screen.png")   # 返回 TextBlock 列表
"""

import os
import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TextBlock:
    """一个文字块"""
    text: str = ""
    bbox: tuple = (0, 0, 0, 0)      # (x1, y1, x2, y2)
    confidence: float = 1.0
    is_edge: bool = False             # 是否靠近屏幕边缘(可能被截断)

    @property
    def combined_text(self) -> str:
        return self.text

    @property
    def center(self) -> tuple:
        return ((self.bbox[0] + self.bbox[2]) // 2, (self.bbox[1] + self.bbox[3]) // 2)


@dataclass
class OCRResult:
    """OCR 识别结果"""
    blocks: list[TextBlock] = field(default_factory=list)
    backend: str = "unknown"
    elapsed_ms: float = 0
    error: str = ""

    @property
    def full_text(self) -> str:
        """按从上到下、从左到右排序后的完整文字"""
        sorted_blocks = sorted(self.blocks, key=lambda b: (b.bbox[1], b.bbox[0]))
        return "\n".join(b.text for b in sorted_blocks if b.text.strip())

    @property
    def text_lines(self) -> list[TextBlock]:
        """按阅读顺序排列的文字行"""
        return sorted(self.blocks, key=lambda b: (b.bbox[1], b.bbox[0]))


class OCREngine:
    """多后端 OCR 引擎（延迟初始化，仅在首次调用 extract 时加载模型）"""

    def __init__(self, backend: str = "auto", lang: str = "ch"):
        """
        Args:
            backend: "auto" | "paddleocr" | "easyocr" | "uiautomator"
            lang: 语言代码，传给 OCR 后端
        """
        self.backend = backend
        self.lang = lang
        self._ocr = None
        self._active_backend = None
        self._initialized = False

    # ============================================================
    # 后端初始化（延迟加载）
    # ============================================================

    def _ensure_initialized(self):
        """延迟初始化：仅在首次真实 OCR 调用时加载模型"""
        if self._initialized:
            return

        backends_to_try = []

        if self.backend == "auto":
            backends_to_try = ["paddleocr", "easyocr", "uiautomator"]
        else:
            backends_to_try = [self.backend]

        for name in backends_to_try:
            try:
                if name == "paddleocr":
                    self._init_paddleocr()
                elif name == "easyocr":
                    self._init_easyocr()
                elif name == "uiautomator":
                    self._init_uiautomator()
                if name == "uiautomator" or self._ocr is not None:
                    self._active_backend = name
                    print(f"[OCR] 使用后端: {name}")
                    self._initialized = True
                    return
            except Exception as e:
                print(f"[OCR] {name} 初始化失败: {e}")
                continue

        self._active_backend = "uiautomator"
        self._initialized = True
        print("[OCR] ⚠ 所有后端初始化失败，回退到 uiautomator dump 模式")

    def _init_paddleocr(self):
        """初始化 PaddleOCR"""
        try:
            from paddleocr import PaddleOCR
            self._ocr = PaddleOCR(lang=self.lang, use_angle_cls=True, show_log=False)
        except ImportError:
            raise ImportError("PaddleOCR 未安装。请运行: pip install paddleocr paddlepaddle")

    def _init_easyocr(self):
        """初始化 EasyOCR"""
        try:
            import easyocr
            # EasyOCR 使用不同的语言代码：ch_sim(简体中文), en(英文)
            lang_map = {"ch": ["ch_sim", "en"], "en": ["en"], "ch_sim": ["ch_sim", "en"]}
            langs = lang_map.get(self.lang, [self.lang, "en"])
            self._ocr = easyocr.Reader(langs, gpu=False)
        except ImportError:
            raise ImportError("EasyOCR 未安装。请运行: pip install easyocr")

    def _init_uiautomator(self):
        """uiautomator 不需要额外初始化，通过 adb_controller 读取"""
        self._ocr = None  # uiautomator 模式需要外部传入 elements

    # ============================================================
    # 核心：从截图提取文字
    # ============================================================

    def extract(self, image_path: str) -> OCRResult:
        """
        从截图中提取文字。

        Args:
            image_path: 截图文件路径

        Returns:
            OCRResult 包含所有识别到的文字块
        """
        self._ensure_initialized()
        t0 = time.time()

        if not os.path.exists(image_path):
            return OCRResult(error=f"文件不存在: {image_path}")

        try:
            if self._active_backend == "paddleocr":
                blocks = self._extract_paddleocr(image_path)
            elif self._active_backend == "easyocr":
                blocks = self._extract_easyocr(image_path)
            else:
                return OCRResult(
                    error="uiautomator 模式请使用 extract_from_elements() 方法",
                    backend=self._active_backend,
                )

            elapsed = (time.time() - t0) * 1000
            return OCRResult(blocks=blocks, backend=self._active_backend, elapsed_ms=elapsed)

        except Exception as e:
            elapsed = (time.time() - t0) * 1000
            return OCRResult(error=str(e), backend=self._active_backend, elapsed_ms=elapsed)

    def extract_from_elements(self, elements: list) -> OCRResult:
        """
        从 uiautomator dump 的元素列表中提取文字。
        这种方式不需要截图，直接从 UI 层级读取 TextView 内容。

        Args:
            elements: UIElement 列表（来自 ADBController.dump_ui()）

        Returns:
            OCRResult
        """
        t0 = time.time()
        blocks = []

        for elem in elements:
            text = elem.text.strip() if hasattr(elem, 'text') else ""
            # 也检查 content_desc（无障碍描述）
            desc = elem.content_desc.strip() if hasattr(elem, 'content_desc') else ""

            combined = text or desc
            if not combined:
                continue

            bounds = elem.bounds if hasattr(elem, 'bounds') else (0, 0, 0, 0)
            x1, y1, x2, y2 = bounds

            blocks.append(TextBlock(
                text=combined,
                bbox=bounds,
                confidence=1.0,  # UI dump 文字是精确的
            ))

        elapsed = (time.time() - t0) * 1000
        return OCRResult(blocks=blocks, backend="uiautomator", elapsed_ms=elapsed)

    # ============================================================
    # 各后端实现
    # ============================================================

    def _extract_paddleocr(self, image_path: str) -> list[TextBlock]:
        """PaddleOCR 提取"""
        result = self._ocr.ocr(image_path, cls=True)

        if not result or not result[0]:
            return []

        blocks = []
        for line in result[0]:
            bbox_points = line[0]
            text = line[1][0]
            confidence = line[1][1]

            xs = [p[0] for p in bbox_points]
            ys = [p[1] for p in bbox_points]
            bbox = (int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys)))

            blocks.append(TextBlock(text=text, bbox=bbox, confidence=confidence))

        return blocks

    def _extract_easyocr(self, image_path: str) -> list[TextBlock]:
        """EasyOCR 提取"""
        result = self._ocr.readtext(image_path)

        blocks = []
        for detection in result:
            bbox_points, text, confidence = detection
            xs = [p[0] for p in bbox_points]
            ys = [p[1] for p in bbox_points]
            bbox = (int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys)))

            blocks.append(TextBlock(text=text, bbox=bbox, confidence=confidence))

        return blocks

    # ============================================================
    # 辅助方法
    # ============================================================

    def get_text_in_region(self, blocks: list[TextBlock],
                           x1: int, y1: int, x2: int, y2: int) -> str:
        """获取指定区域内的所有文字，按阅读顺序拼接"""
        region_blocks = [
            b for b in blocks
            if b.bbox[0] >= x1 and b.bbox[1] >= y1
            and b.bbox[2] <= x2 and b.bbox[3] <= y2
        ]
        region_blocks.sort(key=lambda b: (b.bbox[1], b.bbox[0]))
        return " ".join(b.text for b in region_blocks)

    @staticmethod
    def split_stem_and_content(blocks: list[TextBlock],
                                stem_bottom_ratio: float = 0.40) -> tuple[str, str]:
        """
        按位置自动分割题干和内容区域。
        题干通常在截图上半部分(前40%)，选项内容在下半部分。

        Args:
            blocks: 文字块列表
            stem_bottom_ratio: 题干区域的底部比率(相对于截图总高度)

        Returns:
            (stem_text, content_text)
        """
        if not blocks:
            return "", ""

        max_y = max(b.bbox[3] for b in blocks)
        split_y = int(max_y * stem_bottom_ratio)

        stem_blocks = [b for b in blocks if b.bbox[3] <= split_y]
        content_blocks = [b for b in blocks if b.bbox[1] >= split_y]

        stem_blocks.sort(key=lambda b: (b.bbox[1], b.bbox[0]))
        content_blocks.sort(key=lambda b: (b.bbox[1], b.bbox[0]))

        stem_text = " ".join(b.text for b in stem_blocks)
        content_text = " ".join(b.text for b in content_blocks)

        return stem_text, content_text


# ============================================================
# 便捷函数：直接传 adb_controller 的 dump_ui 结果来提取文字
# ============================================================

def extract_text_from_ui_elements(elements: list) -> list[TextBlock]:
    """
    从 ADBController.dump_ui() 返回的元素列表中提取文字块。
    不需要 OCR，速度最快。

    Usage:
        adb = ADBController(serial="xxx")
        elements = adb.dump_ui()
        blocks = extract_text_from_ui_elements(elements)
        for b in blocks:
            print(f"  [{b.center}] {b.text}")
    """
    blocks = []
    for elem in elements:
        text = ""
        if hasattr(elem, 'text') and elem.text:
            text = elem.text.strip()
        if not text and hasattr(elem, 'content_desc') and elem.content_desc:
            text = elem.content_desc.strip()
        if not text:
            continue

        bounds = elem.bounds if hasattr(elem, 'bounds') else (0, 0, 0, 0)
        blocks.append(TextBlock(text=text, bbox=bounds, confidence=1.0))

    blocks.sort(key=lambda b: (b.bbox[1], b.bbox[0]))
    return blocks
