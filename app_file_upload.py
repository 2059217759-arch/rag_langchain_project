import streamlit as st
import os
from knowledge_base import KnowledgeBaseService

st.set_page_config(page_title="文本上传", page_icon="📄")

st.title("📄 文本文件上传")

# 创建上传目录,就是在当前文件夹下创建一个uploads目录
upload_dir = "uploads"
os.makedirs(upload_dir, exist_ok=True)

# 上传文件，目前只支持txt文件
uploaded_file = st.file_uploader("选择文本文件", type=["txt"])

# 检查是否已存在服务实例，如果没有则创建
# KnowledgeBaseService()初始化服务实例，相当于cpp的无参构造
# 把这个实例保存在session_state中
if "service" not in st.session_state:
    st.session_state["service"] = KnowledgeBaseService()

# 使用已存在的服务实例
service = st.session_state["service"]

if uploaded_file is not None:

    # 显示文件信息
    col1, col2, col3= st.columns(3)
    with col1:
        st.metric("文件名", uploaded_file.name)
    with col2:
        st.metric("文件类型", uploaded_file.type)
    with col3:
        size_kb = round(uploaded_file.size / 1024, 2)
        st.metric("文件大小", f"{size_kb} KB")

    #  os.path.join是一个路径拼接函数，作用是拼接两个路径，返回拼接后的路径
    file_path = os.path.join(upload_dir, uploaded_file.name)

    # uploaded_file 是一个类似文件的对象（比如 BytesIO），
    # getbuffer() 直接获取其底层内存缓冲区对象，避免额外的复制，适合大文件处理（尤其在需要高效写入时）。
    with open(file_path, "wb") as f:
        f.write(uploaded_file.getbuffer())
    
    st.success(f"✅ 文件已保存到本地: {file_path}")
    
    # 显示内容
    content = uploaded_file.read().decode("utf-8")
    st.text_area("文件内容", content, height=400)

    # 调用knowledge_base服务
    result=service.upload_by_str(data=content,file_name=uploaded_file.name)
    st.info(result) # 显示结果