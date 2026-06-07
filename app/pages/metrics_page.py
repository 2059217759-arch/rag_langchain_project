import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st

from core.metrics import get_metrics_summary, get_recent_metrics

st.set_page_config(page_title="性能监控", page_icon="📊", layout="wide")

_CSS = """
<style>
.main .block-container { padding-top: 1.5rem; }
section[data-testid="stSidebar"] .stButton > button { width: 100%; }
.metric-card {
    background: #F8FAFC;
    border: 1px solid #E2E8F0;
    border-radius: 0.5rem;
    padding: 1rem;
}
</style>
"""
st.markdown(_CSS, unsafe_allow_html=True)

if "access_token" not in st.session_state or not st.session_state["access_token"]:
    st.warning("请先登录")
    st.switch_page("login_page.py")
    st.stop()

# ── Sidebar ──
with st.sidebar:
    st.markdown("### 📊 性能监控")
    st.caption("RAG 系统运行指标")

    st.divider()

    days = st.selectbox("时间范围", [1, 7, 14, 30], index=1, format_func=lambda d: f"最近 {d} 天")

    user_filter = st.radio("用户范围", ["所有用户", "当前用户"], horizontal=True)
    session = st.session_state["username"] if user_filter == "当前用户" else None

    st.divider()

    if st.button("🔄 刷新数据", use_container_width=True):
        st.rerun()

    st.divider()

    if st.button("💬 返回对话", use_container_width=True):
        st.switch_page("pages/chat_page.py")

    st.divider()
    st.caption(f"👤 {st.session_state['username']}")

# ── Main ──
st.markdown("## 📊 性能监控")

summary = get_metrics_summary(session_id=session, days=days)

if summary.get("total_queries", 0) == 0:
    st.info("暂无数据，进行几次对话后将自动显示指标。")
    st.stop()

# KPI 卡片
col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("总查询数", f"{summary['total_queries']:,}")
with col2:
    st.metric("平均延迟", f"{summary['avg_latency_ms'] / 1000:.1f}s")
with col3:
    st.metric("P95 延迟", f"{summary['p95_latency_ms'] / 1000:.1f}s")
with col4:
    total_tokens = summary["total_input_tokens"] + summary["total_output_tokens"]
    st.metric("总 Token 消耗", f"{total_tokens:,}")

st.divider()

# 第二行 KPI
col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("P50 延迟", f"{summary['p50_latency_ms'] / 1000:.1f}s")
with col2:
    st.metric("P99 延迟", f"{summary['p99_latency_ms'] / 1000:.1f}s")
with col3:
    st.metric("平均工具调用", f"{summary['avg_tool_calls']:.1f} 次")
with col4:
    cache_pct = 0
    if summary["total_input_tokens"] > 0:
        cache_pct = summary["total_cache_read_tokens"] / summary["total_input_tokens"] * 100
    st.metric("缓存命中率", f"{cache_pct:.0f}%")

st.divider()

# 延迟分布
st.subheader("⏱️ 延迟分布")
buckets = summary["latency_buckets"]
st.bar_chart(
    {k: v for k, v in buckets.items() if v > 0},
    use_container_width=True,
)

# Token 趋势 + 工具调用分布
col1, col2 = st.columns(2)

with col1:
    st.subheader("📈 每日 Token 趋势")
    trend = summary["daily_trend"]
    if trend:
        chart_data = {
            "日期": [t["day"] for t in trend],
            "Input Token": [t["input_tokens"] for t in trend],
            "Output Token": [t["output_tokens"] for t in trend],
        }
        st.line_chart(chart_data, x="日期", y=["Input Token", "Output Token"])
    else:
        st.caption("暂无数据")

with col2:
    st.subheader("🔧 工具调用分布")
    tool_dist = summary["tool_distribution"]
    if tool_dist:
        st.bar_chart(tool_dist, use_container_width=True)
    else:
        st.caption("暂无数据")

st.divider()

# 延迟细分
st.subheader("🔬 延迟细分")
col1, col2 = st.columns(2)
with col1:
    st.metric("平均检索耗时", f"{summary['avg_retrieval_ms'] / 1000:.1f}s")
with col2:
    st.metric("平均 LLM 耗时", f"{summary['avg_llm_ms'] / 1000:.1f}s")

st.divider()

# 最近查询明细
st.subheader("📋 最近查询明细")
recent = get_recent_metrics(session_id=session, limit=50)
if recent:
    rows = []
    for r in recent:
        rows.append({
            "时间": r["created_at"],
            "用户": r["session_id"],
            "问题": r["question"][:60] + ("..." if len(r["question"]) > 60 else ""),
            "总耗时(s)": f"{r['total_latency_ms']/1000:.1f}",
            "检索(ms)": r["retrieval_latency_ms"],
            "LLM(ms)": r["llm_latency_ms"],
            "工具调用": r["tool_call_count"],
            "Input Token": f"{r['input_tokens']:,}",
            "Output Token": f"{r['output_tokens']:,}",
            "缓存 Token": f"{r['cache_read_tokens']:,}",
        })
    st.dataframe(rows, use_container_width=True, hide_index=True)
