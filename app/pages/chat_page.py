import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
import httpx

from core import config

st.set_page_config(page_title="智能助手", page_icon="💬", layout="wide")

_CSS = """
<style>
.main .block-container { padding-top: 1.5rem; }
section[data-testid="stSidebar"] .stButton > button {
    width: 100%;
}
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

token = st.session_state["access_token"]
username = st.session_state["username"]
headers = {"Authorization": f"Bearer {token}"}

# ── Sidebar ──
with st.sidebar:
    st.markdown("### 🤖 RAG 智能助手")
    st.caption("基于知识库的智能问答")

    st.divider()
    st.markdown(f"**👤 {username}**")
    st.divider()

    if "chat_session_id" in st.session_state:
        st.caption(f"会话: `...{st.session_state['chat_session_id'][-12:]}`")

    if "messages" in st.session_state:
        user_msgs = sum(1 for m in st.session_state.messages if m["role"] == "user")
        st.metric("本轮消息", user_msgs)

    if st.button("🚪 退出登录", use_container_width=True):
        st.session_state["access_token"] = None
        st.session_state["username"] = None
        st.switch_page("login_page.py")

    st.divider()

    # ── 历史会话记录 ──
    st.markdown("##### 📜 最近对话")
    try:
        session_id = st.session_state.get("chat_session_id", username)
        with httpx.Client(base_url=config.API_BASE_URL, headers=headers, timeout=10) as client:
            r = client.get("/api/chat/history", params={"session_id": session_id})
        if r.status_code == 200:
            rounds = r.json().get("rounds", [])
            if rounds:
                for i, rnd in enumerate(rounds[-10:]):
                    label = rnd["question"][:28] + ("..." if len(rnd["question"]) > 28 else "")
                    with st.expander(f"{i+1}. {label}"):
                        st.caption("**问**")
                        st.text(rnd["question"])
                        st.caption("**答**")
                        st.text(rnd["answer"])
            else:
                st.caption("暂无对话记录")
        else:
            st.caption("加载失败")
    except Exception:
        st.caption("加载失败")

    st.divider()

    if st.button("➕ 新建会话", use_container_width=True):
        try:
            with httpx.Client(base_url=config.API_BASE_URL, headers=headers, timeout=10) as client:
                r = client.post("/api/chat/sessions")
            if r.status_code == 200:
                data = r.json()
                st.session_state["chat_session_id"] = data["session_id"]
                st.session_state["messages"] = [
                    {"role": "assistant", "content": "新会话已创建，有什么可以帮你的？"}
                ]
                st.rerun()
        except Exception as e:
            st.error(f"创建会话失败: {e}")

    if st.button("📊 性能监控", use_container_width=True):
        st.switch_page("pages/metrics_page.py")

    if st.button("🔄 清空对话", use_container_width=True):
        session_id = st.session_state.get("chat_session_id", username)
        try:
            with httpx.Client(base_url=config.API_BASE_URL, headers=headers, timeout=10) as client:
                client.request("DELETE", "/api/chat/clear", json={"session_id": session_id})
        except Exception:
            pass
        st.session_state["messages"] = [
            {"role": "assistant", "content": "对话已清空，有什么可以帮你的？"}
        ]
        st.rerun()

# ── Main ──
st.markdown('<div class="title-bar"><h2>💬 智能助手</h2></div>', unsafe_allow_html=True)

# 初始化 session
if "chat_session_id" not in st.session_state:
    st.session_state["chat_session_id"] = username

if "messages" not in st.session_state:
    st.session_state["messages"] = [
        {"role": "assistant", "content": "你好！我是基于知识库的智能助手，请随意提问。"}
    ]

session_id = st.session_state["chat_session_id"]

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
        placeholder = st.empty()
        placeholder.markdown("*思考中...*")

        answer = None
        try:
            with httpx.Client(base_url=config.API_BASE_URL, headers=headers, timeout=300) as client:
                with client.stream(
                    "POST",
                    "/api/chat/send",
                    json={"question": question, "session_id": session_id},
                ) as response:
                    if response.status_code == 200:
                        for line in response.iter_lines():
                            if line.startswith("data: "):
                                data = json.loads(line[6:])
                                if data.get("type") == "answer":
                                    answer = data.get("content", "")
                                    placeholder.markdown(answer)
                                elif data.get("type") == "error":
                                    answer = f"错误: {data.get('content', '未知错误')}"
                                    placeholder.error(answer)
                    else:
                        answer = f"请求失败 (HTTP {response.status_code})"
                        placeholder.error(answer)
        except Exception as e:
            answer = f"连接后端失败: {e}"
            placeholder.error(answer)

        if answer is None:
            answer = "未收到回复，请重试"
            placeholder.warning(answer)

    st.session_state.messages.append({"role": "assistant", "content": answer})
