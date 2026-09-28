"""
src/report_exporter.py — 报告生成 & 导出
负责人：C

职责：
  1. 生成 HTML 报告（全部题目 + 仅错误题目）
  2. 生成 CSV 表格（方便老师导入 Excel 批注）
  3. 打包错误截图 zip
  4. 按版本/Unit/日期组织输出目录结构

调用方：
  routes/export_routes.py → 各导出 API
  src/batch_runner.BatchRunner → 批量跑完自动调用

输出目录结构约定:
  {save_dir}/
    ├── 新湘鲁六上/
    │   ├── U6_基础巩固_20260728/
    │   │   ├── report_full.html       # 全量报告
    │   │   ├── report_errors.html     # 仅错误报告
    │   │   ├── errors.csv             # 错误表格
    │   │   └── screenshots/           # 错误截图
    │   │       ├── q03.png
    │   │       └── q07.png
    │   └── U7_基础巩固_20260728/
    │       └── ...
    └── latest/                        # 快捷入口：软链到最新
        └── report.html
"""

import json
import csv
import io
import shutil
import html
import re
from pathlib import Path
from datetime import datetime
from typing import Optional


# ============================================================
# HTML 报告模板（内联 CSS，无外部依赖）
# ============================================================

_HTML_CSS = """
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
         background:#f5f7fa; color:#333; line-height:1.6; padding:20px; }
  .container { max-width:1100px; margin:0 auto; }
  h1 { font-size:24px; margin-bottom:4px; }
  .meta { color:#888; font-size:13px; margin-bottom:20px; }

  /* 汇总卡片 */
  .summary { display:flex; gap:16px; flex-wrap:wrap; margin-bottom:24px; }
  .summary-card { flex:1; min-width:140px; background:#fff; border-radius:10px;
                   padding:18px 20px; box-shadow:0 1px 4px rgba(0,0,0,.08); text-align:center; }
  .summary-card .num { font-size:32px; font-weight:700; }
  .summary-card .label { font-size:12px; color:#999; margin-top:4px; }
  .s-pass .num { color:#2ecc71; }
  .s-fail .num { color:#e74c3c; }
  .s-uncertain .num { color:#f39c12; }
  .s-conf .num { color:#3498db; }

  /* 题目卡片 */
  .q-card { background:#fff; border-radius:10px; padding:20px 24px;
             margin-bottom:16px; box-shadow:0 1px 4px rgba(0,0,0,.08);
             border-left:5px solid #ddd; transition:border-color .2s; }
  .q-card.pass { border-left-color:#2ecc71; }
  .q-card.fail { border-left-color:#e74c3c; }
  .q-card.uncertain { border-left-color:#f39c12; }
  .q-header { display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; }
  .q-title { font-size:18px; font-weight:600; }
  .q-type { color:#888; font-size:13px; background:#f0f0f0; padding:2px 10px; border-radius:12px; }
  .q-badge { font-size:13px; padding:3px 12px; border-radius:12px; font-weight:600; }
  .q-badge.pass { background:#e8f8f0; color:#27ae60; }
  .q-badge.fail { background:#fde8e8; color:#e74c3c; }
  .q-badge.uncertain { background:#fef5e7; color:#e67e22; }

  /* 维度条 */
  .dim-grid { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
  @media (max-width:600px) { .dim-grid { grid-template-columns:1fr; } }
  .dim-row { display:flex; align-items:center; gap:8px; font-size:13px; }
  .dim-name { width:40px; color:#888; flex-shrink:0; }
  .dim-bar-wrap { flex:1; height:14px; background:#eee; border-radius:7px; overflow:hidden; position:relative; }
  .dim-bar { height:100%; border-radius:7px; transition:width .4s; }
  .dim-bar.pass { background:#2ecc71; }
  .dim-bar.fail { background:#e74c3c; }
  .dim-bar.uncertain { background:#f39c12; }
  .dim-val { width:80px; font-size:12px; text-align:right; flex-shrink:0; }

  /* 详情说明 */
  .details { margin-top:10px; font-size:12px; color:#666; border-top:1px solid #eee; padding-top:10px; }
  .detail-item { margin:2px 0; }
  .detail-item.uncertain { color:#e67e22; font-weight:600; }

  /* 置信度指示器 */
  .conf-dot { display:inline-block; width:8px; height:8px; border-radius:50%; margin-right:4px; }
  .conf-high { background:#2ecc71; }
  .conf-mid { background:#f39c12; }
  .conf-low { background:#e74c3c; }

  .footer { text-align:center; color:#bbb; font-size:12px; margin-top:30px; }
  .no-data { text-align:center; padding:60px 0; color:#bbb; font-size:16px; }

  /* 导出按钮 */
  .toolbar { display:flex; gap:10px; margin-bottom:20px; flex-wrap:wrap; }
  .btn { padding:8px 18px; border:none; border-radius:6px; cursor:pointer; font-size:13px; font-weight:600; transition:opacity .2s; }
  .btn:hover { opacity:.85; }
  .btn-primary { background:#3498db; color:#fff; }
  .btn-outline { background:#fff; color:#3498db; border:1px solid #3498db; }

  @media print { body { background:#fff; padding:0; } .q-card { box-shadow:none; break-inside:avoid; } }
</style>
"""


class ReportExporter:
    """报告导出器 — 支持 HTML / CSV / ZIP"""

    def __init__(self, save_dir: str = None):
        base = Path(save_dir or str(Path(__file__).parent.parent / "outputs" / "reports"))
        self.save_dir = Path(base)
        self.save_dir.mkdir(parents=True, exist_ok=True)

    # ============================================================
    # 题干清洗（过滤状态栏时间/得分/进度等 UI 噪音）
    # ============================================================
    @staticmethod
    def _clean_stem(stem: str) -> str:
        """清洗题干：去掉状态栏时间(21:12)/得分(77.0)/进度(3/40)/百分比(100%)等 UI 噪音。
        按 engine 提取时的连接符" / "拆分，逐段判定；返回清洗后的题干，空则返回空串。"""
        s = (stem or "").strip()
        if not s:
            return ""
        _noise = re.compile(
            r"^(?:"
            r"还剩[：:]?\s*\d{1,2}:\d{2}"   # 还剩 19:58
            r"|\d{1,2}:\d{2}"               # 21:12
            r"|\d+\.?\d*\s*%"               # 77.0% / 100%
            r"|\d+\s*/\s*\d+"               # 3/40
            r"|\d+\.\d+"                    # 77.0
            r"|\d+"                         # 100
            r"|第\d+题"                     # ★ 第25题（题号占位，非题干）
            r")\s*$"
        )
        # ★ 题号占位题干："第4题（听音选择词汇）" → 去掉"第N题（"前缀保留题型
        # ★ 2026-09-20 修正：旧写法不管有没有剥掉前缀，都无条件去掉**结尾**括号 →
        #   像"第3大题·第3题（口语训练）"这种正常标签会被啃成"…（口语训练"（缺右括号）。
        #   只有当确实剥掉了"第N题（"这个**左**括号时，才去掉配对的**右**括号。
        _stripped = re.sub(r"^第\d+题[（(]", "", s)
        if _stripped != s:
            s = re.sub(r"[）)]\s*$", "", _stripped)
        # 按 engine 连接符拆（" / " 及兼容的 |｜·），中文逗号属于题干本身不拆
        parts = [p.strip() for p in re.split(r"\s*(?:/|｜|\|)\s*", s)]
        clean = [p for p in parts if p and not _noise.match(p)]
        out = " / ".join(clean)
        return out[:120] if out else ""

    def _loc_label(self, q: dict, meta: dict = None) -> str:
        """生成题目定位标签：
        - 脚本审查题（口语训练）：模块 · 脚本审查 · U3·第2大题·第4小题（可快速定位）
        - 跑题/快查：模块 · 子模块 · 第N题（如：听力专项 · 练习 · 第3题）
        """
        mod = (q.get("module", "") or "").strip()
        stage = (q.get("stage", "") or "").strip()
        if not mod:
            qid = q.get("qid", "")
            _m = re.match(r"^([^-]+)-?([^-]*)$", qid or "")
            if _m and _m.group(1) not in ("", "auto", "quick"):
                mod = _m.group(1)
        # ★ 2026-08-25 口语训练错题定位：脚本审查题用 position 字段（"U3·第2大题·第4小题"），
        #   不再笼统显示"口语训练·第45题"（口语训练脚本 100 题，Q45 定位不到具体页）
        _pos = (q.get("position") or "").strip()
        _note = q.get("note", "") or ""
        if _pos and ("脚本" in _note or (q.get("qid", "") or "").find("-脚本-") >= 0):
            return f"{mod} · 脚本审查 · {_pos}"
        # ★ 2026-09-20：口语训练的 auto-* 基础记录带的是 progress（"大4-Q3"）而不是
        #   position → 旧代码一路落到最后一行，卡片标题只剩模块名"口语训练"，
        #   检查人员在报告里定位不到具体题（用户明确要求"必须明确题目位置"）。
        _mp = re.match(r"^大(\d+)\s*-\s*Q(\d+)$", str(q.get("progress") or "").strip())
        if _mp:
            _u = str(q.get("_unit") or (meta or {}).get("unit") or "").strip()
            _p = f"第{_mp.group(1)}大题·第{_mp.group(2)}小题"
            return f"{mod} · U{_u} · {_p}" if _u and _u.isdigit() else f"{mod} · {_p}"
        qno = q.get("module_qno") or q.get("idx") or q.get("progress") or "?"
        if isinstance(qno, float):
            qno = int(qno) if qno == int(qno) else qno
        return f"{mod} · {stage}" if stage else str(mod)

    # ============================================================
    # HTML 报告
    # ============================================================

    def export_html_full(self, questions: list[dict], metadata: dict = None,
                         only_errors: bool = False) -> str:
        """
        生成完整的 self-contained HTML 报告。

        Args:
            questions: 题目列表，每个元素为 dict，格式同 inspection_state.json 的 questions 条目
            metadata: {"version": "新湘鲁六上", "unit": 6, "stage": "基础巩固", "docx": "..."}
            only_errors: True=仅导出错误题目
        Returns:
            报告文件路径
        """
        meta = metadata or {}
        version = meta.get("version", "未知版本")
        unit = meta.get("unit", "?")
        stage = meta.get("stage", "?")
        date_str = meta.get("date", datetime.now().strftime("%Y-%m-%d %H:%M"))

        qs = [q for q in questions if not only_errors or not q.get("overall_passed", True)]
        if not qs:
            # 无结果时也生成一个空报告
            html = self._render_html([], meta, only_errors)
        else:
            html = self._render_html(qs, meta, only_errors)

        # 写入文件
        filename = "report_errors.html" if only_errors else "report_full.html"
        out_dir = self.organize_output_dir(version, unit, stage)
        out_path = out_dir / filename
        out_path.write_text(html, encoding="utf-8")
        return str(out_path)

    def export_html_errors(self, questions: list[dict], metadata: dict = None) -> str:
        """仅导出错误题目HTML"""
        return self.export_html_full(questions, metadata, only_errors=True)

    # ============================================================
    # 内部 HTML 渲染
    # ============================================================

    def _render_html(self, questions: list[dict], metadata: dict,
                     only_errors: bool) -> str:
        meta = metadata or {}
        version = meta.get("version", "未知版本")
        unit = meta.get("unit", "?")
        stage = meta.get("stage", "?")
        date_str = meta.get("date", datetime.now().strftime("%Y-%m-%d %H:%M"))

        total = len(questions)
        passed = sum(1 for q in questions if q.get("overall_passed"))
        failed = total - passed
        uncertain = sum(1 for q in questions if q.get("error_dimensions", []))
        # ★ 2026-09-10 修复：下面 HTML 模板里引用了 {pass_rate} 但从未定义 →
        #   生成报告时直接抛 NameError（"查看报告"整体失败；tests/test_e2e_pipeline.py 同错）。
        pass_rate = round(passed / total * 100) if total else 0

        # 平均置信度
        confs = []
        for q in questions:
            for dim in ["stem_reason", "content_reason", "image_reason", "answer_reason"]:
                if dim in q and q[dim]:
                    confs.append(80)  # 粗略估计，后续可从 details 中提取
        avg_conf = round(sum(confs) / len(confs)) if confs else 0

        cards_html = "\n".join(self._render_question(q) for q in questions)

        title = f"英语宝题目审查报告 — {version} U{unit} {stage}"
        if only_errors:
            title += "（仅错误）"

        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
{_HTML_CSS}
</head>
<body>
<div class="container">

  <h1>{title}</h1>
  <div class="meta">生成时间: {date_str} | 版本: {version} | Unit {unit} {stage} | 题目数: {total}</div>

  <div class="summary">
    <div class="summary-card s-pass"><div class="num">{passed}</div><div class="label">通过</div></div>
    <div class="summary-card s-fail"><div class="num">{failed}</div><div class="label">不通过</div></div>
    <div class="summary-card s-uncertain"><div class="num">{uncertain}</div><div class="label">需人工复核</div></div>
    <div class="summary-card s-conf"><div class="num">{avg_conf}%</div><div class="label">平均置信度</div></div>
    <div class="summary-card"><div class="num">{pass_rate}%</div><div class="label">通过率</div></div>
  </div>

  <div class="toolbar">
    <button class="btn btn-primary" onclick="window.print()">打印报告</button>
    <button class="btn btn-outline" onclick="document.querySelectorAll('.details').forEach(d=>d.style.display=d.style.display==='none'?'block':'none')">展开/收起详情</button>
  </div>

  {cards_html if questions else no_data_html}

  <div class="footer">英语宝审查智能体 v3 · 自动生成 · 仅供参考，最终判定以人工确认为准</div>

