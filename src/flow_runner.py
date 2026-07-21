"""
英语宝模块检测 - 流程执行引擎

用 YAML 定义检测流程，引擎自动执行。
无需 WorkBuddy 介入，脚本独立运行完成全流程。

用法:
    python flow_runner.py flows/login.yaml
    python flow_runner.py flows/module_test.yaml --module "单词学习"

流程文件格式 (YAML):
    name: "登录流程"
    description: "英语宝登录"
    steps:
      - action: launch_app
        package: "com.dinoenglish.yyb"

      - action: click_element
        text: "我已阅读并同意"

      - action: click_element
        text: "登录"

      - action: wait_for_element
        text: "同意"
        timeout: 5

      - action: click_element
        text: "同意"

      - action: wait_for_element
        resource_id: "close_iv"
        timeout: 10

      - action: click_element
        resource_id: "close_iv"

      - action: screenshot
        name: "login_complete"
"""

import yaml
import os
import sys
import time
import json
import argparse

# 支持两种导入方式：作为包导入 / 直接运行
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from .adb_controller import ADBController
    from .config_loader import load_config
except ImportError:
    from adb_controller import ADBController
    from config_loader import load_config


class FlowRunner:
    """流程执行引擎"""

    def __init__(self, serial: str = "", output_dir: str = "outputs"):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
        self.adb = ADBController(serial=serial, screenshot_dir=os.path.join(output_dir, "screenshots"))
        self.results = []

    def run_file(self, flow_path: str, variables: dict = None) -> dict:
        """执行YAML流程文件"""
        with open(flow_path, "r", encoding="utf-8") as f:
            flow = yaml.safe_load(f)

        flow_name = flow.get("name", os.path.basename(flow_path))
        steps = flow.get("steps", [])

        print(f"\n{'='*60}")
        print(f"开始执行流程: {flow_name}")
        print(f"步骤数: {len(steps)}")
        print(f"{'='*60}\n")

        start_time = time.time()
        passed = 0
        failed = 0

        for i, step in enumerate(steps):
            step_num = i + 1
            action = step.get("action", "")
            print(f"\n--- Step {step_num}/{len(steps)}: {action} ---")

            # 替换变量
            if variables:
                step = self._inject_variables(step, variables)

            try:
                success = self._execute_step(step)
                if success:
                    passed += 1
                else:
                    failed += 1
                    if step.get("required", True) is False:
                        print(f"  (非必需步骤，继续)")
                    else:
                        print(f"  ⚠ 必需步骤失败!")
                        # 截图保留证据
                        self.adb.screenshot(f"failed_step_{step_num}.png")
            except Exception as e:
                failed += 1
                print(f"  ❌ 异常: {e}")
                self.adb.screenshot(f"error_step_{step_num}.png")

            self.results.append({
                "step": step_num,
                "action": action,
                "success": success if "success" in dir() else False,
                "detail": step.get("text", "") or step.get("resource_id", "") or step.get("name", ""),
            })

        elapsed = time.time() - start_time

        # 保存日志
        log_path = os.path.join(self.output_dir, f"flow_log_{int(time.time())}.json")
        self.adb.save_log(log_path)

        summary = {
            "flow_name": flow_name,
            "total_steps": len(steps),
            "passed": passed,
            "failed": failed,
            "elapsed_seconds": round(elapsed, 1),
            "log_file": log_path,
        }

        print(f"\n{'='*60}")
        print(f"流程完成: {flow_name}")
        print(f"通过 {passed}/{len(steps)}, 失败 {failed}, 耗时 {elapsed:.1f}s")
        print(f"日志: {log_path}")
        print(f"{'='*60}")

        return summary

    def _inject_variables(self, step: dict, variables: dict) -> dict:
        """将变量注入步骤参数"""
        result = {}
        for key, value in step.items():
            if isinstance(value, str):
                for var_name, var_value in variables.items():
                    value = value.replace(f"${{{var_name}}}", str(var_value))
            result[key] = value
        return result

    def _execute_step(self, step: dict) -> bool:
        """执行单个步骤"""
        action = step.get("action", "")

        if action == "tap":
            return self.adb.tap(step["x"], step["y"])

        elif action == "click_element":
            return self.adb.click_element(
                text=step.get("text", ""),
                resource_id=step.get("resource_id", ""),
                content_desc=step.get("content_desc", ""),
                exact=step.get("exact", False),
            )

        elif action == "swipe":
            return self.adb.swipe(
                step["x1"], step["y1"], step["x2"], step["y2"],
                step.get("duration", 300),
            )

        elif action == "scroll_down":
            self.adb.scroll_down(step.get("distance", 500))
            return True

        elif action == "scroll_up":
            self.adb.scroll_up(step.get("distance", 500))
            return True

        elif action == "screenshot":
            name = step.get("name", "")
            self.adb.screenshot(f"{name}.png" if name else "")
            return True

        elif action == "wait":
            self.adb.wait(step.get("seconds", 1))
            return True

        elif action == "wait_for_element":
            return self.adb.wait_for_element(
                text=step.get("text", ""),
                resource_id=step.get("resource_id", ""),
                content_desc=step.get("content_desc", ""),
                timeout=step.get("timeout", 10),
            )

        elif action == "verify_element":
            """验证元素存在（不点击），用于检测流程"""
            found = self.adb.is_element_present(
                text=step.get("text", ""),
                resource_id=step.get("resource_id", ""),
                content_desc=step.get("content_desc", ""),
            )
            label = step.get("text", "") or step.get("resource_id", "")
            if not found:
                self.adb._log("验证", f"❌ 未找到 '{label}'", success=False)
                self.adb.screenshot(f"verify_fail_{label}.png")
            else:
                self.adb._log("验证", f"✅ 找到 '{label}'", success=True)
            return found

        elif action == "verify_text_matches":
            """验证屏幕上的文字与预期一致（用于内容校验）"""
            expected = step.get("expected", "")
            elem = self.adb.find_element(text=expected)
            if elem:
                self.adb._log("文字校验", f"✅ '{expected}' 存在", success=True)
                return True
            else:
                self.adb._log("文字校验", f"❌ '{expected}' 不存在", success=False)
                self.adb.screenshot(f"text_mismatch_{expected}.png")
                return False

        elif action == "input_text":
            return self.adb.input_text(step.get("text", ""))

        elif action == "press_back":
            return self.adb.press_back()

        elif action == "press_home":
            return self.adb.press_home()

        elif action == "press_enter":
            return self.adb.press_enter()

        elif action == "launch_app":
            return self.adb.launch_app(
                step.get("package", ""),
                step.get("activity", ""),
            )

        elif action == "dump_ui":
            """保存当前UI结构用于分析"""
            elements = self.adb.dump_ui()
            dump_path = os.path.join(self.output_dir, "screenshots", f"ui_dump_{int(time.time())}.txt")
            with open(dump_path, "w", encoding="utf-8") as f:
                for elem in elements:
                    if elem.text or elem.resource_id or elem.clickable:
                        label = elem.text or elem.resource_id or elem.content_desc
                        f.write(f"{label} | center={elem.center} | clickable={elem.clickable}\n")
            print(f"  UI dump 保存到: {dump_path}")
            return True

        elif action == "list_clickable":
            """列出当前页面所有可点击元素（调试用）"""
            elements = self.adb.dump_ui()
            print("  当前页面可点击元素:")
            for elem in elements:
                if elem.clickable:
                    label = elem.text or elem.resource_id or elem.content_desc or "未命名"
                    print(f"    '{label}' at {elem.center}")
            return True

        else:
            print(f"  ⚠ 未知操作: {action}")
            return False


# ============================================================
# 命令行入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="英语宝检测流程执行引擎")
    parser.add_argument("flow", help="YAML流程文件路径")
    parser.add_argument("--serial", default="SKSCIF4T7PFMQS5X", help="设备序列号")
    parser.add_argument("--output", default="outputs", help="输出目录")
    parser.add_argument("--var", action="append", default=[], help="变量 key=value")

    args = parser.parse_args()

    # 解析变量
    variables = {}
    for v in args.var:
        if "=" in v:
            k, val = v.split("=", 1)
            variables[k] = val

    runner = FlowRunner(serial=args.serial, output_dir=args.output)
    summary = runner.run_file(args.flow, variables)

    # 退出码
    sys.exit(0 if summary["failed"] == 0 else 1)


if __name__ == "__main__":
    main()
