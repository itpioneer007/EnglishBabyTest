"""
题目内容校验 - 独立测试脚本

无需连接 Android 设备即可测试 OCR + 文字对比功能。
使用示例截图或生成测试图片来验证校验逻辑。

用法:
    # 测试文字对比（不依赖OCR）
    python test_question_checker.py --mode text

    # 测试完整流程（自动生成测试图片 + Mock OCR）
    python test_question_checker.py --mode full

    # 测试完整流程（使用真实OCR，需提前下载模型）
    python test_question_checker.py --mode full --real-ocr

    # 使用自定义截图
    python test_question_checker.py --mode full --image test_screenshot.png
"""

import os
import sys
import argparse

# Windows 控制台 UTF-8 输出
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# 添加 src 到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from question_checker import QuestionChecker, load_questions_from_json
from ocr_engine import OCREngine, TextBlock, OCRResult


class MockOCREngine:
    """模拟 OCR 引擎 - 当真实OCR模型无法下载时使用"""

    def __init__(self):
        self.backend = "mock"
        self._active_backend = "mock"

    def extract(self, image_path: str) -> OCRResult:
        """返回模拟的OCR识别结果（与 generate_test_image 生成的图片内容对应）"""
        # 坐标对应 1080x2400 截图，题干在上半部分，选项在中下部分
        blocks = [
            TextBlock(text="单词学习 - Unit 1 Hello", bbox=(40, 30, 700, 80), confidence=0.99),
            TextBlock(text="第1题", bbox=(40, 200, 200, 250), confidence=0.98),
            TextBlock(text="选择正确的单词补全句子:", bbox=(40, 350, 900, 400), confidence=0.97),
            TextBlock(text="Hello, ___ name is Tom.", bbox=(40, 420, 800, 470), confidence=0.96),
            TextBlock(text="A. my", bbox=(40, 1300, 200, 1350), confidence=0.98),
            TextBlock(text="B. I", bbox=(300, 1300, 400, 1350), confidence=0.98),
            TextBlock(text="C. me", bbox=(560, 1300, 660, 1350), confidence=0.98),
            TextBlock(text="D. mine", bbox=(820, 1300, 960, 1350), confidence=0.98),
            TextBlock(text="上一题    下一题    提交", bbox=(40, 2310, 1040, 2360), confidence=0.95),
        ]
        return OCRResult(blocks=blocks, backend="mock", elapsed_ms=1.0)


def test_text_comparison():
    """测试文字对比功能"""
    print("=" * 60)
    print("测试1: 文字模糊匹配和逐字差异")
    print("=" * 60)

    checker = QuestionChecker()

    # 测试1.1: 完全匹配
    print("\n--- 测试1.1: 完全匹配 ---")
    sim = checker._similarity("Hello, my name is Tom.", "Hello, my name is Tom.")
    print(f"  预期: Hello, my name is Tom.")
    print(f"  实际: Hello, my name is Tom.")
    print(f"  相似度: {sim:.2%}  {'✅' if sim >= 0.95 else '❌'}")

    # 测试1.2: 细微差异（空格）
    print("\n--- 测试1.2: 空格差异 ---")
    sim = checker._similarity("Hello, my name is Tom.", "Hello,my name is Tom.")
    print(f"  预期: Hello, my name is Tom.")
    print(f"  实际: Hello,my name is Tom.")
    print(f"  相似度: {sim:.2%}  {'✅' if sim >= 0.95 else '❌'}")

    # 测试1.3: 错字（Helo vs Hello）
    print("\n--- 测试1.3: 错字检测 ---")
    expected = "Hello, my name is Tom."
    actual = "Helo, my name is Tom."
    sim = checker._similarity(expected, actual)
    diffs = checker._diff_text(expected, actual)
    print(f"  预期: {expected}")
    print(f"  实际: {actual}")
    print(f"  相似度: {sim:.2%}")
    print(f"  差异数: {len(diffs)}")
    for d in diffs:
        print(f"    位置{d.position}: 预期'{d.expected}' → 实际'{d.actual}' ({d.diff_type})")

    # 测试1.4: 中文标点
    print("\n--- 测试1.4: 中文标点标准化 ---")
    expected = "选择正确的单词补全句子：Hello，___ name is Tom。"
    actual = "选择正确的单词补全句子: Hello, ___ name is Tom."
    sim = checker._similarity(expected, actual)
    print(f"  预期: {expected}")
    print(f"  实际: {actual}")
    print(f"  标准化后相似度: {sim:.2%}  {'✅' if sim >= 0.95 else '❌'}")

    # 测试1.5: 多字/漏字
    print("\n--- 测试1.5: 漏字检测 ---")
    expected = "选择正确的单词补全句子: Hello, ___ name is Tom."
    actual = "选择正确的单词补全句子: Hello, ___ is Tom."
    sim = checker._similarity(expected, actual)
    diffs = checker._diff_text(expected, actual)
    print(f"  预期: {expected}")
    print(f"  实际: {actual}")
    print(f"  相似度: {sim:.2%}")
    print(f"  差异数: {len(diffs)}")


