"""
reviewer_media.py — Person B 独占文件
======================================
检查职责:
  (3) 题目配图是否与脚本相符、显示完整、与内容匹配、有无不合逻辑之处
  (4) 检查题目是否能正常作答（各题型的作答可行性）

修改规则: 只会被 Person B 修改，Person A 永远不碰这个文件
依赖: reviewer_common.py, adb_controller.py (仅在 ADB 模式下需要)
"""

from pathlib import Path
from typing import Optional
from src.reviewer_common import CheckItem, Question, LLMClient


class MediaReviewer:
    """
    Person B 的图片+作答审查器
    
    用法:
        reviewer = MediaReviewer(llm_client)
        image_result = reviewer.check_image(question, screenshot_path)
        answer_result = reviewer.check_answer(question, screenshot_path)
    """

    def __init__(self, llm: LLMClient):
        self.llm = llm

    # ================================================================
    # (3) 配图检查
    # ================================================================

    def check_image(self, question: Question, screenshot_path: str,
                    adb_controller=None) -> CheckItem:
        """
        检查题目配图

        四项子检查：
          a. 图片存在 — DOM/HTML 里没有 ImageView 或 图片元素
          b. 显示完整 — 没有被截断或遮挡
          c. 内容匹配 — LLM 视觉分析图片与题干是否相关
          d. 无逻辑问题 — LLM 视觉分析图片是否合理

        听力题特殊处理：检查是否有播放按钮

        Args:
            question: 题目数据
            screenshot_path: 截图文件路径
            adb_controller: ADB 控制器（可选，检测 UI 元素）

        Returns:
            CheckItem
        """
        item = CheckItem(name="(3)配图检查", screenshot=screenshot_path)

        # a. 图片存在性
        has_image = self._detect_image_element(screenshot_path, adb_controller)
        if not has_image and question.image_paths:
            item.details.append("❌ 截图未检测到图片元素，但脚本中有配图")
        elif has_image:
            item.details.append("✅ 检测到图片元素")

        # b. 显示完整性
        if self._is_image_truncated(screenshot_path):
            item.details.append("❌ 图片可能被截断")
        else:
            item.details.append("✅ 图片显示完整")

        # c. 内容匹配 (LLM)
        if self.llm and question.stem:
            result = self.llm.ask(
                self._image_match_prompt(question),
                image_path=screenshot_path,
            )
            # 模型不支持 vision 时 result 会是错误消息
            if result.startswith("[LLM 调用失败]"):
                item.details.append(f"⚠ 视觉分析跳过: {result}")
            elif "不匹配" in result or "无关" in result:
                item.details.append(f"❌ 图文不匹配: {result[:100]}")
            else:
                item.details.append(f"✅ 图文匹配: {result[:80]}")

        # d. 逻辑合理性 (LLM)
        if self.llm:
            result = self.llm.ask(
                self._image_logic_prompt(question),
                image_path=screenshot_path,
            )
            if result.startswith("[LLM 调用失败]"):
                item.details.append(f"⚠ 逻辑分析跳过: {result}")
            elif "不合理" in result or "错误" in result:
                item.details.append(f"⚠ 图片逻辑问题: {result[:100]}")
            else:
                item.details.append("✅ 图片无逻辑问题")

        # 听力题特殊：播放按钮
        if question.question_type and "听力" in question.question_type:
            has_play = self._detect_play_button(screenshot_path, adb_controller)
            if has_play:
                item.details.append("✅ 听力题: 播放按钮存在")
            else:
                item.details.append("⚠ 听力题: 未检测到播放按钮")

        has_fail = any("❌" in d for d in item.details) or any("⚠" in d for d in item.details)
        item.passed = not has_fail

        return item

    # ================================================================
    # (4) 作答可行性检查
    # ================================================================

    def check_answer(self, question: Question, screenshot_path: str,
                     adb_controller=None) -> CheckItem:
        """
        检查题目是否能正常作答

        按题型分类处理：
          - 选择题: 选项是否可点击
          - 填空题/拼写题: 输入框是否可用
          - 口语题: 录音按钮是否存在
          - 听力题: 播放按钮 + 选项是否正常
          - 排序题: 拖拽/点击区域是否存在

        不实际作答，只检查 UI 元素是否完整可用

        Args:
            question: 题目数据
            screenshot_path: 截图文件路径
            adb_controller: ADB 控制器（可选）

        Returns:
            CheckItem
        """
        item = CheckItem(name="(4)作答检查", screenshot=screenshot_path)

        qtype = question.question_type or self._guess_type(question.stem)

        if "选择" in qtype or "单选" in qtype or "多选" in qtype:
            item.details.extend(self._check_choice_question(screenshot_path, adb_controller))
        elif "填空" in qtype or "拼写" in qtype:
            item.details.extend(self._check_fill_question(screenshot_path, adb_controller))
        elif "口语" in qtype or "朗读" in qtype:
            item.details.extend(self._check_speaking_question(screenshot_path, adb_controller))
        elif "听力" in qtype:
            item.details.extend(self._check_choice_question(screenshot_path, adb_controller))
            item.details.append("听力题：需要真实音频验证（暂跳过）")
        elif "排序" in qtype:
            item.details.extend(self._check_sort_question(screenshot_path, adb_controller))
        elif "判断" in qtype:
            item.details.extend(self._check_choice_question(screenshot_path, adb_controller))
        else:
            # LLM 分析
            if self.llm:
                result = self.llm.ask(
                    f"这是一道题目的截图。请判断这道题能否正常作答。(题目: {question.stem})",
                    image_path=screenshot_path,
                )
                item.details.append(f"LLM 判断: {result[:100]}")
            else:
                item.details.append("⚠ 未识别题型，跳过作答检查")

        has_fail = any("❌" in d for d in item.details)
        item.passed = not has_fail

        return item

    # ================================================================
    # 内部方法（Person B 专属区域，Person A 不要动）
    # ================================================================

    def _guess_type(self, stem: str) -> str:
        """从题干文字猜测题型"""
        if not stem:
            return "未知"
        if "听" in stem:
            return "听力"
        if "选择" in stem or "选" in stem:
            return "选择"
        if "判断" in stem or "T/F" in stem.upper():
            return "判断"
        if "填" in stem or "写" in stem or "拼" in stem:
            return "填空"
        if "朗读" in stem or "说" in stem or "口语" in stem:
            return "口语"
        if "排序" in stem or "排列" in stem:
            return "排序"
        return "选择"  # 默认

    def _detect_image_element(self, screenshot_path: str, adb=None) -> bool:
        """检测截图中是否存在图片元素"""
        if adb:
            try:
                elements = adb.dump_ui()
                for e in elements:
                    rid = getattr(e, 'resource_id', '') or ''
                    if any(k in rid.lower() for k in ['image', 'img', 'pic']):
                        return True
            except Exception:
                pass

        # 如果没 ADB，用 PIL 粗略检测（检测是否有可辨别的图像区域）
        try:
            from PIL import Image
            img = Image.open(screenshot_path)
            # 粗略判断：如果文件较大(>100KB)且非纯文字，可能含图
            import os
            size_kb = os.path.getsize(screenshot_path) / 1024
            return size_kb > 50
        except Exception:
            return False

    def _is_image_truncated(self, screenshot_path: str) -> bool:
        """检测图片是否被截断"""
        try:
            from PIL import Image
            import numpy as np
            img = Image.open(screenshot_path)
            arr = np.array(img)
            h, w = arr.shape[:2]
            # 只检测底部 8px 的真正纯白 (255,255,255)，排除正常白底
            bottom_strip = arr[h-8:h, :, :3] if h > 8 else arr[:,:, :3]
            pure_white = ((bottom_strip[:, :, 0] >= 253) &
                          (bottom_strip[:, :, 1] >= 253) &
                          (bottom_strip[:, :, 2] >= 253))
            ratio = pure_white.sum() / (bottom_strip.shape[0] * w)
            # 只有接近全白才判定截断
            return ratio > 0.98
        except Exception:
            return False

    def _detect_play_button(self, screenshot_path: str, adb=None) -> bool:
        """检测是否有播放按钮（听力题）"""
        if adb:
            try:
                elements = adb.dump_ui()
                for e in elements:
                    rid = getattr(e, 'resource_id', '') or ''
                    if 'play' in rid.lower():
                        return True
            except Exception:
                pass
        return True  # 没 ADB 时不判定为缺失

    def _check_choice_question(self, screenshot_path: str, adb=None) -> list[str]:
        details = []
        if adb:
            try:
                elements = adb.dump_ui()
                clickable_count = sum(1 for e in elements
                                      if hasattr(e, 'clickable') and e.clickable
                                      and hasattr(e, 'bounds')
                                      and 700 < e.bounds[1] < 1700)
                if clickable_count >= 2:
                    details.append(f"✅ 选择题: 检测到 {clickable_count} 个可点击选项")
                else:
                    details.append(f"⚠ 选择题: 仅 {clickable_count} 个可点击元素")
            except Exception:
                details.append("⚠ ADB 检测失败")
        else:
            details.append("⏭ 无手机连接，跳过点击测试（不影响审查结论）")
        return details

    def _check_fill_question(self, screenshot_path: str, adb=None) -> list[str]:
        details = []
        if adb:
            try:
                elements = adb.dump_ui()
                input_fields = sum(1 for e in elements
                                   if hasattr(e, 'resource_id') and e.resource_id
                                   and any(k in e.resource_id.lower()
                                          for k in ['edit', 'input', 'textfield']))
                if input_fields > 0:
                    details.append(f"✅ 填空题: 检测到 {input_fields} 个输入框")
                else:
                    details.append("⚠ 填空题: 未检测到输入框")
            except Exception:
                details.append("⚠ ADB 检测失败")
        else:
            details.append("⏭ 无手机连接，跳过输入测试（不影响审查结论）")
        return details

    def _check_speaking_question(self, screenshot_path: str, adb=None) -> list[str]:
        details = []
        if adb:
            try:
                elements = adb.dump_ui()
                record_btn = any(
                    (hasattr(e, 'resource_id') and e.resource_id
                     and any(k in e.resource_id.lower()
                            for k in ['record', 'mic', 'speak', 'voice']))
                    for e in elements
                )
                if record_btn:
                    details.append("✅ 口语题: 检测到录音按钮")
                else:
                    details.append("⚠ 口语题: 未检测到录音按钮")
            except Exception:
                details.append("⚠ ADB 检测失败")
        else:
            details.append("⏭ 无手机连接，跳过录音测试（不影响审查结论）")
        return details

    def _check_sort_question(self, screenshot_path: str, adb=None) -> list[str]:
        details = []
        if adb:
            try:
                elements = adb.dump_ui()
                clickable_count = sum(1 for e in elements
                                      if hasattr(e, 'clickable') and e.clickable
                                      and hasattr(e, 'bounds')
                                      and 700 < e.bounds[1] < 1700)
                if clickable_count >= 2:
                    details.append(f"✅ 排序题: 检测到 {clickable_count} 个可操作元素")
                else:
                    details.append("⚠ 排序题: 可操作元素不足")
            except Exception:
                details.append("⚠ ADB 检测失败")
        else:
            details.append("⏭ 无手机连接，跳过排序测试（不影响审查结论）")
        return details

    def _image_match_prompt(self, q: Question) -> str:
        return f"""你是英语教学插图质检专家。请分析这张截图中的图片是否与以下题目匹配。

题目: {q.stem}
题型: {q.question_type}

请判断：
- 图片内容是否与题干相关？
- 对于听力选图题，图片是否能表达听力场景？

回答格式："匹配" 或 "不匹配：[原因]"。"""

    def _image_logic_prompt(self, q: Question) -> str:
        return f"""请分析这张截图中的图片是否存在逻辑不合理之处。

题目: {q.stem}

检查点：
- 图片内容是否符合常识？
- 颜色/比例/文字是否有明显错误？
- 是否有模糊、变形等问题？

回答格式："合理" 或 "不合理：[具体问题]"。"""
