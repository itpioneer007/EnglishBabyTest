# A 同学 — 分工文档 (审查核心增强)

> **把这个文档发给任何AI，AI就知道你负责什么、能改什么、不能碰什么。**

---

## 一、项目概况

**英语宝模块检测智能体** — 自动检查教育APP"英语宝"中每个模块的每道题，9项检查任意一项不通过 = 错题。三人协作，每人独立一个分支。

你需要帮助的是 **A同学**，负责审查维度的核心增强。

---

## 二、A 的职责

需求文档中你负责的三项 + 脚本自生成：

| # | 任务 | 说明 |
|---|------|------|
| A1 | **(5) 答错后检查** | 每模块首题故意选错 → 截图结果页 → 检查正确答案/知识点/听力文字是否正确 |
| A2 | **(6) 音频检查** | 听力题检测音频可用性（播放按钮可点、有进度变化） |
| A3 | **(8) 模块报告检查** | 全答完后检查完成报告页的得分/知识内容是否正确 |
| A4 | **脚本自动生成** | 无脚本时从知识库提取词汇 → AI推演正确答案 → 输出审查用JSON |

---

## 三、你能改的文件

```
✅ src/post_error_check.py      — A1 实现
✅ src/report_check.py           — A3 实现
✅ src/script_generator.py      — A4 实现
✅ src/review_agent.py           — 扩展 _review_batch 从4维到6维
```

---

## 四、你绝对不能碰的文件

```
❌ routes/          下的任何文件（B 和 C 的路由）
❌ web_server.py    （B 的巡检循环和导航逻辑）
❌ src/batch_runner.py
❌ src/progress_tracker.py
❌ src/recovery_handler.py
❌ src/trace_engine.py
❌ src/error_collector.py
❌ src/report_exporter.py
❌ src/email_sender.py
✅ src/reviewer_common.py  — 可以读，如果需要给公共层加 LLM 工具方法就加（通知 B 和 C）
```

---

## 五、接口约定（你的输出 → B 消费）

你写的函数会被 **B 的巡检循环**调用。你的函数必须返回标准结构：

### 5.1 CheckResult（所有检查的统一返回值）

```python
@dataclass
class CheckResult:
    passed: bool = False    # True=通过, False=不通过
    score: float = 0.0      # 0~1, 默认: 1.0(通过)/0.5(不通过)/1.0(跳过)
    details: list = []      # ["理由", "修改建议", ...]
    error: str = ""         # 异常信息
```

### 5.2 各检查函数的签名

```python
# A1: PostErrorChecker
class PostErrorChecker:
    def check(self, shot_path: str, script_q, ui_texts: list = None) -> CheckResult:
        """检查答错后的结果页截图"""
        pass

# A2: 集成到 review_agent._review_batch, 新增 audio_check 维度
# 数据字段: q.ai_audio (bool/null), q.audio_reason (str)

# A3: ReportChecker
class ReportChecker:
    def check(self, report_shot: str, completed_questions: list,
              expected_score: int = None) -> CheckResult:
        pass

# A4: ScriptGenerator
class ScriptGenerator:
    def generate(self, version: str, unit: int, stage: str) -> list:
        """返回 [{global_idx, stem, recording, answer, options, type_2}, ...]"""
        pass
```

### 5.3 扩展 _review_item 的字段

在 `_review_batch` 中新增的维度，写入 `r.audio_check` / `r.post_error_check` / `r.report_check`。B 的 `record_q_result` 会存这些字段：

```json
{
    "ai_audio": true,           // null=非听力题, true=通过, false=不通过
    "ai_post_error": null,      // null=未触发, true=通过, false=不通过
    "ai_report": null,          // null=非最后一题, true=通过, false=不通过
    "audio_reason": "...",
    "post_error_reason": "...",
    "report_reason": "..."
}
```

---

## 六、怎么独立测试

```bash
cd 英语宝模块检测

# 测试A1答错后检查
python3 -c "
from src.post_error_check import PostErrorChecker
import sys; sys.path.insert(0, '.')
c = PostErrorChecker()
r = c.check('screenshots/test_result.png', mock_question(), ['听录音...'])
print(f'passed={r.passed}, details={r.details}')
"

# 测试A4脚本生成
python3 -c "
from src.script_generator import ScriptGenerator
g = ScriptGenerator()
qs = g.generate('新湘鲁六上', 6, '基础巩固')
print(f'生成{len(qs)}题')
for q in qs[:3]: print(f'  Q{q[\"global_idx\"]}: {q[\"recording\"]} → {q[\"answer\"]}')
"
```

用 `screenshots/test_question.png` 做测试截图（已有一张现成的）。

---

## 七、你的Git分支

```bash
git checkout -b feat/review-core
```

只改你的文件，每天合一次 main。
