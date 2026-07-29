"""
src/dry_run.py — 纯点击遍历（不审题，不断言，只验证能跑完）
负责人：B

用法：
  from src.dry_run import DryRunner
  r = DryRunner(adb)
  ok = r.click_through_module(unit=6, stage="基础巩固")
  → 自动导航 → 逐题点击 → 完成 → 返回 True/False
"""

import time, re


class DryRunner:
    """纯遍历流水线：导航 → 逐题点 → 完成。不截图，不调AI。"""

    def __init__(self, adb):
        self.adb = adb
        self.nav = None          # 延迟加载
        self.recovery = None     # 延迟加载
        self.questions_done = 0
        self.total_questions = 0
        self.current_q = 0

    def click_through_module(self, unit: int, stage: str = "基础巩固",
                             version: str = "新湘鲁六上") -> dict:
        """
        完整遍历一个模块的所有题目。
        不管对错，只要能点到"完成"或最后一题就算成功。

        Returns: {"success": bool, "questions_done": int, "total": int, "error": str}
        """
        try:
            # 导航到答题页
            self._navigate_to_question(version, unit, stage)

            # 逐题点
            self._click_all_questions()

            # 处理完成
            return self._handle_completion()

        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"success": False, "questions_done": self.questions_done,
                    "total": self.total_questions, "error": str(e)[:200]}

    # ============================================
    # 导航
    # ============================================

    def _navigate_to_question(self, version, unit, stage):
        """导航到答题页"""
        from src.universe_navigator import UniverseNavigator
        if self.nav is None:
            self.nav = UniverseNavigator(self.adb)

        # 重置 + 导航
        self.nav.universal_reset()
        ok = self.nav.navigate_to("question_page", {
            "version": version, "unit": unit, "stage": stage,
        })
        if not ok:
            raise RuntimeError("导航到答题页失败")
        print(f"  [DryRun] ✅ 已到达答题页")

    # ============================================
    # 逐题点击
    # ============================================

    def _click_all_questions(self, max_questions: int = 100):
        """逐题点选 → 检查 → 下一题 → 循环"""
        last_q = 0
        stuck_count = 0

        for loop in range(max_questions):
            # 读屏幕
            try:
                elements = self.adb.dump_ui()
            except Exception:
                time.sleep(2)
                continue

            # 检测结果页
            if any('正确答案' in (e.text or '') for e in elements):
                self._click_next(elements)
                time.sleep(1.5)
                continue

            # 检测完成弹窗
            if any((e.text or '').strip() in ['先走一步', '继续练习'] for e in elements):
                print(f"  [DryRun] 检测到完成弹窗")
                return

            # 检测报告页
            all_text = ' '.join([(e.text or '') for e in elements])
            if '完成' in all_text and '得分' in all_text:
                print(f"  [DryRun] 检测到报告页")
                return

            # 读题号
            cur_q = self._read_question_number(elements)
            if not cur_q:
                stuck_count += 1
                if stuck_count > 5:
                    print(f"  [DryRun] ⚠ 连续{stuck_count}次读不到题号，可能已结束")
                    return
                time.sleep(0.5)
                continue

            stuck_count = 0

            # 防卡死
            if cur_q == last_q:
                time.sleep(0.3)
                continue
            last_q = cur_q
            self.current_q = cur_q

            # 更新总数
            for e in elements:
                m = re.match(r'^(\d+)/(\d+)$', (e.text or "").strip())
                if m:
                    self.total_questions = int(m.group(2))
                    break

            # 点击选项：随便选第一个可点击的
            self._click_random_option(elements)
            time.sleep(1)

            # 找"检查"按钮 -> 点
            self._click_check_button()
            time.sleep(1.5)

            self.questions_done += 1
            print(f"  [DryRun] Q{cur_q}/{self.total_questions} ✅")

    # ============================================
    # 子操作
    # ============================================

    def _read_question_number(self, elements) -> int | None:
        for e in elements:
            m = re.match(r'^(\d+)/(\d+)$', (e.text or "").strip())
            if m:
                return int(m.group(1))
        return None

    def _click_random_option(self, elements):
        """点第一个可点击的选项（不管对错）"""
        for e in elements:
            if e.clickable and 400 < e.bounds[1] < 2000 and (e.bounds[2] - e.bounds[0]) > 100:
                if e.center[0] < 150:
                    continue
                self.adb.tap(e.center[0], e.center[1])
                return
        # 兜底
        self.adb.tap(300, 900)

    def _click_check_button(self):
        """点检查/提交按钮"""
        for _ in range(5):
            try:
                elems = self.adb.dump_ui()
            except Exception:
                time.sleep(1)
                continue
            for e in elems:
                t = (e.text or '').strip()
                if t in ['检查', 'Check', '提交', '下一题', '完成']:
                    self.adb.tap(e.center[0], e.center[1])
                    return
            self.adb.tap(540, 2100)
            time.sleep(0.5)

    def _click_next(self, elements):
        """结果页点下一题"""
        for e in elements:
            t = (e.text or '').strip()
            if t in ['下一题', '完成', '继续', 'Next']:
                self.adb.tap(e.center[0], e.center[1])
                return
        self.adb.tap(540, 2174)

    def _handle_completion(self) -> dict:
        """处理完成后的弹窗/报告页"""
        elems = self.adb.dump_ui()

        for e in elems:
            t = (e.text or '').strip()
            if t in ['先走一步', '继续练习', '已完成', '完成']:
                self.adb.tap(e.center[0], e.center[1])
                print(f"  [DryRun] 关完成弹窗: '{t}' at {e.center}")
                time.sleep(1.5)
                break

        print(f"\n  [DryRun] ✅ 遍历完成: {self.questions_done}/{self.total_questions} 题")
        return {
            "success": True,
            "questions_done": self.questions_done,
            "total": self.total_questions,
            "error": "",
        }
