# -*- coding: utf-8 -*-
"""校验一次复跑产出的解析脚本 docx 与图片题截图。

检查项：
  1. gen_scripts/ 下最新 docx（应有本次运行时间戳）
  2. docx 内是否含「位置 / 题干 / 选项 / 答案 / 知识点」结构
  3. 图片题标记「［图片题…需人工复核］」与「图片内容」行是否出现
  4. screenshots/script_imgs/ 是否有新截图
"""
import glob
import os
import sys
import time

ROOT = r"C:\Users\19507\WorkBuddy\安全处理空间\英语宝模块检测"
GEN = os.path.join(ROOT, "gen_scripts")
IMGS = os.path.join(ROOT, "screenshots", "script_imgs")


def newest(pat, limit=1):
    files = glob.glob(pat)
    files.sort(key=os.path.getmtime, reverse=True)
    return files[:limit]


def main():
    print("=" * 62)
    print("① gen_scripts/ 最新产出")
    print("=" * 62)
    cands = newest(os.path.join(GEN, "*.docx"), 6)
    if not cands:
        print("  (无 docx)")
        return 1
    for f in cands:
        print("  ", time.strftime("%m-%d %H:%M:%S", time.localtime(os.path.getmtime(f))),
              "|", os.path.basename(f), "|", os.path.getsize(f), "B")

    target = cands[0]
    print("\n" + "=" * 62)
    print(f"② 解析最新脚本内容: {os.path.basename(target)}")
    print("=" * 62)
    try:
        from docx import Document
    except ImportError:
        print("  python-docx 未安装，跳过内容解析")
        return 2

    doc = Document(target)
    paras = [p.text.strip() for p in doc.paragraphs if p.text and p.text.strip()]
    print(f"  段落数: {len(paras)}")

    kind = {"位置": 0, "题干": 0, "选项": 0, "答案": 0, "知识点": 0, "图片": 0, "待人工": 0}
    img_marks = []
    for t in paras:
        if t.startswith("位置：") or "位置：" in t[:4]:
            kind["位置"] += 1
        if "题干：" in t:
            kind["题干"] += 1
        if "选项：" in t:
            kind["选项"] += 1
        if "答案：" in t or "正确答案：" in t:
            kind["答案"] += 1
        if "知识点：" in t:
            kind["知识点"] += 1
        if "图片内容" in t or "图片题" in t:
            kind["图片"] += 1
            img_marks.append(t[:120])
        if "人工复核" in t:
            kind["待人工"] += 1
    for k, v in kind.items():
        print(f"  {k}: {v}")

    print("\n  ---- 前 40 行正文 ----")
    for t in paras[:40]:
        print("   ", t[:140])
    if img_marks:
        print("\n  ---- 图片题相关行 ----")
        for t in img_marks[:15]:
            print("   ", t)

    print("\n" + "=" * 62)
    print("③ screenshots/script_imgs/")
    print("=" * 62)
    if os.path.isdir(IMGS):
        fs = sorted(glob.glob(os.path.join(IMGS, "*")), key=os.path.getmtime, reverse=True)
        print(f"  文件数: {len(fs)}")
        for f in fs[:15]:
            print("  ", time.strftime("%m-%d %H:%M:%S", time.localtime(os.path.getmtime(f))),
                  os.path.basename(f), os.path.getsize(f), "B")
    else:
        print("  目录不存在")

    # 判定
    print("\n" + "=" * 62)
    print("④ 结论")
    print("=" * 62)
    ok = kind["位置"] > 0 and kind["题干"] > 0
    print("  脚本结构完整（位置+题干）:", "✅" if ok else "❌")
    print("  是否包含图片题条目:", "✅ 有" if kind["图片"] else "— 本次无图片题条目")
    return 0 if ok else 3


if __name__ == "__main__":
    sys.exit(main())
