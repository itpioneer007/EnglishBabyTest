# -*- coding: utf-8 -*-
"""探针：学习「首字母+中文提示 → 选字母补全单词」题型的真实交互方式。

当前设备停在 unitcheck 一道此类题上（14/40）。
步骤：
  1. dump 解析 空位(select_tv) / 已给首字母(question_title_tv) / 字母块(select_btn) / 中文提示
  2. 直接点目标字母块 → 看空位是否被填
  3. 若没填 → 先点空位激活，再点字母块
  4. 输出每步 dump 变化，供写 handler 用

只读 + 少量点击，不改动任何工程文件。
"""
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import uiautomator2 as u2  # noqa: E402

OUT = os.path.join(ROOT, "tmp_gen", "probe_letter_fill.txt")
log = []


def w(*a):
    s = " ".join(str(x) for x in a)
    print(s)
    log.append(s)


def nodes(xml):
    out = []
    for m in re.finditer(r"<node\b[^>]*>", xml):
        tag = m.group(0)
        rid = re.search(r'resource-id="([^"]*)"', tag)
        txt = re.search(r'text="([^"]*)"', tag)
        cls = re.search(r'class="([^"]*)"', tag)
        bm = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', tag)
        if not (rid and bm):
            continue
        out.append({
            "rid": (rid.group(1) or "").split("/")[-1],
            "text": txt.group(1) if txt else "",
            "cls": (cls.group(1) or "").split(".")[-1] if cls else "",
            "b": tuple(map(int, bm.groups())),
            "clk": 'clickable="true"' in tag,
        })
    return out


def scene(xml):
    ns = nodes(xml)
    slots = [n for n in ns if n["rid"] == "select_tv"]
    tiles = [n for n in ns if n["rid"] == "select_btn"]
    prefix = [n for n in ns if n["rid"] == "question_title_tv" and n["text"].strip()
              and re.fullmatch(r"[A-Za-z]+", n["text"].strip())]
    alltxt = "".join(re.findall(r'text="([^"]*)"', xml))
    hint = re.search(r"\[(.{0,60}?)\]", alltxt)
    return slots, tiles, prefix, (hint.group(1) if hint else "")


def ctr(b):
    return ((b[0] + b[2]) // 2, (b[1] + b[3]) // 2)


def main():
    d = u2.connect()
    xml = d.dump_hierarchy()
    slots, tiles, prefix, hint = scene(xml)
    w("=" * 70)
    w("初始页面")
    w("  空位 select_tv :", [(s["text"], s["b"]) for s in slots])
    w("  字母块 select_btn:", [t["text"] for t in tiles])
    w("  字母块 y 区间   :", [t["b"][1] for t in tiles])
    w("  已给首字母      :", [p["text"] for p in prefix])
    w("  中文提示        :", repr(hint))
    w("  期望单词 by → 待补字母 y")

    target = next((t for t in tiles if t["text"].strip().lower() == "y"), None)
    if not target:
        w("!! 页面没有 y 字母块，终止")
        return
    tx, ty = ctr(target["b"])

    def snap(tag):
        x = d.dump_hierarchy()
        s2, _, _, _ = scene(x)
        w("   [%s] 空位状态: %s" % (tag, [(s["text"], s["cls"]) for s in s2]))
        return x

    # ── 实验1：直接点字母块 ──
    w("-" * 70)
    w("实验1：直接点字母块 y @(%d,%d)" % (tx, ty))
    d.click(tx, ty)
    time.sleep(1.2)
    x1 = snap("点后")
    s1, _, _, _ = scene(x1)
    filled = any(s["text"].strip() for s in s1)
    w("  → 空位被填了吗:", filled)

    if not filled:
        # ── 实验2：先点空位激活，再点字母块 ──
        w("-" * 70)
        w("实验2：先点空位激活，再点字母块 y")
        s2, _, _, _ = scene(d.dump_hierarchy())
        if s2:
            sx, sy = ctr(s2[0]["b"])
            d.click(sx, sy)
            w("  → 点空位 @(%d,%d)" % (sx, sy))
            time.sleep(1.0)
            snap("激活后")
            d.click(tx, ty)
            time.sleep(1.2)
            x2 = snap("再点字母后")
            s3, _, _, _ = scene(x2)
            w("  → 空位被填了吗:", any(s["text"].strip() for s in s3))

    # 全页文字，看是否出现"检查/下一题/答对/答错"
    xf = d.dump_hierarchy()
    w("-" * 70)
    w("页面按钮类文字:", [t for t in re.findall(r'text="([^"]*)"', xf)
                        if t.strip() in ("检查", "下一题", "确定", "继续答题", "查看报告")])
    w("题号:", re.findall(r'text="(\d+\s*/\s*\d+)"', xf))

    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(log))


if __name__ == "__main__":
    main()
