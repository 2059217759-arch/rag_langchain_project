import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
import httpx

from core import config

st.set_page_config(page_title="文档上传", page_icon="📄", layout="wide")

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
    margin-bottom: 1rem;
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
headers = {"Authorization": f"Bearer {token}"}

# ── Sidebar ──
with st.sidebar:
    st.markdown("### 🤖 RAG 智能助手")
    st.caption("文档管理与上传")
    st.divider()
    st.markdown(f"**👤 {st.session_state['username']}**")
    st.divider()
    st.page_link("pages/chat_page.py", label="💬 智能对话", use_container_width=True)
    if st.button("🚪 退出登录", use_container_width=True):
        st.session_state["access_token"] = None
        st.session_state["username"] = None
        st.switch_page("login_page.py")

# ── Main ──
st.markdown('<div class="title-bar"><h2>📄 文档上传</h2></div>', unsafe_allow_html=True)

os.makedirs(os.path.join(config.DATA_DIR, "uploads"), exist_ok=True)

uploaded_file = st.file_uploader(
    "选择文本或 Markdown 文件上传到知识库",
    type=["txt", "md"],
    label_visibility="collapsed",
)

if uploaded_file is not None:
    col1, col2 = st.columns(2)

    size_kb = round(uploaded_file.size / 1024, 2)

    with col1:
        st.markdown("#### 📋 文件信息")
        st.markdown(f"**文件名**：{uploaded_file.name}")
        st.markdown(f"**类型**：{uploaded_file.type or '未知'}")
        st.markdown(f"**大小**：{size_kb} KB")

    # 保存到本地 + 调用 FastAPI 上传
    content = uploaded_file.read().decode("utf-8")

    with col2:
        st.markdown("#### ⚙️ 处理结果")
        try:
            with httpx.Client(base_url=config.API_BASE_URL, headers=headers, timeout=120) as client:
                r = client.post(
                    "/api/upload",
                    files={"file": (uploaded_file.name, content.encode("utf-8"), "text/plain")},
                )
            if r.status_code == 200:
                data = r.json()
                st.success(data.get("message", "上传成功"))
            else:
                detail = r.json().get("detail", "上传失败")
                st.error(detail)
        except Exception as e:
            st.error(f"连接后端失败: {e}")

    # 内容预览
    st.markdown("#### 📖 内容预览")
    st.text_area(
        "文件内容",
        content,
        height=360,
        label_visibility="collapsed",
        key="preview",
    )
