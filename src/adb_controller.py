"""
英语宝模块检测 - ADB 智能控制器

核心能力：
  - dump_ui(): 获取当前页面所有UI元素及其精确坐标
  - find_element(): 按文本/resource-id/描述查找元素
  - click_element(): 查找并点击元素（自动定位精确坐标）
  - tap(): 直接坐标点击
  - swipe(): 滑动
  - screenshot(): 截图
  - input_text(): 输入文字
  - wait_for_element(): 等待元素出现
  - is_element_present(): 判断元素是否存在

设计原则：
  - 优先用 uiautomator dump 获取精确坐标（零误差）
  - 支持坐标回退（已知坐标直接用，不用每次dump）
  - 每步操作自动截图+记录日志
"""

import subprocess
import re
import os
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Optional
import json


@dataclass
class UIElement:
    """一个UI元素的完整信息"""
    text: str = ""
    resource_id: str = ""
    class_name: str = ""
    content_desc: str = ""
    clickable: bool = False
    bounds: tuple = (0, 0, 0, 0)  # (x1, y1, x2, y2)
    center: tuple = (0, 0)        # (cx, cy)

    @property
    def width(self):
        return self.bounds[2] - self.bounds[0]

    @property
    def height(self):
        return self.bounds[3] - self.bounds[1]


