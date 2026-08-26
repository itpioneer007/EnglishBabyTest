"""
routes/error_log_routes.py — 实时错题报告接口

提供:
  GET /api/errors/live        返回当前实时生成的"仅错误"可折叠卡片 HTML 报告
                              (审查进行中每出一道错题即更新, 可直接用 iframe 嵌入前端)
  GET /api/errors/live-status 返回报告文件路径与当前错题数 (供前端按钮/提示使用)
"""

from pathlib import Path

from flask import jsonify, send_file


def _find_latest_live_report() -> str:
    """找最新生成的 report_live.html（服务重启后内存路径丢失时的兜底）"""
    try:
        root = Path(__file__).parent.parent / "outputs" / "reports"
        candidates = []
        for p in root.rglob("report_live.html"):
            candidates.append((p.stat().st_mtime, p))
        if candidates:
            candidates.sort(reverse=True)
            return str(candidates[0][1])
    except Exception:
        pass
    return ""


def register(app):
    # 延迟引用 web_server 模块，避免循环导入：
    # web_server 在第 56 行调用本 register() 时，_inspection_state 尚未定义；
    # 处理函数运行时该全局变量早已就绪，故在 handler 内通过 web_server._inspection_state 访问。
    import web_server

    @app.route("/api/errors/live", methods=["GET"])
    def api_error_live():
        """返回实时错题报告 HTML（供前端 iframe 预览）"""
        path = web_server._inspection_state.get("live_report_path", "")
        # ★ 服务重启后内存 live_report_path 丢失 → 兜底读最新生成的报告文件
        if not path or not Path(path).exists():
            path = _find_latest_live_report()
        if not path or not Path(path).exists():
            return jsonify({
                "error": "尚无实时报告，请先运行一次审查",
                "path": ""
            }), 404
        return send_file(
            path,
            as_attachment=False,
            download_name="report_live.html",
            mimetype="text/html",
        )

    @app.route("/api/errors/live-status", methods=["GET"])
    def api_error_live_status():
        """返回实时报告状态（路径 + 错题数），供前端按钮/提示使用

        ★ 2026-08-25 统计口径与 /api/errors/summary 对齐：
          只统计实际测试的题（auto-Q*），不统计脚本全量审查题（*-脚本-Q*）；
          且只有严格不通过(False)才算错题（None 未审查不计）。"""
        path = web_server._inspection_state.get("live_report_path", "")
        questions = web_server._inspection_state.get("questions", {})
        # ★ 服务重启后内存空 → 读持久化文件（data/inspection_state.json）
        if not questions:
            try:
                _p = Path(__file__).parent.parent / "data" / "inspection_state.json"
                if _p.exists():
                    import json as _json
                    questions = (_json.loads(_p.read_text(encoding="utf-8")) or {}).get("questions", {})
            except Exception:
                questions = {}
        if not path or not Path(path).exists():
            path = _find_latest_live_report()
        # ★ 只统计实际测试的题（auto-Q 前缀）；脚本全量审查题（*-脚本-Q*）不计入
        q_items = list(questions.items()) if isinstance(questions, dict) else [
            (str(q.get("qid") or f"q{i}"), q) for i, q in enumerate(questions)]
        tested = [q for _qid, q in q_items
                  if str(_qid).startswith("auto-Q") or
                  (str(_qid).startswith("Q") and "脚本-Q" not in str(_qid))]
        failed = sum(
            1 for q in tested
            if q.get("overall_passed") is False   # ★ 严格不通过；None(未审查)不计
        )
        return jsonify({
            "path": path if (path and Path(path).exists()) else "",
            "failed": failed,
            "total": len(tested),
            "ready": bool(path and Path(path).exists()),
        })

    @app.route("/api/errors/live/regenerate", methods=["POST"])
    def api_error_live_regenerate():
        """★ 即时重新生成实时错题报告（有数据但报告文件不存在/过期时前端调用）。
        → 让「📑 查看报告」按钮永远有实际内容可看，不再显示"暂无报告"空壳。
        """
        try:
            path = web_server._live_regen_error_report()
            if path:
                return jsonify({"success": True, "path": path,
                                "url": "/api/errors/live?t=" + str(int(__import__("time").time()))})
            return jsonify({"success": False, "error": "无错题数据可生成报告"}), 400
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
