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
                    max_steps: int = 30) -> bool:
        """
        从当前页面导航到答题页。
        采用线性直走模式：不反复识别页面，按固定步骤执行。
        每步操作后验证是否到达目标，没到就继续下一步。
        """
        # 先确认现在在首页
        self.universal_reset()

        e = context or {}
        version = e.get("version", "新湘鲁六上")
        unit = e.get("unit", 6)
        stage = e.get("stage", "基础巩固")
        module = e.get("module_type", "听力专项")

        # ====== 第一步：专项突破 ======
        print(f"  [Nav] ① 点专项突破")
        self._tap_text("专项突破")

        # ====== 第二步：找目标模块 ======
        print(f"  [Nav] ② 找模块: {module}")
        if not self._scroll_then_tap(module):
            print(f"  [Nav] ⚠ 未找到模块 '{module}'")
            return False

        # ====== 第三步：检查版本 ======
        print(f"  [Nav] ③ 确认版本")
        self._ensure_version(version)

        # ====== 第四步：找Unit 去练习 ======
        print(f"  [Nav] ④ 找 Unit {unit}")
        if not self._find_unit_and_go(unit):
            print(f"  [Nav] ⚠ 未找到 Unit {unit}")
            return False

        # ====== 第五步：选阶段 ======
        print(f"  [Nav] ⑤ 选阶段: {stage}")
        self._tap_stage(stage)

        # ====== 第六步：开始答题 ======
        print(f"  [Nav] ⑥ 点开始答题")
        self._tap_start_practice()

        # ====== 最终验证 ======
        for _ in range(5):
            self._handle_popups()
            elems = self.adb.dump_ui()
            for e in elems:
                import re
                if re.match(r'\d+/\d+', (e.text or '').strip()):
                    print(f"  [Nav] ✅ 已到达答题页 (检测到题号 {e.text.strip()})")
                    return True
            time.sleep(1)

        # 兜底：可能已经在答题页了但没检测到题号
        print(f"  [Nav] ⚠ 未检测到题号，但流程已执行完毕，继续")
        return True

    def _tap_text(self, keyword: str, max_wait: int = 5) -> bool:
        """点包含某个文字的第一个可点击元素"""
        for _ in range(max_wait):
            elems = self.adb.dump_ui()
            for e in elems:
                if keyword in (e.text or '') and e.clickable and 50 < e.center[1] < 2200:
                    self.adb.tap(e.center[0], e.center[1])
                    time.sleep(1.5)
                    return True
            time.sleep(1)
        return False

    def _scroll_then_tap(self, keyword: str, max_scroll: int = 6) -> bool:
        """向下滚动查找，找到就点击"""
        for _ in range(max_scroll):
            elems = self.adb.dump_ui()
            for e in elems:
                if keyword in (e.text or '') and 100 < e.center[1] < 2200:
                    self.adb.tap(e.center[0], e.center[1])
                    time.sleep(1.5)
                    return True
            # 向下滚动
            self.adb.swipe(540, 1600, 540, 500, 400)
            time.sleep(0.8)
        return False

    def _ensure_version(self, version: str):
        """确认当前版本正确，不正确则切换"""
        grade_kw = {"六上": "六年级上册", "六下": "六年级下册",
                     "五上": "五年级上册", "五下": "五年级下册"}
        target = ""
        for short, full in grade_kw.items():
            if short in version:
                target = full
                break

        elems = self.adb.dump_ui()
        page_text = ' '.join([(e.text or '') for e in elems])

        # 已经正确
        if (target and target in page_text) or (version.replace("新湘鲁","") in page_text):
            print(f"  [Nav]   版本正确: {target or version}")
            return

        # 找年级文字点
        for e in elems:
            t = (e.text or '').strip()
            if any(k in t for k in ["六年级", "五年级", "六上", "五上"]):
                self.adb.tap(e.center[0], e.center[1])
                print(f"  [Nav]   切换版本 → {t}")
                time.sleep(2)
                return

        # 兜底
        self.adb.tap(540, 1200)
        time.sleep(2)

    def _find_unit_and_go(self, unit: int) -> bool:
        """找Unit，点对应去练习"""
        # 滚动找Unit文字
        for _ in range(6):
            elems = self.adb.dump_ui()
            unit_y = None
            for e in elems:
                import re
                if e.text and re.match(rf'^Unit {unit}\b', (e.text or '').strip()):
                    unit_y = e.center[1]
                    break
            if unit_y:
                # 找对应的"去练习"
                for e in elems:
                    if '去练习' in (e.text or '') and abs(e.center[1] - unit_y) < 250:
                        self.adb.tap(e.center[0], e.center[1])
                        print(f"  [Nav]   点'去练习' for U{unit} at {e.center}")
                        time.sleep(4)
                        return True
                # 没找到去练习，点Unit所在行右侧
                self.adb.tap(881, unit_y + 99)
                print(f"  [Nav]   兜底点 Unit 行 at (881, {unit_y+99})")
                time.sleep(4)
                return True
            # 向下滚动
            self.adb.swipe(540, 1800, 540, 500, 400)
            time.sleep(0.8)

        print(f"  [Nav] ⚠ 没找到 Unit {unit}")
        self.adb.tap(540, 1400)
        time.sleep(3)
        return True

    def _tap_stage(self, stage: str):
        """点阶段按钮"""
        for _ in range(5):
            elems = self.adb.dump_ui()
            for e in elems:
                t = (e.text or '').strip()
                if (t == stage or stage in t or t in stage) and e.clickable:
                    if 50 < e.center[1] < 2200:
                        self.adb.tap(e.center[0], e.center[1])
                        print(f"  [Nav]   点阶段 '{t}' at {e.center}")
                        time.sleep(2)
                        return
            time.sleep(1)

    def _tap_start_practice(self):
        """点'开始答题'之类的按钮"""
        for _ in range(3):
            elems = self.adb.dump_ui()
            for e in elems:
                t = (e.text or '').strip()
                if t in ['开始答题', '开始', '去答题', '进入答题', 'Start']:
                    self.adb.tap(e.center[0], e.center[1])
                    print(f"  [Nav]   点'{t}' at {e.center}")
                    time.sleep(3)
                    return
            time.sleep(1)
        self.adb.tap(540, 1916)
        time.sleep(3)

    def _handle_popups(self):
        """关弹窗/完成提示"""
        elems = self.adb.dump_ui()
        for e in elems:
            t = (e.text or '').strip()
            if t in ['先走一步', '继续练习', '关闭', '跳过', '×', '知道了']:
                self.adb.tap(e.center[0], e.center[1])
                time.sleep(1)
                return True
        return False

    # ============================================
    # 以下方法为旧版，保留兼容
    # ============================================

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
        """回到英语宝首页：连续按返回直到主页出现。不重启APP，不清缓存。"""
        print(f"  [Nav] 返回首页...")
        max_back = 8
        for i in range(max_back):
            elements = self.adb.dump_ui()
            texts = ' '.join([(e.text or '') for e in elements])

            # 检测到家了
            if all(kw in texts for kw in ["教材精学", "专项突破"]):
                print(f"  [Nav] ✅ 已回到首页 (第{i}次back后)")
                return True

            # 别按太多次（已经回首页了）
            if i >= max_back - 1:
                print(f"  [Nav] ⚠ 按了{max_back}次返回仍未确认到首页，继续流程")
                return True

            self.adb.press_back()
            time.sleep(0.6)
