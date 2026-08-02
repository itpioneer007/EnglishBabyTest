#!/usr/bin/env python
"""
英语宝 · 自动化控制台（含完整答题流程）
======================================
从浏览器一键启动任务，实时看日志。
"""

import sys, os, json, time, subprocess, threading
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from flask import Flask, Response, request, jsonify, stream_with_context

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
PYTHON = "C:/Users/19507/.workbuddy/binaries/python/versions/3.13.12/python.exe"

app = Flask(__name__)
task_logs = {}
task_status = {}
task_counter = 0


def _background(task_id, script, args="", label=""):
    log = []
    task_status[task_id] = "running"
    task_logs[task_id] = log
    log.append(f"=== 启动任务: {label} ===")
    try:
        script_path = os.path.join(PROJECT_ROOT, "scripts", script)
        cmd = [PYTHON, "-u", script_path]
        if args:
            import shlex
            cmd.extend(shlex.split(args))
        proc = subprocess.Popen(cmd, cwd=PROJECT_ROOT,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1)
        for line in iter(proc.stdout.readline, ""):
            log.append(line.rstrip())
            if len(log) > 300:
                log[:] = log[-300:]
        proc.wait()
        task_status[task_id] = "done" if proc.returncode == 0 else "error"
        # 附加报告
        report_path = os.path.join(PROJECT_ROOT, "outputs", "qa_report.json")
        if os.path.exists(report_path):
            log.append("\n=== 答题报告 ===")
            with open(report_path, encoding="utf-8") as f:
                report = json.load(f)
            if isinstance(report, dict):
                qs = report.get("questions_count", 0)
                log.append(f"题数: {qs}")
                for r in report.get("records", []):
                    log.append(f"  Q{r['q_no']}: 选{r.get('my_answer','?')} 正确:{r.get('correct_answer','?')}")
            log.append("=== 报告结束 ===")
    except Exception as e:
        log.append(f"\n>>> 异常: {e}")
        task_status[task_id] = "error"


@app.route("/")
def index():
    return HTML_PAGE

@app.route("/api/status")
def api_status():
    result = {}
    for tid, st in task_status.items():
        result[tid] = {"status": st, "count": len(task_logs.get(tid, []))}
    return jsonify(result)

@app.route("/api/log/<task_id>")
def api_log(task_id):
    def gen():
        last_len = 0
        while task_status.get(task_id) == "running":
            lines = task_logs.get(task_id, [])
            if len(lines) > last_len:
                for line in lines[last_len:]:
                    yield f"data: {line}\n\n"
                last_len = len(lines)
            time.sleep(0.3)
        lines = task_logs.get(task_id, [])
        for line in lines[last_len:]:
            yield f"data: {line}\n\n"
        yield f"data: [[DONE]] {task_status.get(task_id, 'unknown')}\n\n"
    return Response(stream_with_context(gen()), mimetype="text/event-stream")

@app.route("/api/run", methods=["POST"])
def api_run():
    global task_counter
    data = request.get_json() or {}
    script = data.get("script", "")
    args = data.get("args", "")
    label = data.get("label", script)
    task_counter += 1
    tid = f"task_{task_counter}"
    task_status[tid] = "starting"
    task_logs[tid] = []
    t = threading.Thread(target=_background, args=(tid, script, args, label), daemon=True)
    t.start()
    return jsonify({"task_id": tid, "label": label, "status": "started"})

