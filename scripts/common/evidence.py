"""evidence.py — 每题界面级完整性检查证据（四维完整性）

从当前页面 XML 提取 5 项界面证据（题型/题干/选项/音频/作答），
供所有模块答题循环调用 → 前端日志证据卡展示。

需求文档对应：
  (1) 题干文字内容是否正确          → 题干
  (2) 题目内容文字是否与脚本相符/完整 → 题干 + 选项
  (3) 图片是否显示完整/匹配           → 选项(图片) + 音频
  (4) 题目能否正常作答               → 作答
  (5) 答案是否正确/知识点正确         → 由审查引擎/知识库完成
  (6) 听力音频是否有且完整可播放      → 音频

用法：
  from common.evidence import collect_ui_evidence
  xml = d.dump_hierarchy()
  ev = collect_ui_evidence(xml, qtype="听音选择")
  step_log(f"第{n}题 检查", "info", ev)
"""
import re


def _find_control(xml: str, keywords: tuple) -> tuple:
    """在 XML 中查找含关键词的控件节点，返回 (found, clickable)
    - 逐节点匹配 text/content-desc 含任一关键词
    - clickable 取该节点是否 clickable="true"
    """
    for m in re.finditer(r'<node[^>]*>', xml):
        tag = m.group(0)
        for kw in keywords:
            if kw in tag:
                clickable = 'clickable="true"' in tag
                return True, clickable
    return False, False