def test_truncation_detection():
    """测试截断检测"""
    print("\n" + "=" * 60)
    print("测试2: 截断检测")
    print("=" * 60)

    checker = QuestionChecker()

    # 测试2.1: 正常文字（不应截断）
    print("\n--- 测试2.1: 正常文字 ---")
    blocks = [
        TextBlock(text="A. my  B. I  C. me  D. mine", bbox=(100, 800, 900, 850), confidence=0.98),
        TextBlock(text="选择正确的单词补全句子.", bbox=(100, 700, 900, 750), confidence=0.99),
    ]
    complete, evidence = checker._check_truncation(blocks)
    print(f"  截断: {'否 ✅' if complete else '是 ❌'}")
    if evidence:
        for e in evidence:
            print(f"    证据: {e}")

    # 测试2.2: 截断文字（靠近底部且无标点）
    print("\n--- 测试2.2: 靠近底部的截断文字 ---")
    blocks = [
        TextBlock(text="选择正确的单词补全句子: Hello", bbox=(100, 2385, 900, 2420), confidence=0.97),
    ]
    complete, evidence = checker._check_truncation(blocks)
    print(f"  截断: {'否 ✅' if complete else '是 ❌'}")
    if evidence:
        for e in evidence:
            print(f"    证据: {e}")


def test_with_real_ocr(image_path: str, use_real_ocr: bool = False):
    """使用 OCR 测试完整校验流程

    Args:
        image_path: 截图文件路径
        use_real_ocr: True=使用真实EasyOCR/PaddleOCR, False=使用Mock OCR
    """
    print("\n" + "=" * 60)
    if use_real_ocr:
        print("测试3: 完整真实OCR + 校验流程")
    else:
        print("测试3: 完整校验流程 (Mock OCR模拟)")
    print("=" * 60)

    # 加载测试数据
    data_path = os.path.join(os.path.dirname(__file__), "data", "sample_questions.json")
    questions = load_questions_from_json(data_path)

    # 初始化 OCR
    if use_real_ocr:
        ocr = OCREngine(backend="auto")
    else:
        ocr = MockOCREngine()
        print("[OCR] 使用 Mock OCR（无需下载模型）")

    # 对每道题做校验
    for q in questions[:1]:  # 只测第一题
        checker = QuestionChecker(expected_data=q)
        checker.ocr = ocr  # 手动注入 OCR 引擎

        # 执行题干校验
        print(f"\n题目: {q['question_id']}")
        print(f"预期题干: {q['stem_text']}")
        print(f"预期内容: {q['content_text']}")

        result = checker.check_all(image_path)

        print(f"\n{'='*40} 校验结果 {'='*40}")
        stem = result["stem"]
        print(f"\n  [题干校验]")
        print(f"  通过: {'✅ 是' if stem['passed'] else '❌ 否'}")
        print(f"  相似度: {stem['similarity']:.1%}")
        if stem.get("actual"):
            print(f"  OCR识别文本: {stem['actual']}")
        if stem["diffs"]:
            print(f"  差异 ({len(stem['diffs'])}处):")
            for d in stem["diffs"]:
                print(f"    位置{d['pos']}: 预期'{d['expected']}' → 实际'{d['actual']}' ({d['type']})")

        content = result["content"]
        print(f"\n  [内容校验]")
        print(f"  与脚本相符: {'✅ 是' if content['script_match'] else '❌ 否'} (相似度: {content['similarity']:.1%})")
        print(f"  显示完整:   {'✅ 是' if content['display_complete'] else '❌ 否'}")
        print(f"  知识性错误: {len(content['knowledge_errors'])}个")
        print(f"  逻辑性错误: {len(content['logic_errors'])}个")
        if content.get("trunction_evidence"):
            print(f"  截断证据:")
            for e in content["trunction_evidence"]:
                print(f"    - {e}")
        if content.get("knowledge_errors"):
            print(f"  知识性错误详情:")
            for e in content["knowledge_errors"]:
                print(f"    - {e}")
        if content.get("logic_errors"):
            print(f"  逻辑性错误详情:")
            for e in content["logic_errors"]:
                print(f"    - {e}")

        print(f"\n  总体判定: {'✅ 全部通过' if (stem['passed'] and content['script_match'] and content['display_complete']) else '❌ 存在问题'}")


