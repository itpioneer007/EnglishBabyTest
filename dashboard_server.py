#!/usr/bin/env python
"""
英语宝 · 自动化控制台 v4（对接拆分后的 config.py + engine.py + main.py）
=====================================================================
前端一键点击 → 后端线程内调用最新引擎函数 → 实时日志 + 汇总结果
"""

import sys, os, json, time, threading, contextlib, io

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.join(PROJECT_ROOT, "scripts")
sys.path.insert(0, SCRIPTS_DIR)

from flask import Flask, Response, request, jsonify, stream_with_context

from config import MODULE_CONFIG, GRADE_LEVEL, BOOK_VERSION, APP_PACKAGE, TARGET_MODULES
from engine import u2, close_ad, dismiss_global_popups, ensure_grade, run_single_module, back_to_home

app = Flask(__name__)
task_logs = {}
task_status = {}
task_results = {}
task_counter = 0

# ============ 引擎执行（线程内，捕获 stdout 实时日志） ============

class LogCapture(io.StringIO):
    """捕获 print 输出到任务日志"""
    def __init__(self, task_id):
        super().__init__()
        self.task_id = task_id
    def write(self, s):
        if s.strip():
            task_logs.setdefault(self.task_id, []).append(s.rstrip())
            if len(task_logs[self.task_id]) > 500:
                task_logs[self.task_id][:] = task_logs[self.task_id][-500:]
        return super().write(s)
    def flush(self):
        pass


def _run_detect(task_id, modules, grade, version):
    """在线程里执行模块检测"""
    log = task_logs.setdefault(task_id, [])
    result = {"modules": [], "total_questions": 0, "ok_count": 0,
              "started_at": time.strftime("%H:%M:%S"), "elapsed": 0}
    t0 = time.time()
    try:
        # 连接设备
        log.append("=== 启动自动化引擎 v3 ===")
        log.append(f"📋 目标模块: {modules}")
        log.append(f"📚 年级: {version} {grade}")
        d = u2.connect()
        log.append("✅ 设备已连接")
        d.app_stop(APP_PACKAGE); time.sleep(1)
        d.app_start(APP_PACKAGE); time.sleep(5)

        # 关广告 + 切年级
        dismiss_global_popups(d)
        close_ad(d)
        if not ensure_grade(d, grade, version):
            log.append("❌ 年级切换失败")
            task_status[task_id] = "error"
            return

        # 逐个模块检测
        for i, mod in enumerate(modules, 1):
            cfg = MODULE_CONFIG.get(mod)
            if not cfg:
                log.append(f"❌ 未知模块: {mod}，跳过")
                continue
            log.append(f"\n  [{i}/{len(modules)}]")
            q = run_single_module(d, mod, cfg)
            entry = {"module": mod, "questions": q,
                     "status": "成功" if q > 0 else "跳过/无数据"}
            result["modules"].append(entry)
            result["total_questions"] += q
            if q > 0:
                result["ok_count"] += 1
            log.append(f"✅ 模块 {mod} 完成: {q} 题")
            # 回主页（最后一个模块后不用回，直接展示状态）
            if i < len(modules):
                log.append(f"↩ 返回主页...")
                back_to_home(d, grade)
                time.sleep(2)

        result["elapsed"] = round(time.time() - t0, 1)
        result["finished_at"] = time.strftime("%H:%M:%S")
        log.append(f"\n{'='*45}")
        log.append(f"📊 汇总: 总模块{len(result['modules'])} | 有题{result['ok_count']} | 总题数{result['total_questions']} | 耗时{result['elapsed']}s")
        log.append(f"{'='*45}")
        task_results[task_id] = result
        task_status[task_id] = "done"
    except Exception as e:
        log.append(f"\n>>> 异常: {e}")
        task_status[task_id] = "error"


def _background(task_id, payload):
    """线程包装：重定向 stdout 捕获引擎日志"""
    task_status[task_id] = "running"
    modules = payload.get("modules", ["听力专项"])
    grade = payload.get("grade", "五年级上册")
    version = payload.get("version", "湘少版")
    capture = LogCapture(task_id)
    with contextlib.redirect_stdout(capture):
        _run_detect(task_id, modules, grade, version)


# ============ API ============

@app.route("/")
def index():
    return HTML_PAGE

