"""面向「使用这个工具测 App 的人」的话术层：把技术异常翻译成「现象 + 处理建议」。

★ 2026-10-19 新增。用户定调（试用反馈 + 二次校准）：
  1. **读日志的人不是写代码的人。** 前端日志里【绝不】出现 traceback、异常类名、
     HTTP 状态码、供应商名、内部字段名、Python 变量 repr。
  2. **技术细节不丢，只是换个地方。** 一律 `print()` 到服务端日志
     （`server_output.log`），需要排查的人去那里看；前端只留一句可读的说明。
  3. **一步是一步。** 这一步做了什么、成没成、下一步去哪，直说，不拐弯：
     - 失败就是「检测中断」，不许再写「完成」；
     - 0 题就是「未检测到题目」，不许算作「成功」，更不许写「全部完成」。
  4. **语气对齐常规 App 报错**：第三人称陈述现象，随后给出处理建议；
     不用「你看一眼」「用不了」「一台都找不到」这类口语，也不用感叹号。

对外函数：
  human_error(exc, module)   → (现象说明, 处理建议, 技术细节)
  human_units(units)         → "单元：全部单元" / "单元：听力专项 U2、U4"
  status_of(result)          → "ok" | "empty" | "failed"
  summary_text(results)      → 本轮结算的一句话（含 0 题警示）
  module_log(module, q)      → (模块结束的那句话, 日志级别)
  clean_step_text(text)      → 清掉 emoji / 坐标 / 异常串等机器痕迹
"""

import re

# ============================================================
# 模块层文案清洗（step_log 的唯一出口调用它）
# ============================================================
# ★ 2026-10-19 用户定调：「不需要特别口语化，就和正常 app 报错一样……
#   以第三人称讲述」。模块里的 step_log 是使用者直接看的流程日志，
#   因此不允许出现 emoji 图标、控件坐标、异常类名、内部变量名。
_EMOJI_RE = re.compile(
    "["
    "\U0001F000-\U0001FAFF"   # 图形符号（📖 📊 🎤 🎯 🎮 🏫 🏁 📄 ...）
    "\U00002600-\U000027BF"   # ✅ ❌ ⚠ ✏ ✔ ✘ ★
    "\U00002B00-\U00002BFF"   # ⭐ ⬇
    "\U00002300-\U000023FF"   # ⏹ ⏳ ⏭
    "\U000025A0-\U000025FF"   # ▶ ◀ ●
    "\U00002190-\U000021FF"   # ← → ↔ ↩ ↺ ⇒
    "\U00002500-\U0000257F"   # ─ │ ├ └ ═ ═
    "\U0000FE0F\U000020E3"    # 变体选择符 / 键帽
    "]+"
)
# 控件坐标：@(540,1200) —— 使用者看不出意义，只暴露实现细节
_COORD_RE = re.compile(r"\s*@\(\s*-?\d+\s*,\s*-?\d+\s*\)")
# 括号里的 Python 异常 repr：（KeyError: 'x'）/（TimeoutError）
_EXC_IN_PAREN_RE = re.compile(
    r"[（(]\s*(?:[A-Za-z_]+\.)*[A-Z][A-Za-z_]*(?:Error|Exception|Timeout)[^（）()]*[）)]"
)
# 连续空白
_WS_RE = re.compile(r"[ \t]{2,}")
# 日志尾巴上的裸异常：`登录失败: KeyError('x')` / `: URLError(...)`
#   —— 使用者只需要知道"失败了"，异常类型与消息属于技术细节（服务端日志里有原文）。
_EXC_TAIL_RE = re.compile(
    r"[:：]\s*(?:[A-Za-z_][\w.]*(?:Error|Exception|Timeout|Warning)\b.*"
    r"|\['.*$)", re.S)
# 调试用的屏幕坐标：`at (540, 1200)` / `at 540,1200`
_AT_COORD_RE = re.compile(r"\s+at\s+\(?\s*-?\d+\s*,\s*-?\d+\s*\)?")
# 置信度等调试字段：`(conf=0.87)`
_DEBUG_FIELD_RE = re.compile(r"\s*\((?:conf|rid|id|idx)=[^)]*\)")


# 括号里的内部字段名：（卡片 rid）/（resource-id / xpath / bounds）
_BRACKET_TECH_RE = re.compile(
    r"[（(][^）()]*\b(?:rid|resource-id|resourceId|xpath|bounds|selector)\b[^）()]*[）)]",
    re.I)


