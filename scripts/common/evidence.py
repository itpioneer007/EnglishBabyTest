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


def _find_control(xml: str, keywords: tuple, rid_pattern: str = None) -> tuple:
    """在 XML 中查找含关键词的控件节点，返回 (found, clickable)
    - 优先匹配 clickable="true" 的节点（避免误命中介绍/标签文本）
    - 逐节点匹配 text/content-desc 含任一关键词
    - ★ 也匹配 resource-id 中的 play/sound/audio/speaker/mic/record 模式
      （真实 App 扬声器/麦克风按钮常是 rid=id/play_box，text/content-desc 为空）
      ★ 2026-08-24：rid_pattern 可定制——播放检查传 (play|sound|audio|speaker)，
      麦克风检查传 (record|mic)，避免"iv_caption_play 播放图标被当麦克风"这类串检
    - clickable 取该节点是否 clickable="true"
    - ★ 2026-08-24：命中非 clickable 文本节点时，会向上/向外查找包含该节点的
      clickable 父容器（如口语训练 record_btn 容器内含 "点击录音" 文本）
    """
    xml = xml or ""
    if rid_pattern is None:
        rid_pattern = r'resource-id="[^"]*(play|sound|audio|speaker|mic|record)[^"]*"'
    _rid_re = re.compile(rid_pattern)
    # ★ 2026-08-24：系统状态栏/通知栏节点永远不是 App 控件，必须跳过——
    #   例：com.android.systemui:id/dynamic_icon_group 含子串 "mic"（dynaMIC），
    #   会被麦克风 rid 模式误命中 → 倒计时中误报"麦克风存在"
    def _is_system(tag: str) -> bool:
        return "com.android.systemui" in tag or 'package="android"' in tag
    # 先收集所有 clickable 节点 bounds，用于后续“包含关系”判定
    _clickables = []
    for m in re.finditer(r'<node[^>]*>', xml):
        tag = m.group(0)
        if _is_system(tag) or 'clickable="true"' not in tag:
            continue
        b = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', tag)
        if not b:
            continue
        _clickables.append((int(b.group(1)), int(b.group(2)), int(b.group(3)), int(b.group(4)), tag))

    def _contained_by_clickable(x1, y1, x2, y2, margin=20):
        """判断某个区域是否被某个 clickable 节点包含（或中心落在其中）。"""
        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
        for bx1, by1, bx2, by2, tag in _clickables:
            # 区域中心落在 clickable 容器内，或容器几乎完全包含目标区域
            if (bx1 - margin <= cx <= bx2 + margin and by1 - margin <= cy <= by2 + margin) or \
               (bx1 <= x1 and by1 <= y1 and bx2 >= x2 and by2 >= y2):
                return True
        return False

    # 第一轮：只找 clickable=true 的节点（避免误命中介绍文案等非控件文本）
    for m in re.finditer(r'<node[^>]*>', xml):
        tag = m.group(0)
        if _is_system(tag) or 'clickable="true"' not in tag:
            continue
        for kw in keywords:
            if kw in tag:
                return True, True
        if _rid_re.search(tag):
            return True, True
    # 第二轮：兜底找含关键词/rid 的节点（含 clickable=false 的），并尝试找外部 clickable 容器
    nodes = list(re.finditer(r'<node[^>]*>', xml))
    for idx, m in enumerate(nodes):
        tag = m.group(0)
        if _is_system(tag):
            continue
        hit = False
        for kw in keywords:
            if kw in tag:
                hit = True
                break
        if not hit and _rid_re.search(tag):
            hit = True
        if not hit:
            continue
        clickable = 'clickable="true"' in tag
        b = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', tag)
        if b and not clickable:
            bx1, by1, bx2, by2 = map(int, b.groups())
            # 2.1 向上/向外找包含自己的 clickable 容器（口语训练 record_btn 容器）
            if _contained_by_clickable(bx1, by1, bx2, by2):
                clickable = True
            # 2.2 容器内子节点可点击 → 也视为可点击（仅限容器类节点）
            #    ★ 2026-08-24：TextView/ImageView 等叶子控件跳过——否则大段题干文字
            #      （如 tv_caption 含"录音"）因几何上重叠播放图标被误提升为可点击
            if not clickable:
                _leaf = re.search(r'class="android\.widget\.(TextView|ImageView|Button|ImageButton)"', tag)
                if not _leaf:
                    for m2 in nodes[idx + 1:]:
                        t2 = m2.group(0)
                        b2 = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', t2)
                        if not b2:
                            continue
                        x1, y1, x2, y2 = map(int, b2.groups())
                        if x1 >= bx1 and y1 >= by1 and x2 <= bx2 and y2 <= by2:
                            if 'clickable="true"' in t2:
                                clickable = True
                                break
                        else:
                            break  # 超出容器范围 = 非子节点
        return True, clickable
    return False, False