@app.route("/api/status")
def api_status():
    return jsonify({tid: {"status": st,
                          "count": len(task_logs.get(tid, [])),
                          "result": task_results.get(tid)}
                    for tid, st in task_status.items()})

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

@app.route("/api/detect", methods=["POST"])
def api_detect():
    """一键检测：前端发模块列表 + 年级 → 后台跑引擎"""
    global task_counter
    data = request.get_json() or {}
    modules = data.get("modules", ["听力专项"])
    grade = data.get("grade", "五年级上册")
    version = data.get("version", "湘少版")
    task_counter += 1
    tid = f"task_{task_counter}"
    task_status[tid] = "starting"
    task_logs[tid] = []
    task_results[tid] = {}
    payload = {"modules": modules, "grade": grade, "version": version}
    t = threading.Thread(target=_background, args=(tid, payload), daemon=True)
    t.start()
    return jsonify({"task_id": tid, "modules": modules, "grade": grade, "status": "started"})

@app.route("/api/modules")
def api_modules():
    """返回引擎里已配置的模块列表"""
    return jsonify({"modules": list(MODULE_CONFIG.keys()),
                    "grade": GRADE_LEVEL,
                    "version": BOOK_VERSION})

@app.route("/api/result/<task_id>")
def api_result(task_id):
    return jsonify(task_results.get(task_id, {}))


