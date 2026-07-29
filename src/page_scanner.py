"""
src/page_scanner.py — APP页面扫描工具
负责人：B

用法：手机连上，在APP的每个关键页面运行一次扫描。
扫描结果自动存入 data/app_page_map.json，供 universe_navigator 使用。

运行方式:
  python3 src/page_scanner.py                     # 扫描当前页面
  python3 src/page_scanner.py --name "unit_list"  # 扫描并命名
  python3 src/page_scanner.py --reset             # 清空地图
  python3 src/page_scanner.py --print             # 打印当前地图
"""

import sys, json, time, argparse
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).parent.parent
MAP_FILE = PROJECT_ROOT / "data" / "app_page_map.json"


def scan_current_page(name: str = None, adb=None) -> dict:
    """扫描当前APP页面，返回所有可见UI元素"""
    if adb is None:
        sys.path.insert(0, str(PROJECT_ROOT))
        from src.adb_controller import ADBController
        adb = ADBController(serial=None, screenshot_dir=str(PROJECT_ROOT / "screenshots"))

    elements = adb.dump_ui()
    visible = []
    for e in elements:
        t = (e.text or '').strip()
        if t and 50 < e.center[1] < 2200:
            visible.append({
                "text": t,
                "center": list(e.center),
                "clickable": e.clickable,
                "bounds": list(e.bounds),
                "class": e.cls or "",
            })

    # 截图
    shot_name = (name or "scan") + ".png"
    adb.screenshot(shot_name)

    info = {
        "name": name or "unknown",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elements": visible,
        "element_count": len(visible),
        "fingerprint_texts": [v["text"] for v in visible[:20]],
        "screenshot": shot_name,
    }

    # 打印摘要
    print(f"\n📱 页面扫描: {info['name']}")
    print(f"   元素数: {len(visible)}")
    print(f"   关键文字: {info['fingerprint_texts'][:10]}")
    print(f"   截图: screenshots/{shot_name}")

    return info


def save_to_map(page_info: dict):
    """保存到页面地图"""
    app_map = {}
    if MAP_FILE.exists():
        with open(MAP_FILE, "r", encoding="utf-8") as f:
            app_map = json.load(f)

    name = page_info["name"]
    app_map[name] = page_info

    MAP_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(MAP_FILE, "w", encoding="utf-8") as f:
        json.dump(app_map, f, ensure_ascii=False, indent=2)
    print(f"   ✅ 已保存到 {MAP_FILE}")


def print_map():
    if not MAP_FILE.exists():
        print("暂无地图文件")
        return
    with open(MAP_FILE, "r", encoding="utf-8") as f:
        app_map = json.load(f)
    print(f"\n📍 APP页面地图 ({len(app_map)} 页):")
    for name, info in app_map.items():
        fps = info.get("fingerprint_texts", [])[:5]
        print(f"  [{name}] {fps}")


# ============================================
# 命令行接口
# ============================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="英语宝APP页面扫描工具")
    parser.add_argument("--name", "-n", help="页面名称，如 unit_list / stage_select")
    parser.add_argument("--reset", action="store_true", help="清空页面地图")
    parser.add_argument("--print", "-p", action="store_true", help="打印当前地图")
    args = parser.parse_args()

    if args.reset:
        if MAP_FILE.exists():
            MAP_FILE.unlink()
        print("地图已清空")
        sys.exit(0)

    if getattr(args, "print"):
        print_map()
        sys.exit(0)

    sys.path.insert(0, str(PROJECT_ROOT))
    from src.adb_controller import ADBController

    adb = ADBController(serial=None, screenshot_dir=str(PROJECT_ROOT / "screenshots"))

    info = scan_current_page(args.name, adb)
    save_to_map(info)
