# -*- coding: utf-8 -*-
"""
C3  错误输出文件夹
=================
把每道错题整理成一个文件夹（分工文档 5.3）：
   errors/新湘鲁六上_U6/模块A/Q03/   （按 版本_单元/模块/题号 分层）
      ├─ screenshot.png   (从 screenshots/ 复制的 APP 原图)
      ├─ marked.png       (画好红框的图，由 C2 生成)
      ├─ error.json       (溯源数据，由 C1 生成)
      └─ error_card.html  (红框图+错因合并卡片，单文件可直接发给老师)
"""

import os
import json
import base64
import shutil
from datetime import datetime
from src.trace_engine import TraceEngine

# e英语宝 跳转链接（想跳到具体题目时，把这里换成 e英语宝提供的专属链接即可）
# 默认指向官网：手机装了 App 时点它有机会直接唤起 App；电脑上则点开官网。
EYYB_APP_LINK = "https://m.eyyb.vip/"


def _norm_unit(seg):
    """把单元段统一成 'U6' 这种样子（'6'→'U6'，'U6'→'U6'）。"""
    seg = str(seg)
    return seg if seg.startswith("U") else f"U{seg}"


class ErrorCollector:
    """错误收集器：遍历所有题，把没过的题整理成 errors/ 文件夹。"""

    def __init__(self, output_root: str = "outputs"):
        self.output_root = output_root
        self.engine = TraceEngine()

    def collect(self, questions: dict, version: str, unit) -> dict:
        """
        输入：
           questions : inspection_state.json 里的 questions 字典
           version   : 教材名，如 "新湘鲁六上"
           unit      : 单元号，如 6 → 会拼成 "U6"
        输出（分工文档 5.3 约定的返回）：
           {"failed": 出错题数, "total": 总题数, "output_dir": 报告根目录}
        """
        now = datetime.now()
        today = now.strftime("%Y%m%d")
        ts = now.strftime("%H%M")

        # 先扫一遍所有"未通过"题，收集它们各自的版本/单元
        # —— 支持同一批里混多个版本/单元，给这次运行文件夹起合适名字
        _seen_versions, _seen_units = set(), set()
        for _qid, _qd in questions.items():
            if _qd.get("overall_passed") is not False:
                continue
            _p = _qid.split("-")
            if _p:
                _seen_versions.add(_p[0])
            if len(_p) >= 3:
                _seen_units.add(_norm_unit(_p[2]))

        # 输出根目录命名：
        #   单版本单单元 → 保留旧样式 版本/单元_日期_时分（如 新湘鲁六上/U6_20260730_1700）
        #   多版本/多单元 → 多版本_日期_时分（混批也不会归错类）
        if len(_seen_versions) == 1 and len(_seen_units) == 1:
            output_dir = os.path.join(self.output_root, next(iter(_seen_versions)),
                                      f"{next(iter(_seen_units))}_{today}_{ts}")
        else:
            output_dir = os.path.join(self.output_root, f"多版本_{today}_{ts}")
        errors_dir = os.path.join(output_dir, "errors")
        os.makedirs(errors_dir, exist_ok=True)

        total = len(questions)
        failed = 0

        for qid, qd in questions.items():
            if qd.get("overall_passed") is not False:
                continue  # 这题通过了，跳过

            failed += 1

            # 每题用【自己】的 qid 拆 版本/单元/题号，不再依赖整批统一的 version/unit
            # —— 一批数据里混了多个版本/单元，也会各自归到正确的文件夹
            _parts = qid.split("-")
            _own_version = _parts[0] if len(_parts) > 0 else "未知版本"
            _own_unit = _norm_unit(_parts[2] if len(_parts) >= 3 else "U0")
            # 短题号：取末尾的 "Q03"
            short = _parts[-1]

            # 模块：当作子文件夹名（把 Windows 路径非法字符替换成下划线，避免报错）
            # 优先用数据里的 module 字段；没有就从 qid 第2段读（"新湘鲁六上-模块A-U6-Q03" → "模块A"）
            _module = qd.get("module") or (_parts[1] if len(_parts) >= 2 else "未分类模块")
            for _ch in '/\\:*?"<>|':
                _module = _module.replace(_ch, "_")

            # 分层目录：errors/{本題版本}_{本題单元}/{模块}/{题号}/
            # 例：errors/新湘鲁六上_U6/模块A/Q03/
            q_dir = os.path.join(errors_dir, f"{_own_version}_{_own_unit}", _module, short)
            os.makedirs(q_dir, exist_ok=True)

            # 1) 复制 APP 原图到 screenshot.png
            src_shot = os.path.join(self.engine.screenshots_dir, qd.get("screenshot", ""))
            dst_shot = os.path.join(q_dir, "screenshot.png")
            if os.path.exists(src_shot):
                shutil.copy(src_shot, dst_shot)

            # 2) 生成溯源数据（C1）
            trace = self.engine.generate(qid, qd)

            # 3) 画红框（C2）
            marked_path = os.path.join(q_dir, "marked.png")
            if os.path.exists(src_shot):
                self.engine.draw_mark(qd.get("screenshot", ""), trace["checks"], marked_path)

            # 4) 写 error.json
            with open(os.path.join(q_dir, "error.json"), "w", encoding="utf-8") as f:
                json.dump(trace, f, ensure_ascii=False, indent=2)

            # 5) 生成合并卡片 error_card.html（红框图内嵌 + 错因表，发给老师用）
            self._build_card(qid, qd, trace, marked_path, q_dir)

        return {
            "failed": failed,
            "total": total,
            "output_dir": output_dir,
        }

    def _build_card(self, qid, qd, trace, marked_path, q_dir):
        """生成 error_card.html：把红框图(base64 内嵌)和错因表合并成一个文件。

        表格只有两列：『错误维度』(出错的是哪方面) ｜ 『原因』。
        不再单列"程度"(高/中/低)，因为老师看维度名更直观。
        """
        # 红框图转 base64 内嵌，保证单文件可独立打开、不依赖外部图片
        img_b64 = ""
        if os.path.exists(marked_path):
            with open(marked_path, "rb") as f:
                img_b64 = base64.b64encode(f.read()).decode("ascii")

        rows = ""
        for c in trace.get("checks", []):
            rows += (
                f'<tr>'
                f'<td>{c.get("dimension", "")}</td>'
                f'<td style="text-align:left">{c.get("reason", "")}</td>'
                f'</tr>'
            )
        if not rows:
            rows = '<tr><td colspan="2">（无具体错因记录）</td></tr>'

        # 从 qid 解析可读的"归属信息"，让卡片自带单元/版本/模块，不依赖外部文件
        # qid 格式：教材-模块-单元-题号，如 新湘鲁六上-模块A-U6-Q03
        _parts = qid.split("-")
        _ver = _parts[0] if len(_parts) > 0 else ""
        _mod = _parts[1] if len(_parts) > 1 else ""
        _unit = _parts[2] if len(_parts) > 2 else ""
        _qnum = _parts[-1] if _parts else qid
        ctx = f"教材：{_ver}　｜　模块：{_mod}　｜　单元：{_unit}　｜　题号：{_qnum}"

        sc = trace.get("script_context", {})
        card = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>错题卡片 · {qid}</title>