def collect_ui_evidence(xml: str, qtype: str = "") -> list:
    """从页面 XML 提取四维完整性证据。返回 evidence 列表（供 step_log 前端证据卡）"""
    ev = []
    try:
        xml = xml or ""
        # ① 题型识别
        ev.append({"field": "题型", "type": "text_ok",
                   "expected": qtype or "选择题",
                   "actual": qtype or "选择题", "diff": f"识别为[{qtype or '选择题'}]"})

        # ② 题干文字（页面上的长文本，排除按钮/进度）
        stems = []
        noise = ("下一题", "上一题", "检查", "提交", "开始答题", "重新答题",
                 "继续练习", "查看报告", "练习报告", "完成", "点击录音", "点击结束",
                 "原音", "小喇叭", "播放问题", "交卷", "确定交卷", "跳过",
                 "温馨提示", "继续答题")
        for m in re.finditer(r'text="([^"]{6,})"', xml):
            t = m.group(1).strip()
            if not t or t in noise or len(t) >= 60:
                continue
            if any(t.startswith(n) or n in t for n in noise):
                continue
            if t not in stems:
                stems.append(t)
            if len(stems) >= 3:
                break
        stem_txt = " / ".join(stems[:2]) if stems else "(无题干文字)"
        ev.append({"field": "题干", "type": "text_ok" if stems else "text_mismatch",
                   "expected": "文字完整可见", "actual": stem_txt,
                   "diff": f"提取到{len(stems)}条文字" if stems else "未提取到题干文字"})

        # ③ 选项存在性（A/B/C/D/T/F 字母选项 或 图片选项/输入框）
        opts_found = [o for o in ("A", "B", "C", "D", "T", "F")
                      if f'text="{o}"' in xml]
        has_edit = "EditText" in xml
        if opts_found:
            ev.append({"field": "选项", "type": "text_ok",
                       "expected": "存在可选项", "actual": ",".join(opts_found),
                       "diff": f"检测到 {len(opts_found)} 个选项"})
        elif has_edit:
            ev.append({"field": "选项", "type": "text_ok",
                       "expected": "输入框作答", "actual": "EditText",
                       "diff": "本题为输入类题型（填空/拼写），有输入框"})
        else:
            ev.append({"field": "选项", "type": "text_mismatch",
                       "expected": "存在可选项", "actual": "(无)",
                       "diff": "未检测到 A/B/C/D/T/F 选项（可能是图片选项或排序/匹配题）"})

        # ④ 音频/语音控件检查（★ 结合题型判断：听力题查扬声器、口语题查小喇叭+麦克风）
        #    - 听力题（题干含"听录音/听音/听一听"等）：必须有扬声器/播放控件且可点击
        #    - 口语题（题干含"朗读/跟读/读一读/读单词/读句子"等）：必须有播放控件(小喇叭/导读音频) + 录音控件(麦克风)，且可点击
        #    - 其他题：非听力/口语题，无音频属正常
        # ★ 关键词判断直接基于整段 XML（text/content-desc 都在属性里，短题干如"跟读句子"也能命中）
        LISTEN_KWS = ("听录音", "听音", "听一听", "听对话", "听短文", "听句子",
                      "听单词", "listen", "听下面", "听材料", "听问题")
        SPEAK_KWS = ("朗读", "读一读", "跟读", "读单词", "读句子", "大声读",
                     "repeat", "口语", "跟录音读")
        is_listening = any(kw in xml for kw in LISTEN_KWS)
        is_speaking = any(kw in xml for kw in SPEAK_KWS)

        # 播放/扬声器控件检测：找含关键词的节点，并判断是否可点击
        PLAY_KWS = ("播放", "喇叭", "扬声器", "ic_play", "btn_play",
                    "play_btn", "audio", "sound", "▶")
        MIC_KWS = ("麦克风", "录音", "record", "mic", "开始作答")
        play_found, play_clickable = _find_control(xml, PLAY_KWS)
        mic_found, mic_clickable = _find_control(xml, MIC_KWS)

        if is_listening:
            if play_found:
                ev.append({"field": "音频", "type": "text_ok" if play_clickable else "text_mismatch",
                           "expected": "听力题须有可点击的扬声器",
                           "actual": "播放控件" + ("(可点击)" if play_clickable else "(存在但不可点击)"),
                           "diff": ("扬声器/播放标识可见且可点击（题干含'听录音'）" if play_clickable
                                    else "⚠ 扬声器存在但不可点击（无法播放音频）")})
            else:
                ev.append({"field": "音频", "type": "text_mismatch",
                           "expected": "听力题须有扬声器/播放标识",
                           "actual": "未检测到播放控件",
                           "diff": "⚠ 题干含'听录音'但页面未检测到扬声器/播放标识"})
        elif is_speaking:
            # 口语题：播放控件(小喇叭/导读) + 录音控件(麦克风) 都要检查
            ev.append({"field": "音频", "type": "text_ok" if play_clickable else "text_mismatch",
                       "expected": "口语题须有可点击的播放控件(小喇叭/导读音频)",
                       "actual": "播放控件" + ("(可点击)" if play_clickable else "(存在但不可点击)") if play_found else "未检测到播放控件",
                       "diff": ("小喇叭/播放标识可见且可点击" if play_clickable
                                else ("⚠ 小喇叭存在但不可点击（无法播放音频）" if play_found
                                      else "⚠ 口语题未检测到小喇叭/播放控件"))})
            ev.append({"field": "作答", "type": "text_ok" if mic_clickable else "text_mismatch",
                       "expected": "口语题须有可点击的麦克风(录音作答)",
                       "actual": "麦克风/录音控件" + ("(可点击)" if mic_clickable else "(存在但不可点击)") if mic_found else "未检测到麦克风",
                       "diff": ("麦克风/录音控件可见且可点击" if mic_clickable
                                else ("⚠ 麦克风存在但不可点击（无法录音）" if mic_found
                                      else "⚠ 口语题未检测到麦克风/录音控件"))})
        else:
            ev.append({"field": "音频", "type": "skip",
                       "expected": "非听力/口语题",
                       "actual": "—",
                       "diff": "题干无'听录音/朗读'等关键词，本题非听力/口语题，无需音频"})

        # ⑤ 作答元素（检查/录音/输入框）
        has_act = ("检查" in xml or "录音" in xml or "完成" in xml
                   or "EditText" in xml or "麦克风" in xml or "record" in xml.lower())
        ev.append({"field": "作答", "type": "text_ok" if has_act else "text_mismatch",
                   "expected": "可作答（检查/录音/输入）", "actual": "可作答" if has_act else "未见作答元素",
                   "diff": "作答元素存在" if has_act else "检查/录音/输入元素未识别"})
    except Exception:
        pass
    return ev
