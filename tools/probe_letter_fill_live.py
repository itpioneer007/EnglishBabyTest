# -*- coding: utf-8 -*-
"""只读探针：在真机当前页验证「字母块补全单词」的解析 + 单词推断（不点击、不答题）。

当前设备停在这类题上（15/40，听录音型）。本探针只做：
  1. uiautomator dump → question_types.parse_letter_fill 解析
  2. 打印 首字母/空位数/字母块/中文提示/题干
  3. 调 engine._letter_fill_word（走真实 LLM）推断单词，并核对
     "单词长度 = 首字母 + 空位数" 与 "所需字母都在字母块里"
不点任何东西 → 不影响答题状态。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import uiautomator2 as u2  # noqa: E402
from question_types import parse_letter_fill, _has_letter_tiles, detect_question_type  # noqa: E402
import engine  # noqa: E402

OUT = os.path.join(ROOT, "tmp_gen", "probe_letter_live.txt")
log = []


def w(*a):
    s = " ".join(str(x) for x in a)
    print(s)
    log.append(s)


def main():
    d = u2.connect()
    xml = d.dump_hierarchy()
    info = parse_letter_fill(xml)
    w("题型检测:", detect_question_type(xml), "| _has_letter_tiles =", _has_letter_tiles(xml))
    w("题干:", repr(info["cap"]))
    w("已给首字母:", repr(info["prefix"]))
    w("空位数:", len(info["slots"]), [s["text"] for s in info["slots"]])
    w("字母块:", [t["text"] for t in info["tiles"]])
    w("中文提示:", repr(info["hint"]))
    n_slot = len(info["slots"])
    pool = [t["text"] for t in info["tiles"]]
    word, src = engine._letter_fill_word(info["prefix"], info["hint"], pool, n_slot=n_slot)
    w("LLM 推断:", repr(word), "| 来源:", src)
    if word:
        need = word[len(info["prefix"]):]
        w("需补字母:", list(need), "| 长度校验:",
          len(word) == len(info["prefix"]) + n_slot,
          "| 字母池校验:", all(c in [p.lower() for p in pool] for c in need))
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(log))


if __name__ == "__main__":
    main()
