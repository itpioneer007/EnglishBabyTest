"""
src/smart_parser.py — 自然语言 → 批量任务计划
负责人：B

职责：别人说一句"帮我检测新湘鲁六上U6-U9听力专项"，
      自动解析出 {version, units, stages, module_type}

不限制格式，"u6-u9" / "第六到第九单元" / "6到9单元" 都能识别
"""

import re

# ============================================
# 版本名映射表（口语化 → 系统内部名）
# ============================================
VERSION_ALIAS = {
    "新湘鲁": "新湘鲁",
    "湘鲁": "新湘鲁",
    "新湘少": "新湘鲁",
    "湘少": "新湘少",
    "湘教": "新湘少",
}
GRADE_ALIAS = {
    "六上": "六上", "六年级上册": "六上", "六上": "六上",
    "六下": "六下", "六年级下册": "六下",
    "五上": "五上", "五年级上册": "五上",
    "五下": "五下", "五年级下册": "五下",
}
MODULE_ALIAS = {
    "听力": "听力专项",
    "听力专项": "听力专项",
    "巧记": "巧记单���",
    "巧记单词": "巧记单词",
    "知识": "知识过关",
    "知识过关": "知识过关",
    "口语": "口语训练",
    "口语训练": "口语训练",
}
STAGE_ALIAS = {
    "基础": "基础巩固",
    "基础巩固": "基础巩固",
    "综合": "综合进阶",
    "综合进阶": "综合进阶",
    "难点": "难点突破",
    "难点突破": "难点突破",
}


def parse(text: str, use_llm: bool = True) -> dict:
    """
    输入任意自然语言，解析出批量检测任务计划

    示例输入:
        "帮我检测新湘鲁六上U6-U9的基础巩固听力专项"
        "请检查湘少版五年级上册6到9单元听力"
        "跑一下新湘鲁六上听力专项 基础巩固 U6-9"

    返回:
        {
            "version": "新湘鲁六上",
            "units": [6, 7, 8, 9],
            "stages": ["基础巩固"],
            "module_type": "听力专项",
            "raw_text": "原始输入"
        }
    """
    result = {
        "version": "新湘鲁六上",   # 默认
        "units": [6],
        "stages": ["基础巩固"],
        "module_type": "听力专项",
        "raw_text": text,
    }

    # 第一步: 正则快速匹配
    parsed = _regex_parse(text)
    if parsed:
        result.update(parsed)
        return result

    # 第二步: LLM兜底
    if use_llm:
        try:
            llm_result = _llm_parse(text)
            if llm_result:
                result.update(llm_result)
        except Exception:
            pass

    return result


def _regex_parse(text: str) -> dict | None:
    """正则快速匹配常见格式"""
    result = {}

    # === 版本 ===
    # 新湘鲁六上 / 湘鲁版六年级上册
    ver_map = {
        "新湘鲁六上": "新湘鲁六上", "新湘鲁六下": "新湘鲁六下",
        "新湘鲁五上": "新湘鲁五上", "新湘鲁五下": "新湘鲁五下",
        "新湘少六上": "新湘鲁六上", "新湘少五上": "新湘鲁五上",
        "湘少版五上": "新湘鲁五上", "湘鲁版六上": "新湘鲁六上",
    }
    for alias, real in ver_map.items():
        if alias in text:
            result["version"] = real
            break
    # 模糊：湘鲁 + 六年级 = 新湘鲁六上
    if not result.get("version"):
        if "湘鲁" in text or "湘少" in text:
            grade = None
            for g in ["六年级", "五年级"]:
                if g in text:
                    grade = "六" if "六" in g else "五"
                    break
            term = "下" if "下" in text else "上"
            if grade:
                result["version"] = f"新湘鲁{grade}{term}"

    # === Unit 范围 ===
    # U6-U9 / u6-9 / 6到9 / 第六到第九 / 6~9 / 6至9
    unit_patterns = [
        r"""u(\d+)\s*[-~至到]\s*(?:u)?(\d+)""",
        r"""(\d+)\s*[-~至到]\s*(\d+)\s*单""",
        r"""第[六七八九十\d]+[单]*[元到至]+第?[六七八九十\d]+""",
    ]
    for pat in unit_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            u1 = int(m.group(1))
            u2 = int(m.group(2))
            result["units"] = list(range(u1, u2 + 1))
            break
    # 单个unit: U6
    if not result.get("units"):
        m = re.search(r"""[uU](\d+)""", text)
        if m:
            u = int(m.group(1))
            result["units"] = [u]

    # === 阶段 ===
    for alias, real in STAGE_ALIAS.items():
        if alias in text:
            result["stages"] = [real]
            break

    # === 模块 ===
    for alias, real in MODULE_ALIAS.items():
        if alias in text:
            result["module_type"] = real
            break

    return result if len(result) >= 3 else None


def _llm_parse(text: str) -> dict | None:
    """用LLM兜底解析任意表述"""
    from src.reviewer_common import LLMClient

    client = LLMClient.from_config()
    prompt = f"""你是一个任务解析器。从用户的话里提取英语宝模块检测任务。

用户说: "{text}"

请返回一个JSON对象,只包含以下字段:
- version: 教材版本。可选值: "新湘鲁六上","新湘鲁六下","新湘鲁五上","新湘鲁五下","新湘少五上","新湘少五下"
- units: 要检查的单元号列表,如 [6,7,8,9]。如果只有一个单元写成 [6]
- stages: 阶段列表。可选值: ["基础巩固"],["综合进阶"],["难点突破"]。没说默认["基础巩固"]
- module_type: 模块类型。可选值: "听力专项","巧记单词","知识过关","口语训练"。没说默认"听力专项"

只返回JSON,不要其他内容。
如果无法解析,返回 {{}}"""

    answer = client.ask(prompt)
    answer = answer.strip()
    if answer.startswith("```"):
        answer = answer.split("```")[1]
        if answer.startswith("json"):
            answer = answer[4:]
    try:
        import json
        return json.loads(answer)
    except Exception:
        return None


# ============================================
# 命令行测试
# ============================================
if __name__ == "__main__":
    tests = [
        "帮我检测新湘鲁六年级上册的U6-U9听力专项模块",
        "请检查湘少版五年级上册6到9单元听力",
        "跑一下新湘鲁六上基础巩固 U6-9",
        "检测六上U7-U9综合进阶的知识过关",
        "检查U6听力专项",
    ]
    for t in tests:
        r = parse(t, use_llm=False)
        print(f"输入: {t}")
        print(f"结果: version={r['version']} units={r['units']} stages={r['stages']} module={r['module_type']}")
        print()
