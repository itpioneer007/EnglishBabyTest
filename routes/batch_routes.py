"""
routes/batch_routes.py — 批量自动化调度
负责：B同学

接口列表：
  POST /api/batch/start       → 启动批量任务(传入版本+Unit范围+阶段列表)
  GET  /api/batch/status      → 当前进度 {completed, total, current_module, eta}
  POST /api/batch/pause       → 暂停
  POST /api/batch/resume      → 继续
  POST /api/batch/cancel      → 取消
  GET  /api/batch/history     → 历史批量任务记录

依赖：
  src.batch_runner.BatchRunner   — 批量任务调度器
  src.progress_tracker.ProgressTracker — 进度持久化

数据结构约定（见 接口约定.md）
"""

from flask import jsonify, request
from datetime import datetime
import json
from pathlib import Path

# ============================================
# 数据契约
# ============================================
"""
_batch_plan 结构（B 的输入）:
{
    "version": "新湘鲁六上",
    "units": [6, 7, 8, 9],
    "stages": ["基础巩固", "综合进阶"],
    "docx": "260717新湘鲁六上听力专项(已二校).docx",
    "email_to": "teacher@school.com"   // 可选：跑完自动发给谁
}

_batch_status 结构（B 的输出，A 和 C 都读）:
{
    "running": true,
    "plan": { "version": "...", "units": [6,7,8,9], "stages": ["基础巩固"] },
    "completed": [
        {"unit": 6, "stage": "基础巩固", "questions": 14, "passed": 10, "failed": 4, "duration": "4m12s"}
    ],
    "current": {"unit": 7, "stage": "基础巩固", "question": "Q03"},
    "pending": [{"unit": 7, "stage": "综合进阶"}, {"unit": 8, "stage": "基础巩固"}, ...],
    "failed_modules": [{"unit": 9, "stage": "难点突破", "reason": "导航失败", "retries": 3}],
    "started_at": "2026-07-28T17:00:00",
    "eta_remaining": "12分钟",
    "paused": false
}
"""


