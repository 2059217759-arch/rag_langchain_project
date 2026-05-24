import os
import sys 

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st

from core.auth import register_user, login_user

st.set_page_config(page_title="登录", page_icon="🔐")

if "access_token" not in st.session_state:
    st.session_state["access_token"] = None
if "username" not in st.session_state:
    st.session_state["username"] = None

# 判断是否已登录，已经登录则显示已登录信息并跳转到那两个页面
if st.session_state["access_token"]:
    st.success(f"已登录：{st.session_state['username']}")
    st.page_link("pages/chat_page.py", label="进入智能助手")
    st.page_link("pages/upload_page.py", label="进入文件上传")
    if st.button("退出登录"):
        st.session_state["access_token"] = None
        st.session_state["username"] = None
        st.rerun()
else:
    tab1, tab2 = st.tabs(["登录", "注册"])

    with tab1:
        st.subheader("用户登录")
        login_username = st.text_input("用户名", key="login_user")
        login_password = st.text_input("密码", type="password", key="login_pass")
        if st.button("登录", type="primary"):

            # 调用登录接口，创建令牌
            ok, msg, token = login_user(login_username, login_password)
            if ok and token:
                # 登录成功，在前端状态中保存令牌、用户名
                st.session_state["access_token"] = token
                st.session_state["username"] = login_username
                st.success(msg) # 提示登录成功
                st.rerun() # 重新运行当前页面，会跳到17行
            else:
                st.error(msg)

    with tab2:
        st.subheader("用户注册")
        reg_username = st.text_input("用户名", key="reg_user")
        reg_password = st.text_input("密码", type="password", key="reg_pass")
        if st.button("注册", type="primary"):
            ok, msg = register_user(reg_username, reg_password)
            if ok:
                st.success(msg)
            else:
                st.error(msg)
