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


def register(app, state_provider=None):
    """注册报告导出相关路由到 Flask app

    state_provider: 可选 callable，返回当前内存 _inspection_state（dict）。
       ★ 多模块检测结果在内存中是最新的（含全部模块），文件可能被
         新任务启动时清空覆盖 → 导出必须优先读内存，文件仅作兜底。
    """

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
        
        # ★ 加载巡检数据：优先内存（多模块最新结果），文件兜底
        st = {}
        questions = {}
        if state_provider:
            try:
                _mem = state_provider() or {}
                if _mem.get("questions"):
                    st = _mem
                    questions = _mem.get("questions", {})
            except Exception:
                pass
        if not questions:
            state_path = Path(__file__).parent.parent / "data" / "inspection_state.json"
            if state_path.exists():
                with open(state_path, "r", encoding="utf-8") as f:
                    st = json.load(f)
                    questions = st.get("questions", {})

        # 过滤：指定ID或全部
        ids = data.get("result_ids", [])
        if ids:
            questions = {k: v for k, v in questions.items() if k in ids}

        # 调用新的 ReportExporter
        from src.report_exporter import ReportExporter
        exporter = ReportExporter(save_dir)
        qlist = list(questions.values()) if isinstance(questions, dict) else questions
        report_path = exporter.export_html_full(qlist, metadata={
            "version": st.get("version", ""),
            "unit": st.get("unit", 0),
            "stage": st.get("stage", ""),
        })

        total = len(qlist)
        passed_count = sum(1 for q in qlist if q.get("overall_passed"))
        return jsonify({
            "success": True,
            "path": str(report_path),
            "url": f"/api/export/download/{Path(report_path).name}",
            "stats": {"total": total, "passed": passed_count, "failed": total - passed_count}
        })


    # ========================================
    # DOCX 错题报告（检查人员专用：按模块分组，含位置/原因/建议/截图）
    # ========================================

    @app.route("/api/export/docx", methods=["POST"])
    def api_export_docx():
        """
        生成按模块分组的错题报告 DOCX。
        POST Body: {} 或 { module: "听力专项" }（可选，只导出指定模块）
        → 返回下载URL
        """
        data = request.get_json() or {}
        only_module = data.get("module", "")

        config = _load_export_config()
        save_dir = config.get("save_dir", "") or str(Path(__file__).parent.parent / "outputs" / "reports")

        # ★ 加载巡检数据：优先内存（多模块检测最新结果，含全部模块）；
        #   文件仅兜底（服务重启后无内存时用文件）
        st = {}
        questions = {}
        if state_provider:
            try:
                _mem = state_provider() or {}
                if _mem.get("questions"):
                    st = _mem
                    questions = _mem.get("questions", {})
            except Exception:
                pass
        if not questions:
            state_path = Path(__file__).parent.parent / "data" / "inspection_state.json"
            if state_path.exists():
                with open(state_path, "r", encoding="utf-8") as f:
                    st = json.load(f)
                    questions = st.get("questions", {})

        # 构造带 qid 的列表
        qlist = []
        for k, v in (questions.items() if isinstance(questions, dict) else []):
            item = dict(v or {})
            item["qid"] = k
            if only_module and only_module not in k:
                continue
            qlist.append(item)

        from src.report_exporter import ReportExporter
        exporter = ReportExporter(save_dir)
        report_path = exporter.export_docx(qlist, metadata={
            "version": st.get("version", "未知版本"),
            "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        })

        if not report_path:
            return jsonify({"success": False, "error": "报告生成失败（python-docx 不可用？）"}), 500

        return jsonify({
            "success": True,
            "path": str(report_path),
            "url": f"/api/export/download/{Path(report_path).name}",
            "stats": {"total_questions": len(qlist),
                      "error_questions": sum(1 for q in qlist
                                             if q.get("overall_passed") is False
                                             or q.get("question_type") == "错题截图")}
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
        
        # ★ 加载巡检数据：优先内存（多模块最新结果），文件兜底
        questions = {}
        if state_provider:
            try:
                _mem = state_provider() or {}
                if _mem.get("questions"):
                    questions = _mem.get("questions", {})
            except Exception:
                pass
        if not questions:
            state_path = Path(__file__).parent.parent / "data" / "inspection_state.json"
            if state_path.exists():
                with open(state_path, "r", encoding="utf-8") as f:
                    questions = json.load(f).get("questions", {})

        # 只导出错误题
        failed = {k: v for k, v in questions.items() if not v.get("overall_passed")}
        
        # 使用 ReportExporter
        from src.report_exporter import ReportExporter
        exporter = ReportExporter(save_dir)
        qlist = list(questions.values()) if isinstance(questions, dict) else questions
        csv_path = exporter.export_csv(qlist)
        
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
        # ★ 加载巡检数据：优先内存（多模块最新结果），文件兜底
        questions = {}
        if state_provider:
            try:
                _mem = state_provider() or {}
                if _mem.get("questions"):
                    questions = _mem.get("questions", {})
            except Exception:
                pass
        if not questions:
            state_path = Path(__file__).parent.parent / "data" / "inspection_state.json"
            if state_path.exists():
                with open(state_path, "r", encoding="utf-8") as f:
                    questions = json.load(f).get("questions", {})

        # 找不通过的题
        failed = {k: v for k, v in questions.items() if not v.get("overall_passed")}
        if not failed:
            return jsonify({"error": "没有不通过的题目"}), 400

        # 使用 ReportExporter
        from src.report_exporter import ReportExporter
        exporter = ReportExporter()
        qlist = list(questions.values()) if isinstance(questions, dict) else questions
        zip_path = exporter.export_screenshots_zip(qlist)
        
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

        # 也检查 save_dir / gen_scripts（生成脚本也走这里下载）
        if not file_path.exists():
            config = _load_export_config()
            save_dir = config.get("save_dir", "")
            if save_dir:
                file_path = Path(save_dir) / filename
        if not file_path.exists():
            _gen = Path(__file__).parent.parent / "gen_scripts"
            if _gen.exists():
                file_path = _gen / filename

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
