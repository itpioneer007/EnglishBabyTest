"""
src/universe_navigator.py — 通用导航引擎
负责人：B

设计理念：
  把英语宝APP的所有页面建成一张"地图"（有向图）。
  每个页面有“指纹”（一组独特的UI元素文字），
  每条边是一个操作（点击某个按钮 → 到下一页）。
  
  无论当前在哪一页，都能通过最短路径导航到任意目标页。
  操作后验证是否到达预期页面，未到达则自动恢复。
"""

import time
import re
from pathlib import Path
from typing import Optional


# ============================================
# 页面指纹：什么文字组合能唯一确定当前页
# ============================================
PAGE_FINGERPRINTS = {
    # ---- 顶层 ----
    "english_tab_home": ["教材精学", "专项突破"],
    "main_home": ["小学", "我的练习", "学习计划"],

    # ---- 专项突破 ----
    "special_modules": ["专项突破"],  # 模块列表页

    # 各模块内页的特征
    "listening_select_version": ["当前版本", "年级"],  # 听力专项 → 版本选择
    "listening_unit_list": ["听力专项", "去练习", "Unit"],  # 听力专项 → Unit列表

    # ---- 通用子页面 ----
    "unit_list": ["去练习", "Unit"],
    "stage_select": ["基础巩固", "综合进阶"],
    "question_page": [],  # 运行时填充：1/N 格式
    "result_page": ["正确答案"],
    "report_page": ["完成", "得分"],  # 模块完成报告
    "completion_popup": ["先走一步", "继续练习"],

    # ---- 异常页面 ----
    "ad_popup": ["关闭", "跳过", "×"],
    "loading": ["加载中", "Loading"],
    "error_page": ["网络错误", "重试"],
}


# ============================================
# 页面迁移图（有向图）
# ============================================
# 格式: "当前页": {"目标页": {"action": "tap", "target_text": "...", "fallback_coord": (x,y)}}
NAV_GRAPH = {
    "main_home": {
        "special_modules": {
            "action": "tap",
            "target_text": "专项突破",
            "fallback_coord": (135, 1335),
            "wait_after": 2,
        },
        # 教材精学入口（以后需要再加）
    },
    "special_modules": {
        "listening_select_version": {
            "action": "scroll_then_tap",
            "target_text": "听力专项",
            "scroll_direction": "down",
            "scroll_times": 5,
            "fallback_coord": (540, 800),
            "wait_after": 2,
        },
        # 巧记单词 / 知识过关 等模块入口（待补充）
    },
    "listening_select_version": {
        "listening_unit_list": {
            "action": "tap_version_then_unit",
            # 特殊动作：先确认版本正确，不正确则点切换，然后等Unit列表出现
        },
    },
    "unit_list": {
        "stage_select": {
            "action": "tap_unit_go_practice",
            # 点某个Unit的"去练习"
        },
    },
    "stage_select": {
        "question_page": {
            "action": "tap_stage_then_start",
            # 点阶段名称 → 点开始答题 → 验证出现1/N
        },
    },
    "completion_popup": {
        "main_home": {
            "action": "tap",
            "target_text": "先走一步",
            "fallback_coord": (324, 1288),
            "wait_after": 2,
        },
    },
    # 异常恢复（任意页 → 主页）
    "any": {
        "main_home": {
            "action": "universal_reset",
            # 连续按返回 → 重启APP → 首页
        },
    },
}