def _load_progress():
    """加载批量进度（断点续传用）"""
    progress_path = Path(__file__).parent.parent / "data" / "batch_progress.json"
    if progress_path.exists():
        with open(progress_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


_BATCH_STATUS = {
    "running": False,
    "plan": {},
    "completed": [],
    "current": None,
    "pending": [],
    "failed_modules": [],
    "started_at": None,
    "eta_remaining": "",
    "paused": False
}

# 全局引用（保持对runner实例的引用方便pause/resume/cancel）
_batch_runner = None


def _on_batch_progress(status: dict):
    """进度回调：同步到 _BATCH_STATUS 供前端轮询"""
    global _BATCH_STATUS
    status["paused"] = _BATCH_STATUS.get("paused", False)
    _BATCH_STATUS = status


def _on_batch_complete(result: dict):
    """完成回调：自动导出错误到输出文件夹"""
    global _BATCH_STATUS
    _BATCH_STATUS["running"] = False
    _BATCH_STATUS["paused"] = False
    _BATCH_STATUS["current"] = None

    # 自动调用 C 的 ErrorCollector
    try:
        from src.error_collector import ErrorCollector
        from pathlib import Path
        import json

        state_path = Path(__file__).parent.parent / "data" / "inspection_state.json"
        if state_path.exists():
            with open(state_path, "r", encoding="utf-8") as f:
                questions = json.load(f).get("questions", {})

            if questions:
                plan = _BATCH_STATUS.get("plan", {})
                version = plan.get("version", "未知版本")
                # 使用最后一个模块的信息
                last_completed = _BATCH_STATUS.get("completed", [])
                if last_completed:
                    last = last_completed[-1]
                    coll = ErrorCollector()
                    coll.collect(questions, version, last.get("unit", 0), last.get("stage", ""))
                    print(f"[BatchRoutes] 自动导出完成: {coll.current_dir}")
    except Exception as e:
        print(f"[BatchRoutes] 自动导出失败: {e}")


def register(app):
    """注册批量调度相关路由到 Flask app"""

    @app.route("/api/batch/start", methods=["POST"])
    def api_batch_start():
        global _batch_runner

        data = request.get_json() or {}
        plan = {
            "version": data.get("version", "新湘鲁六上"),
            "units": data.get("units", [6]),
            "stages": data.get("stages", ["基础巩固"]),
            "docx": data.get("docx", ""),
            "email_to": data.get("email_to", ""),
        }

        if _batch_runner and _batch_runner.running:
            return jsonify({"error": "已有批量任务在运行"}), 409

        from src.batch_runner import BatchRunner

        _batch_runner = BatchRunner(
            plan,
            on_progress=_on_batch_progress,
            on_complete=_on_batch_complete,
        )

        _batch_runner.start()
        eta = _batch_runner.estimate_time()
        return jsonify({
            "success": True,
            "modules": len(_batch_runner.pending),
            "eta": eta,
        })


    @app.route("/api/batch/status")
    def api_batch_status():
        return jsonify(_BATCH_STATUS)


    @app.route("/api/batch/pause", methods=["POST"])
    def api_batch_pause():
        if _batch_runner:
            _batch_runner.pause()
        return jsonify({"success": True})


    @app.route("/api/batch/resume", methods=["POST"])
    def api_batch_resume():
        if _batch_runner:
            _batch_runner.resume()
        return jsonify({"success": True})


    @app.route("/api/batch/cancel", methods=["POST"])
    def api_batch_cancel():
        if _batch_runner:
            _batch_runner.cancel()
        return jsonify({"success": True})


    @app.route("/api/batch/dry-run", methods=["POST"])
    def api_batch_dry_run():
        """
        纯遍历模式：不审题，不断言，只点完所有题
        POST Body: {"text": "帮我检测新湘鲁U6-U9听力专项"} 或 {"version","units","stages"}
        """
        global _BATCH_STATUS

        data = request.get_json() or {}
        text = data.get("text", "").strip()

        # 从自然语言解析
        if text:
            from src.smart_parser import parse
            plan = parse(text)
        else:
            plan = {
                "version": data.get("version", "新湘鲁六上"),
                "units": data.get("units", [6]),
                "stages": data.get("stages", ["基础巩固"]),
            }

        # 标记运行
        _BATCH_STATUS["running"] = True
        _BATCH_STATUS["plan"] = plan
        _BATCH_STATUS["started_at"] = datetime.now().isoformat()
        _BATCH_STATUS["completed"] = []
        _BATCH_STATUS["failed_modules"] = []
        _BATCH_STATUS["paused"] = False

        import threading

        def run():
            global _BATCH_STATUS
            from src.dry_run import DryRunner
            from web_server import get_adb, log_msg

            adb = get_adb()
            runner = DryRunner(adb)

            tasks = []
            for u in plan.get("units", []):
                for s in plan.get("stages", []):
                    tasks.append({"unit": u, "stage": s})
            _BATCH_STATUS["pending"] = [dict(t) for t in tasks]

            for task in tasks:
                if not _BATCH_STATUS["running"]:
                    break
                while _BATCH_STATUS.get("paused"):
                    time.sleep(1)

                _BATCH_STATUS["current"] = {"unit": task["unit"], "stage": task["stage"]}

                result = runner.click_through_module(
                    task["unit"], task["stage"],
                    plan.get("version", "新湘鲁六上")
                )
                if result["success"]:
                    _BATCH_STATUS["completed"].append({
                        "unit": task["unit"], "stage": task["stage"],
                        "questions": result["questions_done"],
                    })
                else:
                    _BATCH_STATUS["failed_modules"].append({
                        "unit": task["unit"], "stage": task["stage"],
                        "reason": result.get("error", "未知"),
                    })

            _BATCH_STATUS["running"] = False
            _BATCH_STATUS["current"] = None
            _BATCH_STATUS["paused"] = False

        t = threading.Thread(target=run, daemon=True)
        t.start()

        modules = len(plan.get("units", [])) * len(plan.get("stages", []))
        return jsonify({"success": True, "modules": modules, "eta": f"约{modules * 3}分钟"})


    @app.route("/api/batch/parse", methods=["POST"])
    def api_batch_parse():
        """
        自然语言 → 结构化任务计划
        POST Body: {"text": "帮我们检测新湘鲁六年级上册的U6-U9听力专项"}
        → {"version":"新湘鲁六上","units":[6,7,8,9],"stages":["基础巩固"],"module_type":"听力专项"}
        """
        data = request.get_json() or {}
        text = data.get("text", "").strip()
        if not text:
            return jsonify({"error": "请输入描述"}), 400

        from src.smart_parser import parse
        plan = parse(text)
        return jsonify(plan)


    @app.route("/api/batch/history")
    def api_batch_history():
        """返回历史批量任务记录"""
        history_path = Path(__file__).parent.parent / "data" / "batch_history.json"
        if history_path.exists():
            with open(history_path, "r", encoding="utf-8") as f:
                return jsonify(json.load(f))
        return jsonify([])


    @app.route("/batch")
    def page_batch():
        """批量控制页面"""
        from flask import render_template
        return render_template("batch.html")
