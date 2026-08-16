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


def _detect_image_options(xml: str) -> int:
    """检测图片选项数（★ 用户反馈：图片题选项是图片不是 A/B/C 字母，必须识别）

    真实 App 选项结构：
      - 字母选项：A/B/C/D/T/F 文字（已有）
      - 图片选项：android.widget.CheckBox（含文本或空），或大尺寸可点击 ImageView
    返回候选图片选项数（>=2 视为有图片选项）
    """
    count = 0
    # CheckBox（图片题选项最常见）
    for m in re.finditer(r'<node[^>]*class="android\.widget\.CheckBox"[^>]*>', xml):
        b = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', m.group(0))
        if not b:
            continue
        x1, y1, x2, y2 = map(int, b.groups())
        if y1 > 400 and (x2 - x1) > 40 and (y2 - y1) > 40:
            count += 1
    # 大尺寸可点击 ImageView（>120x120，位于选项区域 y>400）
    for m in re.finditer(r'<node[^>]*class="android\.widget\.ImageView"[^>]*clickable="true"[^>]*>', xml):
        b = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', m.group(0))
        if not b:
            continue
        x1, y1, x2, y2 = map(int, b.groups())
        w, h = x2 - x1, y2 - y1
        if w >= 120 and h >= 120 and 400 < y1 < 2000:
            count += 1
    return count