def collect_ui_evidence(xml: str, qtype: str = "", skip_stem: bool = False) -> list:
    """从页面 XML 提取四维完整性证据。返回 evidence 列表（供 step_log 前端证据卡）

    skip_stem: True 时不输出"题干"维度（口语训练同大题第 2-N 小题用——大题题干已在
               第一小题下显示过，下面小题不再重复；下滑后大题题干会被滚动条挤出，
               残留旧 XML 导致大题题干错位）
    """
    ev = []
    # ★ is_speaking/is_listening 提前定义：③ 选项检查（口语题跳过"无选项"）在 ④ 之前执行，
    #   必须在函数开头就可用，否则 NameError 被 except 吞掉 → 证据只返回前 2 项（用户实测）
    SPEAK_KWS_EARLY = ("朗读", "读一读", "跟读", "读单词", "读句子", "大声读",
                       "repeat", "口语", "跟录音读", "已朗读", "未朗读", "正在朗读")
    LISTEN_KWS_EARLY = ("听录音", "听音", "听一听", "听对话", "听短文", "听句子",
                        "听单词", "listen", "听下面", "听材料", "听问题")
    is_speaking = any(kw in xml for kw in SPEAK_KWS_EARLY) if xml else False
    is_speaking = is_speaking or qtype in ("口语训练", "朗读", "跟读", "人机对话")
    is_listening = any(kw in xml for kw in LISTEN_KWS_EARLY) if xml else False
    is_listening = is_listening or qtype in ("听力专项", "听力训练", "磨耳精听")
    try:
        xml = xml or ""
        # ① 题型识别
        ev.append({"field": "题型", "type": "text_ok",
                   "expected": qtype or "选择题",
                   "actual": qtype or "选择题", "diff": f"识别为[{qtype or '选择题'}]"})

        # ② 题干文字（页面上的长文本，排除按钮/进度/反馈弹窗/计时器/顶部导航）
        #   skip_stem=True 时不输出"题干"维度（口语训练同大题第 2-N 小题用——
        #   大题题干已在第一小题下显示过，下面小题不再重复；
        #   下滑后大题题干 tv_caption 会被滚动条挤出可视区，残留旧 XML 抓的
        #   大题题干会错位显示成上面大题的内容——不重复展示即可）
        stems = [] if not skip_stem else None
        seen = set()
        noise = ("下一题", "上一题", "检查", "提交", "开始答题", "重新答题",
                 "继续练习", "查看报告", "练习报告", "完成", "点击录音", "点击结束",
                 "原音", "小喇叭", "播放问题", "交卷", "确定交卷", "跳过",
                 "温馨提示", "继续答题",
                 # ★ 反馈弹窗 / 倒计时 / 得分等非题干文字（否则"恭喜你 回答正确"会被当题干）
                 "恭喜", "回答正确", "回答错误", "很遗憾", "答对了", "答错了",
                 "练习结束还剩", "还剩", "得分", "用时", "获得", "本题得分", "作答正确", "作答错误",
                 # ★ 图片提示等非题干
                 "点击图片查看高清大图", "查看高清大图", "点击查看高清大图", "高清大图",
                 # ★ 顶部导航/标题/按钮（口语训练答题页顶部"口语训练湘少六上U1"+ "退出训练"
                 #   + "答题卡" + "口语训练"模块标题都被误当题干——必须排除）
                 "退出训练", "答题卡", "口语训练", "听力专项", "口语训练", "单元自检",
                 "知识过关", "巧记单词", "语音评测", "全脑记词", "单词听写",
                 "已朗读", "未朗读", "正在朗读", "朗读", "跟读", "读一读", "听一听",
                 "上一页", "下一页", "上一小题", "下一小题",
                 "训练规则说明", "好的，我知道啦~", "好的，我知道了",
                 "开始测试", "开始考试", "开始练习", "考试结束", "本次考试结束",
                 "耗时", "时长", "总时长", "用时", "提交答卷", "重新作答", "查看解析",
                 "答案", "正确答案", "错误答案", "本次得分", "本大题", "本小题",
                 "分值", "满分", "本组",
                 # ★ 口语训练列表页/答题页顶部栏（用户实测"考前突破/当前版本/练习记录"被误当题干）
                 "考前突破", "当前版本", "练习记录", "退出训练",
                 # ★ 口语训练进度（"口语训练湘少六上U1"是顶部标题，含 U 编号的也排除）
                 "口语训练湘少")
        # 计时器/倒计时（如 "19:58"、"还剩：19:58"）+ 得分/进度（77.0、3/40、100%）
        #   + 分值标记 "2分" / "(2分)" / "（2分）" 排除（口语训练小题"him." 旁边常带"（2分）"）
        _timer_pat = re.compile(
            r"^\d{1,2}:\d{2}$|^还剩[：:]\s*\d{1,2}:\d{2}$|"
            r"^\d+(\.\d+)?%?$|^\d+\s*/\s*\d+$|^\d+分$|"
            r"^[（(]\s*\d+\s*分\s*[）)]$"
        )
        # ★ 分值后缀清洗："听单词...。 (共2分)" → 去掉" (共N分)" 保留题干
        def _strip_score(t: str) -> str:
            return re.sub(r"[（(]\s*共\s*\d+\s*分\s*[）)]", "", t).strip()
        # ★ skip_stem=True 时跳过整个题干提取段（stems=None），避免 stems.append 崩溃
        if stems is not None:
            # ★ 优先 question_title_tv（App 真题干节点）
        #   ★ 真机 dump 属性顺序是 text 在 resource-id 之前（cur_home/oral_q3 实测），
        #     不能写 "rid…text" 的顺序正则，改为先定位节点再取 text
        #   ★ 2026-08-24：知识过关填字母页 question_title_tv 是【多个字母块节点】
        #     （"n"/"c"/"("/"友好的；"/"吸引人"/"的)"…），只取第一条且短文本无汉字
        #     跳过（否则字母块/词义被当题干 → "友好的； / 吸引人"）
            for _nm in re.finditer(r'<node[^>]*question_title_tv[^>]*>', xml):
                _tm = re.search(r'text="([^"]+)"', _nm.group(0))
                if _tm:
                    t = _strip_score(_tm.group(1).strip())  # ★ 清洗尾缀"(共N分)"
                    if t and t not in seen and len(t) < 60 \
                            and (len(t) >= 4 or re.search(r'[\u4e00-\u9fff]', t)):
                        seen.add(t)
                        stems.append(t)
                break  # ★ 只取第一条（知识过关的 question_title_tv 是多个字母块，不能全收）
            # ★★★ 大题题干优先：tv_caption（大题介绍节点，如口语训练
            #   "请大声朗读你看到的句子，注意字母组合ee的发音。点击"录音"开始作答。…(共15分)"）
            #   用户要求：口语训练大题题干 = 题目介绍内容（听录音，回答问题什么的）；
            #   小题题干（要读的单词/句子）由模块 _find_active_sub_question 单独提取记录，不混入。
            #   长度放宽到 160（大题介绍通常 60~120 字，旧逻辑 len>=60 会把它过滤掉）
            _caption_taken = False
            for _nm in re.finditer(r'<node[^>]*tv_caption[^>]*>', xml):
                _tm = re.search(r'text="([^"]+)"', _nm.group(0))
                if _tm:
                    t = _strip_score(_tm.group(1).strip())
                    if t and t not in seen and len(t) < 160:
                        seen.add(t)
                        stems.append(t)
                        _caption_taken = True
                break  # 大题介绍只有一条
            # ★ 兜底：其他长文本（缩短到 ≥4 字符，抓到"听录音选图"等短题干）
            for m in re.finditer(r'text="([^"]{4,})"', xml):
                # ★ 口语题已拿到大题题干(tv_caption)时跳过兜底：
                #   避免把小题句子（speech_content 等）混进"题干"字段
                if is_speaking and _caption_taken:
                    break
                t = _strip_score(m.group(1).strip())  # ★ 清洗尾缀"(共N分)"
                if not t or t in seen or t in noise or len(t) >= 60:
                    continue
                # ★ 单元标题（"Unit 1 What does she look like?"）与词义行（"adj. 新来的；新的"）
                #   不是题干（知识过关页顶部标题+词义提示被误当题干，用户实测）
                if re.match(r'^Unit\s*\d+', t, re.IGNORECASE) or \
                   re.match(r'^(n|v|adj|adv|det|pron|prep|conj|num|art|int)\.', t, re.IGNORECASE):
                    continue
                # ★ 词义/提示碎片（知识过关填字母页 "( 友好的；" / "吸引人" / "的)" 被拆段）：
                #   纯中文短碎片（<5 字符无英文）、括号开头、分号/右括号结尾 → 不是题干
                if (len(t) < 5 and not re.search(r'[A-Za-z]', t)) \
                        or t.startswith(("（", "(")) or t.endswith(("；", ")")):
                    continue
                # ★ 排除选项文本："A. fast" / "B. food"（字母+句点+内容）
                if re.match(r"^[TFABCDE][\.、．]\s*\S", t):
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
            # ★★★ 口语/朗读题型特殊路径：用户实测大题题干（如 "him."）在"请阅读题目"和
            #   "练习结束还剩"之间。question_title_tv 兜底都拿不到时，按"区间提取"拿到真题干。
            #   区间：y 坐标在 "请阅读题目"/"请朗读题目" 节点之后、"练习结束"节点之前
            if not stems and is_speaking:
                _zone_texts = []
                _low, _high = 0, 99999
                for m in re.finditer(r'<node[^>]*>', xml):
                    b = m.group(0)
                    tm = re.search(r'text="([^"]+)"', b)
                    bm = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', b)
                    if not (tm and bm):
                        continue
                    txt = tm.group(1).strip()
                    if "请阅读题目" in txt or "请朗读题目" in txt or "练习结束" in txt:
                        y1 = int(bm.group(2)); y2 = int(bm.group(4))
                        if "请阅读" in txt or "请朗读" in txt:
                            _low = max(_low, y2)  # 题目在"请阅读"之后
                        if "练习结束" in txt:
                            _high = min(_high, y1)  # 题目在"练习结束"之前
                for m in re.finditer(r'<node[^>]*>', xml):
                    b = m.group(0)
                    tm = re.search(r'text="([^"]+)"', b)
                    bm = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', b)
                    if not (tm and bm):
                        continue
                    y1 = int(bm.group(2))
                    t = tm.group(1).strip()
                    if y1 < _low or y1 > _high:   # 不在题目区间
                        continue
                    if t in noise or any(n in t for n in noise):
                        continue
                    # ★ 单元标题/词义行不是题干（同兜底规则）
                    if re.match(r'^Unit\s*\d+', t, re.IGNORECASE) or \
                       re.match(r'^(n|v|adj|adv|det|pron|prep|conj|num|art|int)\.', t, re.IGNORECASE):
                        continue
                    if t in seen or len(t) < 2 or len(t) > 30:
                        continue
                    if _timer_pat.match(t):
                        continue
                    # ★ 排除"小题标题/序号"：1./2./3. 或 "1"/"1 " 这种纯序号
                    if re.match(r"^\d+[\.、\s]*$", t):
                        continue
                    _zone_texts.append(t)
                    seen.add(t)
                    if len(_zone_texts) >= 3:
                        break
                if _zone_texts:
                    stems = _zone_texts
        stem_txt = " / ".join(stems[:2]) if stems else "(无题干文字)"
        if not skip_stem:
            ev.append({"field": "题干", "type": "text_ok" if stems else "text_mismatch",
                       "expected": "文字完整可见", "actual": stem_txt,
                       "diff": f"提取到{len(stems)}条文字" if stems else "未提取到题干文字"})
        # ★ 2026-08-25 skip_stem=True 时题干提取段全部跳过，但"seen"后续不再使用，
        #   且 stems=None 时上面的提取逻辑（question_title_tv/tv_caption/兜底/zone）已在
        #   if stems is not None 保护外——需确认所有 stems.append 都在保护内：见下方 for 循环

        # ③ 选项存在性（字母选项 A/B/C/D/T/F 或 图片选项 CheckBox/大图）
        #   ★ 兼容 "A. fast" / "B. food" 带句点选项（普通听力/选择题目常见）
        opts_found = [o for o in ("A", "B", "C", "D", "T", "F")
                      if f'text="{o}"' in xml]
        if not opts_found:
            # "A. xxx" 带句点选项 → 也识别为字母选项
            opts_found = [m.group(1) for m in re.finditer(
                r'text="([TFABCDE])[\.、．]\s*[^"]{1,40}"', xml)][:6]
        has_edit = "EditText" in xml
        # ★ 图片选项检测：CheckBox（图片题常见）或大尺寸可点击 ImageView
        image_opt_count = _detect_image_options(xml) if not opts_found else 0
        # ★ 字母按钮检测（知识过关填字母题）：多个小尺寸 clickable LinearLayout/FrameLayout
        #   （字母按钮无文本，uiautomator 读不到 → 靠尺寸+clickable 特征，2 行 5 列 193x137）
        _letter_btns = 0
        if not opts_found:
            for _ml in re.finditer(
                r'<node[^>]*class="android\.widget\.(LinearLayout|FrameLayout)"[^>]*clickable="true"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
                xml,
            ):
                _bx1, _by1, _bx2, _by2 = (int(_ml.group(2)), int(_ml.group(3)),
                                          int(_ml.group(4)), int(_ml.group(5)))
                if 90 < (_bx2 - _bx1) < 340 and 70 < (_by2 - _by1) < 260 \
                        and 250 < _by1 < 2200:
                    _letter_btns += 1
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
        elif _letter_btns >= 4:
            # ★ 填字母题（知识过关）：字母按钮作答，无 A/B/C 选项属正常 → skip
            ev.append({"field": "选项", "type": "skip",
                       "expected": "填字母题无ABC选项", "actual": f"字母按钮×{_letter_btns}",
                       "diff": f"字母补全题：{_letter_btns} 个字母按钮作答，无需 A/B/C 选项"})
        elif is_speaking:
            # ★ 口语题（录音作答）：无选项属正常，作答方式为"点麦克风"
            #   此前误判"未检测到选项"与 AI"无ABC选项"（用户实测）现跳过
            ev.append({"field": "选项", "type": "skip",
                       "expected": "口语题无选项", "actual": "录音作答",
                       "diff": "口语题作答方式为点麦克风录音，无需选项"})
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
        # ★ 同时用传入的 qtype（口语训练题在答题页 XML 不含"朗读/跟读"等关键词，
        #   qtype 参数更可靠：口语训练模块明确传 qtype="口语训练"）
        #   （is_listening/is_speaking 已在函数开头基于 qtype+XML 预定义，这里增强 XML 关键词命中）
        is_listening = is_listening or any(kw in xml for kw in LISTEN_KWS)
        is_speaking = is_speaking or any(kw in xml for kw in SPEAK_KWS)

        # ★ 图片/大图题（题干带"看图片/图片"或页面主体是大 ImageView）：
        #   听力图片题音频自动播放（无需手动点扬声器），口语图片题直接朗读，
        #   → 音频维度 skip，避免"听单词/看图选词"误报"未检测到播放控件"
        _has_big_image = False
        for _mi in re.finditer(r'<node[^>]*class="android\.widget\.ImageView"[^>]*>', xml):
            _bm = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', _mi.group(0))
            if _bm:
                _x1, _y1, _x2, _y2 = map(int, _bm.groups())
                if (_x2 - _x1) > 500 and (_y2 - _y1) > 300 and 300 < _y1 < 1600:
                    _has_big_image = True
                    break
        _is_image_q = _has_big_image or ("图片" in xml and ("看图片" in xml or "看图" in xml or "观察图片" in xml))
        if _is_image_q:
            # 图片题：题干/图片可见即可，音频（自动播放/无独立播放控件）不单独检查
            ev.append({"field": "音频", "type": "skip",
                       "expected": "图片题（音频自动播放/无独立播放控件）",
                       "actual": "图片作答",
                       "diff": "图片/大图题，听力音频通常自动播放，无需手动点扬声器"})
            # ★ 注意：直接结束④，不再走下方听力/口语的音频检查
            _audio_skipped = True
        else:
            _audio_skipped = False

        # 播放/扬声器控件检测：找含关键词的节点，并判断是否可点击
        PLAY_KWS = ("播放", "喇叭", "扬声器", "ic_play", "btn_play",
                    "play_btn", "audio", "sound", "▶", "原音")
        # ★ 麦克风检测：口语训练答题页录音控件核心文本是"点击录音/点击结束"
        #   （实际麦克风图标是图片无文本）。这些文本控件 100% 关联到录音功能，可靠。
        #   ★ 2026-08-24：不能包含泛词"录音/开始作答/继续作答"——大题说明文字(tv_caption)
        #   里就有"点击"录音"开始作答"，会被误判为麦克风 → 倒计时中误报"麦克风可点击"。
        #   只认：record/mic（resource-id 必含）+"点击录音/点击结束/点击完成/麦克风"精确词
        MIC_KWS = ("record", "mic", "点击录音", "点击结束", "点击完成", "麦克风")
        play_found, play_clickable = _find_control(
            xml, PLAY_KWS, rid_pattern=r'resource-id="[^"]*(play|sound|audio|speaker)[^"]*"')
        mic_found, mic_clickable = _find_control(
            xml, MIC_KWS, rid_pattern=r'resource-id="[^"]*(record|mic)[^"]*"')

        if _audio_skipped:
            pass  # 图片题已发 skip，不再走听力/口语音频检查
        elif is_speaking:
            # ★ 口语分支优先（2026-08-24）：跟读题题干"听录音，跟读单词"同时命中听/说关键词，
            #   若 is_listening 优先 → 跟读题被当听力题 → 误报"扬声器存在但不可点击"
            #   （知识过关 U2 报告第5/7/13/14题实测）
            # ★ 口语题：是否检查播放控件(小喇叭)取决于题干是否要求"点击小喇叭/播放问题"
            #   ★ 用户实测：有些口语小题没有小喇叭，题干没提到"小喇叭/播放"就不该检查！
            #   题干/页面含"小喇叭/播放问题/先听/听一听再读/点小喇叭" → 必须有小喇叭可点
            #   否则 → 播放控件 skip（该小题就是直接朗读，无需小喇叭）
            _need_play = any(k in xml for k in
                             ("小喇叭", "播放问题", "点击播放", "先听", "听一听再",
                              "点小喇叭", "播放录音", "听音跟读", "听录音跟读", "播放",
                              "原音"))  # ★ 语音评测"原音"按钮 = 播放控件，须可点
            if _need_play:
                ev.append({"field": "音频", "type": "text_ok" if play_clickable else "text_mismatch",
                           "expected": "口语题须有可点击的播放控件(小喇叭/导读音频)",
                           "actual": "播放控件" + ("(可点击)" if play_clickable else "(存在但不可点击)") if play_found else "未检测到播放控件",
                           "diff": ("小喇叭/播放标识可见且可点击（题干要求点击小喇叭）" if play_clickable
                                    else ("⚠ 小喇叭存在但不可点击（无法播放音频）" if play_found
                                          else "⚠ 题干要求点击小喇叭但未检测到播放控件"))})
            else:
                # ★ 题干没提小喇叭 → 不检查播放控件（该小题直接朗读，无小喇叭属正常）
                ev.append({"field": "音频", "type": "skip",
                           "expected": "口语题无需小喇叭",
                           "actual": "直接朗读",
                           "diff": "题干未提及小喇叭/播放，本题直接朗读作答，无需检查小喇叭"})
            # 麦克风始终检查（口语题作答核心）
            ev.append({"field": "作答", "type": "text_ok" if mic_clickable else "text_mismatch",
                       "expected": "口语题须有可点击的麦克风(录音作答)",
                       "actual": "麦克风/录音控件" + ("(可点击)" if mic_clickable else "(存在但不可点击)") if mic_found else "未检测到麦克风",
                       "diff": ("麦克风/录音控件可见且可点击" if mic_clickable
                                else ("⚠ 麦克风存在但不可点击（无法录音）" if mic_found
                                      else "⚠ 口语题未检测到麦克风/录音控件"))})
        elif is_listening:
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
        #   - 口语题：麦克风（点录音）= 核心作答入口（麦克风是 ImageView 无文本，
        #     但 resource-id 必含 record/mic；_find_control 已检测 mic_found/mic_clickable）
        _act_signals = (
            "检查" in xml or "检测" in xml or "完成" in xml or "提交" in xml
            or "录音" in xml or "点击结束" in xml or "点击录音" in xml or "回放" in xml
            or "EditText" in xml or "麦克风" in xml or "record" in xml.lower()
            or bool(re.search(r'text="[TFABCDE]"', xml))
            or bool(re.search(r'text="[TFABCDE][\.、．]\s*\S', xml))  # ★ "A. fast" 带句点选项
            or "CheckBox" in xml
            or "朗读" in xml or "跟读" in xml   # ★ 口语题必有"朗读"/"跟读"题型文本
        )
        # ★ 口语/朗读题型：④ 已单独检查麦克风 clickable → 作答入口存在 = 作答通过
        #   解决"作答元素: 检查/录音/输入元素未识别"误报（用户实测：麦克风是 ImageView 无文本，
        #   XML dump 时若"点击录音"刚切换到"点击结束"瞬间，_act_signals 字符串都抓不到）
        if is_speaking and mic_found and mic_clickable:
            _act_signals = True
        # ★ 填字母题（知识过关）：字母按钮（≥4 个小尺寸 clickable 容器）= 作答入口
        #   字母按钮无文本，_act_signals 字符串/大图兜底都抓不到 → 必须按特征识别
        if not _act_signals and _letter_btns >= 4:
            _act_signals = True
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