HTML_PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>英语宝 · 自动化控制台 v3</title>
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
.log-box{background:#0d1117;color:#c9d1d9;border:1px solid #30363d;border-radius:8px;padding:12px;height:420px;overflow-y:auto;font-family:'SF Mono','Consolas',monospace;font-size:.78rem;line-height:1.6;white-space:pre-wrap}
.log-ok{color:#3fb950}.log-err{color:#f85149}.log-warn{color:#d29922}.log-info{color:#58a6ff}
.status-row{display:flex;gap:16px;margin-top:8px;align-items:center;font-size:.82rem}
.dot{width:10px;height:10px;border-radius:50%;display:inline-block;margin-right:4px}
.dot.run{background:#d29922;animation:pulse 1s infinite}
.dot.done{background:#3fb950}.dot.err{background:#f85149}
@keyframes pulse{50%{opacity:.4}}
.cmd-input{width:100%;padding:10px;background:#0d1117;border:1px solid #30363d;border-radius:6px;color:#e6edf3;font-size:.85rem;margin-bottom:8px}
.cmd-input::placeholder{color:#8b949e}
select{width:100%;padding:10px;background:#0d1117;border:1px solid #30363d;border-radius:6px;color:#e6edf3;font-size:.85rem;margin-bottom:8px}
.res-table{width:100%;border-collapse:collapse;font-size:.82rem}
.res-table th,.res-table td{border:1px solid #30363d;padding:8px 10px;text-align:left}
.res-table th{background:#21262d;color:#58a6ff;font-weight:600}
.res-ok{color:#3fb950;font-weight:600}
.res-skip{color:#d29922;font-weight:600}
.sum-box{background:#0d1117;border:1px solid #30363d;border-radius:8px;padding:14px;margin-top:12px;display:grid;grid-template-columns:repeat(4,1fr);gap:10px;text-align:center}
.sum-box .num{font-size:1.4rem;font-weight:700;color:#58a6ff}
.sum-box .lbl{font-size:.72rem;color:#8b949e;margin-top:2px}
</style>
</head>
<body>
<div class="header">
  <div>
    <h1>🤖 英语宝 · 自动化控制台 v3</h1>
    <div class="sub" id="versionInfo">引擎加载中…</div>
  </div>
  <div style="text-align:right;font-size:.8rem">
    <div id="taskStatus">就绪</div>
    <div style="opacity:.6">SKSCIF4T7PFMQS5X</div>
  </div>
</div>

<div class="container">
<div class="grid2">

<!-- 左列：控制 -->
<div>
  <div class="card">
    <h2>🚀 模块检测</h2>
    <div class="btns">
      <button class="btn blue" onclick="detect(['听力专项'])">
        听力专项<span class="sub">完整流程</span></button>
      <button class="btn green" onclick="detect(['听力专项','单元自检','单词听写'])">
        批量检测<span class="sub">3个模块</span></button>
    </div>
    <div style="margin-top:12px">
      <h2 style="font-size:.9rem">✏️ 自定义检测</h2>
      <select id="moduleSelect" multiple size="6"></select>
      <button class="btn purple" style="width:100%;margin-top:8px" onclick="customDetect()">执行选中模块</button>
    </div>
  </div>

  <div class="card">
    <h2>📊 检测结果</h2>
    <div id="resultArea">
      <p style="color:#8b949e;font-size:.82rem">运行检测后自动显示</p>
    </div>
  </div>
</div>

<!-- 右列：日志 -->
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
</div>

<script>
let es = null;
let currentTask = null;

function detect(modules) {
  if (es) { es.close(); es = null; }
  document.getElementById('logBox').textContent = '启动中…\n';
  document.getElementById('taskStatus').textContent = '运行中';
  document.getElementById('dotArea').innerHTML = '<span class="dot run"></span>运行中';
  document.getElementById('resultArea').innerHTML = '<p style="color:#8b949e;font-size:.82rem">检测进行中…</p>';

  fetch('/api/detect', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({modules, grade:'五年级上册', version:'湘少版'})
  }).then(r=>r.json()).then(d => {
    currentTask = d.task_id;
    streamLog(d.task_id);
  });
}

function customDetect() {
  const sel = document.getElementById('moduleSelect');
  const modules = Array.from(sel.selectedOptions).map(o => o.value);
  if (!modules.length) { alert('请先选择模块'); return; }
  detect(modules);
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
      loadResult(taskId);
      return;
    }
    let cls = '';
    if (e.data.includes('✅')) cls = 'log-ok';
    else if (e.data.includes('❌')) cls = 'log-err';
    else if (e.data.includes('⚠') || e.data.includes('跳过')) cls = 'log-warn';
    else if (e.data.includes('===') || e.data.includes('📊') || e.data.includes('📋')) cls = 'log-info';

    if (box.textContent === '启动中…\n') box.textContent = '';
    box.innerHTML += '<span class="' + cls + '">' + esc(e.data) + '</span>\n';
    box.scrollTop = box.scrollHeight;
    document.getElementById('logCount').textContent = box.children.length + ' 行';
  };
  es.onerror = function() {
    dot.innerHTML = '<span class="dot err"></span>断连';
  };
}

function loadResult(taskId) {
  fetch('/api/result/' + taskId).then(r=>r.json()).then(d => {
    const area = document.getElementById('resultArea');
    if (!d.modules || !d.modules.length) {
      area.innerHTML = '<p style="color:#8b949e;font-size:.82rem">无结果数据</p>';
      return;
    }
    let html = '<table class="res-table"><tr><th>模块</th><th>题数</th><th>状态</th></tr>';
    d.modules.forEach(m => {
      const ok = m.status === '成功';
      html += '<tr><td>' + m.module + '</td><td>' + m.questions + '</td>'
            + '<td class="' + (ok ? 'res-ok' : 'res-skip') + '">' + m.status + '</td></tr>';
    });
    html += '</table>';
    html += '<div class="sum-box">'
          + '<div><div class="num">' + d.modules.length + '</div><div class="lbl">模块数</div></div>'
          + '<div><div class="num">' + d.ok_count + '</div><div class="lbl">成功</div></div>'
          + '<div><div class="num">' + d.total_questions + '</div><div class="lbl">总题数</div></div>'
          + '<div><div class="num">' + (d.elapsed||0) + 's</div><div class="lbl">耗时</div></div>'
          + '</div>';
    html += '<div style="margin-top:8px;font-size:.75rem;color:#8b949e">开始 ' + d.started_at + ' · 结束 ' + (d.finished_at||'') + '</div>';
    area.innerHTML = html;
  }).catch(() => {});
}

function loadModules() {
  fetch('/api/modules').then(r=>r.json()).then(d => {
    const sel = document.getElementById('moduleSelect');
    sel.innerHTML = '';
    d.modules.forEach(m => {
      const opt = document.createElement('option');
      opt.value = m; opt.textContent = m;
      sel.appendChild(opt);
    });
    document.getElementById('versionInfo').textContent = d.version + ' ' + d.grade + ' · ' + d.modules.length + '个模块可测';
  });
}

function esc(t) {
  return t.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

loadModules();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    print("🤖 英语宝控制台 v3: http://localhost:8866")
    app.run(host="0.0.0.0", port=8866, debug=False, threaded=True)