class UniverseNavigator:
    """通用导航引擎：任意页面 → 任意目标页面"""

    def __init__(self, adb):
        self.adb = adb
        self.current_page = None
        self.history = []  # [(page_name, timestamp)]

        # 运行时指纹：question_page 的特征在跑的时候才知道
        self._runtime_fingerprints = dict(PAGE_FINGERPRINTS)

    # ============================================
    # 页面识别
    # ============================================

    def identify_page(self, elements: list = None) -> str:
        """
        根据当前UI元素识别页面。
        返回页面名称，如 "unit_list" / "question_page" / "result_page" / "unknown"
        """
        if elements is None:
            elements = self.adb.dump_ui()
        texts = ' '.join([(e.text or '') for e in elements])

        # 1. 检查是否有题号 "1/15"
        m = re.search(r'(\d+)/(\d+)', texts)
        if m:
            self.current_page = "question_page"
            return "question_page"

        # 2. 检查指纹匹配
        for page_name, keywords in self._runtime_fingerprints.items():
            if not keywords:
                continue
            if all(kw in texts for kw in keywords):
                self.current_page = page_name
                return page_name

        # 3. 单关键词宽松匹配
        for page_name, keywords in self._runtime_fingerprints.items():
            if not keywords:
                continue
            if any(kw in texts for kw in keywords):
                self.current_page = page_name
                return page_name

        self.current_page = "unknown"
        return "unknown"

    # ============================================
    # 导航到目标页
    # ============================================

    def navigate_to(self, target_page: str, context: dict = None,
                    max_steps: int = 20) -> bool:
        """
        从当前页面导航到目标页。
        context 可包含: {"unit": 6, "stage": "基础巩固", "version": "新湘鲁六上"}

        Returns: True 表示成功到达目标页
        """
        steps_taken = 0

        while steps_taken < max_steps:
            cur = self.identify_page()

            if cur == target_page:
                print(f"  [Nav] ✅ 已到达: {target_page}")
                return True

            # 异常页面先处理
            if cur in ("ad_popup", "completion_popup"):
                self._handle_interruption(cur)
                steps_taken += 1
                continue

            if cur == "loading":
                time.sleep(3)
                steps_taken += 1
                continue

            # 未知页面 → 尝试回退
            if cur == "unknown":
                print(f"  [Nav] ⚠ 未知页面，尝试回退...")
                self.adb.press_back()
                time.sleep(1.5)
                steps_taken += 1
                continue

            # 用专用处理函数导航
            handled = self._step_toward(cur, target_page, context)
            if not handled:
                print(f"  [Nav] ⚠ 无法从 {cur} 到 {target_page}，尝试通用回退")
                self.adb.press_back()
                time.sleep(1.5)
            steps_taken += 1

        print(f"  [Nav] ❌ 超时未到达目标: {target_page}（已尝试{max_steps}步）")
        return False

    # ============================================
    # 每步导航的具体实现
    # ============================================

    def _step_toward(self, current: str, target: str, ctx: dict) -> bool:
        """从current页向target靠近一步。返回True表示做了一次有效操作。"""

        # --- 主页 → 专项突破 ---
        if current == "main_home" and target in ("special_modules",
                                                  "listening_select_version",
                                                  "listening_unit_list",
                                                  "unit_list",
                                                  "stage_select",
                                                  "question_page"):
            return self._go_special_modules()

        # --- 专项突破模块列表 → 听力专项 ---
        if current == "special_modules" and target in ("listening_select_version",
                                                        "listening_unit_list",
                                                        "unit_list",
                                                        "stage_select",
                                                        "question_page"):
            return self._go_listening()

        # --- 听力专项版本页 → Unit列表 ---
        if current == "listening_select_version":
            return self._go_unit_list(ctx)

        # --- Unit列表 → 阶段选择 ---
        if current == "listening_unit_list" or current == "unit_list":
            return self._go_stage_select(ctx)

        # --- 阶段选择 → 答题 ---
        if current == "stage_select":
            return self._go_question_page(ctx)

        # --- 答题中 → 继续看题（不需要额外导航）---
        if current == "question_page":
            return True  # 已经在答题页了

        # --- 结果页 → 下一题 ---
        if current == "result_page":
            return self._go_next_question()

        return False

    def _go_special_modules(self) -> bool:
        """主页 → 专项突破"""
        elems = self.adb.dump_ui()
        for e in elems:
            if e.text and '专项突破' in (e.text or ''):
                self.adb.tap(e.center[0], e.center[1])
                print(f"  [Nav] 主页 → 专项突破 at {e.center}")
                time.sleep(2)
                return True
        # 兜底
        self.adb.tap(135, 1335)
        time.sleep(2)
        return True

    def _go_listening(self) -> bool:
        """专项突破模块列表 → 听力专项"""
        elems = self.adb.dump_ui()
        for e in elems:
            if e.text and '听力' in (e.text or '') and 100 < e.center[1] < 2200:
                self.adb.tap(e.center[0], e.center[1])
                print(f"  [Nav] → 听力专项 at {e.center}")
                time.sleep(2)
                return True

        # 没看到，向上滚动找
        for _ in range(5):
            self.adb.swipe(540, 1600, 540, 600, 400)
            time.sleep(0.5)
            elems = self.adb.dump_ui()
            for e in elems:
                if e.text and '听力' in (e.text or '') and 100 < e.center[1] < 2200:
                    self.adb.tap(e.center[0], e.center[1])
                    print(f"  [Nav] 滚动后 → 听力专项 at {e.center}")
                    time.sleep(2)
                    return True
        return False

    def _go_unit_list(self, ctx: dict) -> bool:
        """版本选择页 → Unit列表（确认版本正确+点Unit）"""
        version = (ctx or {}).get("version", "新湘鲁六上")
        unit = (ctx or {}).get("unit", 6)

        elems = self.adb.dump_ui()

        # 检查当前版本是否匹配
        version_kw = "六上" if "六上" in version else "六下" if "六下" in version else "五上" if "五上" in version else "五下"
        version_long = {"六上": "六年级上册", "六下": "六年级下册",
                        "五上": "五年级上册", "五下": "五年级下册"}.get(version_kw, "")

        page_text = ' '.join([(e.text or '') for e in elems])
        if version_long and version_long in page_text:
            print(f"  [Nav] 版本正确: {version_long}")
        elif version_kw and version_kw in page_text:
            print(f"  [Nav] 版本匹配({version_kw})")
        else:
            # 尝试点击版本切换
            for e in elems:
                if e.text and version_kw in (e.text or ''):
                    self.adb.tap(e.center[0], e.center[1])
                    print(f"  [Nav] 切换版本 → {version_kw} at {e.center}")
                    time.sleep(2)
                    break
            else:
                self.adb.tap(540, 1200)
                time.sleep(2)

        # 找Unit
        elems = self.adb.dump_ui()
        unit_y = None
        for scroll_attempt in range(6):
            for e in elems:
                if e.text and re.match(rf'^Unit {unit}\b', (e.text or '').strip()):
                    unit_y = e.center[1]
                    break
            if unit_y:
                break
            if scroll_attempt < 5:
                self.adb.swipe(540, 1800, 540, 500, 400)
                time.sleep(0.8)
                elems = self.adb.dump_ui()

        if not unit_y:
            print(f"  [Nav] ⚠ 未找到 Unit {unit}")
            self.adb.tap(540, 1400)
            time.sleep(3)
            return True  # 先点一下看看

        # 点"去练习"
        for e in elems:
            if '去练习' in (e.text or '') and abs(e.center[1] - unit_y) < 250:
                self.adb.tap(e.center[0], e.center[1])
                print(f"  [Nav] 点'去练习' for U{unit} at {e.center}")
                time.sleep(4)
                return True

        # 兜底
        self.adb.tap(882, unit_y + 99)
        time.sleep(4)
        return True

    def _go_stage_select(self, ctx: dict) -> bool:
        """Unit列表 → 阶段选择"""
        stage = (ctx or {}).get("stage", "基础巩固")
        elems = self.adb.dump_ui()

        # 直接找阶段按钮
        for _ in range(5):
            for e in elems:
                t = (e.text or '').strip()
                if (t == stage or stage in t or t in stage) and e.clickable:
                    if 50 < e.center[1] < 2200:
                        self.adb.tap(e.center[0], e.center[1])
                        print(f"  [Nav] 点'{t}' at {e.center}")
                        time.sleep(3)
                        return True
            time.sleep(1)
            elems = self.adb.dump_ui()

        print(f"  [Nav] ⚠ 未找到 {stage}")
        return True

    def _go_question_page(self, ctx: dict) -> bool:
        """阶段选择 → 答题页"""
        elems = self.adb.dump_ui()

        # 找"开始答题"
        for e in elems:
            if (e.text or '').strip() in ['开始答题', '去答题', '进入答题']:
                self.adb.tap(e.center[0], e.center[1])
                print(f"  [Nav] 点'开始答题' at {e.center}")
                time.sleep(4)
                return True

        # 兜底
        self.adb.tap(540, 1916)
        time.sleep(4)
        return True

    def _go_next_question(self) -> bool:
        """结果页 → 下一题"""
        elems = self.adb.dump_ui()
        for e in elems:
            t = (e.text or '').strip()
            if t in ['下一题', '完成', '继续', 'Next']:
                self.adb.tap(e.center[0], e.center[1])
                print(f"  [Nav] 点'{t}' at {e.center}")
                time.sleep(1.5)
                return True
        self.adb.tap(540, 2100)
        time.sleep(1.5)
        return True

    # ============================================
    # 异常处理
    # ============================================

    def _handle_interruption(self, page_type: str):
        """处理弹窗/完成提示等中断"""
        elems = self.adb.dump_ui()

        if page_type == "ad_popup":
            close_texts = ['关闭', '跳过', '×', '知道了', '确定']
            for e in elems:
                t = (e.text or '').strip()
                if any(c in t for c in close_texts):
                    self.adb.tap(e.center[0], e.center[1])
                    print(f"  [Nav] 关闭弹窗: '{t}' at {e.center}")
                    time.sleep(1)
                    return

        if page_type == "completion_popup":
            for e in elems:
                t = (e.text or '').strip()
                if t in ['先走一步', '继续练习']:
                    self.adb.tap(e.center[0], e.center[1])
                    print(f"  [Nav] 关完成弹窗: '{t}' at {e.center}")
                    time.sleep(2)
                    return

    def universal_reset(self):
        """终极重置：任何页面 → 英语宝首页"""
        print(f"  [Nav] 执行通用重置...")
        # 连续退出
        for _ in range(4):
            self.adb.press_back()
            time.sleep(0.5)

        # 强杀重启
        self.adb._adb(["shell", "am", "force-stop", "com.dinoenglish.yyb"])
        time.sleep(2)
        self.adb.launch_app("com.dinoenglish.yyb")
        time.sleep(5)

        # 关弹窗
        elems = self.adb.dump_ui()
        self._handle_interruption("ad_popup")

        # 点英语Tab
        self.adb.tap(108, 2233)
        time.sleep(2)
        print(f"  [Nav] ✅ 已回到英语宝首页")