</div>
</body>
</html>"""

    def _render_question(self, q: dict) -> str:
        """渲染单道题目卡片"""
        qid = q.get("qid", "?")
        idx = q.get("idx", 0)
        qtype = q.get("question_type", "?")
        stem = self._clean_stem(q.get("stem", ""))[:60]
        overall_passed = q.get("overall_passed", False)
        error_dims = q.get("error_dimensions", [])

        # 判断状态
        if error_dims:
            card_class = "uncertain"
            badge_class = "uncertain"
            badge_text = "⚠ 需人工复核"
        elif overall_passed:
            card_class = "pass"
            badge_class = "pass"
            badge_text = "通过"
        else:
            card_class = "fail"
            badge_class = "fail"
            badge_text = "不通过"

        # 各维度状态
        dims = [
            ("题干", "stem_reason", q.get("stem_reason", "")),
            ("内容", "content_reason", q.get("content_reason", "")),
            ("配图", "image_reason", q.get("image_reason", "")),
            ("作答", "answer_reason", q.get("answer_reason", "")),
        ]

        dim_rows = []
        for dname, dattr, dreason in dims:
            val = q.get(f"ai_{dattr.replace('_reason','')}", False) if dattr.endswith("_reason") else None
            # 从 details 中判断
            dim_passed = dname not in error_dims
            if dreason:
                if "通过" in dreason and "不通过" not in dreason:
                    dim_passed = True
                elif "不通过" in dreason:
                    dim_passed = False
                elif "需人工复核" in dreason or "无法解析" in dreason:
                    dim_passed = None

            bar_class = "pass" if dim_passed is True else ("fail" if dim_passed is False else "uncertain")
            bar_pct = 100 if dim_passed is True else (30 if dim_passed is False else 50)
            label = "通过" if dim_passed is True else ("不通过" if dim_passed is False else "不确定")

            dim_rows.append(f"""<div class="dim-row">
  <span class="dim-name">{dname}</span>
  <div class="dim-bar-wrap"><div class="dim-bar {bar_class}" style="width:{bar_pct}%"></div></div>
  <span class="dim-val">{label}</span>
</div>""")

        details_html = ""
        for dname, dattr, dreason in dims:
            if dreason:
                cls = "detail-item"
                if "需人工复核" in dreason or "无法解析" in dreason:
                    cls += " uncertain"
                details_html += f'<div class="{cls}"><strong>{dname}:</strong> {dreason[:200]}</div>'

        return f"""<div class="q-card {card_class}">
  <div class="q-header">
    <span class="q-title">Q{idx} {stem}</span>
    <span class="q-type">{qtype}</span>
    <span class="q-badge {badge_class}">{badge_text}</span>
  </div>
  <div class="q-loc">{self._loc_label(q)} · 第{idx}题</div>
  <div class="dim-grid">
    {''.join(dim_rows)}
  </div>
  {"<div class='details'>" + details_html + "</div>" if details_html else ""}
