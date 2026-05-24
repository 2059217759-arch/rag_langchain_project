# RAG 智能助手

基于 LangChain + Streamlit 的 RAG 问答系统，支持文件上传、向量检索和对话记忆。

## 功能

- 文本文件上传与向量化入库
- 基于文档的智能问答
- 用户注册/登录（JWT 认证）
- 对话历史记录

## 技术栈

| 组件 | 技术 |
|------|------|
| 框架 | Streamlit |
| LLM | 通义千问 (qwen-max) |
| Embedding | DashScope text-embedding-v4 |
| 向量库 | ChromaDB |
| 数据库 | MySQL |
| 认证 | JWT + bcrypt |

## 快速开始

### 1. 环境要求

- Python 3.10+
- MySQL 5.7+

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置

复制 `.env` 并修改数据库连接信息：

```bash
cp .env.example .env//作者懒没创建模板，自己让ai配环境吧
```

### 4. 启动

```bash
streamlit run app/login_page.py
```

### 5. 使用

1. 注册账号并登录
2. 在「文件上传」页面上传文本文件
3. 在「智能助手」页面基于文档内容提问

## 项目结构

```
rag_project/
├── app/
│   ├── login_page.py      # 登录/注册页面
│   └── pages/
│       ├── chat_page.py   # 智能助手页面
│       └── upload_page.py # 文件上传页面
├── core/
│   ├── auth.py            # JWT 认证
│   ├── config.py          # 配置
│   ├── database.py        # MySQL 连接
│   ├── ingestion.py       # 文档入库
│   ├── rag.py             # RAG 服务
│   └── vector_store.py    # 向量存储
├── storage/
│   └── chat_history.py    # 对话历史
└── data/                  # 运行时数据
```
