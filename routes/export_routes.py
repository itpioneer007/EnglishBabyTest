"""
routes/export_routes.py — 报告输出 & 分发
负责：C同学

接口列表：
  POST /api/export/html          → 生成HTML报告，返回URL
  POST /api/export/csv           → 生成CSV表格
  POST /api/export/screenshots   → 打包错误截图成zip
  GET  /api/export/download/<filename>  → 下载导出文件
  POST /api/export/email         → 发送报告邮件
  GET  /api/export/config        → 获取导出配置
  POST /api/export/config        → 更新导出配置

依赖：
  src.report_exporter.ReportExporter  — 报告生成器
  src.email_sender.EmailSender        — 邮件发送
"""

from flask import jsonify, request, send_file
from datetime import datetime
import json, os, shutil
from pathlib import Path

# ============================================
# 数据契约
# ============================================
"""
_export_config 结构:
{
    "save_dir": "D:\\审查报告",           // 报告保存目录
    "save_screenshots": true,             // 是否保留出错截图
    "email_to": "teacher@school.com",     // 邮件接收人
    "email_enabled": false,               // 是否启用邮件发送
    "webhook_url": ""                     // 企微/钉钉 Webhook URL(可选)
}

C 的导出读取 A 的 _trace_detail 结构（见 trace_routes.py 中的 _data_contract）
同时也读取现有的 _inspection_state 中的 questions 数据
"""


_EXPORT_CONFIG_PATH = Path(__file__).parent.parent / "data" / "export_config.json"
_DEFAULT_EXPORT_CONFIG = {
    "save_dir": "",
    "save_screenshots": True,
    "email_to": "",
    "email_enabled": False,
    "webhook_url": "",
}


