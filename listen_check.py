"""
listen_check.py — 听力转写 ↔ 界面题干/选项 比对
================================================
把 ASR 转写出来的「实际播放的听力内容」和界面上提取到的「题干 + 选项文字」做比对，
给出「疑似错误」线索。

设计原则：保守优先，宁可漏报不可误报。
  - 纯规则启发式，不依赖大模型（快、可离线、可解释）。
  - 只输出「线索」，最终是否真的出错由人工/后续大模型复核判断。

对外接口：
  compare_transcript_to_ui(transcript, stem_text, option_texts) -> dict
     返回 {
        verdict: "ok" | "suspect",     # 是否疑似不符
        coverage: float,              # 题干/选项内容词在转写中的覆盖率(0~1)
        matched: [..],                # 双方都出现的词
        missing: [..],                # 界面有、但转写里没出现的词（重点看）
        extra: [..],                  # 转写有、但界面没出现的词
        note: str,                    # 人读的结论
      }
"""
import json
import re

_CJK = re.compile(r"[\u4e00-\u9fff]")
_ENG = re.compile(r"[a-zA-Z]+")


def _tokenize(text):
    """英文按词(小写)，中文按单字；返回 token 集合。"""
    if not text:
        return set()
    toks = set()
    for w in _ENG.findall(text.lower()):
        if len(w) > 1:  # 过滤 a/an 等过短无意义词，但保留 cat/dog 等
            toks.add(w)
    for ch in _CJK.findall(text):
        toks.add(ch)
    return toks


def _normalize(text):
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def compare_transcript_to_ui(transcript, stem_text, option_texts=None):
    """比对转写与界面文本。

    transcript:     ASR 转写的听力内容
    stem_text:      界面提取的题干文字
    option_texts:   选项文字列表（可空）
    """
    option_texts = option_texts or []
    ui_text = " ".join([stem_text or ""] + list(option_texts))

    t_tok = _tokenize(transcript)
    u_tok = _tokenize(ui_text)

    if not u_tok:
        return {
            "verdict": "ok", "coverage": 1.0, "matched": [],
            "missing": [], "extra": sorted(t_tok),
            "note": "界面未提取到可比对文本，跳过自动比对",
        }

    if not t_tok:
        return {
            "verdict": "suspect", "coverage": 0.0, "matched": [],
            "missing": sorted(u_tok), "extra": [],
            "note": "转写结果为空，无法比对（可能录音失败/识别失败）",
        }

    matched = t_tok & u_tok
    missing = u_tok - t_tok
    extra = t_tok - u_tok
    coverage = len(matched) / len(u_tok)

    # ★ 听力场景核心信号：播出来的英文内容，是否命中某个选项？
    #   （题干多为中文说明，不应计入"内容词"，否则会大量误报）
    opt_tok = set()
    for o in option_texts:
        opt_tok |= _tokenize(o)
    option_hit = bool(opt_tok & t_tok)

    # 保守判定：覆盖率<30% 且 没命中任何选项 → 疑似不符
    suspect = (coverage < 0.30) and (not option_hit)
    verdict = "suspect" if suspect else "ok"

    if option_hit:
        note = (f"转写命中的选项内容词（如 {sorted(opt_tok & t_tok)}），"
                f"与播放音频基本一致；界面文本重合度 {coverage:.0%}")
    elif suspect:
        note = (f"转写与界面选项均不吻合(重合度 {coverage:.0%})，"
                f"界面有 {len(missing)} 个内容词未在听力中出现，建议人工核对")
    else:
        note = f"转写与界面文本基本吻合(重合度 {coverage:.0%})"

    return {
        "verdict": verdict,
        "coverage": round(coverage, 2),
        "option_hit": option_hit,
        "matched": sorted(matched),
        "missing": sorted(missing),
        "extra": sorted(extra),
        "note": note,
    }


# ============================================================
# ★ 新增：LLM 语义比对 / 答案推断（应对同义替换、长难句）
#    复用项目统一 LLM 客户端 src.reviewer_common.LLMClient（已配置 qwen-plus 等）
# ============================================================

