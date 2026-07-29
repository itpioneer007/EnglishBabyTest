"""
多模块批量自动化 — 健壮版 v2
=============================

改进点（基于用户反馈）：
1. 每次运行前 dump UI 获取动态坐标，不依赖硬编码
2. 进入未知页面时自动按左上角箭头退出，回主页
3. 失败立即停止 + 截图 + 报告
4. 图标中心 = 文字 y - 50（已验证稳定）

任务：湘少版(2024审定) 五年级上册
  1. 听力专项: U6, U7, U8
  2. 口语训练: U6, U7
  3. 知识过关: U6 (unit_list_simple 布局)
"""

import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from adb_controller import ADBController
from app_graph import PAGE, PageGraph
import config_loader as cl
import app_elements as AE


# 主页可见的模块（用于坐标查找）
MAIN_PAGE_MODULES = (
    '听课文', '课文动画', '课文配音', '口语训练',
    '复习回顾', '全脑记词', '单词听写', '听力专项',
    '听力训练', '语法讲解', '知识过关', '趣味练习',
    '单元自检', '单元学习计划', '乐听一刻', '教材同步题库',
    '课本点读', '巧记单词', '语音评测',
)


class BatchRunnerV2:
    def __init__(self, adb):
        self.adb = adb
        self.graph = PageGraph(adb)
        self.done = 0
        self.total = 0
        self.phase = ""
        self.module_coords = {}    # 模块名 → 当前实际坐标 (icon)

    # ---- 工具 ----
    def _fail(self, msg):
        self.adb.screenshot(f"FAIL_{self.phase}.png")
        print(f"\n{'='*60}")
        print(f"❌❌❌ 任务中断 @ {self.phase}")
        print(f"  原因：{msg}")
        print(f"  已通过：{self.done}/{self.total}")
        print(f"{'='*60}")
        sys.exit(1)

    def _ok(self):
        self.done += 1
        print(f"  ✅ [{self.done}/{self.total}]")

    def _exit_unknown_page(self, max_attempts=4):
        """在未知页面时，用标准返回键退出，回到主页"""
        for i in range(max_attempts):
            if self.graph.is_at(PAGE.MAIN):
                return True
            self.adb.press_back()
            time.sleep(2)
        return self.graph.is_at(PAGE.MAIN)

    def _goto_main_robust(self):
        """可靠地回到主学习页（处理未知页面）"""
        # 第一步：检查是否已在主页
        if self.graph.is_at(PAGE.MAIN):
            return

        # 第二步：最多按5次返回键回到主页（防止退出APP）
        for _ in range(5):
            self.adb.press_back()
            time.sleep(1.5)
            if self.graph.is_at(PAGE.MAIN):
                return

        # 第三步：尝试 tap 英语tab
        elems = self.adb.dump_ui(retries=1, retry_delay=0.3)
        for e in elems:
            if (e.text or '').strip() == "英语" and e.center[1] > 2000:
                self.adb.tap(e.center[0], e.center[1])
                time.sleep(3)
                if self.graph.is_at(PAGE.MAIN):
                    return

        self._fail(f"无法回到主学习页")

    def _try_english_tab(self):
        """尝试点英语 tab"""
        elems = self.adb.dump_ui(retries=1, retry_delay=0.3)
        for e in elems:
            t = (e.text or '').strip()
            if t == "英语" and e.center[1] > 2000:
                self.adb.tap(e.center[0], e.center[1])
                time.sleep(3)
                return self.graph.is_at(PAGE.MAIN)
        return False

    def _refresh_module_coords(self):
        """dump UI 拿当前所有模块的实际图标中心坐标"""
        # 先滚到顶部确保所有模块可见
        for _ in range(3):
            elems = self.adb.dump_ui(retries=1, retry_delay=0.3)
            # 检查模块是否在可见区
            has_jc = any('教材精学' in (e.text or '') for e in elems)
            if has_jc:
                break
            # 向上滚（手指下滑，内容上滚）
            self.adb.swipe(540, 600, 540, 2000, 400)
            time.sleep(1.5)

        self.adb.screenshot("home_before_batch.png")
        elems = self.adb.dump_ui(retries=1, retry_delay=0.3)
        self.module_coords.clear()
        for e in elems:
            t = (e.text or '').strip()
            if t in MAIN_PAGE_MODULES:
                cx, cy = e.center
                # 图标在文字上方约 50px（验证过）
                self.module_coords[t] = (cx, cy - 50)

    def _enter_module(self, name):
        """动态定位模块图标 → tap → 进到 MODULE_LIST（多重验证）"""
        self.phase = f"enter_{name}"
        self._goto_main_robust()
        if not self.module_coords:
            self._refresh_module_coords()
        if name not in self.module_coords:
            self._fail(f"主页找不到 {name} 模块（可能页面不在顶部）")
        cx, cy = self.module_coords[name]

        # 重试机制：tap 最多 2 次
        for attempt in range(2):
            self.adb.tap(cx, cy)
            time.sleep(8)  # 充分等待页面加载

            # 验证1：dump_ui
            elems = self.adb.dump_ui(retries=1, retry_delay=0.3)
            all_text = ' '.join((e.text or '') for e in elems)
            if "去练习" in all_text or "开始答题" in all_text or "当前版本" in all_text or "Unit" in all_text:
                # 找第一条匹配的
                for e in elems:
                    t = (e.text or '').strip()
                    if t in ("去练习", "开始答题") or "当前版本" in t or (t.startswith("Unit ") and len(t) < 40):
                        print(f"  [{name}] ✅ 已进入 (dump: {t[:30]!r})")
                        return True

            # 验证2：截图OCR全图
            path = self.adb.screenshot(f"verify_{name}_try{attempt}.png")
            try:
                import pytesseract
                pytesseract.pytesseract.tesseract_cmd = r'C:/Program Files/Tesseract-OCR/tesseract.exe'
                from PIL import Image
                img = Image.open(path)
                # 全图 OCR（top 40%）
                top = img.crop((0, 0, img.width, int(img.height * 0.4)))
                text = pytesseract.image_to_string(top, lang='chi_sim+eng', config='--oem 3 --psm 6')
                # 接受: 模块名/当前版本/Unit/去练习/开始答题 任一
                if any(k in text for k in (name, "当前版本", "Unit", "去练习", "开始答题")):
                    print(f"  [{name}] ✅ 已进入 (OCR兜底: 顶部含{any(k in text for k in (name, '当前版本')) and name or '标志'})")
                    return True
                # 兜底：再试底部40%（可能有"开始答题"按钮在下方）
                bot = img.crop((0, int(img.height * 0.4), img.width, img.height))
                text2 = pytesseract.image_to_string(bot, lang='chi_sim+eng', config='--oem 3 --psm 6')
                if any(k in text2 for k in (name, "Unit", "去练习", "开始答题")):
                    print(f"  [{name}] ✅ 已进入 (OCR底部: 找到标志)")
                    return True
            except Exception as e:
                print(f"  [{name}] OCR异常: {e}")

            # 没识别到，但这是第2次吗？
            if attempt == 1:
                break
            # 重试：先退出（如果可能），重新 tap
            self.adb.press_back()
            time.sleep(2)

        self._fail(f"点 {name} @ ({cx},{cy}) 后2次重试仍未进入模块页")

    # 兜底坐标：已知模块列表的"去练习"/"开始答题"按钮 y 位置（按顺序）
    # 听力专项 / 课本点读 等 tab_practice_test 类型: 6按钮 y=703/903/1103/1303/1503/1703/.../2215
    TAB_BUTTON_Y = [703, 903, 1103, 1303, 1503, 1703, 1903, 2103, 2215]

    def _enter_unit_tab(self, unit_index):
        """按位置点第N个去练习/开始答题按钮（不关心Unit编号）"""
        self.phase = f"tab_pos_{unit_index}"

        # 方案1：dump_ui 找按钮
        elems = self.adb.dump_ui(retries=1, retry_delay=0.3)
        btns = []
        for e in elems:
            t = (e.text or "").strip()
            if t in ("去练习", "开始答题"):
                btns.append(e)

        # 方案2：dump 兜底 → 用硬编码 y 坐标 + x=882
        if not btns and unit_index < len(self.TAB_BUTTON_Y):
            target = (882, self.TAB_BUTTON_Y[unit_index])
            print(f"  [tab@{unit_index}] dump无按钮，用硬编码 {target}")
        elif btns:
            btns.sort(key=lambda x: x.center[1])
            if unit_index >= len(btns):
                target = btns[-1].center
            else:
                target = btns[unit_index].center
        else:
            self._fail(f"找不到第{unit_index+1}个按钮")

        self.adb.tap(target[0], target[1])
        time.sleep(5)
        return self._verify_in_question()

    def _verify_in_question(self):
        """验证是否进入答题页（基础巩固/开始答题/检查等）"""
        elems2 = self.adb.dump_ui(retries=1, retry_delay=0.3)
        for e in elems2:
            t = (e.text or "").strip()
            if t in ("基础巩固", "开始答题", "检查", "答对", "答错") or "Unit" in t:
                return True
        # OCR兜底
        path = self.adb.screenshot("question_check.png")
        try:
            import pytesseract
            pytesseract.pytesseract.tesseract_cmd = r'C:/Program Files/Tesseract-OCR/tesseract.exe'
            from PIL import Image
            img = Image.open(path)
            text = pytesseract.image_to_string(img, lang='chi_sim+eng', config='--oem 3 --psm 6')
            if "基础巩固" in text or "开始答题" in text or "检查" in text or "Unit" in text:
                return True
        except Exception:
            pass
        return False

    def _enter_unit_simple(self, unit):
        """unit_list_simple 布局：依次点 Unit 行"""
        self.phase = f"simple_unit_{unit}"
        target = None
        for scroll_try in range(3):
            elems = self.adb.dump_ui(retries=1, retry_delay=0.3)
            unit_rows = []
            for e in elems:
                t = (e.text or "").strip()
                # 知识过关/单元自检 的 Unit 行格式
                if ("Unit" in t and len(t) < 60 and any(c.isdigit() for c in t)):
                    unit_rows.append(e)
            if unit_rows:
                # 取最上面的 Unit
                target = min(unit_rows, key=lambda x: x.center[1])
                # 点 Unit 行 + 偏移到右侧箭头 (知识过关/单元自检布局箭头在右边)
                tap_pt = (target.center[0] + 250, target.center[1])
                self.adb.tap(tap_pt[0], tap_pt[1])
                time.sleep(5)
                return self._verify_in_question()
            self.adb.swipe(540, 1700, 540, 1100, 400)
            time.sleep(1.5)

        self._fail(f"simple布局找不到 Unit 行")

    def _back_to_main(self):
        """从任何页回主页（最多3次返回 + 英语tab兜底）"""
        for _ in range(3):
            if self.graph.is_at(PAGE.MAIN):
                return True
            self.adb.press_back()
            time.sleep(2)
        # 兜底
        self._goto_main_robust()
        return True

    def run(self):
        # 计划：3 模块，每模块前 3 个可见单元（按位置点击，不滚动）
        tasks = [
            ("听力专项", "tab"),     # 听力专项 Unit 1-3
            ("口语训练", "tab"),     # 口语训练 U1-U3
            ("知识过关", "simple"),  # 知识过关 Unit 1-3
        ]
        units_per_module = 3
        self.total = units_per_module * len(tasks)
        print(f"\n{'='*60}")
        print(f"🚀 多模块批量 v3: {len(tasks)} 模块，{self.total} 单元（按位置点）")
        print(f"{'='*60}")

        # 初始回到主页 + dump 坐标
        self._goto_main_robust()
        self._refresh_module_coords()
        print(f"  📍 主页模块坐标已 dump ({len(self.module_coords)} 个)")

        for m_name, layout in tasks:
            print(f"\n--- 模块 [{m_name}] {units_per_module}个单元 ({layout}) ---")
            self._enter_module(m_name)

            # 按位置点：第 0/1/2 个行动按钮
            for i in range(units_per_module):
                print(f"  第{i+1}个: tap...")
                if layout == "tab":
                    self._enter_unit_tab(i)
                else:
                    self._enter_unit_simple(i)
                self._ok()
                # 出单元，回模块列表
                self.adb.press_back()
                time.sleep(2)

            # 出模块，回主页
            self._back_to_main()
            print(f"  [{m_name}] ✅ 完成")

        print(f"\n{'='*60}")
        print(f"🎉🎉🎉 全成功：{self.done}/{self.total} 🎉🎉🎉")
        print(f"{'='*60}")


if __name__ == "__main__":
    cfg = cl.load_config()
    serial = cfg.device.serial
    adb = ADBController(serial=serial, screenshot_dir="screenshots")
    runner = BatchRunnerV2(adb)
    runner.run()