def _load_export_config():
    if _EXPORT_CONFIG_PATH.exists():
        with open(_EXPORT_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return dict(_DEFAULT_EXPORT_CONFIG)


def _save_export_config(config):
    _EXPORT_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_EXPORT_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def register(app):
    """注册报告导出相关路由到 Flask app"""

    # ========================================
    # 导出配置
    # ========================================

    @app.route("/api/export/config", methods=["GET"])
    def api_export_config():
        return jsonify(_load_export_config())


    @app.route("/api/export/config", methods=["POST"])
    def api_export_config_save():
        config = request.get_json() or {}
        _save_export_config(config)
        return jsonify({"success": True})


    # ========================================
    # HTML 报告
    # ========================================

    @app.route("/api/export/html", methods=["POST"])
    def api_export_html():
        """
        生成 HTML 报告
        POST Body: { result_ids: ["qid1","qid2"] } 或空=全部
        → 返回下载URL
        """
        data = request.get_json() or {}
        config = _load_export_config()
        save_dir = config.get("save_dir", "") or str(Path(__file__).parent.parent / "outputs" / "reports")
        
        # 加载巡检数据
        state_path = Path(__file__).parent.parent / "data" / "inspection_state.json"
        questions = {}
        if state_path.exists():
            with open(state_path, "r", encoding="utf-8") as f:
                st = json.load(f)
                questions = st.get("questions", {})
        
        # 过滤：指定ID或全部
        ids = data.get("result_ids", [])
        if ids:
            questions = {k: v for k, v in questions.items() if k in ids}

        # ===== C 在这里实现 =====
        # TODO(C): 调用 src.report_exporter.ReportExporter
        # exporter = ReportExporter(save_dir)
        # report_path = exporter.export_html(questions)
        
        # 骨架：生成一个简单的HTML
        report_dir = Path(save_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        
        total = len(questions)
        passed = sum(1 for q in questions.values() if q.get("overall_passed"))
        failed_qs = {k: v for k, v in questions.items() if not v.get("overall_passed")}
        
        html = _build_html_report(questions, total, passed, failed_qs)
        report_path = report_dir / f"inspect_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
        report_path.write_text(html, encoding="utf-8")
        
        return jsonify({
            "success": True,
            "path": str(report_path),
            "url": f"/api/export/download/{report_path.name}",
            "stats": {"total": total, "passed": passed, "failed": total - passed}
        })


    # ========================================
    # CSV 导出
    # ========================================

    @app.route("/api/export/csv", methods=["POST"])
    def api_export_csv():
        """生成 CSV 表格（仅错误题）"""
        data = request.get_json() or {}
        config = _load_export_config()
        save_dir = config.get("save_dir", "") or str(Path(__file__).parent.parent / "outputs" / "reports")
        
        state_path = Path(__file__).parent.parent / "data" / "inspection_state.json"
        questions = {}
        if state_path.exists():
            with open(state_path, "r", encoding="utf-8") as f:
                questions = json.load(f).get("questions", {})
        
        # 只导出错误题
        failed = {k: v for k, v in questions.items() if not v.get("overall_passed")}
        
        # ===== C 在这里实现 =====
        # TODO(C): 调用 src.report_exporter.ReportExporter.export_csv()
        import csv, io
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["题号", "题型", "综合得分", "通过", "题干理由", "内容理由", "配图理由", "作答理由"])
        for qid, q in failed.items():
            writer.writerow([
                qid, q.get("question_type", ""), q.get("overall_score", 0),
                "是" if q.get("overall_passed") else "否",
                q.get("stem_reason", ""), q.get("content_reason", ""),
                q.get("image_reason", ""), q.get("answer_reason", "")
            ])
        
        report_dir = Path(save_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        csv_path = report_dir / f"errors_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        csv_path.write_text(buf.getvalue(), encoding="utf-8-sig")  # utf-8-sig 兼容Excel
        
        return jsonify({
            "success": True,
            "path": str(csv_path),
            "url": f"/api/export/download/{csv_path.name}",
            "count": len(failed)
        })


    # ========================================
    # 截图打包
    # ========================================

    @app.route("/api/export/screenshots", methods=["POST"])
    def api_export_screenshots():
        """打包错误题截图成 zip 供下载"""
        state_path = Path(__file__).parent.parent / "data" / "inspection_state.json"
        questions = {}
        if state_path.exists():
            with open(state_path, "r", encoding="utf-8") as f:
                questions = json.load(f).get("questions", {})
        
        # 找不通过的题
        failed = {k: v for k, v in questions.items() if not v.get("overall_passed")}
        if not failed:
            return jsonify({"error": "没有不通过的题目"}), 400
        
        # 打包截图
        import zipfile
        shots_dir = Path(__file__).parent.parent / "screenshots"
        zip_path = Path(__file__).parent.parent / "outputs" / "reports" / f"error_screenshots_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        zip_path.parent.mkdir(parents=True, exist_ok=True)
        
        with zipfile.ZipFile(zip_path, "w") as zf:
            for qid, q in failed.items():
                shot = q.get("screenshot", "")
                if shot:
                    shot_full = shots_dir / shot
                    if shot_full.exists():
                        zf.write(shot_full, f"{qid}_{shot}")
        
        return jsonify({
            "success": True,
            "path": str(zip_path),
            "url": f"/api/export/download/{zip_path.name}",
            "count": len(failed)
        })


    # ========================================
    # 下载
    # ========================================

    @app.route("/api/export/download/<filename>")
    def api_export_download(filename):
        """下载导出文件"""
        reports_dir = Path(__file__).parent.parent / "outputs" / "reports"
        file_path = reports_dir / filename
        
        # 也检查 save_dir
        if not file_path.exists():
            config = _load_export_config()
            save_dir = config.get("save_dir", "")
            if save_dir:
                file_path = Path(save_dir) / filename
        
        if file_path.exists():
            return send_file(str(file_path), as_attachment=True)
        return jsonify({"error": "文件不存在"}), 404


    # ========================================
    # 邮件发送
    # ========================================

    @app.route("/api/export/email", methods=["POST"])
    def api_export_email():
        """发送报告邮件"""
        data = request.get_json() or {}
        to_email = data.get("to", "")
        config = _load_export_config()
        
        if not to_email:
            to_email = config.get("email_to", "")
        if not to_email:
            return jsonify({"error": "未配置收件人邮箱"}), 400
        
        # ===== C 在这里实现 =====
        # TODO(C): 调用 src.email_sender.EmailSender.send_report()
        # 先导出HTML再发邮件
        
        return jsonify({
            "success": True,
            "to": to_email,
            "message": "邮件发送功能需要配置 SMTP。请在出口配置中设置 SMTP 账号密码。"
        })


    @app.route("/export")
    def page_export():
        """导出管理页面"""
        from flask import render_template
        return render_template("export.html")


# ============================================
# 骨架 HTML 报告生成器（C 会替换为完整的）
# ============================================

def _build_html_report(questions, total, passed, failed_qs):
    """简单的HTML报告模板 — C 会替换为更完整的版本"""
    failed_count = len(failed_qs)
    
    failed_html = ""
    for qid, q in sorted(failed_qs.items()):
        dims = ""
        for d in ["stem", "content", "image", "answer"]:
            pas = q.get(f"ai_{d[:3]}", False)
            reason = q.get(f"{d}_reason", "")[:80] if pas is not None else ""
            dims += f'<tr><td>{d}</td><td>{"✅" if pas else "❌"}</td><td>{reason}</td></tr>'
        
        shot = q.get("screenshot", "")
        shot_html = ""
        if shot:
            shot_path = Path(__file__).parent.parent / "screenshots" / shot
            if shot_path.exists():
                import base64
                shot_html = f'<img src="data:image/png;base64,{base64.b64encode(shot_path.read_bytes()).decode()}" style="max-width:300px;border:1px solid #ddd;border-radius:6px">'
        
        failed_html += f'''
        <div style="border:1px solid #fecaca;border-radius:8px;margin:12px 0;padding:16px;background:#fef2f2">
            <h3>{qid} [{q.get("question_type","")}] 得分:{q.get("overall_score",0):.2f}</h3>
            {shot_html}
            <table style="width:100%;margin-top:12px">
                <tr style="background:#fafbfc"><th>维度</th><th>结果</th><th>理由</th></tr>
                {dims}
            </table>
        </div>'''
    
    return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>审查报告</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:"Microsoft YaHei",sans-serif;max-width:900px;margin:0 auto;padding:20px;color:#333}}
h1{{font-size:22px;margin-bottom:8px}}
.stat{{background:#f8fafc;padding:12px 20px;border-radius:8px;margin:12px 0}}
</style></head>
<body>
<h1>英语宝题目审查报告</h1>
<p>生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M")}</p>
<div class="stat">📊 共{total}题 | ✅通过{passed}题 | ❌不通过{failed_count}题</div>
{failed_html if failed_html else '<p style="color:#16a34a;font-size:18px">🎉 全部通过!</p>'}
</body></html>'''
