import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st

from core.rag import RagService

if "access_token" not in st.session_state or not st.session_state["access_token"]:
    st.warning("请先登录")
    st.switch_page("login_page.py")
    st.stop()

st.title("智能助手")
st.divider()

if "messages" not in st.session_state:
    st.session_state["messages"] = [
        {"role": "assistant", "content": "欢迎来到智能助手，请输入问题。"}
    ]

if "rag" not in st.session_state:
    st.session_state["rag"] = RagService()

for message in st.session_state.messages:
    if message["role"] == "user":
        st.chat_message("user").write(message["content"])
    else:
        st.chat_message("assistant").write(message["content"])

question = st.chat_input("请输入问题：")

if question:
    st.chat_message("user").write(question)
    st.session_state.messages.append({"role": "user", "content": question})

    res = st.session_state["rag"].get_chain().invoke(
        {"question": question},
        config={"configurable": {"session_id": st.session_state["username"]}},
    )
    st.chat_message("assistant").write(res)
    st.session_state.messages.append({"role": "assistant", "content": res})