@app.route("/api/report")
def api_report():
    path = os.path.join(PROJECT_ROOT, "outputs", "qa_report.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return jsonify(json.load(f))
    return jsonify({"error": "no report"})


HTML_PAGE = r"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>英语宝 · 自动化控制台</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Microsoft YaHei',sans-serif;background:#0d1117;color:#e6edf3}
.header{background:linear-gradient(135deg,#1f6feb,#0d47a1);padding:24px 32px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px}
.header h1{font-size:1.3rem}.header .sub{font-size:.8rem;opacity:.7}
.container{max-width:1100px;margin:0 auto;padding:20px 16px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media(max-width:800px){.grid2{grid-template-columns:1fr}}

.card{background:#161b22;border:1px solid #30363d;border-radius:10px;padding:20px;margin-bottom:16px}
.card h2{font-size:1.05rem;margin-bottom:12px;color:#58a6ff}

.btns{display:flex;flex-wrap:wrap;gap:8px}
.btn{padding:12px 16px;border:none;border-radius:6px;font-size:.85rem;font-weight:600;cursor:pointer;color:#fff;flex:1;min-width:140px;transition:all .2s}
.btn.blue{background:#1f6feb}.btn.blue:hover{background:#388bfd}
.btn.green{background:#238636}.btn.green:hover{background:#2ea043}
.btn.orange{background:#d29922}.btn.orange:hover{background:#e3b341}
.btn.purple{background:#6e40c9}.btn.purple:hover{background:#7c51d1}
.btn:disabled{opacity:.4;cursor:not-allowed}
.btn .sub{font-size:.72rem;opacity:.8;display:block;margin-top:2px}

.log-box{background:#0d1117;color:#c9d1d9;border:1px solid #30363d;border-radius:8px;padding:12px;height:500px;overflow-y:auto;font-family:'SF Mono','Consolas',monospace;font-size:.78rem;line-height:1.6;white-space:pre-wrap}
.log-ok{color:#3fb950}.log-err{color:#f85149}.log-warn{color:#d29922}.log-info{color:#58a6ff}

.status-row{display:flex;gap:16px;margin-top:8px;align-items:center;font-size:.82rem}
.dot{width:10px;height:10px;border-radius:50%;display:inline-block;margin-right:4px}
.dot.run{background:#d29922;animation:pulse 1s infinite}
.dot.done{background:#3fb950}.dot.err{background:#f85149}
@keyframes pulse{50%{opacity:.4}}

.report-card{background:#0d1117;border:1px solid #30363d;border-radius:8px;padding:12px;margin:4px 0;font-size:.82rem}
.report-card .r-q{color:#58a6ff;font-size:.75rem}
.report-card .r-ans{display:flex;gap:10px;margin-top:4px}
.ans-mine{color:#d29922}.ans-correct{color:#3fb950}.ans-wrong{color:#f85149}

.cmd-input{width:100%;padding:10px;background:#0d1117;border:1px solid #30363d;border-radius:6px;color:#e6edf3;font-size:.85rem;margin-bottom:8px}
.cmd-input::placeholder{color:#8b949e}
</style>
</head>
<body>
<div class="header">
  <div>
    <h1>🤖 英语宝 · 自动化控制台</h1>
    <div class="sub">湘少版(2024审定)五年级上册 · ADB 连接</div>
  </div>
  <div style="text-align:right;font-size:.8rem">
    <div id="taskStatus">就绪</div>
    <div style="opacity:.6" id="deviceId">SKSCIF4T7PFMQS5X</div>
  </div>
</div>

<div class="container">

<div class="grid2">

<!-- 左列 -->
<div>

<div class="card">
  <h2>🚀 一键任务</h2>
  <div class="btns">
    <button class="btn blue" onclick="run('run_engine.py','听力专项','完整答题 - 听力专��')">
      完整答题<span class="sub">听力专项</span></button>
    <button class="btn green" onclick="run('run_engine.py','听力专项,单词学习','多模块检测')">
      多模块检测<span class="sub">听力+单词</span></button>
  </div>
</div>

<div class="card">
  <h2>✏️ 自定义指令</h2>
  <input class="cmd-input" id="customCmd" placeholder="输入模块名，如：听力专项">
  <button class="btn purple" style="width:100%" onclick="custom()">执行</button>
</div>

<div class="card">
  <h2>📊 答题报告</h2>
  <div id="reportArea">
    <p style="color:#8b949e;font-size:.82rem">运行一次完整答题后自动显示</p>
  </div>
  <button class="btn blue" style="margin-top:8px;width:100%" onclick="loadReport()">刷新报告</button>
</div>

</div>

<!-- 右列 -->
<div class="card" style="display:flex;flex-direction:column">
  <h2>📋 实时日志 <span id="logStatus"></span></h2>
  <div class="log-box" id="logBox">点击左侧按钮开始……</div>
  <div class="status-row">
    <span id="dotArea"></span>
    <span id="logCount" style="color:#8b949e"></span>
    <button onclick="document.getElementById('logBox').textContent=''" style="margin-left:auto;font-size:.75rem;border:1px solid #30363d;background:#0d1117;color:#8b949e;padding:4px 12px;border-radius:4px;cursor:pointer">清空</button>
  </div>
</div>

</div>

<!-- 自动化机制说明 -->
<div class="container">
<div class="card">
  <h2>🔧 自动化引擎架构（B 角色：全自动引擎）</h2>

  <!-- 三层架构 -->
  <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin-bottom:14px">
    <div style="background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:12px;text-align:center">
      <div style="font-size:1.2rem;margin-bottom:2px">📋 B1 批量调度</div>
      <div style="font-size:.75rem;color:#8b949e;line-height:1.5">
        <code>batch_runner.py</code><br>
        任务清单 → 依次执行<br>
        失败重试 → 断点续传
      </div>
    </div>
    <div style="background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:12px;text-align:center">
      <div style="font-size:1.2rem;margin-bottom:2px">🔄 B4 异常恢复</div>
      <div style="font-size:.75rem;color:#8b949e;line-height:1.5">
        <code>recovery_handler.py</code><br>
        广告弹窗 → 暂无数据<br>
        APP崩溃 → 继续对话框
      </div>
    </div>
    <div style="background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:12px;text-align:center">
      <div style="font-size:1.2rem;margin-bottom:2px">📊 B5 进度追踪</div>
      <div style="font-size:.75rem;color:#8b949e;line-height:1.5">
        <code>progress_tracker.py</code><br>
        实时进度 → 预估剩余<br>
        JSON 持久化（断点）
      </div>
    </div>
  </div>

  <!-- 执行流程 -->
  <h3 style="font-size:.9rem;color:#58a6ff;margin-bottom:6px">任务执行流水线</h3>
  <div style="display:flex;align-items:center;font-size:.78rem;color:#8b949e;padding:6px 0;border-bottom:1px solid #21262d">
    <span style="background:#1f6feb33;color:#58a6ff;padding:2px 6px;border-radius:3px;font-weight:600;margin-right:6px">1</span>
    <span>侦测任务类型（go_module / go_unit / answer_question / nav_back……）</span>
  </div>
  <div style="display:flex;align-items:center;font-size:.78rem;color:#8b949e;padding:6px 0;border-bottom:1px solid #21262d">
    <span style="background:#1f6feb33;color:#58a6ff;padding:2px 6px;border-radius:3px;font-weight:600;margin-right:6px">2</span>
    <span>定位引擎<span style="color:#3fb950"> uiautomator</span> dump XML → 找 text/资源ID → 取 bounds 中心</span>
  </div>
  <div style="display:flex;align-items:center;font-size:.78rem;color:#8b949e;padding:6px 0;border-bottom:1px solid #21262d">
    <span style="background:#1f6feb33;color:#58a6ff;padding:2px 6px;border-radius:3px;font-weight:600;margin-right:6px">3</span>
    <span>异常检测层检查当前页（无数据？弹窗？崩溃？）<span style="color:#d29922">→ 恢复/跳过</span></span>
  </div>
  <div style="display:flex;align-items:center;font-size:.78rem;color:#8b949e;padding:6px 0;border-bottom:1px solid #21262d">
    <span style="background:#1f6feb33;color:#58a6ff;padding:2px 6px;border-radius:3px;font-weight:600;margin-right:6px">4</span>
    <span>ADB 执行点击<span style="color:#3fb950"> {{input tap x y}}</span> → 等待页面加载 → 记录结果</span>
  </div>
  <div style="display:flex;align-items:center;font-size:.78rem;color:#8b949e;padding:6px 0">
    <span style="background:#1f6feb33;color:#58a6ff;padding:2px 6px;border-radius:3px;font-weight:600;margin-right:6px">5</span>
    <span>更新进度追踪器 → 如失败标记并终止 → 返回</span>
  </div>

  <!-- 三人协作 -->
  <h3 style="font-size:.9rem;color:#58a6ff;margin:12px 0 6px">三人协作关系</h3>
  <div style="display:flex;gap:8px;font-size:.78rem">
    <div style="flex:1;background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:10px;text-align:center">
      <div style="color:#58a6ff;font-weight:600">A 审查增强</div>
      <div style="color:#8b949e;margin:4px 0">调 <code>review_agent.py</code><br>对截图做 6 维审查</div>
    </div>
    <div style="flex:1;background:#1f6feb22;border:1px solid #1f6feb;border-radius:6px;padding:10px;text-align:center">
      <div style="color:#58a6ff;font-weight:600">B 全自动引擎 ← 当前</div>
      <div style="color:#8b949e;margin:4px 0">
        <code>batch_runner.py</code><br>
        <code>recovery_handler.py</code><br>
        <code>progress_tracker.py</code>
      </div>
      <div style="color:#8b949e">↓ 产出截图 + 任务数据</div>
    </div>
    <div style="flex:1;background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:10px;text-align:center">
      <div style="color:#58a6ff;font-weight:600">C 错误输出</div>
      <div style="color:#8b949e;margin:4px 0">调 <code>export</code> 函数<br>生成教师报告</div>
    </div>
  </div>
  <div style="font-size:.75rem;color:#8b949e;margin-top:8px;padding:8px;background:#0d1117;border-radius:4px">
    B 产生的截图直达 A 的审查模块；产生的任务数据直达 C 的导出模块。
    三者通过文件路径 <code>outputs/</code> + <code>screenshots/</code> 解耦。
  </div>

  <!-- 已踩坑 -->
  <h3 style="font-size:.9rem;color:#58a6ff;margin:12px 0 6px">已踩过的坑 & 解决方案</h3>
  <div style="font-size:.78rem;color:#8b949e">
    <div style="display:flex;padding:4px 8px;border-bottom:1px solid #21262d">
      <span style="color:#f85149;margin-right:8px">⚠</span>
      <span>uiautomator 在模块列表页只返回标题「考前突破」</span>
      <span style="margin-left:auto;color:#3fb950">→ 硬编码 @(882, 703) 兜底</span>
    </div>
    <div style="display:flex;padding:4px 8px;border-bottom:1px solid #21262d">
      <span style="color:#f85149;margin-right:8px">⚠</span>
      <span>答题 1-2 题后弹「完成?% 继续练习？」对话框</span>
      <span style="margin-left:auto;color:#3fb950">→ recovery 自动检测并点继续</span>
    </div>
    <div style="display:flex;padding:4px 8px;border-bottom:1px solid #21262d">
      <span style="color:#f85149;margin-right:8px">⚠</span>
      <span>Android back 在答题页被吃掉，退出不了</span>
      <span style="margin-left:auto;color:#3fb950">→ 改用左上箭头 @(80, 165)</span>
    </div>
    <div style="display:flex;padding:4px 8px">
      <span style="color:#f85149;margin-right:8px">⚠</span>
      <span>PaddleOCR 3.3.1 + Windows ONEDNN 崩溃</span>
      <span style="margin-left:auto;color:#3fb950">→ 装 PaddlePaddle 3.2.0</span>
    </div>
  </div>
</div>
</div>

</div><!-- 结束 HTML_PAGE -->

<script>
let es = null;
let currentTask = null;

function run(script, args, label) {
  if (es) { es.close(); es = null; }
  document.getElementById('logBox').textContent = '启动中…\n';
  document.getElementById('taskStatus').textContent = '运行中';
  document.getElementById('dotArea').innerHTML = '<span class="dot run"></span>运行中';

  fetch('/api/run', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({script, args, label})
  }).then(r=>r.json()).then(d => {
    currentTask = d.task_id;
    streamLog(d.task_id);
  });
}

function custom() {
  const c = document.getElementById('customCmd').value.trim();
  if (!c) return;
  run('run_engine.py', c, c);
}

function streamLog(taskId) {
  if (es) es.close();
  es = new EventSource('/api/log/' + taskId);
  const box = document.getElementById('logBox');
  const dot = document.getElementById('dotArea');

  es.onmessage = function(e) {
    if (e.data.startsWith('[[DONE]]')) {
      const st = e.data.split(' ')[1];
      dot.innerHTML = st === 'done'
        ? '<span class="dot done"></span>完成'
        : '<span class="dot err"></span>出错';
      document.getElementById('taskStatus').textContent = st === 'done' ? '就绪' : '出错';
      es.close();
      loadReport();
      return;
    }
    let cls = '';
    if (e.data.includes('✅')) cls = 'log-ok';
    else if (e.data.includes('❌')) cls = 'log-err';
    else if (e.data.includes('⚠') || e.data.includes('跳过')) cls = 'log-warn';
    else if (e.data.includes('===') || e.data.includes('▶')) cls = 'log-info';
    else if (e.data.startsWith('Q') && e.data.includes('/')) cls = 'log-ok';

    if (box.textContent === '启动中…\n') box.textContent = '';
    box.innerHTML += '<span class="' + cls + '">' + esc(e.data) + '</span>\n';
    box.scrollTop = box.scrollHeight;
    document.getElementById('logCount').textContent = box.children.length + ' 行';
  };
  es.onerror = function() {
    dot.innerHTML = '<span class="dot err"></span>断连';
  };
}

function loadReport() {
  fetch('/api/report').then(r=>r.json()).then(d => {
    const area = document.getElementById('reportArea');
    if (d.error) { area.innerHTML = '<p style="color:#8b949e;font-size:.82rem">暂无报告</p>'; return; }
    let html = '<div style="margin-bottom:8px;font-size:.82rem">';
    html += '<span style="color:#58a6ff">' + d.module + '</span>';
    html += ' · ' + d.unit;
    html += ' · ' + (d.completed_at || '');
    html += ' · 共' + (d.questions_count || 0) + '题';
    html += '</div>';
    (d.records || []).forEach(r => {
      const isCorrect = r.correct_answer && r.my_answer !== r.correct_answer;
      html += '<div class="report-card">';
      html += '<div class="r-q">Q' + r.q_no + '/' + r.total + '</div>';
      html += '<div style="margin:2px 0">' + r.question + '</div>';
      html += '<div class="r-ans">';
      html += '我的: <span class="ans-mine">' + (r.my_answer || '?') + '</span>';
      if (r.correct_answer) {
        html += '正确: <span class="ans-correct">' + r.correct_answer + '</span>';
        html += isCorrect ? ' <span class="ans-wrong">✗</span>' : ' <span class="ans-correct">✓</span>';
      }
      html += '</div></div>';
    });
    area.innerHTML = html;
  }).catch(() => {});
}

function esc(t) {
  return t.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

loadReport();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    print("🤖 英语宝控制台: http://localhost:8866")
    app.run(host="0.0.0.0", port=8866, debug=False, threaded=True)