def generate_test_image():
    """生成一张测试用的模拟题目截图"""
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new('RGB', (1080, 2400), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)

    # 尝试加载中文字体
    font_paths = [
        "C:/Windows/Fonts/msyh.ttc",       # 微软雅黑
        "C:/Windows/Fonts/simhei.ttf",     # 黑体
        "C:/Windows/Fonts/simsun.ttc",     # 宋体
        "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
    ]
    font = None
    for fp in font_paths:
        if os.path.exists(fp):
            try:
                font = ImageFont.truetype(fp, 36)
                break
            except Exception:
                continue

    if font is None:
        font = ImageFont.load_default()

    # 标题栏
    draw.rectangle([(0, 0), (1080, 120)], fill=(76, 175, 80))
    draw.text((40, 30), "单词学习 - Unit 1 Hello", fill=(255, 255, 255), font=font)

    # 题号
    draw.text((40, 200), "第1题", fill=(100, 100, 100), font=font)

    # 题干文字（功能区1的检查对象）— 屏幕上半部分
    draw.text((40, 350), "选择正确的单词补全句子:", fill=(0, 0, 0), font=font)
    draw.text((40, 420), "Hello, ___ name is Tom.", fill=(0, 0, 0), font=font)

    # 分隔线
    draw.line([(40, 520), (1040, 520)], fill=(200, 200, 200), width=2)

    # 选项（功能区2的检查对象 - content_text）— 屏幕中下部分
    draw.text((40, 1300), "A. my", fill=(0, 0, 0), font=font)
    draw.text((300, 1300), "B. I", fill=(0, 0, 0), font=font)
    draw.text((560, 1300), "C. me", fill=(0, 0, 0), font=font)
    draw.text((820, 1300), "D. mine", fill=(0, 0, 0), font=font)

    # 底部导航
    draw.rectangle([(0, 2280), (1080, 2400)], fill=(240, 240, 240))
    draw.text((40, 2310), "上一题    下一题    提交", fill=(100, 100, 100), font=font)

    test_path = os.path.join(os.path.dirname(__file__), "outputs", "test_screenshot.png")
    os.makedirs(os.path.dirname(test_path), exist_ok=True)
    img.save(test_path)
    print(f"测试截图已生成: {test_path}")
    return test_path


def main():
    parser = argparse.ArgumentParser(description="题目内容校验 - 独立测试")
    parser.add_argument("--mode", choices=["text", "full", "all"],
                        default="all", help="测试模式: text=仅文字对比, full=完整校验, all=全部")
    parser.add_argument("--image", help="测试用的截图文件路径（full模式需要）")
    parser.add_argument("--real-ocr", action="store_true",
                        help="使用真实OCR引擎（需提前下载模型），否则使用Mock OCR")
    args = parser.parse_args()

    # 文字对比测试（不需要任何外部依赖）
    if args.mode in ("text", "all"):
        test_text_comparison()
        test_truncation_detection()

    # 完整 OCR 测试
    if args.mode in ("full", "all"):
        image = args.image
        if not image:
            print("\n未指定 --image，自动生成测试图片...")
            image = generate_test_image()

        if os.path.exists(image):
            test_with_real_ocr(image, use_real_ocr=args.real_ocr)
        else:
            print(f"\n❌ 截图不存在: {image}")

    print("\n" + "=" * 60)
    print("测试完成!")
    print("=" * 60)


if __name__ == "__main__":
    main()
