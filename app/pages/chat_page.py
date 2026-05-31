import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st

from core.rag import RagService

st.set_page_config(page_title="智能助手", page_icon="💬", layout="wide")

# ── CSS ──
_CSS = """
<style>
.main .block-container { padding-top: 1.5rem; }
/* 侧边栏按钮全宽 */
section[data-testid="stSidebar"] .stButton > button {
    width: 100%;
}
/* 标题栏 */
.title-bar {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding-bottom: 0.5rem;
    border-bottom: 1px solid #E5E7EB;
    margin-bottom: 0.5rem;
}
.title-bar h2 { margin: 0; font-size: 1.4rem; }
</style>
"""
st.markdown(_CSS, unsafe_allow_html=True)

# ── Auth guard ──
if "access_token" not in st.session_state or not st.session_state["access_token"]:
    st.warning("请先登录")
    st.switch_page("login_page.py")
    st.stop()

# ── Sidebar ──
with st.sidebar:
    st.markdown("### 🤖 RAG 智能助手")
    st.caption("基于知识库的智能问答")

    st.divider()

    st.markdown(f"**👤 {st.session_state['username']}**")

    st.divider()

    if "messages" in st.session_state:
        user_msgs = sum(1 for m in st.session_state.messages if m["role"] == "user")
        st.metric("本轮消息", user_msgs)

    if st.button("🚪 退出登录", use_container_width=True):
        st.session_state["access_token"] = None
        st.session_state["username"] = None
        st.switch_page("login_page.py")

    st.divider()

    # ── 历史会话记录 ──
    st.markdown("##### 📜 最近 10 轮对话")
    try:
        from storage.chat_history import MySQLChatMessageHistory
        rounds = MySQLChatMessageHistory.get_recent_rounds(
            st.session_state["username"], rounds=10
        )
        if rounds:
            for i, r in enumerate(rounds):
                label = r["question"][:28] + ("..." if len(r["question"]) > 28 else "")
                with st.expander(f"{i+1}. {label}"):
                    st.caption("**问**")
                    st.text(r["question"])
                    st.caption("**答**")
                    st.text(r["answer"])
        else:
            st.caption("暂无对话记录")
    except Exception:
        st.caption("加载失败")

    st.divider()

    if st.button("🔄 清空对话", use_container_width=True):
        st.session_state["messages"] = [
            {"role": "assistant", "content": "对话已清空，有什么可以帮你的？"}
        ]
        st.rerun()

# ── Main ──
st.markdown('<div class="title-bar"><h2>💬 智能助手</h2></div>', unsafe_allow_html=True)

if "messages" not in st.session_state:
    st.session_state["messages"] = [
        {"role": "assistant", "content": "你好！我是基于知识库的智能助手，请随意提问。"}
    ]

if "rag" not in st.session_state:
    with st.spinner("正在加载模型..."):
        st.session_state["rag"] = RagService()

# 历史消息
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.write(message["content"])

# 输入框
question = st.chat_input("输入你的问题，按回车发送...")

if question:
    with st.chat_message("user"):
        st.write(question)
    st.session_state.messages.append({"role": "user", "content": question})

    with st.chat_message("assistant"):
        with st.spinner("思考中..."):
            res = st.session_state["rag"].invoke(
                question, st.session_state["username"]
            )
        st.write(res)
    st.session_state.messages.append({"role": "assistant", "content": res})
