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
    """完成回调：自动收集错误 + 生成报告 + 导出"""
    global _BATCH_STATUS
    _BATCH_STATUS["running"] = False
    _BATCH_STATUS["paused"] = False
    _BATCH_STATUS["current"] = None

    # 1. ErrorCollector: 收集错误到输出目录
    try:
        from src.error_collector import ErrorCollector
        from pathlib import Path
        import json

        state_path = Path(__file__).parent.parent / "data" / "inspection_state.json"
        if state_path.exists():
            with open(state_path, "r", encoding="utf-8") as f:
                state = json.load(f)
            questions = state.get("questions", [])

            if questions:
                plan = _BATCH_STATUS.get("plan", {})
                version = plan.get("version", "未知版本")
                last_completed = _BATCH_STATUS.get("completed", [])
                if last_completed:
                    last = last_completed[-1]
                    coll = ErrorCollector()
                    coll.collect(questions, version, last.get("unit", 0), last.get("stage", ""))
                    print(f"[BatchRoutes] 错误收集完成: {coll.current_dir}")
    except Exception as e:
        print(f"[BatchRoutes] 错误收集失败: {e}")

    # 2. ReportExporter: 生成 HTML + CSV + ZIP 报告
    try:
        from src.report_exporter import ReportExporter
        from pathlib import Path
        import json

        state_path = Path(__file__).parent.parent / "data" / "inspection_state.json"
        if state_path.exists():
            with open(state_path, "r", encoding="utf-8") as f:
                state = json.load(f)
            questions = state.get("questions", [])

            if questions:
                plan = _BATCH_STATUS.get("plan", {})
                last_completed = _BATCH_STATUS.get("completed", [])
                metadata = {
                    "version": plan.get("version", ""),
                    "unit": last_completed[-1].get("unit", 1) if last_completed else 1,
                    "stage": last_completed[-1].get("stage", "") if last_completed else "",
                }

                exporter = ReportExporter()
                results = exporter.export_all(questions, metadata=metadata)
                _BATCH_STATUS["export_results"] = results
                print(f"[BatchRoutes] 报告生成完成: {results.get('output_dir', '')}")
    except Exception as e:
        print(f"[BatchRoutes] 报告生成失败: {e}")


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
            from web_server import get_adb
            import time as _time

            adb = get_adb()
            runner = DryRunner(adb)
            module_start = None

            tasks = []
            for u in plan.get("units", []):
                for s in plan.get("stages", []):
                    tasks.append({"unit": u, "stage": s})
            _BATCH_STATUS["pending"] = [dict(t) for t in tasks]
            overall_start = _time.time()

            for task in tasks:
                if not _BATCH_STATUS["running"]:
                    break
                while _BATCH_STATUS.get("paused"):
                    _time.sleep(1)

                _BATCH_STATUS["current"] = {"unit": task["unit"], "stage": task["stage"]}
                log = f"▶ 开始模块: U{task['unit']} {task['stage']}"
                module_start = _time.time()

                result = runner.click_through_module(
                    task["unit"], task["stage"],
                    plan.get("version", "新湘鲁六上")
                )
                module_elapsed = _time.time() - module_start
                mod_time = f"{int(module_elapsed//60)}m{int(module_elapsed%60)}s"

                entry = {
                    "unit": task["unit"],
                    "stage": task["stage"],
                    "questions": result.get("questions_done", 0),
                    "duration": mod_time,
                }
                if result["success"]:
                    entry["status"] = "done"
                    _BATCH_STATUS["completed"].append(entry)
                else:
                    entry["status"] = "failed"
                    entry["error"] = result.get("error", "未知")
                    _BATCH_STATUS["failed_modules"].append(entry)

                # 累计耗时
                elapsed = _time.time() - overall_start
                _BATCH_STATUS["eta_remaining"] = f"{int(elapsed//60)}m{int(elapsed%60)}s"

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

    @app.route("/runner")
    def page_runner():
        """纯遍历专用页面 — B同学"""
        from flask import render_template
        return render_template("runner.html")

    # ============================================================
    # ★ P1: 审查一致性验证
    # ============================================================

    _consistency_status = {
        "running": False, "results": None, "progress": "", "error": ""
    }

    @app.route("/api/consistency/check", methods=["POST"])
    def api_consistency_check():
        """
        对已审查的题目执行一致性验证
        POST: {"question_ids": ["q001","q002"], "runs": 3}
        或 {"inspection_file": "data/inspection_state.json", "runs": 3, "limit": 10}
        """
        global _consistency_status
        data = request.get_json() or {}
        runs = data.get("runs", 3)

        if _consistency_status["running"]:
            return jsonify({"error": "一致性检查已在运行中"}), 409

        _consistency_status = {"running": True, "results": None, "progress": "初始化...", "error": ""}

        import threading
        def run():
            global _consistency_status
            try:
                from src.review_agent import ReviewAgent
                from src.consistency_checker import ConsistencyChecker

                agent = ReviewAgent()
                checker = ConsistencyChecker(agent)

                # 加载题目
                inspection_file = data.get("inspection_file", "")
                if inspection_file:
                    import json as _json
                    with open(inspection_file, "r", encoding="utf-8") as f:
                        state = _json.load(f)
                    questions_dict = {}
                    shots_dict = {}
                    limit = data.get("limit", 10)
                    for qd in state.get("questions", [])[:limit]:
                        qid = qd["qid"]
                        from src.parse_yingyubao_docx import YingYuBaoQuestion
                        q = YingYuBaoQuestion(
                            idx=qd.get("idx", 0),
                            stem=qd.get("stem", ""),
                            type_2=qd.get("question_type", ""),
                            answer=qd.get("script_answer", ""),
                        )
                        questions_dict[qid] = q
                        shots_dict[qid] = qd.get("screenshot", "")
                else:
                    # 手动指定题目ID
                    qids = data.get("question_ids", [])
                    questions_dict = {
                        q: YingYuBaoQuestion(idx=int(q[1:]) if q.startswith("q") else i)
                        for i, q in enumerate(qids)
                    }
                    shots_dict = {}

                if not questions_dict:
                    _consistency_status["error"] = "无题目可检查"
                    _consistency_status["running"] = False
                    return

                _consistency_status["progress"] = f"正在对 {len(questions_dict)} 道题进行 ×{runs} 次一致性检查..."
                reports = checker.check_batch(questions_dict, shots_dict, runs=runs)
                summary = checker.summary()

                import json as _json
                out = Path(__file__).parent.parent / "outputs" / "consistency_report.json"
                out.parent.mkdir(parents=True, exist_ok=True)
                with open(out, "w", encoding="utf-8") as f:
                    _json.dump(summary, f, ensure_ascii=False, indent=2)

                _consistency_status["results"] = summary
                _consistency_status["progress"] = (
                    f"完成: {summary['total_questions']}题, "
                    f"稳定{summary['stable_questions']}题, "
                    f"不稳定{summary['unstable_questions']}题"
                )
            except Exception as e:
                _consistency_status["error"] = str(e)
            finally:
                _consistency_status["running"] = False

        t = threading.Thread(target=run, daemon=True)
        t.start()
        return jsonify({"success": True, "message": "一致性检查已启动"})

    @app.route("/api/consistency/status")
    def api_consistency_status():
        """查询一致性检查进度"""
        return jsonify(_consistency_status)

    @app.route("/api/consistency/report")
    def api_consistency_report():
        """获取一致性检查报告"""
        p = Path(__file__).parent.parent / "outputs" / "consistency_report.json"
        if p.exists():
            import json as _json
            with open(p, "r", encoding="utf-8") as f:
                return jsonify(_json.load(f))
        return jsonify(_consistency_status.get("results") or {"error": "暂无报告"})

    @app.route("/consistency")
    def page_consistency():
        """一致性验证页面"""
        from flask import render_template
        return render_template("consistency.html")
