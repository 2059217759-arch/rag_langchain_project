import streamlit as st
from rag import RagService

# 创建标题
st.title("智能助手")
st.divider()

if "messages" not in st.session_state:
    st.session_state["messages"]=[{"role": "assistant", "content": "欢迎来到智能助手，请输入问题。"}]

if "rag" not in st.session_state:
    st.session_state["rag"] = RagService()

# 显示会话记录
for message in st.session_state.messages:
    if message["role"] == "user":
        st.chat_message("user").write(message["content"])
    else:
        st.chat_message("assistant").write(message["content"])

# 创建输入框
question = st.chat_input("请输入问题：")

if question:
    # 输出用户的问题
    st.chat_message("user").write(question)
    st.session_state.messages.append({"role": "user", "content": question})

    res=st.session_state["rag"].get_chain().invoke(
        {"question": question},
        config={"configurable": {"session_id": "user_002"}}
        )
    st.chat_message("assistant").write(res)
    # 保存会话记录,加入响应
    st.session_state.messages.append({"role":"assistant","content": res})
