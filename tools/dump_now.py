# -*- coding: utf-8 -*-
"""dump 当前设备页面 XML 到文件，供诊断题型识别问题用。

用法:
    python tools/dump_now.py [输出文件名]
默认输出: tmp_gen/dump_now.xml（同目录另存 dump_now.txt = 文本清单）
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import uiautomator2 as u2  # noqa: E402


def main():
    out_name = sys.argv[1] if len(sys.argv) > 1 else "dump_now"
    outdir = os.path.join(ROOT, "tmp_gen")
    os.makedirs(outdir, exist_ok=True)

    d = u2.connect()
    info = d.info
    xml = d.dump_hierarchy()

    xml_path = os.path.join(outdir, out_name + ".xml")
    with open(xml_path, "w", encoding="utf-8") as f:
        f.write(xml)

    lines = []
    lines.append("screenOn=%s 当前Activity=%s 分辨率=%sx%s" % (
        info.get("screenOn"), info.get("currentPackageName"),
        info.get("displayWidth"), info.get("displayHeight")))
    lines.append("")
    lines.append("─" * 60)
    lines.append("节点清单（有 text / resource-id / clickable 的）")
    lines.append("─" * 60)

    import re
    for m in re.finditer(r"<node\b[^>]*>", xml):
        tag = m.group(0)
        rid = re.search(r'resource-id="([^"]*)"', tag)
        txt = re.search(r'text="([^"]*)"', tag)
        cls = re.search(r'class="([^"]*)"', tag)
        bm = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', tag)
        r = rid.group(1) if rid else ""
        t = txt.group(1) if txt else ""
        c = cls.group(1) if cls else ""
        b = bm.group(0) if bm else ""
        clk = 'clickable="true"' in tag
        if not (t or r or clk):
            continue
        lines.append("text=%-28s rid=%-34s cls=%-34s clk=%-5s %s" % (
            repr(t), r, c.split(".")[-1], clk, b))

    # 判定探针
    lines.append("")
    lines.append("─" * 60)
    lines.append("题型判定探针")
    lines.append("─" * 60)
    probes = {
        "有 EditText": 'class="android.widget.EditText"' in xml,
        "有 select_tv": "select_tv" in xml,
        "有 select_btn": "select_btn" in xml,
        "有大写字母选项(T/F/A-E)": bool(re.search(r'text="[TFABCDE]"', xml)),
        "含'选词'": "选词" in xml,
        "含'选择正确的单词'": "选择正确的单词" in xml,
        "含'补全'": "补全" in xml,
        "含'填空'": "填空" in xml,
    }
    for k, v in probes.items():
        lines.append("  %-28s %s" % (k, v))

    lines.append("")
    lines.append("题目文本(前20条 text):")
    texts = [t for t in re.findall(r'text="([^"]*)"', xml) if t.strip()]
    for t in texts[:20]:
        lines.append("   " + t)

    txt_path = os.path.join(outdir, out_name + ".txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print("xml ->", xml_path)
    print("txt ->", txt_path)


if __name__ == "__main__":
    main()
