import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st

from core.ingestion import IngestionService
from core import config

st.set_page_config(page_title="文档上传", page_icon="📄", layout="wide")

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

if "ingestion" not in st.session_state:
    st.session_state["ingestion"] = IngestionService()

service = st.session_state["ingestion"]

# 上传区域
st.markdown('<div class="card">', unsafe_allow_html=True)
uploaded_file = st.file_uploader(
    "选择文本或 Markdown 文件上传到知识库",
    type=["txt", "md"],
    label_visibility="collapsed",
)
st.markdown('</div>', unsafe_allow_html=True)

if uploaded_file is not None:
    # 文件信息 + 处理结果
    col1, col2 = st.columns(2)

    size_kb = round(uploaded_file.size / 1024, 2)

    with col1:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown("#### 📋 文件信息")
        st.markdown(f"**文件名**：{uploaded_file.name}")
        st.markdown(f"**类型**：{uploaded_file.type or '未知'}")
        st.markdown(f"**大小**：{size_kb} KB")
        st.markdown('</div>', unsafe_allow_html=True)

    # 保存文件
    file_path = os.path.join(config.DATA_DIR, "uploads", uploaded_file.name)
    with open(file_path, "wb") as f:
        f.write(uploaded_file.getbuffer())

    content = uploaded_file.read().decode("utf-8")

    with col2:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown("#### ⚙️ 处理结果")
        result = service.upload_by_str(data=content, file_name=uploaded_file.name)
        if "成功" in result:
            st.success(result)
        elif "跳过" in result:
            st.warning(result)
        else:
            st.error(result)
        st.markdown('</div>', unsafe_allow_html=True)

    # 内容预览
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown("#### 📖 内容预览")
    st.text_area(
        "文件内容",
        content,
        height=360,
        label_visibility="collapsed",
        key="preview",
    )
    st.markdown('</div>', unsafe_allow_html=True)