class ADBController:
    """ADB 智能控制器"""

    def __init__(self, serial: str = "", screenshot_dir: str = "screenshots"):
        self.serial = serial
        self.screenshot_dir = screenshot_dir
        os.makedirs(screenshot_dir, exist_ok=True)
        self.step_count = 0
        self.log: list[dict] = []

    def _adb(self, args: list[str], timeout: int = 15) -> tuple[int, str]:
        """执行ADB命令"""
        cmd = ["adb"]
        if self.serial:
            cmd.extend(["-s", self.serial])
        cmd.extend(args)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                                encoding="utf-8", errors="replace")
        stdout = result.stdout or ""
        stderr = result.stderr or ""
        return result.returncode, (stdout + stderr).strip()

    def _log(self, action: str, detail: str, success: bool = True):
        """记录操作日志"""
        entry = {
            "step": self.step_count,
            "time": time.strftime("%H:%M:%S"),
            "action": action,
            "detail": detail,
            "success": success,
        }
        self.log.append(entry)
        status = "✅" if success else "❌"
        print(f"  {status} [{entry['time']}] {action}: {detail}")

    # ============================================================
    # 截图
    # ============================================================

    def screenshot(self, filename: str = "") -> str:
        """截图并保存到本地，返回文件路径"""
        self.step_count += 1
        if not filename:
            filename = f"step_{self.step_count:03d}.png"
        local_path = os.path.join(self.screenshot_dir, filename)
        remote = "/sdcard/yyb_shot.png"

        self._adb(["shell", "screencap", "-p", remote])
        self._adb(["pull", remote, local_path])
        self._adb(["shell", "rm", remote])
        self._log("截图", filename)
        return local_path

    # ============================================================
    # UI 层次结构 dump（核心功能）
    # ============================================================

    def dump_ui(self, retries: int = 3, retry_delay: float = 1.5) -> list[UIElement]:
        """获取当前页面所有UI元素，返回列表
        自动重试以应对轮播图等导致 idle state 拿不到的情况
        """
        remote = "/sdcard/yyb_ui.xml"
        last_error = ""

        for attempt in range(retries):
            # 等待动画/轮播稳定
            if attempt > 0:
                time.sleep(retry_delay)

            self._adb(["shell", "uiautomator", "dump", remote])
            code, output = self._adb(["shell", "cat", remote])

            if output and "<hierarchy" in output:
                self._adb(["shell", "rm", remote])
                elements = self._parse_ui_xml(output)
                if elements:
                    return elements
            last_error = f"attempt {attempt+1} 失败"

        self._adb(["shell", "rm", remote])
        self._log("dump_ui", f"重试{retries}次仍失败: {last_error}", success=False)
        return []

    def _parse_ui_xml(self, xml_str: str) -> list[UIElement]:
        """解析UI XML，返回元素列表"""
        elements = []
        try:
            root = ET.fromstring(xml_str)
        except ET.ParseError:
            return []

        for node in root.iter("node"):
            bounds_str = node.get("bounds", "")
            nums = re.findall(r"\d+", bounds_str)
            if len(nums) != 4:
                continue

            x1, y1, x2, y2 = map(int, nums)
            elem = UIElement(
                text=node.get("text", ""),
                resource_id=node.get("resource-id", ""),
                class_name=node.get("class", ""),
                content_desc=node.get("content-desc", ""),
                clickable=node.get("clickable", "false") == "true",
                bounds=(x1, y1, x2, y2),
                center=((x1 + x2) // 2, (y1 + y2) // 2),
            )
            elements.append(elem)

        return elements

    # ============================================================
    # 元素查找
    # ============================================================

    def find_element(
        self,
        text: str = "",
        resource_id: str = "",
        content_desc: str = "",
        clickable_only: bool = False,
        exact: bool = False,
    ) -> Optional[UIElement]:
        """
        查找元素，返回第一个匹配的UIElement
        默认模糊匹配（contains），exact=True 时精确匹配
        """
        elements = self.dump_ui()

        for elem in elements:
            if clickable_only and not elem.clickable:
                continue

            if exact:
                if text and text == elem.text:
                    return elem
                if resource_id and resource_id == elem.resource_id:
                    return elem
                if content_desc and content_desc == elem.content_desc:
                    return elem
            else:
                if text and text in elem.text:
                    return elem
                if resource_id and resource_id in elem.resource_id:
                    return elem
                if content_desc and content_desc in elem.content_desc:
                    return elem

        return None

    def find_all(
        self,
        text: str = "",
        resource_id: str = "",
        content_desc: str = "",
    ) -> list[UIElement]:
        """查找所有匹配的元素"""
        elements = self.dump_ui()
        results = []

        for elem in elements:
            match = True
            if text and text not in elem.text:
                match = False
            if resource_id and resource_id not in elem.resource_id:
                match = False
            if content_desc and content_desc not in elem.content_desc:
                match = False
            if match:
                results.append(elem)

        return results

    def is_element_present(
        self,
        text: str = "",
        resource_id: str = "",
        content_desc: str = "",
    ) -> bool:
        """判断元素是否存在"""
        return self.find_element(text, resource_id, content_desc) is not None

    # ============================================================
    # 点击操作
    # ============================================================

    def tap(self, x: int, y: int) -> bool:
        """直接坐标点击"""
        self.step_count += 1
        code, _ = self._adb(["shell", "input", "tap", str(x), str(y)])
        success = code == 0
        self._log("点击", f"坐标 ({x}, {y})", success)
        time.sleep(0.5)
        return success

    def click_element(
        self,
        text: str = "",
        resource_id: str = "",
        content_desc: str = "",
        exact: bool = False,
    ) -> bool:
        """
        查找并点击元素（推荐方式）
        自动通过 uiautomator dump 获取精确坐标
        exact=True 精确匹配（避免"登录"误匹配"学生登录"）
        """
        elem = self.find_element(text, resource_id, content_desc, clickable_only=False, exact=exact)
        if elem is None:
            self._log("点击", f"未找到元素: text='{text}' id='{resource_id}' exact={exact}", success=False)
            return False

        cx, cy = elem.center
        self.step_count += 1
        code, _ = self._adb(["shell", "input", "tap", str(cx), str(cy)])
        success = code == 0
        label = elem.text or elem.resource_id or elem.content_desc or f"({cx},{cy})"
        self._log("点击", f"'{label}' at ({cx}, {cy})", success)
        time.sleep(0.5)
        return success

    # ============================================================
    # 滑动操作
    # ============================================================

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> bool:
        """滑动"""
        self.step_count += 1
        code, _ = self._adb([
            "shell", "input", "swipe",
            str(x1), str(y1), str(x2), str(y2), str(duration_ms)
        ])
        success = code == 0
        direction = "向下滚动" if y2 < y1 else "向上滚动" if y2 > y1 else "水平滑动"
        self._log("滑动", f"{direction}: ({x1},{y1})→({x2},{y2})", success)
        time.sleep(0.8)
        return success

    def scroll_down(self, distance: int = 500):
        """页面向下滚动（手指上滑）"""
        cx = 540  # 屏幕水平中心
        self.swipe(cx, 1500, cx, 1500 - distance)

    def scroll_up(self, distance: int = 500):
        """页面向上滚动（手指下滑）"""
        cx = 540
        self.swipe(cx, 800, cx, 800 + distance)

    # ============================================================
    # 文本输入
    # ============================================================

    def input_text(self, text: str) -> bool:
        """输入文本（需先聚焦到输入框）"""
        self.step_count += 1
        # ADB input text 不支持中文，中文需用 ADBKeyboard IME
        if any("\u4e00" <= c <= "\u9fff" for c in text):
            self._log("输入", f"中文输入需ADBKeyboard: '{text}'", success=False)
            return False

        code, _ = self._adb(["shell", "input", "text", text])
        success = code == 0
        self._log("输入", f"'{text}'", success)
        time.sleep(0.3)
        return success

    # ============================================================
    # 等待
    # ============================================================

    def wait_for_element(
        self,
        text: str = "",
        resource_id: str = "",
        content_desc: str = "",
        timeout: int = 10,
        poll_interval: float = 1.0,
    ) -> bool:
        """等待元素出现，超时返回False"""
        self.step_count += 1
        start = time.time()
        found = False

        while time.time() - start < timeout:
            if self.find_element(text, resource_id, content_desc):
                found = True
                break
            time.sleep(poll_interval)

        label = text or resource_id or content_desc
        self._log("等待", f"'{label}' {'出现' if found else '超时'}({timeout}s)", found)
        return found

    def wait(self, seconds: float):
        """简单等待"""
        time.sleep(seconds)
        self._log("等待", f"{seconds}秒")

    # ============================================================
    # 按键
    # ============================================================

    def press_back(self) -> bool:
        """返回键"""
        code, _ = self._adb(["shell", "input", "keyevent", "4"])
        self._log("按键", "返回(Back)", code == 0)
        time.sleep(0.5)
        return code == 0

    def press_home(self) -> bool:
        """Home键"""
        code, _ = self._adb(["shell", "input", "keyevent", "3"])
        self._log("按键", "Home", code == 0)
        time.sleep(0.5)
        return code == 0

    def press_enter(self) -> bool:
        """回车键"""
        code, _ = self._adb(["shell", "input", "keyevent", "66"])
        self._log("按键", "Enter", code == 0)
        time.sleep(0.3)
        return code == 0

    # ============================================================
    # APP 控制
    # ============================================================

    def launch_app(self, package: str, activity: str = "") -> bool:
        """启动APP"""
        if activity:
            cmd = ["shell", "am", "start", "-n", f"{package}/{activity}"]
        else:
            cmd = ["shell", "monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1"]
        code, _ = self._adb(cmd)
        self._log("启动APP", f"{package}", code == 0)
        time.sleep(3)
        return code == 0

    def get_current_activity(self) -> str:
        """获取当前前台Activity"""
        code, output = self._adb([
            "shell", "dumpsys", "activity", "activities"
        ])
        match = re.search(r"mResumedActivity.*?{.*?\s(\S+)\s", output)
        if match:
            return match.group(1)
        return ""

    # ============================================================
    # 日志输出
    # ============================================================

    def save_log(self, path: str):
        """保存操作日志到JSON文件"""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.log, f, ensure_ascii=False, indent=2)
        print(f"\n日志已保存: {path}")

    def print_summary(self):
        """打印操作摘要"""
        total = len(self.log)
        success = sum(1 for e in self.log if e["success"])
        failed = total - success
        print(f"\n{'='*50}")
        print(f"操作摘要: 共 {total} 步, 成功 {success}, 失败 {failed}")
        print(f"{'='*50}")


# ============================================================
# 快速测试
# ============================================================

if __name__ == "__main__":
    adb = ADBController(serial="SKSCIF4T7PFMQS5X", screenshot_dir="screenshots")

    # 测试: dump UI 并打印所有可点击元素
    print("=== 当前页面可点击元素 ===")
    elements = adb.dump_ui()
    for elem in elements:
        if elem.clickable or elem.text:
            label = elem.text or elem.resource_id or elem.content_desc
            if label:
                print(f"  '{label}' at {elem.center} clickable={elem.clickable}")
