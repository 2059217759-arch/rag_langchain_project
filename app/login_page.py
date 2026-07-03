import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import httpx

from core import config
from core.logging_config import setup_logging

setup_logging()

st.set_page_config(page_title="RAG 智能助手", page_icon="🤖", layout="centered")

_CSS = """
<style>
.main .block-container { padding-top: 3rem; }
.login-card {
    max-width: 420px;
    margin: 0 auto;
    padding: 2.5rem 2rem 2rem;
}
.login-card .stButton > button {
    width: 100%;
}
.brand { text-align: center; margin-bottom: 1.5rem; }
.brand h1 { font-size: 2rem; margin: 0; }
.brand p { font-size: 0.95rem; margin-top: 0.25rem; }
</style>
"""
st.markdown(_CSS, unsafe_allow_html=True)

# ── Session init ──
if "access_token" not in st.session_state:
    st.session_state["access_token"] = None
if "username" not in st.session_state:
    st.session_state["username"] = None

# ── Already logged in ──
if st.session_state["access_token"]:
    st.markdown('<div class="brand"><h1>🤖 RAG 智能助手</h1></div>', unsafe_allow_html=True)
    st.success(f"已登录：**{st.session_state['username']}**")
    col_a, col_b = st.columns(2) # 创建两个列
    with col_a: 
        st.page_link("pages/chat_page.py", label="💬 进入对话", use_container_width=True)
    with col_b:
        st.page_link("pages/upload_page.py", label="📄 文档上传", use_container_width=True)
    if st.button("退出登录", use_container_width=True):
        st.session_state["access_token"] = None
        st.session_state["username"] = None
        st.rerun()
else:
    st.markdown('<div class="brand"><h1>🤖 RAG 智能助手</h1><p>基于知识库的智能问答系统</p></div>', unsafe_allow_html=True)

    st.markdown('<div class="login-card">', unsafe_allow_html=True)

    tab1, tab2 = st.tabs(["登录", "注册"])

    with tab1:
        login_username = st.text_input("用户名", key="login_user", placeholder="请输入用户名")
        login_password = st.text_input("密码", type="password", key="login_pass", placeholder="请输入密码")
        if st.button("登 录", type="primary", use_container_width=True, key="btn_login"):
            try:
                # 当程序执行到 with 行时，会调用 httpx.Client 对象的 __enter__ 方法。
                # 初始化 HTTP 客户端，建立必要的连接池等资源。
                with httpx.Client(base_url=config.API_BASE_URL, timeout=10) as client:
                    r = client.post(
                        "/api/auth/login",
                        json={"username": login_username, "password": login_password},
                    )
                if r.status_code == 200: # r是响应对象
                    data = r.json()
                    st.session_state["access_token"] = data["token"]
                    st.session_state["username"] = login_username
                    st.success(data["message"])
                    st.rerun()
                else:
                    detail = r.json().get("detail", "登录失败")
                    st.error(detail)
            except Exception as e:
                st.error(f"连接后端失败: {e}")

    with tab2:
        reg_username = st.text_input("用户名", key="reg_user", placeholder="至少3个字符")
        reg_password = st.text_input("密码", type="password", key="reg_pass", placeholder="至少6个字符")
        if st.button("注 册", type="primary", use_container_width=True, key="btn_register"):
            try:
                with httpx.Client(base_url=config.API_BASE_URL, timeout=10) as client:
                    r = client.post(
                        "/api/auth/register",
                        json={"username": reg_username, "password": reg_password},
                    )
                if r.status_code == 200:
                    data = r.json()
                    st.success(data["message"])
                else:
                    detail = r.json().get("detail", "注册失败")
                    st.error(detail)
            except Exception as e:
                st.error(f"连接后端失败: {e}")

    st.markdown('</div>', unsafe_allow_html=True)