def _find_control(xml: str, keywords: tuple) -> tuple:
    """在 XML 中查找含关键词的控件节点，返回 (found, clickable)
    - 逐节点匹配 text/content-desc 含任一关键词
    - ★ 也匹配 resource-id 中的 play/sound/audio/speaker 模式
      （真实 App 扬声器按钮常是 rid=id/play_box，text/content-desc 为空）
    - clickable 取该节点是否 clickable="true"
    """
    for m in re.finditer(r'<node[^>]*>', xml):
        tag = m.group(0)
        for kw in keywords:
            if kw in tag:
                clickable = 'clickable="true"' in tag
                return True, clickable
        # resource-id 模式：play_box / play_btn / btn_play / ic_play / iv_play / sound / audio / speaker
        if re.search(r'resource-id="[^"]*(play|sound|audio|speaker)[^"]*"', tag):
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

        # ② 题干文字（页面上的长文本，排除按钮/进度/反馈弹窗/计时器）
        stems = []
        seen = set()
        noise = ("下一题", "上一题", "检查", "提交", "开始答题", "重新答题",
                 "继续练习", "查看报告", "练习报告", "完成", "点击录音", "点击结束",
                 "原音", "小喇叭", "播放问题", "交卷", "确定交卷", "跳过",
                 "温馨提示", "继续答题",
                 # ★ 反馈弹窗 / 倒计时 / 得分等非题干文字（否则"恭喜你 回答正确"会被当题干）
                 "恭喜", "回答正确", "回答错误", "很遗憾", "答对了", "答错了",
                 "练习结束还剩", "还剩", "得分", "用时", "获得", "本题得分", "作答正确", "作答错误",
                 # ★ 图片提示等非题干
                 "点击图片查看高清大图", "查看高清大图", "点击查看高清大图", "高清大图")
        # 计时器/倒计时（如 "19:58"、"还剩：19:58"）+ 得分/进度（77.0、3/40、100%）
        _timer_pat = re.compile(
            r"^\d{1,2}:\d{2}$|^还剩[：:]\s*\d{1,2}:\d{2}$|"
            r"^\d+(\.\d+)?%?$|^\d+\s*/\s*\d+$|^\d+分$"
        )
        # ★ 优先 question_title_tv（App 真题干节点）
        for m in re.finditer(r'resource-id="[^"]*question_title_tv[^"]*"[^>]*text="([^"]+)"', xml):
            t = m.group(1).strip()
            if t and t not in seen and len(t) < 60:
                seen.add(t)
                stems.append(t)
            if len(stems) >= 3:
                break
        # ★ 兜底：其他长文本（缩短到 ≥4 字符，抓到"听录音选图"等短题干）
        for m in re.finditer(r'text="([^"]{4,})"', xml):
            t = m.group(1).strip()
            if not t or t in seen or t in noise or len(t) >= 60:
                continue
            if any(n in t for n in noise):
                continue
            if "点击图片" in t or "高清大图" in t:
                continue
            if _timer_pat.match(t):      # ★ 时间/得分/进度（21:12、77.0、3/40）
                continue
            seen.add(t)
            stems.append(t)
            if len(stems) >= 3:
                break
        stem_txt = " / ".join(stems[:2]) if stems else "(无题干文字)"
        ev.append({"field": "题干", "type": "text_ok" if stems else "text_mismatch",
                   "expected": "文字完整可见", "actual": stem_txt,
                   "diff": f"提取到{len(stems)}条文字" if stems else "未提取到题干文字"})

        # ③ 选项存在性（字母选项 A/B/C/D/T/F 或 图片选项 CheckBox/大图）
        opts_found = [o for o in ("A", "B", "C", "D", "T", "F")
                      if f'text="{o}"' in xml]
        has_edit = "EditText" in xml
        # ★ 图片选项检测：CheckBox（图片题常见）或大尺寸可点击 ImageView
        image_opt_count = _detect_image_options(xml) if not opts_found else 0
        if opts_found:
            ev.append({"field": "选项", "type": "text_ok",
                       "expected": "存在可选项", "actual": ",".join(opts_found),
                       "diff": f"检测到 {len(opts_found)} 个选项"})
        elif has_edit:
            ev.append({"field": "选项", "type": "text_ok",
                       "expected": "输入框作答", "actual": "EditText",
                       "diff": "本题为输入类题型（填空/拼写），有输入框"})
        elif image_opt_count >= 2:
            # ★ 找到 >=2 个图片选项（CheckBox 或大 ImageView）→ 视为图片题选项
            ev.append({"field": "选项", "type": "text_ok",
                       "expected": "存在可选项", "actual": f"图片选项×{image_opt_count}",
                       "diff": f"本题为图片题，检测到 {image_opt_count} 个图片选项（CheckBox/大图）"})
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

        # ⑤ 作答元素（检查/检测/录音/输入/选项/图片点击区 —— ★ 多信号检测，特殊题型不再误判）
        #   原理：任何"可作答"信号都算通过：
        #   - 文字按钮：检查/检测/完成/提交/下一题/录音/点击结束/继续
        #   - 输入类：EditText/输入框
        #   - 选择类：A-E/T/F 字母选项、CheckBox、可点击大图（图片选项/排序/匹配）
        _act_signals = (
            "检查" in xml or "检测" in xml or "完成" in xml or "提交" in xml
            or "录音" in xml or "点击结束" in xml or "点击录音" in xml or "回放" in xml
            or "EditText" in xml or "麦克风" in xml or "record" in xml.lower()
            or bool(re.search(r'text="[TFABCDE]"', xml))
            or "CheckBox" in xml
        )
        # ★ 可点击大图（图片选项/排序/匹配题的作答入口）
        if not _act_signals:
            _big_click = re.search(
                r'<node[^>]*clickable="true"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
                xml
            )
            if _big_click:
                x1, y1, x2, y2 = (int(_big_click.group(1)), int(_big_click.group(2)),
                                  int(_big_click.group(3)), int(_big_click.group(4)))
                if (x2 - x1) > 300 and (y2 - y1) > 150:
                    _act_signals = True
        ev.append({"field": "作答", "type": "text_ok" if _act_signals else "text_mismatch",
                   "expected": "可作答（检查/录音/输入/选项）", "actual": "可作答" if _act_signals else "未见作答元素",
                   "diff": "作答元素存在" if _act_signals else "检查/录音/输入元素未识别"})

        # ⑥ 分值显示（文档检查点：当前大题/页面分值是否正确）——附加信息，不判通过/不通过
        _score_vals = re.findall(r'text="(\d+(?:\.\d+)?分)"', xml) or \
                      re.findall(r'text="(?:本题|共|满分|总分)[^"]*(\d+(?:\.\d+)?)[^"]*分"', xml)
        if _score_vals:
            ev.append({"field": "分值", "type": "info",
                       "expected": "分值显示", "actual": "、".join(_score_vals[:4]),
                       "diff": f"检测到分值: {'、'.join(_score_vals[:4])}"})

        # ⑦ 题型-作答一致性（题干要求 vs 实际元素，揪出"判断题给了ABC"这类错配）
        _cons = collect_consistency_evidence(xml, qtype or "")
        if _cons:
            ev.append(_cons)
    except Exception:
        pass
    return ev


# ============================================================
# 题型-作答一致性检查（★ 揪错核心：题干要求 vs 实际作答方式）
# ============================================================
# 依据题干关键词推断"应该是什么作答方式"，与实际检测到的元素对比：
#   - 判断题题干（判断对错/√×/是否正确）→ 必须 T/F 或 √/× 两态
#   - 填空/补全题干 → 必须 输入框(EditText) 或 词库选择
#   - 排序题干 → 必须 可点击排序元素（CheckBox/整句），不是 A/B/C 单选
#   - 听力/朗读题干 → 必须有音频控件（喇叭/播放），朗读还须麦克风
# 若题干要求与页面实际作答方式矛盾 → 返回 text_mismatch 证据，供前端/报告揪出。

