# -*- coding: utf-8 -*-
"""
C4  HTML / CSV 报告
===================
生成三份文件（分工文档 5.3 / 5.4）：
   report_full.html    全貌报告（对 + 错都列）
   report_errors.html  仅错误报告
   summary.csv         错误汇总表
"""

import os
import csv
import html
from src.trace_engine import TraceEngine
from src.error_collector import EYYB_APP_LINK


def _module_of(qid: str, qd: dict) -> str:
    """取题目的'模块'。
    优先用数据里显式写的 module 字段；
    否则从 qid 解析（qid 格式：教材-模块-单元-题号，如 新湘鲁六上-模块A-U6-Q03）。
    """
    if qd.get("module"):
        return str(qd["module"])
    parts = qid.split("-")
    if len(parts) >= 4:
        return parts[1]
    return ""


class ReportExporter:
    """报告导出器：把题目数据渲染成网页和表格。"""

    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        self.engine = TraceEngine()
        os.makedirs(output_dir, exist_ok=True)

    # ---------------------------------------------------------------
    # 内部：生成一行 HTML 表格
    # ---------------------------------------------------------------
    def _render_row(self, qid, qd, include_all=True):
        passed = qd.get("overall_passed")
        # 仅错误报告时，跳过通过题
        if not include_all and passed is not False:
            return ""

        if passed is False:
            trace = self.engine.generate(qid, qd)
            details = "<br>".join(
                f"• [{c['dimension']}] {html.escape(c['reason'])}" for c in trace["checks"]
            )
            status = '<span style="color:#d00;font-weight:bold;">未通过</span>'
        else:
            details = "—"
            status = '<span style="color:#0a0;font-weight:bold;">通过</span>'

        module = _module_of(qid, qd)
        return f"""<tr>
  <td>{html.escape(qid)}</td>
  <td>{html.escape(module)}</td>
  <td>{html.escape(str(qd.get('question_type', '')))}</td>
  <td>{status}</td>
  <td>{details}</td>
</tr>"""

    # ---------------------------------------------------------------
    # 内部：拼完整 HTML 页面
    # ---------------------------------------------------------------
    def _build_html(self, questions, metadata, only_errors=False):
        rows = "\n".join(
            self._render_row(qid, qd, include_all=not only_errors)
            for qid, qd in questions.items()
        )
        title = "英语宝检测 · 全貌报告" if not only_errors else "英语宝检测 · 仅错误报告"
        return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>{title}</title>
<style>
  body{{font-family:system-ui,"Microsoft YaHei",sans-serif;margin:24px;color:#222;}}
  h1{{font-size:20px;}}
  .meta{{color:#666;font-size:13px;margin-bottom:8px;}}
  .open-app{{display:inline-block;margin:4px 0 14px;padding:9px 16px;
            background:#1a73e8;color:#fff;text-decoration:none;border-radius:6px;font-size:14px;}}
  .open-app:hover{{background:#1558b0;}}
  table{{border-collapse:collapse;width:100%;margin-top:12px;font-size:14px;}}
  th,td{{border:1px solid #ddd;padding:8px 10px;text-align:left;vertical-align:top;}}
  th{{background:#f5f5f5;}}
</style></head>
<body>
<h1>{title}</h1>
<p class="meta">教材：{html.escape(metadata.get('version',''))} ｜ 单元：{html.escape(str(metadata.get('unit','')))} ｜ 生成时间：{html.escape(metadata.get('time',''))}</p>
<a class="open-app" href="{EYYB_APP_LINK}" target="_blank" rel="noopener">点击进入 e英语宝 查看本题</a>
<table>
<tr><th>题号</th><th>模块</th><th>题型</th><th>状态</th><th>错误详情</th></tr>
{rows}
</table>
</body></html>"""

    # ---------------------------------------------------------------
    # 对外方法（签名按分工文档 5.4）
    # ---------------------------------------------------------------
    def export_html_full(self, questions: dict, metadata: dict) -> str:
        """生成全貌 HTML 报告 → 返回文件路径"""
        path = os.path.join(self.output_dir, "report_full.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(self._build_html(questions, metadata, only_errors=False))
        return path

    def export_html_errors(self, questions: dict, metadata: dict) -> str:
        """生成仅错误 HTML 报告 → 返回文件路径（文档 5.3 要求的 report_errors.html）"""
        path = os.path.join(self.output_dir, "report_errors.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(self._build_html(questions, metadata, only_errors=True))
        return path

    def export_csv(self, questions: dict) -> str:
        """生成错误 CSV → 返回文件路径"""
        path = os.path.join(self.output_dir, "summary.csv")
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["qid", "module", "question_type", "overall_passed", "failed_dimensions", "reasons"])
            for qid, qd in questions.items():
                if qd.get("overall_passed") is not False:
                    continue
                trace = self.engine.generate(qid, qd)
                dims = ";".join(c["dimension"] for c in trace["checks"])
                reasons = ";".join(c["reason"] for c in trace["checks"])
                w.writerow([qid, _module_of(qid, qd), qd.get("question_type", ""), "False", dims, reasons])
        return path