<style>
  body{{font-family:system-ui,"Microsoft YaHei",sans-serif;margin:20px;color:#222;}}
  h2{{font-size:18px;margin-bottom:6px;}}
  .meta{{color:#666;font-size:13px;margin-bottom:12px;}}
  .open-app{{display:inline-block;margin:4px 0 14px;padding:9px 16px;
            background:#1a73e8;color:#fff;text-decoration:none;border-radius:6px;font-size:14px;}}
  .open-app:hover{{background:#1558b0;}}
  img{{max-width:100%;border:1px solid #ddd;margin-bottom:12px;}}
  table{{border-collapse:collapse;width:100%;font-size:14px;}}
  th,td{{border:1px solid #ddd;padding:8px 10px;text-align:left;vertical-align:top;}}
  th{{background:#f5f5f5;}}
</style></head>
<body>
<h2>错题卡片 · {_qnum}</h2>
<p class="meta">{ctx}</p>
<p class="meta">原始题号：{qid}</p>
<a class="open-app" href="{EYYB_APP_LINK}" target="_blank" rel="noopener">在 e英语宝 中查看本题</a>
<img src="data:image/png;base64,{img_b64}" alt="红框标注图">
<table>
  <tr><th>错误维度</th><th>原因</th></tr>
  {rows}
</table>
<p class="meta">题干：{sc.get('stem', '')}</p>
<p class="meta">标准答案：{sc.get('answer', '')}</p>
</body></html>"""
        with open(os.path.join(q_dir, "error_card.html"), "w", encoding="utf-8") as f:
            f.write(card)
