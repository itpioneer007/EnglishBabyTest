"""教材分册扫描（新旧分开）— 独立命令行入口

用法（手机连着 adb）：
    python scripts/scan_textbook_list.py
    python scripts/scan_textbook_list.py --out outputs/web/textbook_list.json
    python scripts/scan_textbook_list.py --expect-old 8

流程（2026-09-08 用户指定规格）：
  ① 进入课本切换页面
  ② 循环：读取当前页面所有文本控件 → 提取年级分册 → 滑动上翻
  ③ 判断：滑动前后没有新增课本条目 → 停止滚动
  ④ 对 book_list 做去重
  ⑤ 输出 json
  ⑥ 湘鲁旧版校验：预期 8 套分册，数量不对添加 warning

限制：
  ❌ 不用多张截图 OCR   ❌ 不读取出版社   ❌ 不图像识别封面
  ✅ 全部读取 APP 控件文本，滚动遍历列表，只解析文字

★ 新旧分开：页面上方【新教材】区 → new_books；版本分组标题下方 → old_books。
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    ap = argparse.ArgumentParser(description="扫描英语宝「切换课本」页的教材分册（新旧分开）")
    ap.add_argument("--out", default="outputs/web/textbook_list.json",
                    help="输出 json 路径（默认 outputs/web/textbook_list.json）")
    ap.add_argument("--expect-old", type=int, default=8,
                    help="湘鲁旧版预期分册数（默认 8）")
    ap.add_argument("--rounds", type=int, default=15, help="最大滚动轮数（默认 15）")
    args = ap.parse_args()

    try:
        import uiautomator2 as u2
    except ImportError:
        print("❌ 缺少 uiautomator2，请先 pip install uiautomator2")
        return 1

    print("=" * 56)
    print("  教材分册扫描（新旧分开）")
    print("=" * 56)

    try:
        d = u2.connect()
        if not d.info:
            print("❌ 设备连接失败")
            return 1
    except Exception as e:
        print(f"❌ 设备连接异常: {e}")
        return 1

    from common.setup import scan_textbook_list

    result = scan_textbook_list(d, max_rounds=args.rounds, expect_old=args.expect_old)

    # ⑤ 输出 json
    print()
    print(f"  【新教材】 {result['new_count']} 套: "
          f"{[b['grade'] for b in result['new_books']]}")
    print(f"  【旧教材】 {result['old_count']} 套: "
          f"{[b['grade'] for b in result['old_books']]}")
    print(f"  版本标题:   {result['version_titles']}")
    print(f"  滚动轮数:   {result['rounds']}")
    if result["warnings"]:
        print()
        for w in result["warnings"]:
            print(f"  ⚠ {w}")

    # 落盘
    out_path = args.out
    try:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print()
        print(f"  ✅ 已写出: {out_path}")
    except Exception as e:
        print(f"  ⚠ 写出失败: {e}")

    print()
    print("---- JSON ----")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
