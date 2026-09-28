"""
reviewer_common.py — 三人协作共享层 (LLM / 配置 / 公共工具)

职责: 数据模型、LLM 客户端、题目加载器
原则: 两个人都不需要改这个文件（除非要加新数据类型）
"""

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from difflib import SequenceMatcher


# ============================================================
# .env 文件加载（无外部依赖）
# ============================================================

def _load_dotenv(dotenv_path: str = None) -> dict:
    """从 .env 文件加载环境变量到 os.environ，返回加载的键值对"""
    if dotenv_path is None:
        # 从当前文件向上找项目根目录
        dotenv_path = Path(__file__).parent.parent / ".env"
    dotenv_path = Path(dotenv_path)
    if not dotenv_path.exists():
        return {}
    loaded = {}
    with open(dotenv_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                os.environ[key] = value
                loaded[key] = value
    return loaded


# ============================================================
# 数据模型（全项目统一）
# ============================================================

@dataclass
class CheckItem:
    """单项检查结果 — 贯穿四项检查的通用格式"""
    name: str                          # 检查项名称（中文）
    passed: bool = False               # 是否通过
    screenshot: str = ""               # 截图路径
    actual_text: str = ""              # 实际检测到的文字
    expected_text: str = ""            # 脚本中的预期文字
    details: list = field(default_factory=list)  # 详细描述
    error: str = ""                    # 出错信息
    similarity: float = 0.0            # 相似度（0-1）

    def to_dict(self):
        return {
            "name": self.name,
            "passed": self.passed,
            "actual_text": self.actual_text,
            "expected_text": self.expected_text,
            "similarity": round(self.similarity, 3),
            "details": self.details,
            "error": self.error,
            "screenshot": self.screenshot,
        }


@dataclass
class Question:
    """单道题目数据结构"""
    idx: int                           # 题号
    stem: str = ""                     # 题干文字
    content: str = ""                  # 题目内容（选项、说明等）
    correct_answer: str = ""           # 正确答案
    question_type: str = ""            # 题型
    knowledge_points: list = field(default_factory=list)
    image_paths: list = field(default_factory=list)  # 配图路径
    expected_image_desc: str = ""      # 脚本中的配图描述（用于对比实际截图）

    def to_dict(self):
        return {
            "idx": self.idx,
            "stem": self.stem,
            "content": self.content,
            "correct_answer": self.correct_answer,
            "question_type": self.question_type,
            "knowledge_points": self.knowledge_points,
            "image_paths": self.image_paths,
        }


# ============================================================
# 题目文件加载器（支持多种格式）
# ============================================================

class QuestionLoader:
    """加载公司提供的题目文件（JSON / Excel / CSV）"""

    @staticmethod
    def from_json(filepath: str) -> list[Question]:
        """从 JSON 文件加载题目列表"""
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        # 自动识别 JSON 结构：可能是 { "questions": [...] } 或直接是数组
        if isinstance(data, dict):
            raw = data.get("questions", data.get("data", []))
        elif isinstance(data, list):
            raw = data
        else:
            raise ValueError(f"不支持的 JSON 结构: {type(data)}")

        questions = []
        for item in raw:
            q = Question(
                idx=item.get("id", item.get("idx", item.get("question_id", 0))),
                stem=item.get("stem", item.get("stem_text", item.get("question", ""))),
                content=item.get("content", item.get("content_text", "")),
                correct_answer=item.get("answer", item.get("correct_answer", item.get("key", ""))),
                question_type=item.get("type", item.get("question_type", "")),
                knowledge_points=item.get("knowledge_points", item.get("knowledge", [])),
                image_paths=item.get("images", item.get("image_paths", [])),
            )
            questions.append(q)

        return questions

    @staticmethod
    def from_docx(filepath: str) -> list[Question]:
        """从 DOCX 文件加载题目（自动识别表格/段落格式）"""
        from docx import Document
        doc = Document(filepath)

        # 方式1: 尝试表格模式
        questions = QuestionLoader._parse_docx_tables(doc)
        if questions:
            return questions

        # 方式2: 段落模式（Q1: xxx \n A: xxx 格式）
        return QuestionLoader._parse_docx_paragraphs(doc)

    @staticmethod
    def _parse_docx_tables(doc) -> list[Question]:
        """从 DOCX 表格中解析题目"""
        questions = []
        for table in doc.tables:
            headers = [cell.text.strip() for cell in table.rows[0].cells]
            if not any(k in headers for k in ['id','题号','题目','题干','stem','question']):
                continue

            for row in table.rows[1:]:
                cells = [cell.text.strip() for cell in row.cells]
                if len(cells) < 2 or not cells[0]:
                    continue
                data = dict(zip(headers, cells))
                q = QuestionLoader._map_docx_row(data)
                if q:
                    questions.append(q)
        return questions

    @staticmethod
    def _parse_docx_paragraphs(doc) -> list[Question]:
        """从 DOCX 段落中解析题目（Q1/Q01/1. 格式）"""
        import re as regex
        questions = []
        current = None
        buf = []

        for para in doc.paragraphs:
            text = para.text.strip()
            if not text:
                continue

            # 检测新题目开始: Q1 / 1. / 第1题 等
            m = regex.match(r'^(?:Q|q)?\s*(\d+)[\.\、\s]|^第\s*(\d+)\s*题', text)
            if m:
                if current:
                    current.stem = '\n'.join(buf[:1]) if buf else ''
                    current.content = '\n'.join(buf[1:]) if len(buf) > 1 else ''
                    questions.append(current)
                qid = int(m.group(1) or m.group(2))
                current = Question(idx=qid)
                buf = [text]
            elif current is not None:
                # 检测答案行
                if regex.match(r'^(答案|Answer|Key)[:：]', text):
                    current.correct_answer = text.split('：')[-1].split(':')[-1].strip()
                elif regex.match(r'^(题型|类型|Type)[:：]', text):
                    current.question_type = text.split('：')[-1].split(':')[-1].strip()
                else:
                    buf.append(text)

        if current:
            current.stem = '\n'.join(buf[:1]) if buf else ''
            current.content = '\n'.join(buf[1:]) if len(buf) > 1 else ''
            questions.append(current)

        return questions

    @staticmethod
    def _map_docx_row(data: dict) -> Question:
        """将 DOCX 表格行映射为 Question（支持中英文列名）"""
        def get(*keys):
            for k in keys:
                if k in data:
                    return data[k]
            return ""
        return Question(
            idx=int(get('id', 'idx', '题号', '序号', 'question_id', '0') or 0),
            stem=get('stem', '题干', '题目', 'question', 'stem_text', '内容'),
            content=get('content', '选项', '内容', 'options', 'content_text'),
            correct_answer=get('answer', '答案', 'key', 'correct_answer', '正确答案'),
            question_type=get('type', '题型', 'question_type', '类型'),
            expected_image_desc=get('image_desc', '配图描述', '图片描述', '配图', 'image', '图片'),
            knowledge_points=get('knowledge', '知识点', 'knowledge_points').split(';') if get('knowledge', '知识点', 'knowledge_points') else [],
        )
        """从 CSV 文件加载"""
        import csv
        questions = []
        with open(filepath, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                q = Question(
                    idx=int(row.get("id", row.get("idx", 0))),
                    stem=row.get("stem", row.get("question", "")),
                    content=row.get("content", row.get("options", "")),
                    correct_answer=row.get("answer", row.get("key", "")),
                    question_type=row.get("type", ""),
                )
                questions.append(q)
        return questions

    @staticmethod
    def from_excel(filepath: str) -> list[Question]:
        """从 Excel 文件加载"""
        try:
            import openpyxl
            wb = openpyxl.load_workbook(filepath)
            ws = wb.active
            headers = [cell.value for cell in ws[1]]
            questions = []
            for row in ws.iter_rows(min_row=2, values_only=True):
                data = dict(zip(headers, row))
                q = Question(
                    idx=int(data.get("id", data.get("idx", 0))),
                    stem=data.get("stem", data.get("question", "")),
                    content=data.get("content", data.get("options", "")),
                    correct_answer=data.get("answer", data.get("key", "")),
                    question_type=data.get("type", ""),
                )
                questions.append(q)
            return questions
        except ImportError:
            raise ImportError("读取 Excel 需要安装 openpyxl: pip install openpyxl")

    @staticmethod
    def describe(filepath: str) -> str:
        """预览文件内容，帮助确认解析是否正确"""
        questions = QuestionLoader.load(filepath)
        lines = [f"文件: {filepath}", f"题目数: {len(questions)}", ""]
        for q in questions:
            lines.append(f"Q{q.idx:02d} | {q.question_type or '?'} | {q.stem[:40]}")
            if q.correct_answer:
                lines.append(f"     答案: {q.correct_answer}")
            if q.expected_image_desc:
                lines.append(f"     配图: {q.expected_image_desc}")
        return "\n".join(lines)

    @staticmethod
    def load(filepath: str) -> list[Question]:
        """自动识别文件格式并加载"""
        ext = Path(filepath).suffix.lower()
        if ext == ".json":
            return QuestionLoader.from_json(filepath)
        elif ext == ".csv":
            return QuestionLoader.from_csv(filepath)
        elif ext in (".xlsx", ".xls"):
            return QuestionLoader.from_excel(filepath)
        elif ext in (".docx", ".doc"):
            return QuestionLoader.from_docx(filepath)
        else:
            raise ValueError(f"不支持的文件格式: {ext}")


# ============================================================
# LLM 客户端（统一接口 — 你配置你的 LLM）
# ============================================================

# ★ 2026-09-10 不可重试的 LLM 错误（额度耗尽 / 密钥无效）：
#   这类错误重试与退避毫无意义，必须快速失败并在上层熔断，
#   否则整个审查/脚本生成流程会以 ~10.8s/题的速度空转（用户会以为"卡死"）。
FATAL_LLM_MARKERS = (
    "402", "payment required", "insufficient balance", "no balance",
    "余额", "欠费", "额度", "配额", "超出",
    "401", "unauthorized", "invalid api key", "authentication",
    # ★ 2026-09-21 补充：百炼免费额度耗尽返回 403（不是 402），
    #   报文体是 AllocationQuota.FreeTierOnly / "Free quota exhausted"。
    #   此前 403 不在名单里 → 被判"可重试" → 白等 1.5+3+4.5s 退避 ×3 次，
    #   整轮 AI 核查以 ~10s/题 的速度空转后静默降级（用户看到的只是"AI 不可用"）。
    "403", "forbidden", "quota", "free tier", "freetieronly", "exhausted",
)


def is_fatal_llm_error(err) -> bool:
    """判断 LLM 错误是否属于"不可重试"（额度/密钥），供快速失败与熔断使用。"""
    s = str(err or "").lower()
    return any(k in s for k in FATAL_LLM_MARKERS)


# ★ 2026-09-10 推理型模型的"思维链吃光输出"问题：
#   百炼的 deepseek-v4-pro-0813 属重度推理模型（实测思考 4000 token 仍未出正文，
#   单次耗时 70.8s、content 为空）。DashScope 支持请求体加 `enable_thinking: false` 关闭，
#   实测同一问题 70.8s → 1.4s 且正文正常。
#   ⚠ 不能全局无脑加：`enable_thinking` 不是所有模型都认。故用白名单限定作用范围。
# ★ 2026-09-23：主模型换成 deepseek-v4.1-flash（V4.1 系列同属推理模型）。
#   实测不关思维链时 200 token 全被 reasoning_content 吃光
#   （usage: text_tokens=0 / finish_reason=length / content 为空），
#   加 enable_thinking:false 后 1.43s 正常出文 → 必须列入本白名单。
#   这里是代码侧兜底：.env 的 LLM_NO_THINK_MODELS 一旦缺失/写错，仍能生效。
# ★ 2026-09-23：`qwen3.7-flash`（视觉备用1）也是重度推理模型。
#   它不关思维链时**不会**返回空串（这点和 deepseek-v4-pro-0813 不同），
#   但单张截图 reasoning_tokens 高达 2200~4600、耗时 18~37s/图（qwen3.8-max 更到 105s）。
#   关掉后实测 3 张真实截图：1.1s 出结果，且**喇叭图标判定（有/无/无）与关前完全一致**
#   —— 该模型的任务是"读屏文字 + 看图标"这类感知题，不需要思维链。
#   ⚠ 该白名单对**视觉调用同样生效**（`_call_api` 按模型名判定，不分文本/视觉）。
_NO_THINK_FALLBACK = ("deepseek-v4.1-flash", "deepseek-v4-pro-0813", "deepseek-v4-pro",
                      "qwen3.7-flash")


def no_think_models() -> tuple:
    """需要显式关闭思维链的模型白名单（env LLM_NO_THINK_MODELS 逗号分隔可覆盖）。"""
    raw = os.environ.get("LLM_NO_THINK_MODELS", "").strip()
    if not raw:
        return _NO_THINK_FALLBACK
    return tuple(x.strip() for x in raw.split(",") if x.strip())


def is_ocr_vision_model(name: str) -> bool:
    """判断视觉模型是否是"纯 OCR 型"（如 qwen3.5-ocr）。

    这类模型读屏极准但**不服从指令**（要 JSON 会返回 {}），
    因此不能直接拿它做六维判断，必须走「OCR 读屏 → 文本模型判断」两段式。
    """
    return bool(name) and "ocr" in str(name).lower()


class LLMClient:
    """
    LLM 统一调用接口

    使用方法（三种，任选一种）：
        # 方式1: 自动从 llm_config.json 读取（推荐）
        client = LLMClient.from_config()

        # 方式2: 直接传参数
        client = LLMClient(api_key="sk-xxx", model="deepseek-chat",
                           base_url="https://api.deepseek.com/v1")

        # 方式3: 从环境变量读取
        export OPENAI_API_KEY="sk-xxx"
        client = LLMClient(model="deepseek-chat")

    调用：
        result = client.ask("请检查这段文字是否有错别字")
        result = client.ask("请分析这张图片", image_path="q01.png")
    """

    # 配置文件路径（相对于项目根目录）
    CONFIG_PATH = "llm_config.json"

    def __init__(self, api_key: str = None, model: str = "deepseek-chat",
                 base_url: str = "https://api.deepseek.com/v1",
                 vision_api_key: str = "", vision_model: str = "",
                 vision_base_url: str = "",
                 vision_model_fallback: str = "",
                 vision_model_fallback2: str = "",
                 vision_model_fallback3: str = "",
                 model_fallback: str = ""):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.model = model
        self.base_url = base_url.rstrip("/")
        # ★ 2026-09-21：文本模型备用（逗号分隔，依次尝试）。
        #   主模型额度耗尽时（百炼 403 AllocationQuota.FreeTierOnly）自动切。
        self.model_fallback = model_fallback
        # 视觉模型（处理图片输入）
        self.vision_api_key = vision_api_key or self.api_key
        self.vision_model = vision_model
        self.vision_base_url = vision_base_url.rstrip("/") if vision_base_url else ""
        # ★ 2026-08-25：视觉模型额度用尽时的备选模型（如 qwen3.7-max-2026-06-08）
        #   调用失败（额度/欠费/429）→ 自动用 fallback 重试，不中断审查
        # ★ 2026-08-30：两级备用 fallback1 → fallback2（如 qwen3.7-plus-2026-05-26 → qwen3.7-max-2026-06-08）
        # ★ 2026-09-23：扩到三级。fallback1 改为 qwen3.7-flash（用户指定）——
        #   它与主视觉 qwen3.8-27b **不同系列**，百炼免费额度按模型独立计，
        #   所以"主模型额度耗尽"这个最典型场景它仍然可用（同系列的 qwen3.8-max/flash 会一起失效）。
        #   实测该模型带 enable_thinking:false 后 1.1s/图，不关则 18~37s（见 no_think_models）。
        self.vision_model_fallback = vision_model_fallback
        self.vision_model_fallback2 = vision_model_fallback2
        self.vision_model_fallback3 = vision_model_fallback3

    @classmethod
    def from_config(cls, config_path: str = None) -> "LLMClient":
        """
        从 llm_config.json + .env 自动读取配置

        优先级：环境变量 > .env 文件 > llm_config.json > 默认值
        """
        path = config_path or cls.CONFIG_PATH
        config = {}

        # 1. 加载 .env 到 os.environ（如果尚未加载）
        _load_dotenv()

        # 2. 加载 llm_config.json（不含密钥）
        if Path(path).exists():
            with open(path, "r", encoding="utf-8") as f:
                config = json.load(f)

        # 3. 按优先级合并：环境变量 > .env > config.json
        api_key = (os.environ.get("LLM_API_KEY")
                   or os.environ.get("OPENAI_API_KEY")
                   or config.get("api_key", ""))
        model = (os.environ.get("LLM_MODEL")
                 or config.get("model", "deepseek-chat"))
        base_url = (os.environ.get("LLM_BASE_URL")
                    or config.get("base_url", "https://api.deepseek.com/v1"))
        vision_api_key = (os.environ.get("VISION_API_KEY")
                          or os.environ.get("LLM_API_KEY")
                          or config.get("vision_api_key", ""))
        vision_model = (os.environ.get("VISION_MODEL")
                        or config.get("vision_model", ""))
        vision_base_url = (os.environ.get("VISION_BASE_URL")
                           or config.get("vision_base_url", ""))
        # ★ 2026-08-25：视觉模型额度用尽备选（VISION_MODEL_FALLBACK / vision_model_fallback）
        vision_model_fallback = (os.environ.get("VISION_MODEL_FALLBACK")
                                 or config.get("vision_model_fallback", ""))
        # ★ 2026-08-30：第二备用（VISION_MODEL_FALLBACK2 / vision_model_fallback2）
        vision_model_fallback2 = (os.environ.get("VISION_MODEL_FALLBACK2")
                                  or config.get("vision_model_fallback2", ""))
        # ★ 2026-09-23：第三备用（VISION_MODEL_FALLBACK3 / vision_model_fallback3）
        vision_model_fallback3 = (os.environ.get("VISION_MODEL_FALLBACK3")
                                  or config.get("vision_model_fallback3", ""))
        # ★ 2026-09-21：文本模型备用链（LLM_MODEL_FALLBACK / model_fallback）
        model_fallback = (os.environ.get("LLM_MODEL_FALLBACK")
                          or config.get("model_fallback", ""))

        return cls(
            api_key=api_key,
            model=model,
            base_url=base_url,
            vision_api_key=vision_api_key,
            vision_model=vision_model,
            vision_base_url=vision_base_url,
            vision_model_fallback=vision_model_fallback,
            vision_model_fallback2=vision_model_fallback2,
            vision_model_fallback3=vision_model_fallback3,
            model_fallback=model_fallback,
        )

    def ask(self, prompt: str, image_path: str = None, image_paths: list = None,
            temperature: float = None) -> str:
        """
        智能路由：
          - 无图片 → 主模型 (DeepSeek)
          - 有图片 + 有视觉模型 → 视觉模型 (qwen3.7-plus)
          - 有图片 + 无视觉模型 → 主模型 (OCR 降级)
          
        参数:
          prompt: 提示词
          image_path: 单张图片路径 (兼容)
          image_paths: 多张图片路径列表 (优先于 image_path)
          temperature: 可选温度；None=用供应商默认。需确定性输出（同图同答）时传 0
        """
        paths = image_paths if image_paths else ([image_path] if image_path else None)

        # ★ 2026-09-10（用户指定 qwen3.5-ocr 做视觉）：纯 OCR 模型 → 两段式
        #   实测 qwen3.5-ocr 读屏极准（逐字 + 坐标），但**不服从指令**：
        #   让它按 JSON 输出六维判断，它会返回 {"stem": {}} 这类空壳；
        #   而同一张图给它 "OCR"，它把屏幕文字一字不差全读出来。
        #   → 因此不能直接拿它当"判断模型"，改为：
        #      第一段 qwen3.5-ocr 读屏取文字  →  第二段 文本模型(deepseek-v4-pro-0813) 做判断
        #   OCR 失败/读不到字时回落到下面的常规视觉路径（qwen3.8 备用视觉推理）。
        if paths and is_ocr_vision_model(self.vision_model):
            _ocr_txt = self._vision_ocr_text(paths)
            if _ocr_txt:
                _enh = (f"{prompt}\n\n[截图 OCR 原文]\n{_ocr_txt[:3000]}\n\n"
                        "以上是该题截图的全部屏幕文字（由 OCR 模型逐字提取）。"
                        "请结合它完成核查。若某项判断依赖图标等 OCR 文字未覆盖的视觉信息，"
                        "请依据文字线索谨慎推断；确实无法确定时标注为[未检]，不要猜测。")
                try:
                    return self._call_api(_enh, image_paths=None, temperature=temperature)
                except Exception as _e_ocr_txt:
                    return self.all_failed_message("OCR 读屏后文本判断失败", _e_ocr_txt)

        if paths and self.vision_model:
            # 有视觉模型：直接发图
            # ★ 2026-08-25：额度用尽自动切换 fallback 模型（qwen3.7-plus → qwen3.7-max-2026-06-08）
            #   识别额度相关错误（insufficient/额度/quota/欠费/429/403），才走 fallback；
            #   其他错误（网络/超时/格式）不切换（可能是临时故障，走纯文本降级）
            # ★ 2026-08-30：两级备用 fallback1 → fallback2，全部失败才降纯文本
            _vision_err = ""
            try:
                return self._call_api(prompt, paths,
                    model=self.vision_model,
                    base_url=self.vision_base_url or self.base_url,
                    api_key=self.vision_api_key,
                    temperature=temperature)
            except Exception as e:
                _vision_err = str(e)
                _e_low = _vision_err.lower()
                _quota_hit = any(k in _e_low for k in
                                 ("insufficient", "quota", "额度", "欠费", "余额",
                                  "429", "403", "free", "耗尽", "用完", "no balance"))
                for _fb_name, _fb in (("fallback", self.vision_model_fallback),
                                      ("fallback2", self.vision_model_fallback2),
                                      ("fallback3", self.vision_model_fallback3)):
                    if not _quota_hit:
                        break
                    if _fb:
                        print(f"⚠ 视觉模型 {self.vision_model} 额度问题({_vision_err[:80]})"
                              f" → 自动切换 {_fb_name}: {_fb}")
                        try:
                            return self._call_api(prompt, paths,
                                model=_fb,
                                base_url=self.vision_base_url or self.base_url,
                                api_key=self.vision_api_key,
                                temperature=temperature)
                        except Exception as e2:
                            _vision_err = str(e2)
                            _e_low = _vision_err.lower()
                            _quota_hit = any(k in _e_low for k in
                                             ("insufficient", "quota", "额度", "欠费", "余额",
                                              "429", "403", "free", "耗尽", "用完", "no balance"))
                # ★ 2026-09-10：末次"降级为纯文本"也必须兜底。
                #   两个供应商同时不可用（实测：DeepSeek 402 余额耗尽 + 通义千问 403 免费额度用尽）
                #   时，原来的裸调用会让 ask() **直接抛 HTTPError**，
                #   调用方若没包 try/except 就会整段崩掉（AI 核查静默失败）。
                try:
                    _txt = self._call_api(prompt, image_paths=None, temperature=temperature)
                    return f"[视觉模型失败: {_vision_err}] → 降级为纯文本分析\n{_txt}"
                except Exception as _e3:
                    return self.all_failed_message(_vision_err, _e3)

        if paths:
            # 无视觉模型：OCR 降级
            return self._ask_with_ocr(prompt, paths[0], temperature=temperature)

        # 纯文本（★ 带重试：网络波动/API限流会偶发空响应或异常，重试 2 次）
        # ★ 2026-09-10：额度/密钥类错误（402 Payment Required / 401）**不可重试** → 立即返回。
        #   否则每次调用白等 1.5+3+4.5s 退避（实测 ~10.8s/次）；整单元 101 题 × 每题尝试 2 次
        #   ≈ 半小时纯空转，用户会以为"卡住/没有结果"。
        _last_err = ""
        _tried_fb = set()
        for _attempt in range(3):
            try:
                _r = self._call_api(prompt, image_paths=None, temperature=temperature)
                if _r and _r.strip():
                    return _r
                _last_err = f"LLM 返回空内容（第{_attempt+1}次尝试）"
            except Exception as e:
                _last_err = f"[LLM 调用失败] {e}（第{_attempt+1}次尝试）"
                if is_fatal_llm_error(e):
                    # ★ 2026-09-21：主文本模型额度/密钥不可用 → 依次切备用模型。
                    #   实测：百炼 deepseek-v4-pro-0813 免费额度耗尽 → 403
                    #   AllocationQuota.FreeTierOnly，而同一 key 下 deepseek-v4-flash /
                    #   deepseek-v3.2 / qwen3.8-* 全部可用。此前没有文本备用，
                    #   一次 403 就让**整轮 AI 核查静默降级**（只做界面级检查），
                    #   用户的"错误原因/修改建议"全部拿不到 —— 静默降级比报错更糟。
                    for _fb in self.fallback_models():
                        if not _fb or _fb == self.model or _fb in _tried_fb:
                            continue
                        _tried_fb.add(_fb)
                        print(f"⚠ 文本模型 {self.model} 不可用（{str(e)[:70]}）"
                              f" → 自动切换备用模型 {_fb}")
                        try:
                            _r = self._call_api(prompt, image_paths=None,
                                                temperature=temperature, model=_fb)
                            if _r and _r.strip():
                                return _r
                        except Exception as e2:
                            _last_err = f"[LLM 调用失败（备用 {_fb}）] {e2}"
                    return _last_err          # 主+备用全不可用 → 快速失败
            import time as _t
            _t.sleep(1.5 * (_attempt + 1))   # 递增退避：1.5s / 3s / 4.5s
        return _last_err

    def fallback_models(self) -> list:
        """文本模型的备用模型列表（主模型额度耗尽/被停用时依次尝试）。"""
        return [m.strip() for m in (self.model_fallback or "").split(",") if m.strip()]

    def _vision_ocr_text(self, paths: list) -> str:
        """用纯 OCR 视觉模型读出截图中的全部屏幕文字（失败/无字返回空串）。

        只用固定提示词 "OCR"：qwen3.5-ocr 对该指令响应最好，
        换成详细指令反而会退化（它把指令也当成待读文字或直接不回）。
        """
        try:
            raw = self._call_api("OCR", paths,
                                 model=self.vision_model,
                                 base_url=self.vision_base_url or self.base_url,
                                 api_key=self.vision_api_key or self.api_key)
        except Exception as e:
            print(f"⚠ OCR 模型 {self.vision_model} 调用失败({str(e)[:90]}) → 回落常规视觉路径")
            return ""
        return self._clean_ocr_text(raw or "")

    @staticmethod
    def _clean_ocr_text(raw: str) -> str:
        """把 OCR 模型的多种返回形态归一为纯文字。

        实测 qwen3.5-ocr 会返回三种形态，必须都兼容：
          1. 纯文本；
          2. JSON 数组 [{"rotate_rect":[...], "text":"..."}, ...]（带坐标，去掉坐标只留文字）；
          3. ```html/<p>…</p>``` 片段（去标签）。
        """
        t = (raw or "").strip()
        if not t:
            return ""
        t = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", t).strip()
        if t[:1] in ("[", "{"):
            try:
                data = json.loads(t)
                items = data if isinstance(data, list) else [data]
                parts = [str(it.get("text", "")).strip()
                         for it in items
                         if isinstance(it, dict) and str(it.get("text", "")).strip()]
                if parts:
                    return "\n".join(parts)
            except Exception:
                pass
        t = re.sub(r"<[^>]+>", " ", t)
        t = re.sub(r"[ \t\u3000]+", " ", t)
        t = re.sub(r"\n\s*\n+", "\n", t)
        return t.strip()

    def _ask_with_ocr(self, prompt: str, image_path: str, temperature: float = None) -> str:
        """
        两步走：本地 OCR 提取截图文字 → 主模型分析
        """
        ocr_text = ""
        try:
            # 优先用项目自带的 OCR 引擎
            from src.ocr_engine import OCREngine
            engine = OCREngine()
            result = engine.extract(image_path)
            texts = [b.text for b in result if hasattr(b, 'text') and b.text]
            ocr_text = " ".join(texts)
        except Exception:
            pass

        if not ocr_text:
            try:
                import subprocess
                # 兜底：Windows 上的 tesseract
                subprocess.run(["tesseract", image_path, "stdout"],
                             capture_output=True, timeout=10)
            except Exception:
                pass

        enhanced_prompt = prompt
        if ocr_text and len(ocr_text) > 5:
            enhanced_prompt += (
                f"\n\n[截图 OCR 文字]\n{ocr_text[:3000]}"
                f"\n\n请结合以上从截图中提取的文字进行分析。"
            )
        else:
            enhanced_prompt += (
                "\n\n(截图中的文字无法自动提取，请仅基于题目信息分析。"
                "如果题目是配图类题目，标注为[无法判断图文匹配--缺少视觉模型]。)"
            )

        # ★ 2026-09-10：同样兜底（见上，两供应商同时不可用时不得抛异常）
        try:
            return self._call_api(enhanced_prompt, image_paths=None, temperature=temperature)
        except Exception as _eo:
            return self.all_failed_message("OCR 降级后调用失败", _eo)

    @staticmethod
    def all_failed_message(err_vision, err_text) -> str:
        """视觉与文本模型全部不可用时返回的结构化提示（不抛异常）。

        ★ 关键：`[LLM 不可用]` 前缀让上层能识别"这不是核查结论，而是模型故障"，
          避免把故障当成"AI 判定通过/不通过"污染审查结果。
        """
        return (f"[LLM 不可用] 视觉模型与文本模型均调用失败，本次未产生真实核查结论。"
                f"视觉模型: {str(err_vision)[:90]}；文本模型: {str(err_text)[:90]}。"
                f"请检查各供应商额度/密钥后重试。")

    def _call_api(self, prompt: str, image_paths: list = None,
                  model: str = None, base_url: str = None,
                  api_key: str = None, temperature: float = None) -> str:
        """底层 API 调用 (支持多图)"""
        import base64
        from urllib.request import Request, urlopen

        use_model = model or self.model
        use_url = (base_url or self.base_url).rstrip("/")
        use_key = api_key or self.api_key

        messages = [{"role": "user", "content": []}]
        messages[0]["content"].append({"type": "text", "text": prompt})

        _img_ok = 0
        _img_missing = []
        if image_paths:
            for img_path in image_paths:
                if img_path and Path(img_path).exists():
                    with open(img_path, "rb") as f:
                        img_b64 = base64.b64encode(f.read()).decode("utf-8")
                    messages[0]["content"].append({
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{img_b64}"}
                    })
                    _img_ok += 1
                elif img_path:
                    _img_missing.append(str(img_path))
            # ★ 2026-09-10：截图缺失时**必须显式告警**。
            #   原逻辑静默跳过 → 模型收到的是纯文本 prompt，只能凭题干"编"结论
            #   （实测：传一个不存在的路径，模型回 "未提供可见截图画面" 却照样输出图标判定）。
            #   这类静默降级会让"AI 瞎判"看起来像正常结论，故补日志。
            if _img_missing:
                print(f"⚠ 截图读取失败/不存在，已跳过 {len(_img_missing)} 张: "
                      f"{_img_missing[:3]}")
            if not _img_ok:
                print("⚠ 本次调用没有任何图片成功加载 → 该结论是纯文本推断，"
                      "不含视觉证据，请勿当作视觉核查结果")

        # ★ Anthropic (Claude) 原生 API 分支
        if "anthropic" in use_url.lower():
            anth_content = []
            if image_paths:
                for img_path in image_paths:
                    if img_path and Path(img_path).exists():
                        with open(img_path, "rb") as f:
                            img_b64 = base64.b64encode(f.read()).decode("utf-8")
                        anth_content.append({
                            "type": "image",
                            "source": {"type": "base64", "media_type": "image/png", "data": img_b64},
                        })
            anth_content.append({"type": "text", "text": prompt})
            body = json.dumps({
                "model": use_model,
                "max_tokens": 2000,
                "messages": [{"role": "user", "content": anth_content}],
            }).encode("utf-8")
            req = Request(
                f"{use_url}/messages",
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": use_key,
                    "anthropic-version": "2023-06-01",
                },
            )
            resp = urlopen(req, timeout=120)
            result = json.loads(resp.read())
            texts = [b.get("text", "") for b in result.get("content", []) if b.get("type") == "text"]
            return "".join(texts)

        # OpenAI 兼容格式
        # ★ 批量审查(33题等大prompt) JSON 输出可能超 1000 token 被截断 → 残缺JSON解析失败
        #   提升到 4000 + 超时 120s
        _payload = {
            "model": use_model,
            "messages": messages,
            "max_tokens": 4000,
        }
        # ★ 2026-09-10：推理型模型必须显式关思维链，否则 4000 token 被思考吃光、正文为空
        #   （见 no_think_models 注释；仅白名单内的模型加此参数，避免影响不认该参数的模型）
        if use_model in no_think_models():
            _payload["enable_thinking"] = False
        # ★ 2026-09-14：可选温度。默认不传（沿用供应商默认，行为与改动前完全一致）；
        #   需要"同一输入必得同一输出"的场景（如口语训练看图补全句子）显式传 0
        if temperature is not None:
            _payload["temperature"] = temperature
        body = json.dumps(_payload).encode("utf-8")

        req = Request(
            f"{use_url}/chat/completions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {use_key}",
            },
        )
        resp = urlopen(req, timeout=120)
        result = json.loads(resp.read())
        return result["choices"][0]["message"]["content"]


# ============================================================
# 文本相似度工具
# ============================================================

def text_similarity(a: str, b: str) -> float:
    """计算两个字符串的相似度（0-1）"""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def find_diff_positions(expected: str, actual: str) -> list[str]:
    """找出两个字符串之间的差异位置"""
    diffs = []
    matcher = SequenceMatcher(None, expected, actual)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "equal":
            diffs.append(f"[{tag}] 预期'{expected[i1:i2]}' vs 实际'{actual[j1:j2]}'")
    return diffs
