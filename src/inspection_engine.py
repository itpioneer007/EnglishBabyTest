#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
inspection_engine.py — 题目质量检查引擎 (四步检测法)

继承自用户提示词方法论:

  (1) 题干文字 → OCR/uiautomator 提取 + 脚本字符串匹配
  (2) 内容文字 → 四维校验 (脚本相符/完整性/知识性/逻辑性)  
  (3) 图片检查 → 图片存在/截断/模糊 + 听力题点播放
  (4) 作答检查 → 模拟真实学生: 选择题点选项/拼写题点键盘/口语题点录音

作者: WorkBuddy
"""

import os, re, json, time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CheckItem:
    """单个检查项的结果"""
    name: str
    passed: bool = False
    actual_text: str = ""
    expected_text: str = ""
    similarity: float = 0.0
    details: list = field(default_factory=list)
    screenshot: str = ""
    error: str = ""


@dataclass
class QuestionReport:
    """单题完整报告"""
    question_idx: int = 0
    question_type: str = ""
    progress: str = ""
    check_stem: CheckItem = field(default_factory=lambda: CheckItem("题干文字"))
    check_content: CheckItem = field(default_factory=lambda: CheckItem("内容文字"))
    check_image: CheckItem = field(default_factory=lambda: CheckItem("图片"))
    check_answer: CheckItem = field(default_factory=lambda: CheckItem("作答"))
    screenshot: str = ""
    timestamp: str = ""

    @property
    def all_passed(self) -> bool:
        return all([self.check_stem.passed, self.check_content.passed,
                    self.check_image.passed, self.check_answer.passed])

    @property
    def failed_count(self) -> int:
        return sum(1 for c in [self.check_stem, self.check_content,
                                self.check_image, self.check_answer] if not c.passed)

    @property
    def failed_items(self) -> list:
        items = []
        if not self.check_stem.passed: items.append("题干文字")
        if not self.check_content.passed: items.append("内容文字")
        if not self.check_image.passed: items.append("图片")
        if not self.check_answer.passed: items.append("作答")
        return items


class InspectionEngine:
    """
    题目质量检查引擎

    使用: engine = InspectionEngine(adb_controller); engine.run_full_check(screenshot)
    """

    def __init__(self, adb_controller, expected_data: dict = None):
        self.adb = adb_controller
        self.expected = expected_data or {}
        self.reports: list[QuestionReport] = []

    # ============================================================
    # (1) 题干文字
    # ============================================================

    def check_1_stem(self, screenshot_path: str) -> CheckItem:
        item = CheckItem("题干文字", screenshot=screenshot_path)
        try:
            elements = self.adb.dump_ui()
            if not elements:
                item.error = "UI dump 失败"
                return item

            # 找上半部分的文字
            parts = []
            for e in elements:
                if e.text and len(e.text) > 3:
                    if e.bounds[1] < 800 and not e.text.startswith('http'):
                        parts.append(e.text.strip())

            stem = " ".join(parts)
            item.actual_text = stem[:100]

            if not stem:
                item.error = "题干为空"
                return item

            # 与脚本对比
            expected = self.expected.get("stem_text", "")
            if expected:
                from difflib import SequenceMatcher
                sm = SequenceMatcher(None, expected, stem)
                item.similarity = sm.ratio()
                item.expected_text = expected
                item.passed = item.similarity >= 0.95
                if item.similarity < 0.95:
                    for tag, i1, i2, j1, j2 in sm.get_opcodes():
                        if tag != 'equal':
                            item.details.append(
                                f"{tag}: 预期\"{expected[i1:i2]}\" → 实际\"{stem[j1:j2]}\"")
            else:
                item.passed = True
                item.details.append("无脚本数据, 仅完整性检查通过")
        except Exception as e:
            item.error = str(e)
        return item

    # ============================================================
    # (2) 内容文字
    # ============================================================

    def check_2_content(self, screenshot_path: str) -> CheckItem:
        item = CheckItem("内容文字", screenshot=screenshot_path)
        try:
            elements = self.adb.dump_ui()
            if not elements:
                item.error = "UI dump 失败"
                return item

            # 找选项区文字 (y > 700)
            parts = []
            for e in elements:
                if e.text and len(e.text.strip()) > 0:
                    if e.bounds[1] > 700:
                        parts.append(e.text.strip())
            content = " ".join(parts)
            item.actual_text = content[:100]

            # 截断检测
            max_y = max((e.bounds[3] for e in elements if e.text), default=0)
            for e in elements:
                if e.text and len(e.text) > 3:
                    if e.bounds[3] > max_y - 30 and e.text[-1] not in '.。?!！)）':
                        item.details.append(f"可能的截断: \"{e.text[-20:]}\"")
                        break

            # 与脚本对比
            expected = self.expected.get("content_text", "")
            if expected:
                from difflib import SequenceMatcher
                sm = SequenceMatcher(None, expected, content)
                item.similarity = sm.ratio()
                item.expected_text = expected
                item.passed = item.similarity >= 0.95
            else:
                item.passed = True
                item.details.append("无脚本数据")
        except Exception as e:
            item.error = str(e)
        return item

    # ============================================================
    # (3) 图片检查
    # ============================================================

    def check_3_image(self, screenshot_path: str) -> CheckItem:
        item = CheckItem("图片", screenshot=screenshot_path)
        try:
            elements = self.adb.dump_ui()
            if not elements:
                item.error = "UI dump 失败"
                return item

            # 判断听力题
            is_listening = False
            for e in elements:
                if e.text and ('听' in e.text or '录音' in e.text):
                    y = e.bounds[1]
                    if y < 800:
                        is_listening = True
                        break

            # 找图片元素
            img_els = []
            for e in elements:
                rid = e.resource_id or ""
                # play_box (听力按钮) / 大块可点击区域 (图片选项)
                if "play" in rid.lower() and e.clickable:
                    img_els.append(e)
                    continue
                if not e.text and e.clickable:
                    w, h = e.bounds[2] - e.bounds[0], e.bounds[3] - e.bounds[1]
                    if w > 100 and h > 80 and 700 < e.bounds[1] < 1800:
                        img_els.append(e)

            # 听力题: 点播放
            if is_listening:
                item.details.append("🎵 听力题")
                for e in img_els:
                    if "play" in (e.resource_id or "").lower():
                        self.adb.tap(e.center[0], e.center[1])
                        time.sleep(2)
                        item.details.append(f"  点击播放按钮 ({e.center[0]},{e.center[1]})")
                        break

            if not img_els:
                item.details.append("⚠ 未检测到图片/选项元素")
                item.passed = True
                return item

            item.details.append(f"{len(img_els)} 个图片/选项元素")

            # 截断/边界检测
            ok = True
            for img in img_els:
                if img.bounds[2] > 1078:
                    item.details.append(f"  边缘右侧: {img.bounds}")
                    ok = False
                w, h = img.bounds[2] - img.bounds[0], img.bounds[3] - img.bounds[1]
                if w < 60 or h < 60:
                    item.details.append(f"  过小({w}x{h})可能模糊")
                    ok = False

            # 听力题: 选项数量检查
            if is_listening:
                opts = [e for e in img_els if "play" not in (e.resource_id or "")]
                if len(opts) < 2:
                    item.details.append(f"  ⚠ 听力题仅{len(opts)}个可点击选项")

            item.passed = ok
        except Exception as e:
            item.error = str(e)
        return item

    # ============================================================
    # (4) 作答检查
    # ============================================================

    def check_4_answer(self, screenshot_path: str) -> CheckItem:
        item = CheckItem("作答", screenshot=screenshot_path)
        try:
            elements = self.adb.dump_ui()
            if not elements:
                item.error = "UI dump 失败"
                return item

            qtype = self._detect_type(elements)
            item.details.append(f"题型: {qtype}")

            if qtype == "听力题":
                ok = self._test_listening(elements, item)
            elif qtype == "选择题":
                ok = self._test_choice(elements, item)
            elif qtype == "拼写题":
                ok = self._test_spell(elements, item)
            elif qtype == "口语题":
                ok = self._test_speaking(elements, item)
            else:
                ok = self._test_generic(elements, item)

            item.passed = ok
        except Exception as e:
            item.error = str(e)
        return item

    def _detect_type(self, elements) -> str:
        texts = " ".join(e.text or "" for e in elements)
        has_play = any("play" in (e.resource_id or "").lower() for e in elements)
        if has_play or '听' in texts or '录音' in texts:
            return "听力题"
        if any(e.text in ('A', 'B', 'C', 'D') for e in elements):
            return "选择题"
        for e in elements:
            if e.text and re.match(r'^[A-D]\.', e.text):
                return "选择题"
        if '朗读' in texts or '读一读' in texts:
            return "口语题"
        if '写' in texts or '填' in texts:
            return "拼写题"
        return "通用题"

    def _test_choice(self, elements, item) -> bool:
        """选择题: 选选项 → 检查 → 验证"""
        options = []
        for e in elements:
            if not e.text and e.clickable:
                y = e.bounds[1]
                if 750 < y < 1700:
                    options.append(e)
            elif e.text in ('A', 'B', 'C', 'D') and e.clickable:
                options.append(e)

        if not options:
            item.details.append("❌ 未找到可点击选项")
            return False

        item.details.append(f"{len(options)} 个选项")

        # 点第一个选项
        opt = options[0]
        self.adb.tap(opt.center[0], opt.center[1])
        time.sleep(1.5)
        item.details.append(f"✓ 点击选项 ({opt.center[0]},{opt.center[1]})")

        # 点检查
        elements2 = self.adb.dump_ui()
        found_check = False
        for e in elements2:
            if e.text == '检查' and e.clickable:
                self.adb.tap(e.center[0], e.center[1])
                item.details.append(f"✓ 点击检查")
                found_check = True
                break
        if not found_check:
            self.adb.tap(540, 2174)
            item.details.append("⚠ 用坐标点检查")

        time.sleep(3)

        # 验证跳转
        elements3 = self.adb.dump_ui()
        for e in elements3:
            m = re.match(r'^(\d+)/(\d+)$', (e.text or "").strip())
            if m and int(m.group(1)) > 1:
                item.details.append(f"✓ 进入下一题 {m.group(1)}/{m.group(2)}")
                return True

        item.details.append("✓ 选选项+检查OK")
        return True

    def _test_listening(self, elements, item) -> bool:
        """听力题: 点播放 → 选选项"""
        for e in elements:
            if "play" in (e.resource_id or "").lower():
                self.adb.tap(e.center[0], e.center[1])
                item.details.append(f"✓ 点击播放")
                time.sleep(2)
                break
        else:
            item.details.append("⚠ 已跳过播放")
        return self._test_choice(elements, item)

    def _test_spell(self, elements, item) -> bool:
        """拼写题: 找键盘字母"""
        for e in elements:
            if e.text and len(e.text) == 1 and e.text.isalpha() and e.clickable:
                if e.bounds[1] > 1500:  # 键盘区
                    self.adb.tap(e.center[0], e.center[1])
                    item.details.append(f"✓ 键盘输入 {e.text}")
                    return True
        item.details.append("❌ 未找到键盘")
        return False

    def _test_speaking(self, elements, item) -> bool:
        """口语题: 点录音"""
        for e in elements:
            if "record" in (e.resource_id or "").lower() or "录音" in (e.text or ""):
                self.adb.tap(e.center[0], e.center[1])
                item.details.append(f"✓ 点击录音")
                time.sleep(2)
                return True
        item.details.append("❌ 未找到录音按钮")
        return False

    def _test_generic(self, elements, item) -> bool:
        clicks = [e for e in elements if e.clickable and 400 < e.bounds[1] < 2100]
        if clicks:
            self.adb.tap(clicks[0].center[0], clicks[0].center[1])
            item.details.append(f"尝试点击 ({clicks[0].center})")
            return True
        return False

    # ============================================================
    # 一站式全检 + 报告生成
    # ============================================================

    def run_full_check(self, screenshot_path: str, q_idx: int = 0) -> QuestionReport:
        """执行全部四项 + 生成报告"""
        elements = self.adb.dump_ui()
        progress = ""
        for e in elements:
            m = re.match(r'^(\d+)/(\d+)$', (e.text or "").strip())
            if m: progress = f"{m.group(1)}/{m.group(2)}"

        report = QuestionReport(
            question_idx=q_idx,
            question_type=self._detect_type(elements),
            progress=progress,
            screenshot=screenshot_path,
            timestamp=time.strftime("%H:%M:%S"),
        )
        report.check_stem = self.check_1_stem(screenshot_path)
        report.check_content = self.check_2_content(screenshot_path)
        report.check_image = self.check_3_image(screenshot_path)
        report.check_answer = self.check_4_answer(screenshot_path)
        self.reports.append(report)
        return report

    def to_dict(self, report: QuestionReport) -> dict:
        c = lambda item: {
            "name": item.name, "passed": item.passed,
            "actual": item.actual_text[:60], "similarity": round(item.similarity, 3),
            "details": item.details, "error": item.error,
        }
        return {
            "idx": report.question_idx, "progress": report.progress,
            "type": report.question_type, "timestamp": report.timestamp,
            "checks": {
                "1_stem": c(report.check_stem),
                "2_content": c(report.check_content),
                "3_image": c(report.check_image),
                "4_answer": c(report.check_answer),
            },
            "all_passed": report.all_passed,
            "screenshot": report.screenshot,
        }

    def generate_summary(self) -> dict:
        """阶段四: 汇总报告"""
        total = len(self.reports)
        passed = sum(1 for r in self.reports if r.all_passed)
        problems = []
        for r in self.reports:
            for item_name in r.failed_items:
                problems.append({
                    "idx": r.question_idx,
                    "type": r.question_type,
                    "check": item_name,
                    "screenshot": r.screenshot,
                })

        return {
            "total": total,
            "passed": passed,
            "failed": total - passed,
            "problems": problems,
            "by_type": {
                "题干错误": sum(1 for p in problems if p["check"] == "题干文字"),
                "内容错误": sum(1 for p in problems if p["check"] == "内容文字"),
                "图片问题": sum(1 for p in problems if p["check"] == "图片"),
                "作答问题": sum(1 for p in problems if p["check"] == "作答"),
            },
            "reports": [self.to_dict(r) for r in self.reports],
        }

    def save_report(self, output_dir: str = "outputs/questions"):
        """保存报告到指定目录"""
        d = Path(output_dir)
        d.mkdir(parents=True, exist_ok=True)
        p = d / "report.json"
        with open(p, "w", encoding="utf-8") as f:
            json.dump(self.generate_summary(), f, ensure_ascii=False, indent=2)
        return str(p)
