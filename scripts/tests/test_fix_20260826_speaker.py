# -*- coding: utf-8 -*-
"""扬声器内容获取测试（2026-08-26 真机验证成果固化）

背景：用户要"获取扬声器播放的单词内容并与脚本 recording 对比"。
真机发现两种可靠来源（无需 ASR 也能拿到！）：
  A. 听音选释义题：答错 → 反馈页「文字解析 / 听力内容：new」→ analysis_tv 字段
  B. 跟读题：页面直接显示英文单词（如 new / adj. 新来的；新的）
     → 提取英文词 + 过滤词性标注(adj/n/v) 与按钮词

运行: python scripts/tests/test_fix_20260826_speaker.py
"""
import sys, re, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "common"))

from common.asr import compare_against_script


def _extract_speaker_from_feedback(xml_text):
    """与 scripts/modules/巧记单词.py 的 _extract_speaker_from_feedback 一致"""
    m = re.search(r'text="听力内容[:：]\s*([A-Za-z0-9\s\'\-]+)', xml_text)
    if m and len(m.group(1).strip()) >= 1:
        return m.group(1).strip().lower()
    m2 = re.search(r'analysis_tv[^>]*text="([^"]*)"', xml_text)
    if m2:
        mm = re.search(r'听力内容[:：]\s*([A-Za-z0-9\s\'\-]+)', m2.group(1))
        if mm and len(mm.group(1).strip()) >= 1:
            return mm.group(1).strip().lower()
    return ""


def _speaker_word_of(xml_text):
    """与 scripts/modules/巧记单词.py 的 _speaker_word_of 一致"""
    _en = re.findall(r"[A-Za-z]{2,}", " ".join(
        t for t in re.findall(r'text="([^"]+)"', xml_text)))
    _f = ("check", "next", "submit", "listen", "original", "play",
          "skip", "retry", "again", "finish", "complete",
          "adj", "n", "v", "adv", "prep", "conj", "pron", "num", "art")
    _c = [w for w in _en if w.lower() not in _f and len(w) >= 2
          and not w.lower().isdigit()]
    return (_c[-1].lower() if _c else "")


passed = 0
failed = 0
def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ✅ {name}")
    else:
        failed += 1
        print(f"  ❌ {name} | {detail}")


print("=== A. 听音选释义题（答错反馈页 听力内容字段）===")
fb1 = '<node text="听力内容：new&#10;" resource-id="com.dinoenglish.yyb:id/analysis_tv"/>'
spk = _extract_speaker_from_feedback(fb1)
check("反馈页提取 new", spk == "new", repr(spk))
check("对比脚本 new → 一致", compare_against_script(spk, "new")["consistent"] is True,
      compare_against_script(spk, "new")["reason"])
check("对比脚本 year → 不符", compare_against_script(spk, "year")["consistent"] is False,
      compare_against_script(spk, "year")["reason"])
fb2 = '<node text="听力内容：My father is a worker.&#10;"/>'
check("句子听力内容提取", _extract_speaker_from_feedback(fb2) == "my father is a worker",
      repr(_extract_speaker_from_feedback(fb2)))
fb3 = '<node resource-id="com.dinoenglish.yyb:id/analysis_tv" text="听力内容：listen&#10;"/>'
check("analysis_tv 属性内提取", _extract_speaker_from_feedback(fb3) == "listen",
      repr(_extract_speaker_from_feedback(fb3)))

print()
print("=== B. 跟读题（页面直接显示单词）===")
gd1 = ('<node text="听录音，跟读单词。"/><node text="new"/>'
       '<node text="adj. 新来的；新的"/><node text="原音"/><node text="点击录音"/>')
spk2 = _speaker_word_of(gd1)
check("跟读题提取 new（过滤adj）", spk2 == "new", repr(spk2))
check("对比脚本 new → 一致", compare_against_script(spk2, "new")["consistent"] is True)
gd2 = ('<node text="听录音，跟读单词。"/><node text="year"/>'
       '<node text="n. 年；岁"/><node text="原音"/>')
check("跟读题 year", _speaker_word_of(gd2) == "year", repr(_speaker_word_of(gd2)))

print()
print("=== C. 纯听音选释义答题页（无英文，需反馈页/ASR）===")
p1 = ('<node text="听录音，选择与录音内容相符的释义。"/>'
      '<node text="旧的"/><node text="A"/><node text="新来的；新的"/>')
check("答题页提取为空（正常）", _speaker_word_of(p1) == "", repr(_speaker_word_of(p1)))

print()
print("=== D. 证据卡消息格式（web_server 正则兼容）===")
# ★ 2026-09-20：同步 web_server 的新契约式正则（前缀定位题号 + 消息含"检查"）。
#   旧写法把题干写死成"恰好一个全角括号组"，题干自带右括号时整题证据被丢弃。
_ws_re = re.compile(r"\s*(?:第(\d+)大题·)?第(\d+)(?:题|小题)")


def _ws_match(msg):
    m = _ws_re.match(msg)
    return bool(m and "检查" in msg)


check("第N题 检查（扬声器内容）格式匹配",
      _ws_match("  第3题 检查（扬声器内容）"))
check("第N题 完整性检查 格式匹配",
      _ws_match("  第3题 完整性检查"))
check("第N大题·第M小题（题干）完整性检查 匹配",
      _ws_match("  第1大题·第2小题（句型提示：x）完整性检查"))
check("题干含嵌套全角括号 仍匹配（回归）",
      _ws_match("  第3大题·第1小题（第11题（仿照例句，说一说。））完整性检查"))
check("答错截图 不被误判为完整性检查",
      not _ws_match("  第2题 答错截图"))

print()
print(f"结果: {passed} 通过, {failed} 失败")
sys.exit(1 if failed else 0)
