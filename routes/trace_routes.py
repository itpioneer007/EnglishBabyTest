"""
routes/trace_routes.py — 错误溯源 & 截图标注
负责：C同学

接口列表：
  GET  /api/trace/<qid>       → 返回单道题的完整溯源数据(截图+脚本+错误维度+修改建议)
  GET  /api/trace/list        → 返回所有不通过题目的简短溯源列表
  GET  /api/trace/screenshot/<qid>/<dim>  → 返回某道题某维度的截图(可带红框标注)

依赖：
  src.trace_engine.TraceEngine  — 生成溯源数据
  src.review_agent.ReviewAgent  — 已有的审查结果(复用现有 _inspection_state)

数据结构约定（见 接口约定.md）
  出入参格式见下方 _data_contract 注释
"""

from flask import jsonify, request, send_file
from datetime import datetime
import json, os
from pathlib import Path

# ============================================
# 数据契约（三人必须一致）
# ============================================
"""
_review_item 结构（已有的，B 的批量调度产出的每条记录）:
{
    "qid": "新湘鲁六上-U6-Q03",
    "idx": 3,
    "question_type": "听音选择词汇",
    "screenshot": "q03.png",
    "stem": "英语课上...",
    "recording": "This student is helpful.",
    "script_answer": "B",
    "ai_stem": false, "ai_content": false, "ai_image": true, "ai_answer": true,
    "stem_reason": "...", "content_reason": "...", "image_reason": "...", "answer_reason": "...",
    "overall_passed": false,
    "overall_score": 0.5
}

_trace_detail 结构（A 生成，C 的导出也读取）:
{
    "qid": "新湘鲁六上-U6-Q03",
    "question_type": "听音选择词汇",
    "screenshot": "q03.png",
    "overall_passed": false,
    "overall_score": 0.5,
    "checks": [
        {
            "dimension": "内容",
            "passed": false,
            "reason": "选项B应为careful，但显示为care",
            "suggestion": "将选项B的care改为careful",
            "severity": "high",
            "error_region": {"x": 200, "y": 800, "w": 300, "h": 50}   // 可选的截图标注坐标
        }
    ],
    "script_context": {
        "stem": "英语课上...",
        "recording": "This student is helpful.",
        "answer": "B",
        "options": ["A. help", "B. helpful", "C. happy"],
        "kb_words": ["helpful", "student", "care"]
    },
    "timestamp": "2026-07-28T17:00:00"
}
"""


# ============================================
# 骨架实现（A 在这里填真正的业务逻辑）
# ============================================

def _load_inspection_state():
    """加载巡检状态数据（复用现有的 _inspection_state 机制）"""
    state_path = Path(__file__).parent.parent / "data" / "inspection_state.json"
    if state_path.exists():
        with open(state_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"questions": {}, "workflow_steps": []}


def register(app):
    """注册溯源相关路由到 Flask app — C同学实现"""

    @app.route("/api/trace/<qid>")
    def api_trace_detail(qid):
        """
        返回单道题的完整溯源数据
        GET /api/trace/新湘鲁六上-U6-Q03
        → { qid, checks: [...], script_context: {...} }
        """
        # ===== C 在这里实现 =====
        state = _load_inspection_state()
        q_data = state.get("questions", {}).get(qid)
        if not q_data:
            return jsonify({"error": "题目不存在"}), 404
        
        # TODO(A): 调用 src.trace_engine.TraceEngine.generate(qid, q_data)
        # 返回 _trace_detail 结构
        from src.trace_engine import TraceEngine
        
        try:
            engine = TraceEngine()
            result = engine.generate(qid, q_data)
            return jsonify(result)
        except ImportError:
            # 骨架模式：返回基础数据
            checks = [
                {"dimension": d, "passed": q_data.get(f"ai_{d[:3]}", False),
                 "reason": q_data.get(f"{_dim_key(d)}_reason", ""), "suggestion": "",
                 "severity": "high" if not q_data.get(f"ai_{d[:3]}", False) else "low"}
                for d in ["stem", "content", "image", "answer"]
            ]
            return jsonify({
                "qid": qid,
                "question_type": q_data.get("question_type", ""),
                "screenshot": q_data.get("screenshot", ""),
                "overall_passed": q_data.get("overall_passed", False),
                "overall_score": q_data.get("overall_score", 0),
                "checks": checks,
                "script_context": {
                    "stem": q_data.get("stem", ""),
                    "recording": q_data.get("recording", ""),
                    "answer": q_data.get("script_answer", ""),
                    "options": [],
                    "kb_words": []
                },
                "timestamp": datetime.now().isoformat()
            })


    @app.route("/api/trace/list")
    def api_trace_list():
        """
        返回所有不通过题目的溯源列表（前端卡片用）
        GET /api/trace/list
        → [{qid, question_type, overall_score, failed_dims}] 只返回不通过的
        """
        # ===== A 在这里实现 =====
        state = _load_inspection_state()
        failed = []
        for qid, q in state.get("questions", {}).items():
            if not q.get("overall_passed", True):
                dims = ["stem", "content", "image", "answer"]
                failed.append({
                    "qid": qid,
                    "idx": q.get("idx", 0),
                    "question_type": q.get("question_type", ""),
                    "overall_score": q.get("overall_score", 0),
                    "screenshot": q.get("screenshot", ""),
                    "failed_dims": [d for d in dims if not q.get(f"ai_{d[:3]}", False)]
                })
        return jsonify({"total": len(failed), "items": failed})


    @app.route("/api/trace/screenshot/<qid>/<dim>")
    def api_trace_screenshot_marked(qid, dim):
        """
        返回标注了错误区域的截图（可选，用Pillow在截图上画红框）
        GET /api/trace/screenshot/新湘鲁六上-U6-Q03/content
        → 返回一张PNG图片
        """
        # ===== A 在这里实现（可选）=====
        # 如果暂时做不了图片标注，直接返回原始截图
        from flask import send_file
        state = _load_inspection_state()
        q_data = state.get("questions", {}).get(qid, {})
        shot_name = q_data.get("screenshot", "")
        if not shot_name:
            return jsonify({"error": "无截图"}), 404
        
        shot_path = Path(__file__).parent.parent / "screenshots" / shot_name
        if shot_path.exists():
            return send_file(str(shot_path), mimetype="image/png")
        return jsonify({"error": "截图文件不存在"}), 404
    
    # ========================================
    # 前端溯源面板页面
    # ========================================
    
    @app.route("/trace")
    def page_trace():
        """溯源详情页（完整的错误审查面板）"""
        from flask import render_template
        return render_template("trace.html")


def _dim_key(dim_short):
    """dim缩写 → 全名映射"""
    return {"stem": "stem", "content": "content", "image": "image", "answer": "answer"}.get(dim_short, dim_short)
