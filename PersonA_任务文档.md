# Person A 任务文档 — 配图审查 + 作答审查

> 你负责：(3) 配图检查 + (4) 作答可行性  
> 搭档负责：(1) 题干文字 + (2) 内容文字  
> 你的工作文件写得最完整，改动量最小。

---

## 一、你要做什么

### (3) 配图检查 — 五件事

| # | 检查内容 | 怎么查 |
|:--|:--|:--|
| a | 图片是否存在 | 截图里有没有配图元素（ImageView 检测） |
| b | 图片是否完整 | 边缘有没有被截断 |
| c | 图片是否与题目匹配 | 图片语义和题干是否相关 → **LLM 直接看图判断** |
| d | 图片是否合理 | 有没有模糊、变形、颜色错误 → **LLM 直接看图判断** |
| e | 听力题特殊处理 | 有没有播放按钮 |

### (4) 作答可行性 — 按题型分别处理

| 题型 | 你要检查什么 | 怎么查 |
|:--|:--|:--|
| 选择题 | 选项能不能点、A/B/C/D 是否清晰可见 | 截图分析 + LLM |
| 填空题 | 输入框是否存在、键盘能否弹出来 | UI dump + LLM |
| 口语题 | 录音按钮是否存在 | UI dump |
| 听力题 | 播放按钮 + 选项是否正常 | UI dump + LLM |
| 判断题 | T/F 是否可点击 | UI dump |
| 排序题 | 可点击/拖拽区域是否存在 | UI dump |

> **有手机时**用 ADB 精确检测 UI 元素，**没手机时**用 LLM 看图判断。两种模式都已写好，切换零成本。

---

## 二、你的文件

```
只有这一个文件你需要改：
  src/reviewer_media.py    ← 你的 MediaReviewer 类

可以参考的老代码：
  src/inspection_engine.py ← 里面有 check_3_image + check_4_answer 的旧实现

可选的依赖（连接手机时需要）：
  src/adb_controller.py
```

**规则**:
- ❌ 不碰 `src/reviewer_text.py` / `src/question_checker.py` / `src/ocr_engine.py`（搭档的）
- ❌ 不碰 `src/reviewer_common.py`（共享层，两个人商量才能改）
- ✅ 只改 `src/reviewer_media.py`

---

## 三、你的代码入口（已经写好）

```python
from src.reviewer_media import MediaReviewer
from src.reviewer_common import LLMClient, QuestionLoader, Question

# 1. 加载公司题目文件
questions = QuestionLoader.load("题目文件.json")

# 2. 接上 LLM
llm = LLMClient(api_key="你的key", model="gpt-4o")
reviewer = MediaReviewer(llm=llm)

# 3. 逐题出报告
for q in questions:
    img = reviewer.check_image(q, f"screenshots/q{q.idx:02d}.png")
    ans = reviewer.check_answer(q, f"screenshots/q{q.idx:02d}.png")

    # 打印结果
    print(f"\n=== Q{q.idx} ===")
    print(f"配图: {'✅' if img.passed else '❌'}")
    for d in img.details:
        print(f"  {d}")
    print(f"作答: {'✅' if ans.passed else '❌'}")
    for d in ans.details:
        print(f"  {d}")
```

---

## 四、你的代码已经有了什么（不需要从头写）

### 已实现的功能 ✅

| 功能 | 方法 | 状态 |
|:--|:--|:--:|
| 图片存在性检测 | `_detect_image_element()` | ✅ 有 ADB 精确检测 + 无 ADB 的 PIL 兜底 |
| 图片截断检测 | `_is_image_truncated()` | ✅ PIL 边缘空白分析 |
| 播放按钮检测 | `_detect_play_button()` | ✅ ADB UI dump |
| LLM 图文匹配 prompt | `_image_match_prompt()` | ✅ 模板已写 |
| LLM 图片逻辑 prompt | `_image_logic_prompt()` | ✅ 模板已写 |
| 选择题 UI 检测 | `_check_choice_question()` | ✅ 统计可点击元素 |
| 填空题 UI 检测 | `_check_fill_question()` | ✅ 检测输入框 |
| 口语题 UI 检测 | `_check_speaking_question()` | ✅ 检测录音按钮 |
| 排序题 UI 检测 | `_check_sort_question()` | ✅ 统计可操作元素 |
| 题型自动识别 | `_guess_type()` | ✅ 从题干文字推断题型 |

---

## 五、你需要完成的任务清单

### 🔴 核心任务 — LLM Prompt 调优

这两个 prompt 是你的核心工作，直接决定审查质量：

- [ ] **调优 `_image_match_prompt()`** — 让 LLM 判断图片和题目是否匹配
  - 现在的 prompt 是通用模板
  - 你应该拿几道**典型的英语题截图**跑一遍
  - 看 LLM 返回的结果够不够精准
  - 比如看看它对"听力选图题"的判断对不对

- [ ] **调优 `_image_logic_prompt()`** — 让 LLM 判断图片有没有逻辑问题
  - 模糊、变形、颜色错乱这些能不能正确识别
  - 需不需要加更多检查点

调试方法：
```python
# 单独测试 prompt 效果
result = reviewer.llm.ask(
    reviewer._image_match_prompt(question),
    image_path="截图文件.png"
)
print(result)  # 看 LLM 怎么回答的，然后改 prompt
```

### 🟡 加分任务

- [ ] **题型识别优化** — `_guess_type()` 目前只是简单关键词匹配。如果你发现公司题目有特殊题型识别不了，在这里加规则。

- [ ] **ADB 模式联调** — 如果你们的电脑连着测试手机，把 `adb_controller` 传进去，UI 检测会更精确。

- [ ] **截图文件名规范** — 和搭档商量好截图的命名规则（建议 `q01.png`, `q02.png`...），统一做法。

---

## 六、你的审查报告输出

每一题的输出格式：

```json
{
  "idx": 1,
  "check_image": {
    "passed": true,
    "details": [
      "✅ 检测到图片元素",
      "✅ 图片显示完整",
      "✅ 图文匹配: 图片内容与听力场景一致",
      "✅ 图片无逻辑问题",
      "✅ 听力题: 播放按钮存在"
    ]
  },
  "check_answer": {
    "passed": true,
    "details": [
      "✅ 选择题: 检测到 3 个可点击选项"
    ]
  }
}
```

---

## 七、你需要搭档给你什么

| 需要 | 谁提供 |
|:--|:--|
| 公司题目文件（含每题答案+配图路径） | 明天向公司要 |
| LLM API key | 公司或你自己的 |
| 题目截图 | 搭档负责生产 |
| 脚本数据（每题的题干+正确答案） | 搭档整理（用于对比） |

---

## 八、你的工作流程（建议）

```
拿到文件 → 接好 LLM → 用 2~3 道题调 prompt
    ↓
prompt 调好了 → 跑全部 40 题 → 出 JSON 报告
    ↓
和搭档的报告合并 → 一份完整的四维审查报告
```

---

_代码已经写好 80%，你的核心工作是调 LLM prompt 让它判断更准。_
