# 文件名: demo_a_frontend.py
# 运行方式: streamlit run demo_a_frontend.py
# 说明: 独立前端，不依赖主项目的 web_server.py 和 routes

import streamlit as st
import json
from pathlib import Path

# 导入你的核心模块（完全独立，不碰B/C的代码）
from src.post_error_check import PostErrorChecker
from src.report_check import ReportChecker
from src.script_generator import ScriptGenerator

# 页面配置
st.set_page_config(page_title="A同学 - 审查核心演示", layout="wide")
st.title("🧪 A 同学 - 审查核心增强独立演示")
st.caption("不依赖B的巡检循环，独立展示 A1~A4 功能 | 数据均来自本地模拟")

# 侧边栏：展示你的职责范围
with st.sidebar:
    st.header("📋 你的功能清单")
    st.markdown("""
    - ✅ **A1** 答错后检查  
    - ✅ **A2** 音频检查 (集成字段展示)  
    - ✅ **A3** 模块报告检查  
    - ✅ **A4** 脚本自动生成  
    """)
    st.divider()
    st.caption("接口标准: 所有函数返回 CheckResult(passed, score, details)")

# 主界面：四个卡片
col1, col2 = st.columns(2)

# ============ A1 卡片 ============
with col1:
    with st.expander("🔍 A1 - 答错后检查", expanded=True):
        if st.button("🧪 运行 A1 检查", key="a1"):
            with st.spinner("正在分析截图..."):
                try:
                    checker = PostErrorChecker()
                    mock_q = {
                        'stem': 'What is this?',
                        'recording': 'apple',
                        'answer': 'A. Apple',
                        'analysis': '苹果的英文发音'
                    }
                    # 使用项目里自带的测试截图
                    shot = "screenshots/test_question.png"
                    if not Path(shot).exists():
                        st.warning("⚠️ 截图不存在，使用模拟数据演示")
                        result = checker.check("", mock_q, [])
                    else:
                        result = checker.check(shot, mock_q, ['听录音选答案'])
                    
                    # 展示结果
                    col_status, col_score = st.columns(2)
                    col_status.metric("检查结果", "✅ 通过" if result.passed else "❌ 不通过")
                    col_score.metric("置信度得分", f"{result.score:.2f}")
                    st.text_area("详细理由", value="\n".join(result.details) if result.details else "无异常", height=100)
                    if result.error:
                        st.error(f"异常: {result.error}")
                except Exception as e:
                    st.error(f"运行异常: {e}")

# ============ A3 卡片 ============
with col2:
    with st.expander("📊 A3 - 模块报告检查", expanded=True):
        if st.button("🧪 运行 A3 检查", key="a3"):
            with st.spinner("正在校验报告页..."):
                try:
                    checker = ReportChecker()
                    completed = [
                        {'id': 1, 'user_answer': 'A', 'correct_answer': 'A', 'score': 10},
                        {'id': 2, 'user_answer': 'B', 'correct_answer': 'C', 'score': 0},
                    ]
                    result = checker.check("screenshots/report.png", completed, expected_score=50)
                    
                    col_status, col_score = st.columns(2)
                    col_status.metric("检查结果", "✅ 通过" if result.passed else "❌ 不通过")
                    col_score.metric("置信度得分", f"{result.score:.2f}")
                    st.text_area("详细理由", value="\n".join(result.details) if result.details else "无异常", height=100)
                except Exception as e:
                    st.error(f"运行异常: {e}")

# ============ A4 卡片（占两列宽度） ============
st.divider()
with st.container():
    st.subheader("📝 A4 - 脚本自动生成")
    col_ver, col_unit, col_stage = st.columns(3)
    with col_ver:
        version = st.text_input("教材版本", value="新湘鲁六上")
    with col_unit:
        unit = st.number_input("单元", min_value=1, max_value=12, value=6)
    with col_stage:
        stage = st.selectbox("阶段", ["基础巩固", "能力提升", "综合测试"])
    
    if st.button("🚀 执行 A4 生成脚本"):
        with st.spinner("AI正在推演题目..."):
            try:
                generator = ScriptGenerator()
                qs = generator.generate(version, int(unit), stage)
                st.success(f"✅ 成功生成 {len(qs)} 道题目")
                
                # 用漂亮的JSON展示前5题
                show_data = qs[:5] if len(qs) > 5 else qs
                st.json(show_data)
                
                # 展示统计信息
                if qs:
                    sample = qs[0]
                    st.caption(f"数据结构字段: {list(sample.keys())}")
            except Exception as e:
                st.error(f"生成异常: {e}")

# ============ A2 集成字段展示 ============
st.divider()
with st.container():
    st.subheader("🎧 A2 - 音频检查集成展示")
    st.caption("说明：A2集成在 review_agent._review_batch 中，最终产出给B消费的JSON字段如下：")
    
    sample_output = {
        "question_id": 101,
        "ai_audio": True,
        "audio_reason": "播放按钮可点击，进度条从0s变化至3.2s，音频正常加载",
        "ai_post_error": None,
        "ai_report": None
    }
    col1, col2 = st.columns([1, 2])
    with col1:
        st.metric("音频状态", "✅ 可用" if sample_output["ai_audio"] else "❌ 异常")
    with col2:
        st.json(sample_output)
    
    st.info("💡 以上字段会被B的 record_q_result 存储，纳入最终报告。")

# 底部契约说明
st.divider()
st.caption("🔗 所有A1/A3函数严格返回 CheckResult(passed, score, details) 结构，与B的接口100%对齐。")