def clean_step_text(text) -> str:
    """把模块日志清成「给使用者看的一句话」。

    只做确定性清理，不改语义：
      1. 去掉 emoji / 装饰符号（用户明确要求前端不出现图标）；
      2. 去掉 `@(x,y)` 控件坐标；
      3. 去掉括号里的异常 repr（`（KeyError: 'x'）`）；
      4. 折叠多余空白，去掉行首缩进。
    真正的措辞问题（0 题却写「完成」、口语化）由各模块源码改，不靠这里兜。
    """
    s = str(text if text is not None else "")
    s = _EMOJI_RE.sub("", s)
    s = _COORD_RE.sub("", s)
    s = _EXC_IN_PAREN_RE.sub("", s)
    s = _BRACKET_TECH_RE.sub("", s)
    s = _WS_RE.sub(" ", s)
    s = s.replace("\u200b", "").replace("\ufeff", "")
    return s.strip()


def clean_log_text(text) -> str:
    """web_server.log_msg 出口用的强化清洗（在 clean_step_text 之上）。

    额外处理三类「只有写代码的人才看得懂」的残渣：
      - 行尾裸异常：`巡检失败: KeyError('x')` → `巡检失败`；
      - 调试坐标：`at (540, 1200)` → 删除；
      - 调试字段：`(conf=0.87)` → 删除。
    异常原文仍由 log_msg 打印到 server_output.log，排查时不受影响。
    """
    s = clean_step_text(text)
    s = _EXC_TAIL_RE.sub("", s)
    s = _AT_COORD_RE.sub("", s)
    s = _DEBUG_FIELD_RE.sub("", s)
    return s.strip().rstrip("：:，,；;")


# ============================================================
# 模块结束 → 三态结算文案
# ============================================================
def module_log(module: str, q, extra: str = ""):
    """模块跑完时该写的那句话，返回 (文案, 日志级别)。

    核心约束（试用反馈的根因）：**0 题不是完成**。
    旧代码无论 q 是几都写「XXX完成，共0题」+ success，
    前端于是出现「5 个模块检测完成、累计 0 题」这种自相矛盾的结论。
    """
    name = str(module or "").strip() or "本模块"
    try:
        q = int(q or 0)
    except Exception:
        q = 0
    tail = clean_step_text(extra or "")
    if q > 0:
        text = f"{name}检测完成，共检测到 {q} 道题"
        return ((text + (f"；{tail}" if tail else "") + "。"), "success")
    text = "本次已完整遍历该模块，App 内未出现可检测的题目，不计入检测结果"
    if tail:
        text += f"（{tail}）"
    return (f"{name}未检测到题目：{text}。", "warning")

_STATUS_OK = "ok"          # 真的测到了题
_STATUS_EMPTY = "empty"    # 跑完了，但一道题都没有 → 不算检测完成
_STATUS_FAILED = "failed"  # 中途出错 → 没有测成


# ============================================================
# 异常 → 可读说明
# ============================================================
def human_error(exc, module: str = ""):
    """把异常翻译成 (现象说明, 处理建议, 技术细节)。

    语气基准：与常规 App 报错一致——第三人称陈述现象，随后给出处理建议，
    不使用口语化表达与感叹号。判定只看**异常类型名 + 消息**。
    顺序有讲究：多设备 > 掉线 > 控件找不到 > 超时 > 连接中断 > 兜底。
    """
    raw = f"{type(exc).__name__}: {exc}"
    low = raw.lower()

    # ① 多台设备在线：u2/adb 无法确定操作对象
    if "more than one device" in low or "more than one emulator" in low:
        return (
            "检测到多台设备同时在线，无法确定操作目标",
            "请仅保留一台设备在线（断开多余的真机或关闭模拟器），并在页面中选中该设备后重新开始检测。",
            raw,
        )

    # ② 设备掉线 / adb 认不到这台机器
    if ("not found" in low and "device" in low) or "no devices" in low \
            or "device offline" in low or "device unauthorized" in low:
        return (
            "目标设备已离线，电脑端无法识别该设备",
            "请检查数据线连接与模拟器运行状态；待设备重新在线并在页面中显示后，重新开始检测。",
            raw,
        )

    # ③ 找不到要点的控件：App 没停在预期页面
    if "uiobjectnotfound" in low or "uiobjectnotfounderror" in low \
            or "不存在" in raw or "no such element" in low:
        return (
            "App 未停留在预期页面，未找到本步骤所需的控件",
            "请确认 App 当前停留在首页，且未被登录页、广告页或其他应用遮挡；返回首页后重新开始检测。",
            raw,
        )

    # ④ 超时
    if "timeout" in low or "timed out" in low:
        return (
            "等待 App 响应超时，页面未能在规定时间内加载完成",
            "请确认设备未锁屏、App 运行正常且网络可用，然后重新开始检测。",
            raw,
        )

    # ⑤ 连接被断开
    if "remote" in low and "closed" in low or "connection" in low \
            or "disconnect" in low or "broken pipe" in low or "reset by peer" in low:
        return (
            "与设备的连接已中断",
            "请重新连接设备，确认设备在线后重新开始检测。",
            raw,
        )

    # ⑥ 锁屏
    if "screen" in low and "off" in low:
        return (
            "设备处于锁屏状态，操作无法继续",
            "请解锁设备并关闭自动锁屏后重新开始检测。",
            raw,
        )

    # ⑦ 兜底：不把原始异常抛给使用者，但明确指出责任方与所需材料
    return (
        "本步骤执行中断，检测未完成",
        "此为程序异常，与 App 无关。请将本日志连同服务端日志 server_output.log "
        "提交给维护人员，修复后重新检测。",
        raw,
    )


