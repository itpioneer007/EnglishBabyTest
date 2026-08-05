# C 同学 — 分工文档 (错误溯源 & 输出交付)

> **把这个文档发给任何AI，AI就知道你负责什么、能改什么、不能碰什么。**

---

## 一、项目概况

**英语宝模块检测智能体** — 自动检查教育APP"英语宝"中每个模块的每道题，9项检查任意一项不通过 = 错题。三人协作，每人独立一个分支。

你需要帮助的是 **C同学**，负责最后一环：错误溯源 + 报告输出 + 分发。

---

## 二、C 的职责

| # | 任务 | 说明 |
|---|------|------|
| C1 | **溯源数据引擎** | 每道错题生成：APP截图+错误维度+原因+修改建议+错误位置坐标 |
| C2 | **截图红框标注** | 用Pillow在出错区域画红框+文字标注 |
| C3 | **错误输出文件夹** | 按版本/Unit/阶段/日期组织目录，含截图+error.json |
| C4 | **HTML报告** | 全貌报告+仅错误报告，可直接发给老师看 |
| C5 | **邮件/通知** | 跑完自动发邮件（附报告+CSV） |

---

## 三、你能改的文件

```
✅ src/trace_engine.py         — C1/C2 溯源数据+截图标注
✅ src/error_collector.py      — C3 错误收集+输出目录
✅ src/report_exporter.py      — C4 HTML/CSV报告
✅ src/email_sender.py         — C5 邮件发送
✅ routes/trace_routes.py      — 溯源API (list/detail/screenshot)
✅ routes/export_routes.py     — 导出API (html/csv/screenshots/email)
```

---

## 四、你绝对不能碰的文件

```
❌ src/review_agent.py         (A 的审查核心)
❌ src/post_error_check.py     (A 的答错检查)
❌ src/report_check.py         (A 的报告检查)
❌ src/script_generator.py     (A 的脚本生成)
❌ src/batch_runner.py         (B 的批量调度)
❌ src/progress_tracker.py     (B 的进度追踪)
❌ src/recovery_handler.py     (B 的异常恢复)
❌ routes/batch_routes.py      (B 的批量API)
❌ web_server.py               (B 的巡检循环→不要碰！)
```

---

## 五、接口约定

### 5.1 你的输入（B 产出 → C 消费）

B 跑完巡检后，审查结果在 `data/inspection_state.json` 中。数据结构：

```json
{
    "questions": {
        "新湘鲁六上-U6-Q03": {
            "qid": "新湘鲁六上-U6-Q03",
            "idx": 3,
            "question_type": "听音选择词汇",
            "screenshot": "q03.png",
            "stem": "英语课上...",
            "recording": "This student is helpful.",
            "script_answer": "B",

            "ai_stem": false,
            "ai_content": false,
            "ai_image": true,
            "ai_answer": true,
            "ai_audio": null,
            "ai_post_error": null,
            "ai_report": null,

            "stem_reason": "[不通过] | ...",
            "content_reason": "...",
            "image_reason": "...",
            "answer_reason": "...",
            "audio_reason": "",
            "post_error_reason": "",
            "report_reason": "",

            "overall_passed": false,
            "overall_score": 0.5
        }
    }
}
```

### 5.2 C1 的 TraceEngine 输出 → C3/C4 消费

```python
class TraceEngine:
    def generate(self, qid: str, question_data: dict) -> dict:
        """
        返回:
        {
            "qid": "新湘鲁六上-U6-Q03",
            "checks": [
                {
                    "dimension": "内容",
                    "passed": false,
                    "reason": "选项B应为careful，实际显示care",
                    "suggestion": "将选项B的care改为careful",
                    "severity": "high",
                    "error_region": {"x": 200, "y": 800, "w": 300, "h": 50}
                }
            ],
            "script_context": {"stem":"...", "recording":"...", "answer":"B", "options":[...]}
        }
        """
```

### 5.3 C3 的输出目录结构

```
{output_root}/新湘鲁六上/U6_基础巩固_20260728/
├── errors/
│   ├── Q03/
│   │   ├── screenshot.png       ← APP原图（从screenshots/复制）
│   │   ├── marked.png           ← 红框标注图
│   │   └── error.json           ← 溯源数据
│   └── Q07/...
├── report_full.html             ← C4 全貌报告
├── report_errors.html           ← C4 仅错误报告
└── summary.csv                  ← 错误汇总表
```

### 5.4 C4 的 ReportExporter 签名

```python
class ReportExporter:
    def export_html_full(self, questions: dict, metadata: dict) -> str:
        """生成全貌HTML报告 → 返回文件路径"""

    def export_csv(self, questions: dict) -> str:
        """生成错误CSV → 返回文件路径"""
```

### 5.5 C5 的 EmailSender 签名

```python
class EmailSender:
    def send_report(self, to_email: str, subject: str,
                    html_body: str = "", attachments: list = None) -> dict:
        """发送报告邮件 → {"success": True/False, "message": "..."}"""
```

---

## 六、怎么独立测试

```bash
cd 英语宝模块检测

# 先准备测试数据：让B跑一遍看看有没有 data/inspection_state.json

# 测试C3错误收集
python3 -c "
from src.error_collector import ErrorCollector
import sys,json; sys.path.insert(0, '.')
state = json.load(open('data/inspection_state.json','r',encoding='utf-8'))
coll = ErrorCollector('outputs/test_reports')
result = coll.collect(state['questions'], '新湘鲁六上', 6, '基础巩固')
print(f'收集完成: {result[\"failed\"]}/{result[\"total\"]}题出错')
print(f'输出目录: {result[\"output_dir\"]}')

# 测试C4 HTML导出
curl -X POST http://localhost:5000/api/export/html
"

# 没有无截图时可以用现有的 screenshots/test_question.png 测试C1
python3 -c "
from src.trace_engine import TraceEngine
t = TraceEngine()
mock = {'qid':'test','ai_stem':False,'stem_reason':'错误原因','overall_passed':False,'overall_score':0.5}
r = t.generate('test-Q01', mock)
print(json.dumps(r, ensure_ascii=False, indent=2))
"
```

---

## 七、你的 Git 分支

```bash
git checkout -b feat/output-trace
```

只改你的文件。你是接收方，不需要主动调用 A 或 B 的函数——你读他们产出的 JSON 文件。
