#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
英语宝模块检测 - 主入口

用法:
    python main.py                          # 交互式选择流程
    python main.py login                    # 运行登录流程
    python main.py flow flows/login.yaml    # 运行指定流程
    python main.py list                     # 列出所有可用流程
    python main.py devices                  # 列出已连接的ADB设备
    python main.py dump                     # dump当前页面UI元素

在 IDE 中:
    直接运行此文件，或在 .vscode/launch.json 中配置。
"""

import os
import sys
import subprocess
import argparse

# 添加 src 到路径
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

from config_loader import load_config
from adb_controller import ADBController
from flow_runner import FlowRunner


def cmd_devices():
    """列出已连接的ADB设备"""
    print("=== 已连接的ADB设备 ===")
    result = subprocess.run(["adb", "devices", "-l"], capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    print(result.stdout)
    if "no devices" in result.stdout.lower() or len(result.stdout.strip().split("\n")) <= 1:
        print("未检测到设备，请检查:")
        print("  1. 手机已通过USB连接电脑")
        print("  2. 手机已开启USB调试")
        print("  3. 手机上已授权调试")


def cmd_list_flows():
    """列出所有可用流程"""
    flows_dir = os.path.join(PROJECT_ROOT, "flows")
    print("=== 可用检测流程 ===")
    if not os.path.exists(flows_dir):
        print("flows/ 目录不存在")
        return

    flows = [f for f in os.listdir(flows_dir) if f.endswith(".yaml") or f.endswith(".yml")]
    if not flows:
        print("未找到流程文件")
        return

    for f in sorted(flows):
        # 读取流程名称
        path = os.path.join(flows_dir, f)
        try:
            import yaml
            with open(path, "r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
            name = data.get("name", f)
            desc = data.get("description", "")
            print(f"  {f}")
            print(f"    名称: {name}")
            if desc:
                print(f"    说明: {desc}")
        except Exception:
            print(f"  {f} (读取失败)")
        print()


def cmd_dump():
    """dump当前页面UI元素"""
    config = load_config()
    adb = ADBController(
        serial=config.device.serial,
        screenshot_dir=config.output.screenshot_dir,
    )

    print("=== 当前页面可点击元素 ===")
    elements = adb.dump_ui()
    for elem in elements:
        if elem.clickable or elem.text:
            label = elem.text or elem.resource_id or elem.content_desc or "未命名"
            print(f"  '{label}' at {elem.center} clickable={elem.clickable}")

    print(f"\n共 {len(elements)} 个元素")
    adb.screenshot("dump_screenshot.png")
    print("截图已保存到 outputs/screenshots/")


def cmd_run_flow(flow_path: str):
    """运行指定流程"""
    # 如果是简写（如 "login"），自动补全路径
    if not os.path.isabs(flow_path) and not os.path.exists(flow_path):
        candidate = os.path.join(PROJECT_ROOT, "flows", flow_path)
        if not candidate.endswith(".yaml"):
            candidate += ".yaml"
        if os.path.exists(candidate):
            flow_path = candidate

    if not os.path.exists(flow_path):
        print(f"❌ 流程文件不存在: {flow_path}")
        print("可用流程:")
        cmd_list_flows()
        return 1

    config = load_config()
    output_dir = os.path.join(PROJECT_ROOT, config.output.dir)

    runner = FlowRunner(
        serial=config.device.serial,
        output_dir=output_dir,
    )
    summary = runner.run_file(flow_path)

    return 0 if summary["failed"] == 0 else 1


def cmd_interactive():
    """交互式选择流程"""
    print("=" * 50)
    print("  英语宝模块检测系统")
    print("=" * 50)
    print()

    flows_dir = os.path.join(PROJECT_ROOT, "flows")
    flows = []
    if os.path.exists(flows_dir):
        flows = [f for f in os.listdir(flows_dir) if f.endswith(".yaml")]

    if not flows:
        print("未找到流程文件，请在 flows/ 目录下创建。")
        return

    print("可用操作:")
    print("  0. 查看已连接设备")
    print("  1. dump当前页面UI")
    for i, f in enumerate(flows):
        print(f"  {i + 2}. 运行 {f}")
    print(f"  {len(flows) + 2}. 退出")
    print()

    choice = input("请选择: ").strip()
    try:
        choice = int(choice)
    except ValueError:
        print("无效输入")
        return

    if choice == 0:
        cmd_devices()
    elif choice == 1:
        cmd_dump()
    elif 2 <= choice <= len(flows) + 1:
        flow_file = flows[choice - 2]
        cmd_run_flow(os.path.join(flows_dir, flow_file))
    elif choice == len(flows) + 2:
        return
    else:
        print("无效选择")


def main():
    parser = argparse.ArgumentParser(
        description="英语宝模块检测系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python main.py              交互式选择
  python main.py login        运行登录流程
  python main.py flow flows/login.yaml   运行指定流程
  python main.py list         列出所有流程
  python main.py devices      查看已连接设备
  python main.py dump         dump当前页面UI
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="子命令")

    subparsers.add_parser("login", help="运行登录流程")
    subparsers.add_parser("list", help="列出所有可用流程")
    subparsers.add_parser("devices", help="查看已连接的ADB设备")
    subparsers.add_parser("dump", help="dump当前页面UI元素")

    flow_parser = subparsers.add_parser("flow", help="运行指定流程文件")
    flow_parser.add_argument("path", help="流程文件路径 (如 flows/login.yaml 或 login)")

    args = parser.parse_args()

    if args.command is None:
        cmd_interactive()
    elif args.command == "login":
        sys.exit(cmd_run_flow("login"))
    elif args.command == "list":
        cmd_list_flows()
    elif args.command == "devices":
        cmd_devices()
    elif args.command == "dump":
        cmd_dump()
    elif args.command == "flow":
        sys.exit(cmd_run_flow(args.path))


if __name__ == "__main__":
    main()
