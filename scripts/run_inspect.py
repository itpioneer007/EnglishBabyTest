"""
英语宝 — 多模块自动化检查调度器 (Inspection Orchestrator)
=========================================================

用途：接收自然语言指令 → 解析 → 按页面地图一步一步执行遍历。

核心流程：
  1. NL 解析 → AutomationPlan
  2. 确保版本 + 年级匹配
  3. 对每个模块、每个单元：
     a. 导航到模块
     b. 进入单元
     c. 截图/检查（未来扩展：自动答题+判错）
     d. 返回模块列表
  4. 所有完成 → 返回主学习页

用法：
  python scripts/run_inspect.py "切换至新湘少五年级上册的第六单元听力专项模块"
  python scripts/run_inspect.py "新湘少五上U6-U9听力专项"
  python scripts/run_inspect.py "人教版四年级下册第一到第三单元课本点读"

当前阶段 (v1)：导航流控 — 精确定位到每个目标单元的入口。
下一阶段 (v2)：加上答题循环（点选项→点检查→点下一题→截图给AI判错）。
"""

import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from adb_controller import ADBController
from nl_parser import parse, AutomationPlan
from app_graph import (
    PAGE, PAGES, PageGraph, PageNode, MODULE_NAME_TO_COORD
)
import config_loader as cl
import app_elements as AE


# ============================================================
# 调度器
# ============================================================

