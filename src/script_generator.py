"""
src/script_generator.py — 脚本自动生成（无脚本时AI自建答案）
负责人：A 同学

职责：
  当没有汤老师提供的脚本时，从知识库自动生成审查用的"参考答案"。
  
流程：
  知识库 DOCX → 解析词汇表 → 根据题型推断答案 → JSON脚本

调用方：B 的巡检循环（巡检开始时检查脚本是否有 → 无则调用本模块）

输出格式：与 parse_yingyubao_docx 的 YingYuBaoQuestion 兼容
"""

import json
from pathlib import Path
from typing import Optional

class ScriptGenerator:
    """从知识库自动生成审查脚本"""

    def __init__(self, knowledge_docx: str = None):
        self.kb_docx = knowledge_docx

    def generate(self, version: str, unit: int, stage: str) -> list:
        """
        生成一个模块的脚本题目列表

        Args:
            version: 如 "新湘鲁六上"
            unit: 6
            stage: "基础巩固"

        Returns:
            [{"global_idx": 1, "stem": "...", "recording": "...", "answer": "B", "options": [...], "type_2": "听音选择词汇"}, ...]
        """
        # ===== A 在这里实现 =====
        # 思路:
        # 1. 解析知识库DOCX → 获取该unit的词汇+例句+音频文字
        # 2. 听力题：录音文字 = 词汇对应的句子 → 答案 = 该词汇对应的选项
        # 3. 阅读题：从段落提取要点生成题目
        # 4. 选择题格式：A/B/C选项从同unit词汇中随机抽取
        # 5. 返回与 parse_yingyubao_docx 兼容的结构
        return []

    def export_json(self, questions: list, output_path: str):
        """导出为JSON供人工审阅"""
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(questions, f, ensure_ascii=False, indent=2)
        print(f"[ScriptGenerator] 脚本已保存: {output_path}")
