import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st

from core.auth import register_user, login_user

st.set_page_config(page_title="RAG 智能助手", page_icon="🤖", layout="centered")

_CSS = """
<style>
.main .block-container { padding-top: 3rem; }
.login-card {
    background: #fff;
    border-radius: 16px;
    padding: 2.5rem 2rem 2rem;
    box-shadow: 0 4px 24px rgba(0,0,0,0.06);
    max-width: 420px;
    margin: 0 auto;
}
.login-card .stTabs [data-baseweb="tab-list"] {
    gap: 0;
    border-bottom: 2px solid #E5E7EB;
}
.login-card .stTabs [data-baseweb="tab"] {
    flex: 1;
    justify-content: center;
    font-size: 1rem;
    font-weight: 600;
    padding: 0.6rem 0;
    border-radius: 0;
    color: #6B7280;
}
.login-card .stTabs [data-baseweb="tab"][aria-selected="true"] {
    color: #1A73E8;
    border-bottom: 2px solid #1A73E8;
    margin-bottom: -2px;
}
.login-card .stButton > button {
    width: 100%;
    border-radius: 10px;
    padding: 0.55rem 0;
    font-size: 1rem;
    font-weight: 600;
    background: #1A73E8;
    color: #fff;
    border: none;
    transition: background 0.2s;
}
.login-card .stButton > button:hover { background: #1557B0; }
.brand { text-align: center; margin-bottom: 1.5rem; }
.brand h1 { font-size: 2rem; color: #1A73E8; margin: 0; }
.brand p { color: #6B7280; font-size: 0.95rem; margin-top: 0.25rem; }
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
    col_a, col_b = st.columns(2)
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
            ok, msg, token = login_user(login_username, login_password)
            if ok and token:
                st.session_state["access_token"] = token
                st.session_state["username"] = login_username
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)

    with tab2:
        reg_username = st.text_input("用户名", key="reg_user", placeholder="至少3个字符")
        reg_password = st.text_input("密码", type="password", key="reg_pass", placeholder="至少6个字符")
        if st.button("注 册", type="primary", use_container_width=True, key="btn_register"):
            ok, msg = register_user(reg_username, reg_password)
            if ok:
                st.success(msg)
            else:
                st.error(msg)

    st.markdown('</div>', unsafe_allow_html=True)