# ============================================================
# 单元范围 → 人话
# ============================================================
def fmt_unit_value(v) -> str:
    """'2,4' / '2-4' / 3 / None / 'NONE' → 'U2、U4' / 'U2–U4' / '' """
    s = str(v if v is not None else "").strip()
    if not s or s.upper() == "NONE":
        return ""
    out = []
    for part in s.replace("，", ",").replace("、", ",").split(","):
        p = part.strip()
        if not p:
            continue
        if "-" in p:
            a, _, b = p.partition("-")
            if a.strip().isdigit() and b.strip().isdigit():
                out.append(f"U{a.strip()}–U{b.strip()}")
                continue
        if p.isdigit():
            out.append(f"U{p}")
        else:
            out.append(p)
    return "、".join(out)


def human_units(units, module_names=None) -> str:
    """把前端传来的单元字典写成测试员能读的一句话。

    旧日志直接 str(dict)：
        单元：{'听力专项': None, '听力专项_测试': None}
    测试员看不出"到底测哪几个单元"。新写法：
        单元：全部单元
        单元：听力专项 U2、U4；口语训练 U3
    """
    if not units:
        return "单元：全部单元"
    segs = []
    try:
        items = list(units.items())
    except Exception:
        return "单元：全部单元"
    for k, v in items:
        u = fmt_unit_value(v)
        if not u:
            continue
        label = str(k).replace("_测试", "·测试")
        segs.append(f"{label} {u}")
    if not segs:
        return "单元：全部单元"
    return "单元：" + "；".join(segs)


# ============================================================
# 模块结果 → 三态
# ============================================================
def status_of(result) -> str:
    """模块结果的三态。兼容旧数据（只有 ok / q 两个字段的）。

    关键：**0 题不是成功**。跑完了但一道题都没有 → empty（未检测）。
    这正是试用反馈里"5 个成功、累计 0 题"的根源：旧逻辑只看没抛异常就算成功。
    """
    r = result or {}
    s = str(r.get("status") or "").strip()
    if s in (_STATUS_OK, _STATUS_EMPTY, _STATUS_FAILED):
        return s
    if not r.get("ok"):
        return _STATUS_FAILED
    try:
        q = int(r.get("q") or 0)
    except Exception:
        q = 0
    return _STATUS_OK if q > 0 else _STATUS_EMPTY


def status_text(status: str) -> str:
    return {
        _STATUS_OK: "检测完成",
        _STATUS_EMPTY: "未检测到题目",
        _STATUS_FAILED: "检测中断",
    }.get(status or "", "未检测")


def count_status(results) -> dict:
    c = {_STATUS_OK: 0, _STATUS_EMPTY: 0, _STATUS_FAILED: 0}
    for r in (results or {}).values():
        c[status_of(r)] += 1
    return c


def summary_text(results) -> str:
    """本轮结算的一句话（供后端日志；前端另行渲染同样的口径）。"""
    results = results or {}
    n = len(results)
    c = count_status(results)
    total_q = 0
    for r in results.values():
        try:
            total_q += int((r or {}).get("q") or 0)
        except Exception:
            pass
    if n == 0:
        return "本轮未执行任何模块（模块列表为空）。"
    if total_q == 0:
        return (f"本轮结束：共 {n} 个模块，未检测到任何题目（0 题）。"
                f"其中 {c[_STATUS_EMPTY]} 个模块在 App 内未出现题目、"
                f"{c[_STATUS_FAILED]} 个检测中断、{c[_STATUS_OK]} 个正常结束。"
                f"本轮无有效检测内容，请核对版本、年级与单元设置后重新检测。")
    tail = f"累计 {total_q} 道题"
    if c[_STATUS_FAILED]:
        return (f"本轮结束：共 {n} 个模块（检测完成 {c[_STATUS_OK]} 个、"
                f"未检测到题目 {c[_STATUS_EMPTY]} 个、检测中断 {c[_STATUS_FAILED]} 个），"
                f"{tail}。")
    if c[_STATUS_EMPTY]:
        return (f"本轮结束：共 {n} 个模块（检测完成 {c[_STATUS_OK]} 个、"
                f"未检测到题目 {c[_STATUS_EMPTY]} 个），{tail}。")
    return f"本轮结束：{n} 个模块全部检测完成，{tail}。"