def _extract_letter_from_llm(resp, valid="TFABCDE"):
    """从 LLM 回复中提取单个合法选项字母。

    兼容多种返回：'A' / '答案：A' / '{"answer":"A"}' / 含 X 表示无法判断。
    """
    if not resp:
        return None
    import re as _re
    import json as _json
    # 1) 优先解析 JSON（如 {"answer":"A"} / {"letter":"B"}）
    try:
        _j = _json.loads(resp)
        _a = str(_j.get("answer") or _j.get("letter") or "").strip().upper()
        if _a and _a[0] in valid:
            return _a[0]
    except Exception:
        pass
    # 2) 退化：找第一个合法字母
    for ch in _re.findall(r"[TFABCDE]", resp.upper()):
        if ch in valid:
            return ch
    return None


def llm_decide_answer(transcript, stem_text, option_texts, llm=None):
    """用 LLM 根据「听力转写 + 题干 + 选项」推断正确选项字母（A-E / T/F）。

    返回 (letter_or_None, reasoning)。
      - 仅在开启语义比对时调用；网络/接口失败返回 (None, "") 由上层降级到 UI 启发式。
      - 图片题/排序题无字母选项时返回 (None, "")（这类题型本就不适用单字母答案）。
    """
    option_texts = option_texts or []
    if not transcript or not option_texts:
        return None, ""
    opt_lines = "\n".join(option_texts)
    prompt = (
        "你是一名小学英语听力题阅卷助手。下面是一段听力题播放内容的语音转写文本，"
        "以及题目界面上的题干和选项。请判断正确答案应是哪一个选项（只输出选项字母）。\n\n"
        f"【听力转写】\n{transcript}\n\n"
        f"【题干】\n{stem_text or '(无题干文字)'}\n\n"
        f"【选项】\n{opt_lines}\n\n"
        "要求：\n"
        "1. 结合转写内容与题干，选出最匹配的选项字母（如 A / B / C / D / T / F）。\n"
        "2. 只输出一个字母，不要解释；若确实无法判断，输出 X。"
    )
    try:
        if llm is None:
            from src.reviewer_common import LLMClient
            llm = LLMClient.from_config()
        resp = (llm.ask(prompt) or "").strip()
    except Exception as e:
        print(f"    ⚠ LLM 答案推断调用失败: {e}")
        return None, ""
    # 明确无法判断
    if resp.upper().strip() == "X":
        return None, resp
    letter = _extract_letter_from_llm(resp, valid="TFABCDE")
    return letter, resp


def llm_compare_transcript_to_ui(transcript, stem_text, option_texts, llm=None):
    """用 LLM 做语义比对（应对同义替换 / 长难句），返回与规则版同结构的 dict。

    失败（网络/接口）时自动回退到规则版 compare_transcript_to_ui，保证不中断主流程。
    """
    option_texts = option_texts or []
    base = compare_transcript_to_ui(transcript, stem_text, option_texts)
    try:
        if llm is None:
            from src.reviewer_common import LLMClient
            llm = LLMClient.from_config()
        opt_block = "\n".join(option_texts) if option_texts else "(无字母选项)"
        prompt = (
            "请判断下面「听力转写内容」与「题目题干/选项」是否语义一致"
            "（即播放的听力确实对应界面题目，而非播放了别的/错误的音频）。\n"
            f"【听力转写】{transcript}\n"
            f"【题干】{stem_text or ''}\n"
            f"【选项】{opt_block}\n"
            "只回答：一致 / 不一致，并给一句简洁理由。"
        )
        resp = (llm.ask(prompt) or "").strip()
        verdict = "suspect" if ("不一致" in resp or "不符" in resp or "不对应" in resp) else "ok"
        base["verdict"] = verdict
        base["note"] = f"[LLM语义比对] {resp}"
        base["llm_reasoning"] = resp
    except Exception as e:
        print(f"    ⚠ LLM语义比对失败，回退规则版: {e}")
    return base


if __name__ == "__main__":
    # 快速自测
    r = compare_transcript_to_ui(
        "Please listen and choose the word cat",
        "听录音，选出你听到的单词",
        ["A. cat", "B. dog", "C. pig"],
    )
    print(json.dumps(r, ensure_ascii=False, indent=2))