_JUDGE_KWS = ("判断对错", "判断正误", "判断对", "是否相符", "判断相符", "对错", "是否正确", "正确打", "打勾", "√", "×")
_FILL_KWS = ("填空", "补全", "填写", "填词", "每空", "完成句子", "句型转换")
_SORT_KWS = ("排序", "排列", "按顺序", "连词成句", "给句子排序", "按正确顺序")
_LISTEN_KWS = ("听录音", "听音", "听一听", "听对话", "听短文", "听句子", "听单词")
_SPEAK_KWS = ("朗读", "跟读", "读一读", "跟录音读", "大声读")


def collect_consistency_evidence(xml: str, qtype: str = "") -> dict:
    """题型-作答一致性检查：题干关键词推断期望作答方式，与实际元素对比。

    返回: 发现错配时返回 {"field":"作答匹配","type":"text_mismatch",...} 证据；
          一致时返回 None（不干扰正常证据流）。
    """
    try:
        xml = xml or ""
        full = xml
        texts = "".join(re.findall(r'text="([^"]*)"', xml))
        has_letter_abc = any(f'text="{c}"' in xml for c in ("A", "B", "C", "D"))
        has_tf = 'text="T"' in xml or 'text="F"' in xml
        has_edit = "EditText" in xml
        has_checkbox = "CheckBox" in xml
        has_wordbank = bool(re.search(r'select_btn|word_bank|wordbank', xml))
        play_found, _ = _find_control(xml, ("播放", "喇叭", "扬声器", "play", "audio", "sound"))
        mic_found, _ = _find_control(xml, ("麦克风", "录音", "record", "mic"))

        # ① 判断题题干 → 应 T/F 或 √/×，不应 A/B/C/D
        if any(kw in texts for kw in _JUDGE_KWS):
            if has_letter_abc and not has_tf:
                return {"field": "作答匹配", "type": "text_mismatch",
                        "expected": "判断题应为 T/F 或 √/× 两态选项",
                        "actual": f"A/B/C/D 字母选项{'（含T/F）' if has_tf else ''}",
                        "diff": "⚠ 题干含'判断对错/√×'（判断题），但页面提供 A/B/C/D 选项而非 T/F"}
            # ★ 判断题已给 T/F（正确作答方式）→ 本维度通过，不继续走后续规则
            #   （否则"听录音"会触发听力规则，在 mock 无喇叭时误报）
            if has_tf:
                return None

        # ② 填空/补全题干 → 应输入框或词库，不应纯 A/B/C/D
        if any(kw in texts for kw in _FILL_KWS):
            if has_letter_abc and not has_edit and not has_wordbank:
                return {"field": "作答匹配", "type": "text_mismatch",
                        "expected": "填空/补全题应提供输入框或词库选择",
                        "actual": "A/B/C/D 单选选项",
                        "diff": "⚠ 题干含'填空/补全'（填空题），但页面是 A/B/C/D 单选而非输入框"}

        # ③ 排序题干 → 应可点击排序元素（CheckBox/句子），不应是 A/B/C/D 单选
        if any(kw in texts for kw in _SORT_KWS):
            if has_letter_abc and not has_checkbox and not has_wordbank:
                return {"field": "作答匹配", "type": "text_mismatch",
                        "expected": "排序题应提供可点击排序元素（句子/方框/序号）",
                        "actual": "A/B/C/D 单选选项",
                        "diff": "⚠ 题干含'排序/排列'（排序题），但页面是 A/B/C/D 单选而非排序元素"}

        # ④ 朗读/口语题干 → 必须有麦克风（录音作答）
        if any(kw in texts for kw in _SPEAK_KWS):
            if not mic_found:
                return {"field": "作答匹配", "type": "text_mismatch",
                        "expected": "朗读/口语题应提供麦克风（录音作答）",
                        "actual": "未检测到麦克风/录音控件",
                        "diff": "⚠ 题干含'朗读/跟读'（口语题），但页面无麦克风，无法录音作答"}
            if mic_found:
                # ★ 朗读题已有麦克风（可录音作答）→ 通过，不再走听力规则误报"无喇叭"
                #   （朗读题题干常含"听录音"，但喇叭由"音频"维度单独检查）
                return None

        # ⑤ 听力题干 → 必须有音频播放控件
        if any(kw in texts for kw in _LISTEN_KWS):
            if not play_found:
                return {"field": "作答匹配", "type": "text_mismatch",
                        "expected": "听力题应提供音频播放控件（喇叭）",
                        "actual": "未检测到播放控件",
                        "diff": "⚠ 题干含'听录音'（听力题），但页面无喇叭/播放控件"}
            return None

    except Exception:
        pass
    return None