</div>"""

    # ============================================================
    # CSV 导出
    # ============================================================

    def export_csv(self, questions: list[dict], only_errors: bool = True) -> str:
        """导出错误题目CSV"""
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([
            "题号", "题型", "题干", "脚本答案", "综合得分",
            "综合通过", "错误维度", "题干判定", "内容判定", "配图判定", "作答判定",
            "需人工复核", "截图",
        ])

        for q in questions:
            if only_errors and q.get("overall_passed"):
                continue
            dims = q.get("error_dimensions", [])
            writer.writerow([
                q.get("qid", ""), q.get("question_type", ""),
                (q.get("stem") or "")[:60], q.get("script_answer", ""),
                q.get("overall_score", 0),
                "是" if q.get("overall_passed") else "否",
                ", ".join(dims) if dims else "无",
                q.get("stem_reason", ""), q.get("content_reason", ""),
                q.get("image_reason", ""), q.get("answer_reason", ""),
                "是" if dims else "否",
                q.get("screenshot", ""),
            ])

        csv_path = self.save_dir / f"errors_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        csv_path.write_text(buf.getvalue(), encoding="utf-8-sig")
        return str(csv_path)

    # ============================================================
    # 截图打包
    # ============================================================

    def export_screenshots_zip(self, questions: list[dict], shots_dir: str = None) -> str:
        """打包错误截图"""
        import zipfile

        shots = Path(shots_dir or Path(__file__).parent.parent / "screenshots")
        zip_path = self.save_dir / f"screenshots_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"

        with zipfile.ZipFile(zip_path, "w") as zf:
            for q in questions:
                if not q.get("overall_passed") or q.get("error_dimensions"):
                    shot = q.get("screenshot", "")
                    if shot:
                        shot_path = shots / shot
                        if shot_path.exists():
                            zf.write(shot_path, f"{q.get('qid','')}_{shot}")
                        else:
                            # 尝试绝对路径
                            shot_path = Path(shot)
                            if shot_path.exists():
                                zf.write(shot_path, f"{q.get('qid','')}_{shot_path.name}")

        return str(zip_path)

    # ============================================================
    # 输出目录管理
    # ============================================================

    def organize_output_dir(self, version: str, unit: int, stage: str) -> Path:
        """创建按版本/Unit/日期组织的输出目录"""
        date_str = datetime.now().strftime('%Y%m%d')
        dir_name = f"U{unit}_{stage}_{date_str}"
        out_dir = self.save_dir / version / dir_name
        out_dir.mkdir(parents=True, exist_ok=True)

        # 更新 latest 快捷入口
        latest = self.save_dir / "latest"
        if latest.exists():
            import os
            if latest.is_symlink() or latest.is_dir():
                try:
                    latest.unlink()
                except Exception:
                    pass
        # Windows 上用 junction 模拟软链
        try:
            import os, sys
            if sys.platform == "win32":
                import shutil
                if latest.exists():
                    shutil.rmtree(latest, ignore_errors=True)
                shutil.copytree(str(out_dir), str(latest), dirs_exist_ok=True)
            else:
                if not latest.exists():
                    latest.symlink_to(out_dir, target_is_directory=True)
        except Exception:
            pass

        return out_dir

    # ============================================================
    # 一键导出（批量跑完后自动调用）
    # ============================================================

    def export_all(self, questions: list[dict], metadata: dict = None,
                   shots_dir: str = None, version: str = None,
                   unit: int = 0, stage: str = "") -> dict:
        """
        一键导出所有格式（HTML + CSV + ZIP）。

        Returns:
            {"html_full": "...", "html_errors": "...", "csv": "...", "zip": "..."}
        """
        meta = metadata or {}
        if version:
            meta.setdefault("version", version)
        if unit:
            meta.setdefault("unit", unit)
        if stage:
            meta.setdefault("stage", stage)

        results = {}
        results["html_full"] = self.export_html_full(questions, meta)
        results["html_errors"] = self.export_html_errors(questions, meta)
        results["csv"] = self.export_csv(questions)
        results["zip"] = self.export_screenshots_zip(questions, shots_dir)

        if version and unit and stage:
            results["output_dir"] = str(self.organize_output_dir(version, unit, stage))

        return results

    # ============================================================
    # DOCX 错题报告（给检查人员查看：按模块分组，含位置/原因/建议/截图）
    # ============================================================

    @staticmethod
    def _parse_qid(qid: str):
        """从题目 key 解析位置信息 → (module, unit, stage, qno)
        支持格式:
          - "听力专项-脚本-Q19"          → (听力专项, 脚本, 无stage, 19)
          - "auto-Q001"                 → (auto, 无, 无, 1)
          - "听力专项-脚本-U6-Q19"       → (听力专项, 脚本, U6, 19)
        """
        s = str(qid)
        m = re.match(r"^(.*?)-?(?:[Qq]0*(\d+))?$", s)
        module = "未知模块"
        stage = ""
        qno = ""
        # 拆出题号
        qm = re.search(r"[Qq]0*(\d+)", s)
        if qm:
            qno = qm.group(1)
        # 拆模块名（第一个 - 前）
        if "-" in s:
            module = s.split("-")[0].strip()
        # 拆阶段（基础巩固/综合进阶/难点突破/脚本 等）
        sm = re.search(r"(基础巩固|综合进阶|难点突破|脚本|练习|测试|单元评价|AI检测)", s)
        if sm:
            stage = sm.group(1)
        return module, "", stage, qno

    @classmethod
    def _script_provenance_lines(cls, meta: dict) -> list:
        """★ 2026-09-21：脚本溯源 → 可读文案 [(level, text)]，level ∈ ok/bad/unk。

        用户连续反馈"没测过的题也乱报"。有了它，报告头部就能直接写明本次结论
        是拿哪份脚本比出来的、这份脚本配不配得上本次运行 —— 不配就明确警告，
        检查人员不会再把"拿错脚本比出来的假错"当真。
        """
        prov = (meta or {}).get("script_provenance") or {}
        out = []
        if not prov:
            return [("unk", "本次运行的比对脚本来源未记录（旧版本产物）→ 脚本相关结论请人工复核")]
        for mod, p in prov.items():
            if not isinstance(p, dict):
                continue
            _f = (p.get("file") or "").strip()
            if p.get("matched") is True:
                out.append(("ok", f"{mod}：比对脚本「{_f or '已挂载'}」（版本/年级匹配 ✓）"))
            else:
                _r = (p.get("reason") or "未挂载对应脚本").strip()
                out.append(("bad", f"{mod}：未做脚本层比对 —— {_r}。"
                                   f"该题单中的脚本相关结论不作为判定依据"))
        return out

    def export_docx(self, questions: list[dict], metadata: dict = None) -> str:
        """生成按模块分组的错题报告 DOCX（检查人员专用）。

        结构:
          标题（版本/日期/总览统计）
          一、模块 A（X 题错）
            · 第N题 [题型] —— 位置说明
              - 出错位置：模块 · 单元 · 第N题
              - 出错理由：...
              - 改进建议：...
              [嵌入截图]
          二、模块 B ...
        """
        try:
            from docx import Document
            from docx.shared import Pt, Inches, RGBColor
            from docx.enum.text import WD_ALIGN_PARAGRAPH
            from docx.enum.table import WD_TABLE_ALIGNMENT
        except ImportError as e:
            print(f"  ⚠ python-docx 不可用: {e}")
            return ""

        meta = metadata or {}
        version = meta.get("version", "未知版本")
        date_str = meta.get("date", datetime.now().strftime("%Y-%m-%d %H:%M"))

        # 只取错题（overall_passed=False 或 question_type=错题截图）
        errors = [q for q in questions
                  if q.get("overall_passed") is False
                  or q.get("question_type") == "错题截图"]
        if not errors:
            errors = [q for q in questions
                      if q.get("overall_passed") is False
                      or q.get("question_type") == "错题截图"]
            # 仍无 → 尝试取所有（报告空白不好看）
            if not errors and questions:
                errors = [q for q in questions
                          if not q.get("overall_passed", True)]

        # 按模块分组（保持出现顺序）
        # ★ 分组：优先用记录里的 module/stage 字段（错题定位：哪个模块·哪个子模块）
        #   找不到再退回 qid 解析（听力专项-脚本-Q19）；question_type 是"题型"不是模块名，不做分组依据
        groups = {}   # module_key -> {"name":..., "items":[...]}
        order = []
        for q in errors:
            qid = q.get("qid", "")
            if not qid:
                qid = f"auto-Q{int(q.get('idx', 1)):03d}"
            # ① 优先 module 字段（web_server 记录时写入）
            mod = (q.get("module", "") or "").strip()
            stage = (q.get("stage", "") or "").strip()
            if not mod:
                # ② 从 qid 解析（有脚本格式：听力专项-脚本-Q19）
                mod, unit, stage2, qno = self._parse_qid(qid)
                if not stage:
                    stage = stage2
                if mod == "未知模块":
                    # ③ 退回 question_type（仅当 module 完全缺失时，如旧数据）
                    qtype = (q.get("question_type", "") or "").strip()
                    qt_clean = re.sub(r"[（(].*?[）)]", "", qtype).strip()
                    if qt_clean and qt_clean not in ("错题截图", "?", "", "未知题型"):
                        mod = qt_clean
                    else:
                        mod = "其他"
            key = f"{mod}|{stage}" if stage else mod
            if key not in groups:
                groups[key] = {"name": f"{mod}" + (f" · {stage}" if stage else ""),
                               "items": []}
                order.append(key)
            groups[key]["items"].append(q)

        doc = Document()

        # 标题
        title = doc.add_heading(f"英语宝错题报告", level=0)
        title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        # ★ 美化：大标题深绿色加粗 + 微软雅黑
        for run in title.runs:
            run.font.color.rgb = RGBColor(0x1B, 0x43, 0x32)  # 深绿
            run.font.name = "微软雅黑"
            run.font.bold = True
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run(f"版本：{version}　|　生成时间：{date_str}")
        run.font.size = Pt(10.5)
        run.font.color.rgb = RGBColor(0x88, 0x88, 0x88)
        run.font.name = "微软雅黑"

        # 总览
        h_summary = doc.add_heading("总览", level=1)
        for run in h_summary.runs:
            run.font.color.rgb = RGBColor(0x2D, 0x6A, 0x4F)  # 中绿
            run.font.name = "微软雅黑"
            run.font.bold = True
            run.font.size = Pt(15)
        summary = doc.add_paragraph()
        total_err = len(errors)
        total_q = len(questions)
        sum_run = summary.add_run(
            f"共检测 {total_q} 题，其中错题/需复核 {total_err} 题，涉及 {len(groups)} 个模块板块。"
        )
        sum_run.font.name = "微软雅黑"
        sum_run.font.size = Pt(11)

        # ★ 2026-09-21：脚本溯源（本次结论拿哪份脚本比出来的、配不配得上）
        for _lv, _txt in self._script_provenance_lines(metadata or {}):
            _pp = doc.add_paragraph()
            _pr = _pp.add_run(f"【脚本比对来源】{_txt}")
            _pr.font.name = "微软雅黑"
            _pr.font.size = Pt(10.5)
            _pr.font.bold = (_lv != "ok")
            _pr.font.color.rgb = {"ok": RGBColor(0x2D, 0x6A, 0x4F),
                                  "bad": RGBColor(0xB0, 0x2A, 0x1E),
                                  "unk": RGBColor(0xA8, 0x6E, 0x00)}.get(_lv, RGBColor(0x66, 0x66, 0x66))

        # 每个模块板块
        for ki, key in enumerate(order, 1):
            g = groups[key]
            h_grp = doc.add_heading(f"{ki}. {g['name']}（错题 {len(g['items'])} 题）", level=1)
            # ★ 美化：模块分组标题中绿色（#2d6a4f）+ 微软雅黑
            for run in h_grp.runs:
                run.font.color.rgb = RGBColor(0x2D, 0x6A, 0x4F)
                run.font.name = "微软雅黑"
                run.font.bold = True
                run.font.size = Pt(14)

            # ★ 组内按 idx 升序排，并重新分配 module_qno（按 stage 从 1 开始计）
            #   解决"第 25 题"问题：脚本 idx 是全局号（基础巩固 1-14 / 综合进阶 15-24 /
            #   难点突破 25-31），但显示应按 stage 内子题号
            sorted_items = sorted(g["items"], key=lambda x: x.get("idx", 0))
            for qi, q in enumerate(sorted_items, 1):
                qid = q.get("qid", "")
                qtype = q.get("question_type", "未知题型")
                qno = q.get("progress", "") or qid
                # ★ 子模块内题号：qi 已是 stage 内顺序（1起）
                #   但原 module_qno 字段是脚本全局 idx 1-31，必须用 qi
                idx = qi

                # 位置说明（★ 已在分组大标题下展示模块，题内只写第几题）
                # 位置说明（★ 2026-08-25 口语训练脚本审查题用 position：U3·第2大题·第4小题；
                #   跑题/快查无 position 时回退"第N题"）
                _pos = (q.get("position") or "").strip()
                if _pos:
                    loc_str = _pos
                else:
                    # ★ 2026-09-20 修复「<｜hy_place▁holder▁no▁813｜>定位错位」：口语训练的大题/小题结构下
                    #   position 常常为空，旧逻辑退回"第{idx}题"，而 idx 是分组内序号
                    #   （1,2,3…）→ 第3大题第2小题被标成"第3题"，和题干里的
                    #   "第3大题·第2题"自相矛盾，检查人员按图索骥会找错题。
                    #   记录自带 big（大题号）与 idx（小题号），直接拼准确定位。
                    #   ★ 小题号必须取记录自带的 idx（= App 真实小题号），不能用分组序号
                    #     qi —— 否则标题会比题干多一位（第3小题 ↔ 第2题）。
                    _big = q.get("big")
                    if _big:
                        loc_str = f"第{_big}大题·第{q.get('idx') or qi}小题"
                    else:
                        # 脚本审查题（idx 是跨阶段全局号 1-31）仍按阶段内重编号
                        loc_str = f"第{idx}题"

                # 题型标题
                h = doc.add_heading(f"{qi}. {loc_str}　[{qtype}]", level=2)
                # ★ 美化：每题标题深灰色
                for run in h.runs:
                    run.font.color.rgb = RGBColor(0x1A, 0x20, 0x2C)  # 近黑
                    run.font.name = "微软雅黑"
                    run.font.bold = True
                    run.font.size = Pt(12.5)

                # 位置（★ 显示"模块 · 子模块 · 第N题"完整路径，检查人员一目了然）
                p = doc.add_paragraph()
                p.add_run("▸ 在 App 中的位置：").bold = True
                p.add_run(f"{g['name']} · {loc_str}")

                # 题干（★ 清洗掉时间/得分等 UI 噪音，非空才展示）
                _stem_clean = self._clean_stem(q.get("stem", ""))
                if _stem_clean:
                    p = doc.add_paragraph()
                    p.add_run("▸ 题干：").bold = True
                    p.add_run(_stem_clean)

                # ★ 6 维度 reason 合并：按"维度:原因"形式拼成一条综合理由（避免重复）
                #   用户实测原版 reasons.append(f"{dim_name}：{r}") 把"内容"维度的同一条
                #   错误重复 push 多条，且改进建议全 fallback 到"人工复核"
                #   → 改为：每个失败维度只取最关键一条，最终拼成 1-2 条简洁理由
                #   ★ 仅 ai_field=False 的维度才算失败（REVIEW/待审/未检=None 不入错题）
                dim_failures = []
                for dim_name, reason_field, ai_field in self._LIVE_DIMS:
                    ai_fail = q.get(ai_field) is False
                    if not ai_fail:
                        continue  # ★ 只收明确不通过的维度
                    r = (q.get(reason_field, "") or "").strip()
                    if not r:
                        r = "未通过"
                    # ★ 截短 reason（避免整段 LLM 大段文字塞进报告）
                    #   ★ 2026-09-20：120 字太短，实测把"建议修改：补充完整题干，例如…"
                    #     拦腰截断，报告里只剩半句。放宽到 240 并在截断处显式加"…"，
                    #     让人一眼知道"后面还有"，而不是读到一句不通的话。
                    _r_flat = re.sub(r"\s+", " ", r)
                    if len(_r_flat) > 240:
                        r_short = _r_flat[:240].rstrip("，,、；; ") + "…"
                    else:
                        r_short = _r_flat
                    dim_failures.append(f"{dim_name}：{r_short}")
                if not dim_failures:
                    # 兜底
                    if q.get("question_type") == "错题截图":
                        dim_failures = ["答题答错（已截图核对）"]
                    else:
                        dim_failures = ["界面检查未通过"]
                # ★ 合并：维度去重（同一维度不重复），最终取前 2 条避免冗长
                seen_dim = set()
                compact_reasons = []
                for r in dim_failures:
                    dim = r.split("：")[0]
                    if dim in seen_dim:
                        continue
                    seen_dim.add(dim)
                    compact_reasons.append(r)
                compact_reasons = compact_reasons[:2]  # 最多 2 条

                p = doc.add_paragraph()
                _r = p.add_run("▸ 出错理由：")
                _r.bold = True
                _r.font.color.rgb = RGBColor(0xC0, 0x39, 0x2B)  # 红色
                p.add_run("\n".join(f"  · {r}" for r in compact_reasons))

                # 改进建议（按失败原因生成针对性建议）
                sugg = self._build_suggestion(q, compact_reasons)
                # ★ 建议去重 + 最多 2 条（避免冗长）
                sugg = sugg[:2]
                p = doc.add_paragraph()
                _s = p.add_run("▸ 改进建议：")
                _s.bold = True
                _s.font.color.rgb = RGBColor(0x1B, 0x43, 0x32)  # 深绿色
                p.add_run("\n".join(f"  · {s}" for s in sugg) if sugg else "  （请人工核对）")

                # 截图
                shot = q.get("screenshot", "")
                if shot:
                    # 尝试从 screenshots 目录找到图片并嵌入
                    shots_dir = Path(__file__).parent.parent / "screenshots"
                    img_path = shots_dir / shot
                    if img_path.exists():
                        try:
                            doc.add_picture(str(img_path), width=Inches(3.2))
                            doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
                        except Exception:
                            pass
                    else:
                        p = doc.add_paragraph()
                        p.add_run(f"（截图文件未找到：{shot}）").font.color.rgb = RGBColor(0x99, 0x99, 0x99)
                else:
                    # ★ 2026-09-20：不要留白。错题报告声明"每题都要有定位截图"，
                    #   拿不到图时必须说清【为什么】以及【怎么定位】，否则检查人员
                    #   只会认为工具不靠谱（而不是"这一题当时没来得及截图"）。
                    p = doc.add_paragraph()
                    r = p.add_run(
                        f"（未捕获到该题画面截图：判定时 App 已离开{loc_str}，"
                        f"无法补拍。请按上面「在 App 中的位置」定位复核）")
                    r.font.size = Pt(9)
                    r.font.color.rgb = RGBColor(0x99, 0x99, 0x99)

                doc.add_paragraph()  # 空行分隔

        # 页脚说明
        doc.add_paragraph()
        foot = doc.add_paragraph()
        foot.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = foot.add_run("英语宝审查智能体 · 自动生成 · 供检查人员参考，最终判定以人工确认为准")
        r.font.size = Pt(9)
        r.font.color.rgb = RGBColor(0xbb, 0xbb, 0xbb)

        # 保存
        version_safe = re.sub(r'[\\/:*?"<>|]', '_', version)
        filename = f"错题报告_{version_safe}_{datetime.now().strftime('%Y%m%d_%H%M')}.docx"
        out_path = self.save_dir / filename
        doc.save(str(out_path))
        print(f"  ✅ DOCX 错题报告: {out_path}")
        return str(out_path)

    @staticmethod
    def _build_suggestion(q: dict, reasons: list) -> list:
        """生成与【具体错误】对应的改进建议。

        ★ 2026-09-20 重写（用户实测两条硬伤）：
          ① 建议与错误牛头不对马嘴 —— 第1题错的是"App 大题说明与脚本不符"，
             建议却写成"请核对配图"。根因：旧实现完全靠**关键词跨维度全文匹配**，
             理由里出现"结合图片"四个字就被 ⑦ 配图规则抢走。
             → 改为【先按维度分流，再在维度内匹配】：题干维度的错绝不会产出配图建议。
          ② 明明记录里存着精准建议（stem_suggestion="补充完整题干，例如…"）却不用，
             反去正则啃被 120 字截断过的理由文本 → 建议本身也被截成半句
             （"补充完整题干，例如\"仿照例句，说一说：I"）。
             → 改为【优先取按维度存档的建议原文】，规则只在缺建议时兜底生成。
        """
        sugg = []
        qtype = (q.get("question_type", "") or "").strip()

        # ── ① 优先：判定那一刻按维度存档的建议（未截断、针对本题本题 Assets）──
        for dim, (r_field, ai_field, s_field) in ReportExporter._DIM_FIELDS.items():
            if q.get(ai_field) is not False:
                continue                       # 该维度没判不通过就不产出建议
            _stored = re.sub(r"\s+", " ", (q.get(s_field, "") or "")).strip()
            if _stored:
                sugg.append(_stored[:200])
                continue
            # 没有存档建议 → 用【未截断】的 reason 原文，按维度挑规则
            _body = ReportExporter._reason_body(q, r_field, reasons, dim)
            _built = ReportExporter._suggest_for_dim(dim, _body, qtype)
            sugg.append(_built)

        # ── ② 答错截图类（不走六维）──
        if not sugg and q.get("question_type") == "错题截图":
            sugg.append("人工核对错题画面：定位答错原因（听音误解/选项混淆/知识点未掌握）")
            sugg.append("针对错题知识点设计专项巩固练习，如高频错词/句型重复训练")

        # ── ③ 兜底（六维全没判 False，但确实被列为错题）──
        if not sugg:
            sugg.append("人工复核该题：对照脚本与 App 实际显示，按上方「出错理由」逐项确认。")

        # ★ 去重（保持顺序）
        seen, uniq = set(), []
        for s in sugg:
            _k = re.sub(r"\s+", " ", str(s or "")).strip()
            if _k and _k not in seen:
                seen.add(_k)
                uniq.append(_k)
        return uniq

    # 维度 → (reason 字段, ai 布尔字段, suggestion 存档字段)
    _DIM_FIELDS = {
        "题干": ("stem_reason", "ai_stem", "stem_suggestion"),
        "内容": ("content_reason", "ai_content", "content_suggestion"),
        "配图": ("image_reason", "ai_image", "image_suggestion"),
        "作答": ("answer_reason", "ai_answer", "answer_suggestion"),
        "音频": ("audio_reason", "ai_audio", "audio_suggestion"),
        "答错后": ("post_error_reason", "ai_post_error", "post_error_suggestion"),
    }

    @staticmethod
    def _reason_body(q: dict, r_field: str, reasons: list, dim: str) -> str:
        """取该维度 reason 的【未截断】正文（剥掉维度前缀 / 脚本层标记）。"""
        body = re.sub(r"\s+", " ", (q.get(r_field, "") or "")).strip()
        if not body:                                # 退回调用方拼好的 compact_reasons
            for r in reasons or []:
                if str(r).startswith(dim + "："):
                    body = str(r)[len(dim) + 1:]
                    break
        body = re.sub(r"^❌\s*", "", body)
        body = re.sub(r"^脚本层不通过[：:]\s*", "", body)
        body = re.split(r"[；;]\s*界面层[：:]", body)[0].strip()
        return body

    # 引号配对优先级：正文里的中文引号混排（App 原文含“录音”这类嵌套引号），
    #   一律用同一种引号配对会提前收尾 → 截半句（如「…点击“录音」）。
    _QUOTE_PAIRS = (("「", "」"), ("“", "”"), ("‘", "’"), ('"', '"'))

    @classmethod
    def _quoted_after(cls, text: str, start: int, limit: int = 120) -> str:
        """从 text 的 start 位置往后取第一段带引号的内容（按引号优先级）。"""
        tail = text[start:]
        for l, r in cls._QUOTE_PAIRS:
            m = re.search(re.escape(l) + rf"(.{{1,{limit}}}?)" + re.escape(r), tail)
            if m:
                return m.group(1).strip()
        return ""

    @staticmethod
    def _suggest_for_dim(dim: str, body: str, qtype: str = "") -> str:
        """按【维度】生成建议（★ 关键：绝不跨维度命中）。"""

        # —— 通用：LLM 已在正文里写了"建议修改：xxx"（未截断，直接采信）——
        m = re.search(r"建议修改[：:]\s*(.+?)(?:[。;；]|$)", body)
        if m and len(m.group(1).strip()) >= 6:
            return m.group(1).strip()[:200]

        if dim == "题干":
            # App ↔ 脚本 文字不一致（最常见的一类，必须给出"照谁改"）
            _i1 = re.search(r"App\s*显示", body)
            _i2 = re.search(r"脚本应为", body)
            if _i1 and _i2 and _i2.start() > _i1.start():
                _a = ReportExporter._quoted_after(body, _i1.end())
                _b = ReportExporter._quoted_after(body, _i2.end())
                if _a and _b:
                    return (f"App 此处显示为「{_a}」，脚本写的是「{_b}」："
                            f"二者必须统一——以脚本为准就把 App 文字改成脚本原文，"
                            f"反之则修正脚本，不要两边各写一套。")
            m = re.search(r"脚本应为", body)
            if m:
                _b = ReportExporter._quoted_after(body, m.end())
                if _b:
                    return (f"把 App 该处文字改成脚本原文「{_b}」；"
                            f"若确认脚本写错则同步修改脚本，两边须逐字一致。")
            # 语法 / 词序 / 拼写
            m = re.search(r"[「“\"](.{1,60}?)[」”\"]应为[「“\"](.{1,60}?)[」”\"]", body)
            if m and any(k in body for k in ("语法", "词序", "拼写", "错误", "笔误")):
                return (f"题干有文字错误：「{m.group(1).strip()}」应为"
                        f"「{m.group(2).strip()}」，请按正确写法修正。")
            # 题干缺失 / 为空
            if any(k in body for k in ("题干为空", "题干为空，", "题干缺失", "题干为空白",
                                       "未提供题干", "未提取到", "没有题干", "题为空白",
                                       "题干为“(空)”", "题干为「空」")):
                return "题干缺失：请在脚本里补写完整题干（含作答指令，如“仿照例句，说一说：…”），否则学生不知道要做什么。"
            # 与脚本不符（无具体脚本原文）
            if "与脚本不符" in body or "不一致" in body:
                return "App 题干与脚本不一致：请对照脚本原文修正 App 或脚本，使两边逐字一致。"
            return "核对 App 该题显示的题干文字与脚本是否逐字一致（含大小写、标点）。"

        if dim == "内容":
            m = re.search(r"[「“\"](.{1,60}?)[」”\"]应为[「“\"](.{1,60}?)[」”\"]", body)
            if m:
                return f"题目内容有误：「{m.group(1).strip()}」应为「{m.group(2).strip()}」，请按此修正。"
            if any(k in body for k in ("超纲", "不符合.*年级", "难度")):
                return "内容难度/用词超纲：请改用本年级教材范围内的词汇与句型。"
            if any(k in body for k in ("知识性", "错误", "不正确")):
                return "题目内容存在知识性错误：请按学科事实/教材原文修正表述。"
            return "核对题目内容（英文表述/知识点）是否准确，并与教材、答案保持一致。"

        if dim == "配图":
            if "未检测" in body or "无法" in body:
                return "需人工核对配图：脚本审查看不到实际图片，请确认配图与题干/答案语义一致且清晰可见。"
            if any(k in body for k in ("不符", "缺失", "空白", "不匹配")):
                return "配图与题目内容不符或缺失：请核对配图，确保与题干/答案语义一致且清晰可见。"
            return "核对配图：确认图片内容与题干要求、正确答案一致。"

        if dim == "作答":
            m = re.search(r"关键词[「“\"](.{1,60}?)[」”\"]", body)
            if m and ("参考答案" in body or "答案" in body):
                return (f"参考答案与关键词「{m.group(1).strip()}」不一致："
                        f"二者必须表述一致，否则学生按关键词作答会被判错。请统一。")
            if any(k in body for k in ("不可点击", "未识别", "未检测", "不可用")):
                return "作答控件异常：请确认录音/输入/提交等控件正常显示且可交互。"
            if "不一致" in body or "不符" in body:
                return "作答要求与脚本不一致：请统一 App 作答形式与脚本描述（含答案/关键词）。"
            return "核对作答环节：参考答案、关键词、作答控件三者须与脚本一致。"

        if dim == "音频":
            if "不可点击" in body or "未检测到播放" in body or "未播放" in body:
                return "听力音频异常：请确认播放控件可点击、音频文件可正常播放（路径/格式/时长）。"
            if "无关" in body or "不符" in body or "不匹配" in body:
                return "音频与题目内容不符：请核对听力材料与题干/选项是否对应。"
            return "核对听力音频：资源是否存在、能否正常播放、内容与题目要求是否匹配。"

        # 答错后
        if "未显示" in body or "没有" in body:
            return "答错后缺少反馈：请补上正确答案/解析提示，帮助学生订正。"
        return "核对答错后的反馈页：确认会给出正确答案或针对性的提示。"

    # 维度展示顺序：(中文名, reason字段, ai_布尔字段)
    _LIVE_DIMS = [
        ("题干", "stem_reason", "ai_stem"),
        ("内容", "content_reason", "ai_content"),
        ("配图", "image_reason", "ai_image"),
        ("作答", "answer_reason", "ai_answer"),
        ("音频", "audio_reason", "ai_audio"),
        ("答错后", "post_error_reason", "ai_post_error"),
    ]

    _HTML_LIVE_CSS = """
    <style>
      * { margin:0; padding:0; box-sizing:border-box; }
      body { font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; background:#f6f4ef; color:#333; line-height:1.6; padding:20px; }
      .container { max-width:840px; margin:0 auto; }
      h1 { font-size:21px; font-weight:700; color:#3a3a3a; }
      .sub { color:#9aa5a0; font-size:13px; margin:4px 0 16px; }
      .stats { display:flex; gap:10px; margin-bottom:18px; flex-wrap:wrap; }
      .stat { flex:1; min-width:120px; background:#fff; border:1px solid #f0e9dd; border-radius:10px; padding:12px; text-align:center; }
      .stat .num { font-size:22px; font-weight:800; }
      .stat .lab { font-size:11px; color:#888; margin-top:2px; }
      .s-fail .num { color:#bc4742; } .s-total .num { color:#3a3a3a; }
      .s-pass .num { color:#2e7d32; } .s-shot .num { color:#c77c00; }
      .card { background:#fff; border:1px solid #f0e9dd; border-left:4px solid #bc4742; border-radius:10px; margin-bottom:10px; overflow:hidden; }
      .card > summary { cursor:pointer; list-style:none; padding:12px 14px; display:flex; align-items:center; gap:9px; }
      .card > summary::-webkit-details-marker { display:none; }
      .card > summary:hover { background:#faf8f3; }
      .badge { background:#fee2e2; color:#bc4742; font-size:10px; font-weight:700; padding:2px 8px; border-radius:6px; }
      .qtitle { font-size:13.5px; font-weight:600; color:#333; }
      .src { margin-left:auto; font-size:10.5px; color:#9aa5a0; }
      .body { padding:0 14px 14px; border-top:1px solid #f3eee4; font-size:12.5px; color:#444; }
      .field { margin-top:9px; } .field b { color:#666; }
      .cause { margin-top:9px; background:#fdecec; border:1px solid #f6c9c9; border-radius:8px; padding:9px 11px; }
      .cause .h { color:#bc4742; font-weight:700; font-size:11.5px; margin-bottom:5px; }
      .fix { margin-top:8px; background:#eafaf0; border:1px solid #bfe9cd; border-radius:8px; padding:9px 11px; }
      .fix .h { color:#2e7d32; font-weight:700; font-size:11.5px; margin-bottom:5px; }
      .shot { margin-top:8px; }
      .shot img { max-width:100%; max-height:340px; border:1px solid #d4dae0; border-radius:7px; }
      .shot .cap { font-size:10px; color:#9aa5a0; margin-bottom:3px; }
      /* ★ 2026-09-17 结构化错题块：结论 → 对照 → 怎么改 */
      .chk { margin-top:9px; border:1px solid #f6c9c9; background:#fffbfb; border-radius:8px; padding:9px 11px; }
      .chk-h { display:flex; align-items:center; gap:6px; flex-wrap:wrap; }
      .chk-t { font-size:12.5px; font-weight:700; color:#7f1d1d; }
      .chk-d { font-size:9.5px; font-weight:700; color:#bc4742; background:#fee2e2; border-radius:5px; padding:1px 7px; }
      .chk-l { font-size:9.5px; font-weight:700; color:#4338ca; background:#eef2ff; border-radius:5px; padding:1px 7px; }
      .chk-s { margin-left:auto; font-size:9.5px; color:#9aa5a0; }
      .cmp { display:flex; gap:8px; margin-top:7px; }
      .cmp > div { flex:1; border-radius:7px; padding:6px 8px; }
      .cmp .bad { background:#fdecec; border:1px solid #f6c9c9; }
      .cmp .good { background:#eafaf0; border:1px solid #bfe9cd; }
      .cmp .lab { font-size:9px; font-weight:700; margin-bottom:2px; }
      .cmp .bad .lab { color:#b91c1c; } .cmp .good .lab { color:#2e7d32; }
      .cmp .val { font-size:11.5px; word-break:break-all; }
      .cmp .bad .val { color:#7f1d1d; } .cmp .good .val { color:#14532d; }
      .chk-detail { font-size:10.5px; color:#6b7280; margin-top:6px; }
      /* ★ 2026-09-20 脚本自检 / 未判定：与"六维不通过"分开呈现（用户反馈
         "20 题全被列成不通过、脚本问题又一条都看不到"） */
      .s-sc .num { color:#c77c00; } .s-undet .num { color:#8a8f8c; }
      .card.sc-card { border-left-color:#c77c00; }
      .card.sc-card > summary:hover { background:#fffaf0; }
      .badge.sc { background:#fef3c7; color:#a16207; }
      .sc { margin-top:9px; border:1px solid #f0d79a; background:#fffdf5; border-radius:8px; padding:9px 11px; }
      .sc-h { display:flex; align-items:center; gap:6px; flex-wrap:wrap; }
      .sc-sev { font-size:9.5px; font-weight:700; border-radius:5px; padding:1px 7px; }
      .sc-sev.hi { background:#fee2e2; color:#b91c1c; }
      .sc-sev.mid { background:#fef3c7; color:#a16207; }
      .sc-sev.lo { background:#eef2f0; color:#6b7280; }
      .sc-t { font-size:12.5px; font-weight:700; color:#92620a; }
      .sc-loc { font-size:9.5px; font-weight:700; color:#a16207; background:#fef3c7; border-radius:5px; padding:1px 7px; }
      .sc-quote { font-family:ui-monospace,Consolas,"Courier New",monospace; font-size:11px;
                  background:#fff; border:1px dashed #e3dccd; border-radius:6px;
                  padding:5px 8px; margin-top:6px; word-break:break-all; color:#7f1d1d; }
      .prov { margin:14px 0 2px; padding:10px 14px; border-radius:8px; font-size:12px; line-height:1.75; }
      .prov-ok  { background:#eef7f0; border:1px solid #bfe0c6; color:#2f6b3d; }
      .prov-bad { background:#fdf2f1; border:1px solid #f0c0ba; color:#9a3325; }
      .prov-unk { background:#fff8e6; border:1px solid #ecd9a6; color:#8a6100; }
      .sc-sec { margin:24px 0 10px; border-top:1px dashed #e3dccd; padding-top:16px; }
      .sc-sec h2 { font-size:15px; font-weight:700; color:#3a3a3a; }
      .sc-sec .hint { font-size:11px; color:#9aa5a0; margin:5px 0 12px; line-height:1.6; }
      /* ★ 2026-09-23 未判定区块：证据不足的题必须可查（旧版只进统计卡、
         不列明细 → 审查员看到"未判定 5"却不知是哪 5 道、为什么） */
      .ud-sec { margin:24px 0 10px; border-top:1px dashed #e3dccd; padding-top:16px; }
      .ud-sec h2 { font-size:15px; font-weight:700; color:#3a3a3a; }
      .ud-sec .hint { font-size:11px; color:#9aa5a0; margin:5px 0 12px; line-height:1.6; }
      .ud-row { display:flex; align-items:baseline; gap:8px; flex-wrap:wrap;
                padding:7px 11px; background:#fbfaf7; border:1px solid #eee9df;
                border-left:3px solid #b9beb9; border-radius:8px; margin-bottom:6px; }
      .ud-q { font-size:12px; font-weight:700; color:#444; }
      .ud-dims { font-size:11px; color:#7d857f; }
      .ud-note { margin-left:auto; font-size:10.5px; color:#a3a8a4; }
      .empty { text-align:center; padding:60px 0; color:#bbb; font-size:15px; }
      .footer { text-align:center; color:#bbb; font-size:12px; margin-top:28px; }
      @media print { body { background:#fff; padding:0; } .card { box-shadow:none; break-inside:avoid; } }
    </style>
    """

    # ── 实时报告：判定口径 + 脚本自检归位 ────────────────────────────
    # ★ 2026-09-20 修复（用户反馈"20 题全被列成不通过 / 脚本问题又看不到"）：
    #   旧口径 `not q.get("overall_passed", True)` 把 None（**未判定**）也当成错题。
    #   口语训练"同大题第 2 小题起不再上报大题说明"的分支恰好让 9 题停在
    #   overall_passed=None，于是报告把它们全部列成"不通过"，理由还只能显示
    #   "未在六维中标记，详见原始理由"。现在三档分开：不通过 / 脚本自检 / 未判定。
    _QKEY_RE = re.compile(r"大(\d+)-Q(\d+)")
    _SC_LOC_RE = re.compile(r"U(\d+)\s*第(\d+)大题(?:\s*第(\d+)小题)?")

    def _live_dim_fail(self, q: dict) -> bool:
        """六维里是否确有维度被判不通过（与 _render_live_card 的取块口径保持一致）。"""
        for _dn, rkey, akey in self._LIVE_DIMS:
            if q.get(akey) is False:
                return True
            if "不通过" in (q.get(rkey) or ""):
                return True
        return False

    def _qkey_of(self, q: dict) -> tuple:
        """题目 → (单元, 大题号, 小题号)。progress 形如 '大4-Q3'。

        单元优先取记录自带的 `_unit`（写入那一刻正是该单元在跑，最可靠）；
        老记录没有该字段时留给调用方用"本次运行单元"兜底。
        """
        m = self._QKEY_RE.search(str(q.get("progress") or ""))
        if not m:
            return ("", None, None)
        return (str(q.get("_unit") or "").strip(), int(m.group(1)), int(m.group(2)))

    def _split_script_issues(self, sc_map, meta: dict, questions: list) -> tuple:
        """把脚本自检问题分成两桶：能归位到某道题的 / 只能放模块级的。

        归位需三条件同时成立，否则一律退回模块级（**绝不硬猜**，宁可少归位，
        也不能把 U7 的问题挂到 U4 的题卡上）：
          ① 位置能解析出 'U<单元> 第<大题>大题 [第<小题>小题]'
          ② 单元号与这道题自己的单元一致
          ③ 记录里存在 progress='大<大题>-Q<小题>'
        所以 '全文'、'U7 第4大题'（无小题号）这类天然只能进模块级。
        """
        per_q, mod = {}, []
        if not isinstance(sc_map, dict):
            return per_q, mod
        _run_unit = str(meta.get("unit") or "").strip()
        _run_unit = _run_unit if _run_unit.isdigit() else ""
        _idx = {}
        for q in questions or []:
            _u, _b, _s = self._qkey_of(q)
            if _b is not None and _s is not None:
                _idx.setdefault((_u or _run_unit, _b, _s), q)
        for _mod_name, _items in sc_map.items():
            if not isinstance(_items, list):
                continue
            for _it in _items:
                if not isinstance(_it, dict):
                    continue
                _rec = dict(_it)
                _rec.setdefault("module", _mod_name)
                _m = self._SC_LOC_RE.search(str(_rec.get("location") or ""))
                _u = _m.group(1) if _m else ""
                _b = int(_m.group(2)) if _m else None
                _s = int(_m.group(3)) if (_m and _m.group(3)) else None
                if _s is not None and (_u, _b, _s) in _idx:
                    per_q.setdefault(id(_idx[(_u, _b, _s)]), []).append(_rec)
                else:
                    mod.append(_rec)
        _rank = {"高": 0, "中": 1, "低": 2}
        mod.sort(key=lambda r: _rank.get(str(r.get("severity") or ""), 3))
        return per_q, mod

    def _render_script_item(self, i: dict) -> str:
        """单条脚本自检问题的块（模块级区块与题卡内共用同一套渲染）。"""
        sev = str(i.get("severity") or "低")
        sev_cls = {"高": "hi", "中": "mid"}.get(sev, "lo")
        parts = [
            '<div class="sc"><div class="sc-h">',
            f'<span class="sc-sev {sev_cls}">{html.escape(sev)}</span>',
            f'<span class="sc-t">{html.escape(str(i.get("type") or "脚本问题"))}</span>',
            f'<span class="sc-loc">{html.escape(str(i.get("location") or "全文"))}</span>',
            '</div>',
        ]
        if i.get("quote"):
            parts.append(f'<div class="sc-quote">{html.escape(str(i["quote"]))}</div>')
        if i.get("detail"):
            parts.append(f'<div class="chk-detail">{html.escape(str(i["detail"]))}</div>')
        if i.get("suggestion"):
            parts.append('<div class="fix"><div class="h">✓ 怎么改</div>'
                         f'{html.escape(str(i["suggestion"]))}</div>')
        parts.append('</div>')
        return "".join(parts)

    def _render_script_section(self, meta: dict) -> str:
        """模块级「脚本自检」区块。

        ★ 2026-09-20 新增：`check_script_completeness` 确定性命中的问题
        （答案↔关键词不一致 / 知识点占位 / 字段名不统一 …）此前**只进前端日志**，
        报告里一条都看不到 —— 这正是用户反馈"脚本问题没检查出来"的落点。
        """
        items = meta.get("_sc_module") or []
        if not items:
            return ""
        _unit = html.escape(str(meta.get("unit") or ""))
        body = "".join(self._render_script_item(i) for i in items)
        return (
            '<div class="sc-sec">'
            f'<h2>脚本自检（{len(items)} 处）</h2>'
            '<div class="hint">含两类：确定性扫描（题号连续性 / 字段名统一 / '
            '参考答案与关键词自洽 / 知识点非占位）与 LLM 篇章语法检查'
            '（只报错误，没有不输出）。<br>'
            f'仅保留本次实跑单元（U{_unit}）范围内的问题；位置带小题号且能对上题卡时'
            '直接归位到对应题卡，其余列在这里。</div>'
            + body + '</div>')

    def _render_undet_section(self, meta: dict) -> str:
        """「未判定（证据不足）」区块：列出是哪几道题、各查到了几维。

        ★ 2026-09-23 新增。此前 `_undet` 只进统计卡，报告里**没有清单** ——
        审查员看到"未判定 5"却查不到是哪 5 道、为什么。典型场景：口语训练
        第4大题（听录音作答）在 App 上只有音频图标 + 录音按钮、无文字题干，
        基础层只剩「作答」1 维可查 → 必落此档。宁可灰着，也不出假通过。
        """
        items = meta.get("_undet_list") or []
        if not items:
            return ""
        _u_meta = str(meta.get("unit") or "").strip()
        rows = []
        for q in items:
            _unit, _big, _sub = self._qkey_of(q)
            _unit = _unit or _u_meta
            _loc = []
            if _unit:
                _loc.append(f"U{_unit}")
            if _big is not None:
                _loc.append(f"第{_big}大题")
            if _sub is not None:
                _loc.append(f"第{_sub}小题")
            _head = " · ".join(_loc) or str(q.get("progress") or "—")
            _dims = (q.get("_score") or {}).get("dims") or []
            _names = [str(d.get("name")) for d in _dims if d.get("passed") is not None]
            _dim_txt = "、".join(_names) if _names else "无"
            _stem = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ",
                                               str(q.get("stem") or ""))).strip()
            # 模块自动生成的占位题面（'第4大题·第1题（口语训练）'）无信息量，不展示
            if re.match(r"^第\d+大题", _stem):
                _stem = ""
            _stem = (_stem[:52] + "…") if len(_stem) > 52 else _stem
            rows.append(
                '<div class="ud-row">'
                f'<span class="ud-q">{html.escape(_head)}</span>'
                f'<span class="ud-dims">仅 {len(_names)} 维可查（'
                f'{html.escape(_dim_txt)}）</span>'
                + (f'<span class="ud-note">{html.escape(_stem)}</span>' if _stem else "")
                + '</div>')
        return (
            '<div class="ud-sec">'
            f'<h2>未判定（{len(items)} 道）</h2>'
            '<div class="hint">这些题在 App 界面上可核实的维度不足（≤1 维），'
            '按「证据不足」处理 —— <b>不参与通过/不通过判定</b>，'
            '建议人工看一眼或补截图后复核。常见于听力/录音作答类小题：'
            '界面只有音频图标与录音按钮，没有文字题干可与脚本比对。</div>'
            + "".join(rows) + '</div>')

    def export_html_live(self, questions: list[dict], metadata: dict = None) -> str:
        """
        生成"仅错误"的实时可折叠卡片 HTML 报告（审查中每出一道错题即调用）。

        与 export_html_full 的区别：
          - 卡片用原生 <details> 折叠（默认收起，点标题展开），无需 JS；
          - 每张卡片内分「错误原因(红框) / 修改建议(绿框) / 截图」三块；
          - 截图拷贝到输出目录并内嵌，文件可单独带走、双击即看。
        """
        meta = dict(metadata or {})
        # ★ 脚本自检问题：能归位到题的挂到题卡上，其余（"全文" / 其他单元）走模块级区块
        _per_q, _mod_issues = self._split_script_issues(
            meta.get("script_issues") or {}, meta, questions)
        meta["_sc_module"] = _mod_issues
        _sc_map = meta.get("script_issues") or {}
        meta["script_issue_count"] = sum(
            len(v) for v in _sc_map.values() if isinstance(v, list))
        if not meta["script_issue_count"]:
            meta["script_issue_count"] = len(_mod_issues) + sum(
                len(v) for v in _per_q.values())
        # ★ 三档分流：不通过（六维明确 False / overall False）· 脚本自检命中 · 未判定
        #   —— 未判定绝不能混进"不通过"列表（旧口径 `not overall_passed` 的错）
        qs, _undet, _undet_list = [], 0, []
        for q in questions:
            _hits = _per_q.get(id(q)) or []
            if _hits:
                q = dict(q)
                q["_sc_issues"] = _hits
            if self._live_dim_fail(q) or q.get("overall_passed") is False or _hits:
                qs.append(q)
            elif q.get("overall_passed") is None:
                _undet += 1
                _undet_list.append(q)
        meta["failed"] = len(qs)
        meta["undetermined"] = _undet
        # ★ 未判定题明细：只计数不列清单的话，审查员看到"未判定 N"无从下手
        meta["_undet_list"] = _undet_list
        html_doc = self._render_live_html(qs, meta)

        version = meta.get("version", "未知版本")
        unit = str(meta.get("unit", "全部"))
        stage = str(meta.get("stage", "全部"))
        date_str = datetime.now().strftime("%Y%m%d")
        # ★ 防御：清洗 Windows 非法字符（<>:"/\|?* 等），避免 WinError 123
        _clean = lambda s: re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", s).strip() or "全部"
        version, unit, stage = _clean(version), _clean(unit), _clean(stage)
        out_dir = self.save_dir / version / f"U{unit}_{stage}_{date_str}"
        out_dir.mkdir(parents=True, exist_ok=True)

        # 拷贝错误截图到输出目录（HTML 用相对路径引用，文件可带走）
        shot_dir = out_dir / "screenshots"
        shot_dir.mkdir(parents=True, exist_ok=True)
        shots_root = Path(__file__).parent.parent / "screenshots"
        _web_dir = self._web_shot_dir()
        for q in qs:
            shot = q.get("screenshot", "")
            if not shot:
                continue
            src = shots_root / shot
            if src.exists():
                try:
                    shutil.copy2(src, shot_dir / shot)
                except Exception:
                    pass
            # ★ 2026-09-17：连同"出错区域特写 / 红框标注"一起拷走，
            #   让报告能显示"截到问题那几行"的图（checker 反馈整屏图看不清问题）。
            for _prefix in ("crop_v2_", "marked_v2_"):
                _w = _web_dir / f"{_prefix}{shot}"
                if _w.exists():
                    try:
                        shutil.copy2(_w, shot_dir / _w.name)
                    except Exception:
                        pass

        out_path = out_dir / "report_live.html"
        out_path.write_text(html_doc, encoding="utf-8")

        # 刷新 latest 快捷入口（复用已有的目录管理逻辑）
        self.organize_output_dir(version, unit, stage)
        return str(out_path)

    def _render_live_html(self, questions: list[dict], meta: dict) -> str:
        version = meta.get("version", "未知版本")
        unit = meta.get("unit", "?")
        stage = meta.get("stage", "?")
        date_str = meta.get("date", datetime.now().strftime("%Y-%m-%d %H:%M"))
        total = meta.get("total", len(questions))
        # ★ 三档分开计数：不通过 / 未判定 / 脚本自检（不再把 None 当不通过）
        failed = meta.get("failed", len(questions))
        undet = meta.get("undetermined", 0)
        sc_total = meta.get("script_issue_count", 0)
        passed = max(total - failed - undet, 0)
        rate = round(passed / total * 100) if total else 0
        cards = "\n".join(self._render_live_card(q, meta) for q in questions)
        sc_section = self._render_script_section(meta)
        ud_section = self._render_undet_section(meta)
        if questions:
            body = cards
        elif undet or sc_total:
            _bits = []
            if undet:
                _bits.append(f"{undet} 道题证据不足未判定")
            if sc_total:
                _bits.append(f"脚本自检命中 {sc_total} 处问题")
            body = ('<div class="empty">六维未发现不通过项；'
                    + "、".join(_bits) + ' —— 详见下方区块</div>')
        else:
            body = f'<div class="empty">暂无错题，{total} 道题全部通过</div>'
        # ★ 2026-09-21：脚本溯源横幅（告诉检查人员：这份错题单的脚本结论可信吗）
        prov_html = "\n  ".join(
            f'<div class="prov prov-{_lv}">{html.escape(_t)}</div>'
            for _lv, _t in self._script_provenance_lines(meta))
        title = f"实时错题报告 — {version} · U{unit} · {stage}"
        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html.escape(title)}</title>
{self._HTML_LIVE_CSS}
</head>
<body>
<div class="container">
  <h1>{html.escape(str(version))} · U{unit} · {stage}</h1>
  <div class="sub">生成于 {date_str} · {failed} 道不通过 · {undet} 道未判定 · 脚本自检 {sc_total} 处 · 审查中实时更新</div>

  {prov_html}

  <div class="stats">
    <div class="stat s-fail"><div class="num">{failed}</div><div class="lab">不通过</div></div>
    <div class="stat s-undet"><div class="num">{undet}</div><div class="lab">未判定</div></div>
    <div class="stat s-sc"><div class="num">{sc_total}</div><div class="lab">脚本自检问题</div></div>
    <div class="stat s-total"><div class="num">{total}</div><div class="lab">已审查</div></div>
    <div class="stat s-pass"><div class="num">{rate}%</div><div class="lab">通过率</div></div>
  </div>

  {body}
  {sc_section}
  {ud_section}

  <div class="footer">英语宝审查智能体 · 自动生成 · 仅供参考，最终以人工确认为准</div>
</div>
</body>
</html>"""

    def _render_live_card(self, q: dict, meta: dict) -> str:
        """单张错题卡片（结构化：结论 → App/脚本对照 → 怎么改 → 定位截图）。

        ★ 2026-09-17 重排：旧版把六维原因堆成"· 维度：长句"列表，
        检查人员要逐字读完才知道错在哪（用户反馈"不够直白、抓不住重点"）。
        现在每个维度渲染成独立结构块，一眼即知"哪一处、现在是什么、应该是什么、怎么改"。
        """
        qid = q.get("qid", "?")
        idx = q.get("idx", "?")
        qtype = q.get("question_type", "?")
        stem = html.escape(str(self._clean_stem(q.get("stem", "")) or ""))
        script_answer = html.escape(str(q.get("script_answer", "") or ""))
        _boxes = q.get("_boxes") or {}

        blocks = []
        for dname, rkey, akey in self._LIVE_DIMS:
            reason = (q.get(rkey, "") or "")
            ai_pass = q.get(akey, None)
            if ai_pass is not False and "不通过" not in reason:
                continue
            dim_key = rkey[:-7]                      # stem_reason → stem
            reason = re.split(r"建议修改[:：]", reason)[0].strip()
            if not reason:
                reason = "（未提供具体原因，请人工确认）"
            blocks.append(self._render_live_check(
                q, dname, dim_key, reason, bool(_boxes.get(dim_key))))

        # ★ 2026-09-20：脚本自检问题归位到本题 → 跟在六维结论后面展示
        #   （"参考答案↔关键词不一致"这类问题在六维里没有对应维度，以前完全不显示）
        _sc = q.get("_sc_issues") or []
        if not blocks:
            if _sc:
                blocks.append('<div class="chk-detail">'
                              '六维检查未发现不通过项；下方为该题的脚本自检问题。</div>')
            else:
                blocks.append('<div class="chk"><div class="chk-detail">'
                              '—（未在六维中标记，详见原始理由）</div></div>')
        for _i in _sc:
            blocks.append(self._render_script_item(_i))

        # 证据截图：出错区域特写 > 红框标注 > 整屏原图
        shot = q.get("screenshot", "")
        shot_html = ""
        if shot:
            _crop = f"crop_v2_{shot}"
            _marked = f"marked_v2_{shot}"
            if (self._web_shot_dir() / _crop).exists():
                use, cap = _crop, "证据截图 · 已定位到出错区域"
            elif (self._web_shot_dir() / _marked).exists():
                use, cap = _marked, "证据截图 · 红框标注（全屏）"
            else:
                use, cap = shot, "证据截图 · 整屏（该题未采集到控件坐标）"
            shot_html = (
                f'<div class="shot"><div class="cap">{html.escape(cap)}</div>'
                f'<img src="screenshots/{html.escape(use)}" alt=""></div>'
            )

        # ★ 徽标/边框按"为什么进报告"区分：六维不通过 vs 仅脚本自检命中
        _dim_fail = self._live_dim_fail(q) or q.get("overall_passed") is False
        if _dim_fail:
            _card_cls, _badge, _badge_cls = "", "不通过", "badge"
        else:
            _card_cls, _badge, _badge_cls = " sc-card", "脚本问题", "badge sc"

        # ★ 2026-09-20：题型标签与模块名重复时不再重复显示（标题里已有模块名，
        #   再挂一个 "[口语训练]" 纯属噪音）
        _qtype_show = "" if str(qtype).strip() in ("", str(q.get("module") or "").strip()) \
            else f'<span class="qtype">[{html.escape(str(qtype))}]</span>'

        return f'''<details class="card{_card_cls}">
  <summary>
    <span class="{_badge_cls}">{_badge}</span>
    <span class="qtitle">{html.escape(self._loc_label(q, meta))}</span>
    {_qtype_show}
  </summary>
  <div class="body">
    <div class="field"><b>题干：</b>{stem or "（无题干文字）"}</div>
    {f'<div class="field"><b>脚本答案：</b><span style="color:#2e7d32;">{script_answer}</span></div>' if script_answer else ""}
    {"".join(blocks)}
    {shot_html}
  </div>
</details>'''

    def _web_shot_dir(self) -> Path:
        """标注图/特写图所在目录（web_server 的 _ensure_marked 输出到这里）"""
        return Path(__file__).parent.parent / "outputs" / "web"

    def _render_live_check(self, q: dict, dname: str, dim_key: str,
                           reason: str, has_box: bool) -> str:
        """渲染单个不通过维度：结论标题 + 双栏对照 + 完整说明 + 怎么改。"""
        quotes = re.findall(r"「([^」]{1,160})」", reason)
        is_cmp = bool(re.search(r"脚本(应|为)|不符", reason))
        if is_cmp:
            labs = ("App 实际", "脚本应为")
        else:
            labs = ("实际", "应改为")
        cmp_html = ""
        if len(quotes) >= 2:
            cmp_html = (
                '<div class="cmp">'
                f'<div class="bad"><div class="lab">{labs[0]}</div>'
                f'<div class="val">{html.escape(quotes[0])}</div></div>'
                f'<div class="good"><div class="lab">{labs[1]}</div>'
                f'<div class="val">{html.escape(quotes[1])}</div></div>'
                '</div>')
            # 双栏已展示引号内容 → 正文里折叠成「…」，避免同一句出现两遍
            detail = re.sub(r"「[^」]{1,160}」", "「…」", reason)
        else:
            detail = reason
        head = re.sub(r"^[❌⚠✅✕✓\s]+", "", reason).strip()
        # 先把引号内容压成「…」再取结论，避免"关键词「bring their rainco…"这种切断
        head = re.sub(r"「[^」]{1,160}」", "「…」", head)
        head = re.split(r"[：:]", head)[0]
        if len(head) > 22:
            head = head[:22] + "…"
        sugg = (q.get(f"{dim_key}_suggestion") or "").strip() \
            or "对照脚本核对并修正该处（保证 App 与脚本逐字一致）"
        box_tag = ('<span class="chk-s">已定位坐标</span>' if has_box else "")
        return (
            f'<div class="chk"><div class="chk-h">'
            f'<span class="chk-t">{html.escape(head)}</span>'
            f'<span class="chk-d">{html.escape(dname)}</span>'
            f'{box_tag}</div>'
            f'{cmp_html}'
            f'<div class="chk-detail">{html.escape(detail)}</div>'
            f'<div class="fix"><div class="h">✓ 怎么改</div>{html.escape(sugg)}</div>'
            f'</div>')
