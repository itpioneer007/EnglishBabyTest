# B 同学 — 分工文档 (全自动引擎)

> **把这个文档发给任何AI，AI就知道你负责什么、能改什么、不能碰什么。**

---

## 一、项目概况

**英语宝模块检测智能体** — 自动检查教育APP"英语宝"中每个模块的每道题，9项检查任意一项不通过 = 错题。三人协作，每人独立一个分支。

你需要帮助的是 **B同学**，负责全自动化调度引擎。

---

## 二、B 的职责

| # | 任务 | 说明 |
|---|------|------|
| B1 | **批量任务内核** | 接受清单 [{version, unit, stage}, ...] → 依次调用现有巡检 → 自动完成 |
| B2 | **多模块导航增强** | 不限于听力专项，支持所有模块（巧记单词/知识过关/口语训练等） |
| B3 | **流程完整性** | 验证"下一题"真正跳转了；全答完正常结束；检查目录文字 |
| B4 | **异常恢复** | 广告弹窗自动关 / 加载超时等 / APP崩溃重启 / 失败重试3次→跳过 |
| B5 | **进度追踪** | 实时进度 + 预��剩余时间 + 断点续传 |

---

## 三、你能改的文件

```
✅ src/batch_runner.py         — B1/B5 核心实现
✅ src/progress_tracker.py     — B5 进度持久化
✅ src/recovery_handler.py     — B4 异常恢复
✅ routes/batch_routes.py      — 批量API (start/status/pause/resume/cancel)
✅ web_server.py               — 增强导航逻辑、巡检循环、集成A和C的检查函数
```

---

## 四、你绝对不能碰的文件

```
❌ routes/trace_routes.py     (C 的溯源路由)
❌ routes/export_routes.py    (C 的导出路由)
❌ src/trace_engine.py         (C 的溯源引擎)
❌ src/error_collector.py      (C 的错误收集)
❌ src/report_exporter.py      (C 的报告导出)
❌ src/email_sender.py         (C 的邮件发送)
❌ src/post_error_check.py     (A 的答错检查)
❌ src/report_check.py         (A 的报告检查)
❌ src/script_generator.py     (A 的脚本生成)
✅ src/review_agent.py  — 可以读，调用 _review_one / _review_batch（不要大改）
```

---

## 五、接口约定

### 5.1 你调用的（A 和 C 提供给你的函数）

```python
# 审查核心 — A 的，WEB_SERVER.PY 中已经可用
from src.review_agent import ReviewAgent, ReviewConfig
agent = ReviewAgent(cfg)
r = agent._review_one(script_q, shot_path, ui_texts=ui_texts)

# 答错后检查 — A 的
from src.post_error_check import PostErrorChecker
post = PostErrorChecker()
result = post.check(shot_path, script_q, ui_texts)

# 报告页检查 — A 的  
from src.report_check import ReportChecker
report = ReportChecker()
result = report.check(report_shot, completed_questions, expected_score)

# 脚本自动生成 — A 的
from src.script_generator import ScriptGenerator
gen = ScriptGenerator()
questions = gen.generate(version, unit, stage)

# 错误输出 — C 的（跑完后调用）
from src.error_collector import ErrorCollector
coll = ErrorCollector(output_root)
coll.collect(review_results, version, unit, stage)
```

### 5.2 你的 BatchRunner 的对外接口

```python
class BatchRunner:
    def __init__(self, plan, on_progress=None, on_complete=None):
        """
        plan = {
            "version": "新湘鲁六上",
            "units": [6, 7, 8, 9],
            "stages": ["基础巩固"],
            "docx": "xxx.docx",     # 空 = AI自动生成
            "email_to": ""          # 空 = 不发邮件
        }
        """

    def estimate_time(self) -> str:
        """返回 "约16分钟" """

    def start(self):
        """后台线程启动"""

    def pause(self) / resume(self) / cancel(self):
        """暂停/继续/取消"""
```

### 5.3 批量状态 JSON（你的 API 返回给前端）

```json
{
    "running": true,
    "paused": false,
    "plan": {"version": "新湘鲁六上", "units": [6,7,8,9], "stages": ["基础巩固"]},
    "completed": [{"unit": 6, "stage": "基础巩固", "questions": 14, "passed": 10, "failed": 4}],
    "current": {"unit": 7, "stage": "基础巩固", "question": "Q03"},
    "pending": [{"unit": 7, "stage": "综合进阶"}, ...],
    "failed_modules": [],
    "started_at": "...",
    "eta_remaining": "12分钟"
}
```

---

## 六、巡检循环骨架（你的核心逻辑）

```python
# 在 web_server.py 的 run_listening_inspect 基础上增强：

for module in plan:
    # 1. 导航到模块（通用导航，不只听力专项）
    navigate_to_module(version, unit, stage, module_type)
    
    # 2. 如果有 A 的脚本生成器，先检查脚本是否存在
    if not docx_exists:
        script_qs = generator.generate(version, unit, stage)
    
    # 3. 逐题巡检（现有逻辑 + A 的增强维度）
    for each_question:
        screenshot
        review = agent._review_one(q, shot, ui_texts)  # A 的6维检查
        
        # 4. 选择正确选项（用脚本答案）
        click_correct_option(script_q.answer)
        
        # 5. 如果是模块首题，再测一次答错 → 调用 A 的 post_error_check
        if is_first_question:
            go_back_and_answer_wrong()
            screenshot_wrong_result
            post_check_result = post_error_checker.check(...)
        
        # 6. 下一题，验证真正跳转了
        
    # 7. 答完 → 检查报告页 → A 的 report_check
    navigate_to_report()
    report_result = report_checker.check(report_shot, ...)
    
    # 8. 出错 → C 的 error_collector
    collector.collect(module_results)
```

---

## 七、怎么独立测试

```bash
cd 英语宝模块检测

# 测试批量调度（不连手机，用模拟数据）
python3 -c "
from src.batch_runner import BatchRunner
import sys; sys.path.insert(0, '.')
plan = {'version':'新湘鲁六上','units':[6],'stages':['基础巩固'],'docx':''}
runner = BatchRunner(plan)
print(f'预估: {runner.estimate_time()}')
assert len(runner.pending) == 1
print('✅ batch_runner 队列构建正常')
"
```

手机连上后，可以通过前端 `http://localhost:5000` 点"开始批量检查"测试完整流程。

---

## 八、你的 Git 分支

```bash
git checkout -b feat/auto-engine
```

只改你的文件。web_server.py 是你和另外两人唯一的交叉点——**只在巡检循环、导航部分加代码，不改结构**。
