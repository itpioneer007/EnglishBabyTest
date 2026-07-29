"""
视觉定位引擎 v2 — 截图 + OCR 直接看屏幕找文字
==============================================

核心理念：不再猜坐标。不管页面滚到哪、广告挡没挡。
先截屏 → OCR 识别 → 找到目标文字 → 返回精确坐标。

后端：优先 PaddleOCR（中文准确率高），降级到 Tesseract（兜底）。
"""

import os
import pytesseract
from PIL import Image
from dataclasses import dataclass


@dataclass
class VisualRect:
    """OCR 识别到的文字区域"""
    text: str
    left: int; top: int; width: int; height: int
    confidence: int = 0

    @property
    def center(self) -> tuple:
        return (self.left + self.width // 2, self.top + self.height // 2)

    @property
    def icon_center(self) -> tuple:
        """图标通常在文字上方约 40px"""
        return (self.center[0], self.center[1] - 40)


# ===== PaddleOCR 后端 =====
_paddle_ocr = None

def _init_paddle():
    global _paddle_ocr
    if _paddle_ocr is not None:
        return True
    try:
        from paddleocr import PaddleOCR
        _paddle_ocr = PaddleOCR(lang='ch', use_angle_cls=False, show_log=False)
        return True
    except ImportError:
        _paddle_ocr = False
        return False


def _ocr_paddle(image_path: str) -> list[VisualRect]:
    """PaddleOCR 识别"""
    if not _init_paddle():
        return []
    import numpy as np
    img = Image.open(image_path).convert('RGB')
    arr = np.array(img)
    result = _paddle_ocr.ocr(arr, cls=False)
    if not result or not result[0]:
        return []
    rects = []
    for line in result[0]:
        box, (text, conf) = line
        x1, y1 = box[0]; x2, y2 = box[2]
        left, top = int(x1), int(y1)
        w, h = int(x2 - x1), int(y2 - y1)
        rects.append(VisualRect(text=text, left=left, top=top, width=w, height=h, confidence=int(conf * 100)))
    return rects


# ===== Tesseract 降级 =====
_tess_ready = False

def _init_tesseract():
    global _tess_ready
    if _tess_ready:
        return
    tess_path = r"C:\Program Files\Tesseract-OCR\tessdata"
    if os.path.exists(tess_path):
        os.environ["TESSDATA_PREFIX"] = tess_path
    pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    _tess_ready = True


def _ocr_tesseract(image_path: str) -> list[VisualRect]:
    """Tesseract OCR 降级方案"""
    _init_tesseract()
    img = Image.open(image_path)
    data = pytesseract.image_to_data(img, lang='chi_sim+eng', config='--oem 3 --psm 6',
                                     output_type=pytesseract.Output.DICT)
    rects = []
    for i in range(len(data['text'])):
        t = (data['text'][i] or '').strip()
        if not t:
            continue
        rects.append(VisualRect(
            text=t,
            left=data['left'][i], top=data['top'][i],
            width=data['width'][i], height=data['height'][i],
            confidence=int(data['conf'][i]) if data['conf'][i] != '-1' else 0,
        ))
    return rects


# ===== 公开 API =====

def ocr(image_path: str) -> list[VisualRect]:
    """OCR 一张截图，返回所有识别区域（优先 PaddleOCR）"""
    rects = _ocr_paddle(image_path)
    if rects:
        return rects
    return _ocr_tesseract(image_path)


def find(image_path: str, text: str) -> VisualRect | None:
    """在截图中找指定文字。返回区域（含中心坐标），未找到返回 None"""
    rects = ocr(image_path)
    # 精确匹配优先
    for r in rects:
        if r.text.strip() == text:
            return r
    # 包含匹配
    for r in rects:
        if text in r.text:
            return r
    return None


def find_all(image_path: str, text: str) -> list[VisualRect]:
    """找截图中所有匹配文字的区域"""
    rects = ocr(image_path)
    return [r for r in rects if text in r.text]


def take_and_find(adb, text: str, shot_dir: str = "screenshots") -> VisualRect | None:
    """
    快捷键：截图 → OCR 找文字 → 返回坐标。
    adb 是 ADBController 实例。
    """
    path = adb.screenshot("_ocr_lookup.png")
    return find(path, text)
