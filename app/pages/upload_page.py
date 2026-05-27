import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st

from core.ingestion import IngestionService
from core import config

if "access_token" not in st.session_state or not st.session_state["access_token"]:
    st.warning("请先登录")
    st.switch_page("login_page.py")
    st.stop()

st.set_page_config(page_title="文本上传", page_icon="📄")

st.title("📄 文本文件上传")

os.makedirs(config.DATA_DIR + "/uploads", exist_ok=True)

uploaded_file = st.file_uploader("选择文本/Markdown 文件", type=["txt", "md"])

if "ingestion" not in st.session_state:
    st.session_state["ingestion"] = IngestionService()

service = st.session_state["ingestion"]

if uploaded_file is not None:
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("文件名", uploaded_file.name)
    with col2:
        st.metric("文件类型", uploaded_file.type)
    with col3:
        size_kb = round(uploaded_file.size / 1024, 2)
        st.metric("文件大小", f"{size_kb} KB")

    file_path = os.path.join(config.DATA_DIR, "uploads", uploaded_file.name)

    with open(file_path, "wb") as f:
        f.write(uploaded_file.getbuffer())

    st.success(f"✅ 文件已保存到本地: {file_path}")

    content = uploaded_file.read().decode("utf-8")
    st.text_area("文件内容", content, height=400)

    result = service.upload_by_str(data=content, file_name=uploaded_file.name)
    st.info(result)
