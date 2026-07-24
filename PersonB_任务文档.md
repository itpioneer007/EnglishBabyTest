# Person B 任务文档 — 题干审查 + 内容审查

> 你负责：(1) 题干文字 + (2) 内容文字  
> 你的搭档负责：(3) 配图 + (4) 作答  
> 共享代码已经搭好，你的工作文件只有一个。

---

## 一、你要做什么

### (1) 题干文字检查

| 检查项 | 怎么查 |
|:--|:--|
| 有没有错别字 | OCR 提取文字 → 和脚本逐字对比 → 标出差异 |
| 有没有语法错误 | 规则检测 + LLM 辅助判断 |
| 是否完整显示 | 检测文字截断标记（末尾 `...` 等） |

### (2) 内容文字检查 — 四件事

| 子项 | 检查内容 | 方式 |
|:--|:--|:--|
| a. 脚本相符 | 选项文字和公司脚本是否一致 | 字符串相似度对比 |
| b. 显示完整 | 有没有被截断或遮挡 | 末尾半句话检测 |
| c. 知识性错误 | 单词拼写、语法、知识点是否对 | **LLM 分析** |
| d. 逻辑性错误 | 选项间是否矛盾、题目条件是否充分 | **LLM 分析** |

---

## 二、你的文件

```
你只需要关注这一个文件：
  src/reviewer_text.py     ← 你的 TextReviewer 类

可参考的老代码（不用改，但可以抄逻辑）：
  src/question_checker.py
  src/ocr_engine.py
```

**重要**: 
- ❌ 不要碰 `src/reviewer_media.py` 和 `src/inspection_engine.py`（那是搭档的）
- ✅ 你只需要在 `src/reviewer_text.py` 里写代码

---

## 三、怎么用（已经帮你接好了！）

### 你的代码入口

```python
from src.reviewer_text import TextReviewer
from src.reviewer_common import LLMClient, QuestionLoader

# 1. 加载公司给的题目文件
questions = QuestionLoader.load("题目文件.json")  # 支持 .json / .xlsx / .csv

# 2. 连上 LLM（用你的 key）
reviewer = TextReviewer(
    llm=LLMClient(api_key="sk-xxx", model="gpt-4o"),
    script_questions=questions,   # 传进脚本做对比
)

# 3. 逐题审查
for q in questions:
    stem = reviewer.check_stem(q, "screenshots/q01.png")
    content = reviewer.check_content(q, "screenshots/q01.png")

    print(f"Q{q.idx} 题干: {'✅' if stem.passed else '❌'}")
    for d in stem.details:
        print(f"  → {d}")

    print(f"Q{q.idx} 内容: {'✅' if content.passed else '❌'}")
    for d in content.details:
        print(f"  → {d}")
```

### 输出格式（`CheckItem`）

```python
CheckItem(
    name="(1)题干文字",
    passed=True,           # ✅ 或 ❌
    actual_text="听录音选图片",    # OCR 提取到的
    expected_text="听录音选图片",  # 脚本里的
    similarity=1.0,        # 相似度 0-1
    details=[
        "✅ 匹配 (相似度 100%)",
        "✅ 文字显示完整",
    ],
    screenshot="screenshots/q01.png",
)
```

---

## 四、你需要完成的任务清单

### 🔴 必须完成

- [ ] **1. OCR 接上** — 在 `reviewer_text.py` 的 `_extract_text()` 方法里，接你的 OCR 引擎。目前代码预留了 `src/ocr_engine.py` 的调用，换成你的就行。

- [ ] **2. LLM Prompt 调优** — 两个 prompt 函数需要你根据实际效果迭代：
  - `_knowledge_prompt()` — 知识性错误检测
  - `_logic_prompt()` — 逻辑性错误检测
  
  > 现在的 prompt 是通用模板，你拿几道题跑一遍，看 LLM 返回结果够不够用，不行就改。

- [ ] **3. 文字截断检测** — `_is_truncated()` 方法是简单的末尾符号检测，如果公司题目有复杂情况（比如文字被图片挡住），需要你改进。

### 🟡 建议完成

- [ ] **4. 做几个测试用例** — 用 `data/sample_questions.json` 跑一遍，确认流程通顺。

- [ ] **5. 错别字规则库** — 可以加一个常见英语错别字的规则表，让 `_has_garbled_text()` 检测更精准。

---

## 五、你的代码结构（`reviewer_text.py` 内部）

```
TextReviewer 类
│
├── check_stem(q, screenshot, ocr_text)
│   └── 内部调用 _extract_text() + text_similarity() + find_diff_positions()
│
├── check_content(q, screenshot, all_text)
│   └── 内部四个子检查：
│       ├── 文本相似度对比
│       ├── 截断检测 _is_truncated()
│       ├── LLM _knowledge_prompt()  ← 你的核心调优点
│       └── LLM _logic_prompt()      ← 你的核心调优点
│
└── 私有方法（你的专属区域）
    ├── _extract_text()        ← 换你的 OCR
    ├── _extract_all_text()    ← 换你的 OCR
    ├── _has_garbled_text()    ← 乱码检测
    ├── _is_truncated()         ← 截断检测
    ├── _knowledge_prompt()    ← LLM prompt 1
    └── _logic_prompt()        ← LLM prompt 2
```

---

## 六、你需要搭档给你什么

| 你需要 | 状态 |
|:--|:--|
| 公司题目文件 | ⏳ 明天向公司要 |
| LLM API key | ⏳ 你手里有或者找公司要 |
| 题目截图 | ⏳ 搭档会提供 |
| 共享代码 `reviewer_common.py` | ✅ 已写好，不用动 |

---

## 七、协作规则（防止 Git 冲突）

| 你可以改 | 你不能碰 |
|:--|:--|
| `src/reviewer_text.py` | `src/reviewer_media.py` |
| `src/question_checker.py` | `src/inspection_engine.py` |
| `src/ocr_engine.py` | `src/adb_controller.py` |

**共享文件**（`web_server.py`、`index.html`）只在标记区域改：
```html
<!-- ====== Person B 区域 —— 题干 + 内容审查 ====== -->
你的前端代码
<!-- ====== Person B 区域结束 ====== -->
```

---

_有问题直接找搭档沟通，或者一起看 `双人协作分工.md`。_