class InspectionOrchestrator:
    """
    多模块检查调度器。
    - 用页面图做导航
    - 用 NL 解析做意图理解
    - 用 ADB Controller 做实际点击
    """

    def __init__(self, adb: ADBController, screenshot_dir: str = "screenshots"):
        self.adb = adb
        self.shot_dir = screenshot_dir
        self.graph = PageGraph(adb)
        self.shot_seq = 0
        self.current_version = ""   # 当前 APP 里的版本
        self.current_grade = ""     # 当前 APP 里的年级

    # ---- 工具 ----
    def _shot(self, label: str) -> str:
        """截图并递增编号"""
        self.shot_seq += 1
        fn = f"insp_{self.shot_seq:03d}_{label}.png"
        return self.adb.screenshot(fn)

    def _tap(self, coord: tuple, label: str, wait: float = 1.5) -> bool:
        x, y = coord
        ok = self.adb.tap(x, y)
        time.sleep(wait)
        print(f"  TAP {label} @ ({x},{y}) -> {'OK' if ok else 'FAIL'}")
        return ok

    def _go_to_main(self):
        """强制回到主学习页"""
        for _ in range(5):
            if self.graph.is_at(PAGE.MAIN):
                self.graph.current_page = PAGE.MAIN
                return
            self.adb.press_back()
            time.sleep(1.0)
        # 兜底：点英语 tab
        self._tap(AE.TAB_ENGLISH["coord"], "英语tab", wait=3.0)
        self.graph.current_page = PAGE.MAIN

    # ---- 版本/年级切换 ----
    def _ensure_version(self, target_version: str):
        """确保当前版本匹配目标版本"""
        target = target_version.strip()
        if self.current_version == target:
            print(f"  ✅ 版本已是 {target}，跳过")
            return
        print(f"\n  [切版本] {self.current_version or '(未知)'} → {target}")
        # 我 → ⚙️ → 个人信息 → 英语所学教材版本
        self._go_to_main()
        self._tap(AE.TAB_ME["coord"], "我tab", wait=2.5)
        self._tap((1000, 170), "设置齿轮", wait=2)
        self._tap((400, 320), "个人信息行", wait=2)
        self._tap((700, 1358), "英语所学教材版本", wait=2.5)

        # 在版本选择页找目标版本
        elems = self.adb.dump_ui(retries=1, retry_delay=0.3)
        for e in elems:
            if target in (e.text or ""):
                cx, cy = e.center
                self._tap((cx, cy), target, wait=3)
                self.current_version = target
                print(f"  ✅ 版本已切换: {target}")
                return
        print(f"  ⚠ 版本选择页未找到: {target}")

    def _ensure_grade(self, target_grade: str):
        """确保当前年级匹配"""
        target = target_grade.strip()
        if self.current_grade == target:
            print(f"  ✅ 年级已是 {target}，跳过")
            return
        print(f"\n  [切年级] → {target}")
        self._go_to_main()
        self._shot("before_grade")
        self._tap((346, 275), "年级选择条", wait=2.5)
        # 找目标年级
        elems = self.adb.dump_ui(retries=1, retry_delay=0.3)
        found = None
        for e in elems:
            if target in (e.text or ""):
                found = e.center
                break
        if found:
            cx, cy = found
            self._tap((cx, cy), target, wait=3)
            self.current_grade = target
            print(f"  ✅ 年级已切换: {target}")
        else:
            print(f"  ⚠ 年级弹窗未找到: {target}，尝试手动查找")
            # 尝试滚动
            for _ in range(3):
                self.adb.swipe(540, 1800, 540, 1200, 300)
                time.sleep(1.5)
                elems = self.adb.dump_ui(retries=1, retry_delay=0.3)
                for e in elems:
                    if target in (e.text or ""):
                        cx, cy = e.center
                        self._tap((cx, cy), target, wait=3)
                        self.current_grade = target
                        print(f"  ✅ 年级已切换(滚动后): {target}")
                        return
        self._shot("after_grade")

    # ---- 模块导航 ----
    def _enter_module(self, module_name: str):
        """从主学习页进入某模块 → MODULE_LIST 页面"""
        print(f"\n  [进模块] {module_name}")
        self._go_to_main()
        self._shot(f"main_before_{module_name}")

        # 查坐标映射
        coord = MODULE_NAME_TO_COORD.get(module_name)
        if coord:
            self._tap(coord, module_name, wait=3)
            self._shot(f"after_enter_{module_name}")
            self.graph.current_page = PAGE.MODULE_LIST
            print(f"  ✅ 已进入: {module_name}")
            return

        # 没找到坐标 → 动态 dump 查找
        elems = self.adb.dump_ui(retries=1, retry_delay=0.3)
        for e in elems:
            if module_name in (e.text or ""):
                cx, cy = e.center
                # 点图标中心（文字中心 y 有误判风险，上移 40px）
                self._tap((cx, cy - 40), module_name, wait=3)
                self._shot(f"after_enter_{module_name}")
                print(f"  ✅ 已进入(动态): {module_name} @ ({cx}, {cy-40})")
                self.graph.current_page = PAGE.MODULE_LIST
                return
        print(f"  ❌ 无法定位模块: {module_name}")

    def _enter_unit(self, unit_num: int):
        """在 MODULE_LIST 页进入指定单元"""
        print(f"\n    [U{unit_num}]")
        self._shot(f"module_before_U{unit_num}")

        # dump 找 "去练习" 按钮
        elems = self.adb.dump_ui(retries=1, retry_delay=0.3)
        # 找到所有 Unit 文本和"去练习"按钮
        unit_found = None
        go_buttons = []
        for e in elems:
            t = (e.text or "").strip()
            if f"Unit {unit_num}" in t and "Unit" in t:
                unit_found = e
            if "去练习" in t:
                go_buttons.append(e)

        if not go_buttons:
            print(f"    ❌ 未找到「去练习」按钮")
            self._shot(f"no_go_button_U{unit_num}")
            return False

        # Unit X 的"去练习"按钮: 找到对应 Unit 下方的第一个"去练习"
        target = None
        if unit_found:
            # 找 Unit 位置下方最近的"去练习"
            uy = unit_found.center[1]
            for btn in go_buttons:
                if btn.center[1] > uy and (target is None or btn.center[1] < target[1]):
                    target = btn.center
        if target is None and go_buttons:
            # 兜底: 第 unit_num 个按钮
            target = go_buttons[min(unit_num - 1, len(go_buttons) - 1)].center

        if target:
            self._tap(target, f"U{unit_num} 去练习", wait=4)
            self._shot(f"U{unit_num}_question")
            self.graph.current_page = PAGE.QUESTION
            return True

        print(f"    ❌ 无法定位 U{unit_num} 的去练习按钮")
        return False

    def _exit_unit(self):
        """从问题页返回模块列表"""
        self.adb.press_back()
        time.sleep(2)
        self.graph.current_page = PAGE.MODULE_LIST

    # ---- 主流程 ----
    def run_plan(self, plan: AutomationPlan):
        """
        执行一个自动化计划。
        plan 来自 nl_parser.parse()。
        """
        print(f"\n{'='*60}")
        print(f"开始执行: {plan.summary()}")
        print(f"{'='*60}")

        # 1. 切版本
        if plan.version:
            self._ensure_version(plan.version)
        else:
            print("  ⚠ 未指定版本，使用当前版本")

        # 2. 切年级
        if plan.grade:
            self._ensure_grade(plan.grade)
        else:
            print("  ⚠ 未指定年级，使用当前年级")

        # 3. 遍历模块
        modules = [plan.module] if plan.module else []
        # 如果 stage 和 module 同名（如"基础巩固"被同时匹配为 module+stage），
        # 则 stage 不单独处理（它可能是 module 的关卡）
        stage = plan.stage if plan.stage != plan.module else ""

        total = len(plan.units) * len(modules) if modules else len(plan.units)
        completed = 0

        for module_name in modules:
            print(f"\n--- 模块: {module_name} ---")
            self._enter_module(module_name)

            for u in plan.units:
                ok = self._enter_unit(u)
                if ok:
                    completed += 1
                    print(f"    ✅ U{u} 入口确认 [{completed}/{total}]")
                    # 返回模块列表，准备下一个 unit
                    self._exit_unit()
                else:
                    print(f"    ❌ U{u} 入口失败")
                time.sleep(1)

            # 返回主学习页
            self.adb.press_back()
            time.sleep(1.5)
            self._shot(f"back_main_after_{module_name}")

        print(f"\n{'='*60}")
        print(f"✅ 完成: {completed}/{total} 个单元入口已确认")
        print(f"{'='*60}")

    def run_nl(self, text: str):
        """一步：自然语言 → 解析 → 执行"""
        plan = parse(text)
        print(f"\n📝 解析: {text}")
        print(f"   版本={plan.version!r}  年级={plan.grade!r}  单元={plan.units}  模块={plan.module!r}")
        if plan.confidence < 0.5:
            print(f"   ⚠ 置信度低({plan.confidence:.0%})，可能解析有误，请确认")
        self.run_plan(plan)


# ============================================================
# 入口
# ============================================================

if __name__ == "__main__":
    text = sys.argv[1] if len(sys.argv) > 1 else "切换至新湘少五年级上册的第六单元听力专项模块"
    cfg = cl.load_config()
    serial = cfg.device.serial
    adb = ADBController(serial=serial, screenshot_dir="screenshots")
    orch = InspectionOrchestrator(adb)
    orch.run_nl(text)
