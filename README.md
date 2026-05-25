# RAG 智能助手

基于 LangChain + Streamlit 的 RAG 问答系统，支持文件上传、向量检索、对话记忆和上下文管理。

## 功能

- **用户注册/登录** — JWT 认证 + bcrypt 密码哈希
- **文件上传入库** — 文本文件自动分段 → 向量化 → ChromaDB，支持 MD5 去重
- **智能问答** — 基于上传文档的 RAG 检索增强生成
- **滑动窗口上下文** — 只保留最近 K 条完整消息，避免上下文爆炸
- **对话摘要** — 超出窗口的历史消息自动压缩为摘要，增量更新，恒定成本

## 技术栈

| 组件 | 技术 |
|------|------|
| 框架 | Streamlit |
| LLM | 通义千问 qwen-max（对话 + 摘要） |
| Embedding | DashScope text-embedding-v4 |
| 向量库 | ChromaDB（持久化） |
| 数据库 | MySQL 5.7+ |
| 认证 | JWT (HS256) + bcrypt |
| RAG 框架 | LangChain（RunnableWithMessageHistory） |

## 项目结构

```
rag_project/
├── app/
│   ├── login_page.py         # 入口：登录 / 注册
│   └── pages/
│       ├── chat_page.py      # 智能助手问答页
│       └── upload_page.py    # 文本文件上传页
├── core/
│   ├── config.py             # 全局配置（环境变量 + 常量）
│   ├── database.py           # MySQL 连接池 + 自动建库建表
│   ├── auth.py               # JWT 签发/解码 + bcrypt 密码管理
│   ├── rag.py                # RAG 服务：检索链 + 摘要管理
│   ├── ingestion.py          # 文档拆分 → 向量化入库 + MD5 去重
│   └── vector_store.py       # ChromaDB 向量存储封装
├── storage/
│   └── chat_history.py       # MySQL 对话历史持久化 + 摘要存取
├── data/
│   ├── chroma_db/            # ChromaDB 持久化文件
│   ├── uploads/              # 用户上传的原始文件
│   ├── chat_history/         # （预留）本地对话历史
│   └── md5.text              # 文件去重 MD5 记录
└── .env                      # 环境变量（API Key、数据库连接等）
```

## 数据库设计

### users
| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT PK | 用户 ID |
| username | VARCHAR(64) UNIQUE | 用户名 |
| password | VARCHAR(256) | bcrypt 哈希 |
| created_at | DATETIME | 注册时间 |

### chat_history
| 字段 | 类型 | 说明 |
|------|------|------|
| id | BIGINT PK | 消息 ID |
| session_id | VARCHAR(128) INDEX | 会话 ID（即用户名） |
| message | JSON | LangChain 消息格式 |
| created_at | DATETIME | 消息时间 |

### chat_summary
| 字段 | 类型 | 说明 |
|------|------|------|
| session_id | VARCHAR(128) PK | 会话 ID |
| summary | TEXT | 旧消息的对话摘要 |
| last_summarized_msg_id | BIGINT | 已摘要到的消息 ID 上限 |
| updated_at | DATETIME | 最后更新 |

## 快速开始

### 1. 环境要求

- Python 3.10+
- MySQL 5.7+

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置 .env

```bash
DASHSCOPE_API_KEY=sk-your-key-here

MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=rag_user
MYSQL_PASSWORD=Rag@123456
MYSQL_DATABASE=rag_db

JWT_SECRET_KEY=your-secret-key-change-in-production
JWT_EXPIRE_HOURS=24
```

### 4. 启动

```bash
streamlit run app/login_page.py
```

### 5. 使用流程

1. 打开浏览器访问 `http://localhost:8501`
2. 注册账号 → 登录
3. 进入「文件上传」页面上传文本文件（.txt）
4. 进入「智能助手」页面，基于文档内容提问

## 上下文管理机制

为了避免对话变长导致 prompt 超出 LLM 上下文窗口，系统使用 **滑动窗口 + 对话摘要** 双层机制：

### 滑动窗口

`MySQLChatMessageHistory.messages` 只返回最近 `WINDOW_SIZE`（默认 10）条消息，等效于 5 轮问答。这部分以完整的 LangChain 消息格式注入 prompt 的 `history` 占位符。

### 对话摘要

窗口之外的旧消息不会直接丢弃，而是通过 `RagService._maybe_update_summary()` 自动压缩：

1. **触发时机**：每次 `invoke()` 完成后自动执行，无需 UI 层关心
2. **增量更新**：只取新溢出窗口的消息，与已有摘要合并，LLM 生成 300 字以内的综合摘要
3. **恒定成本**：摘要长度上限 300 字，不论对话多长，每次摘要调用成本 O(1)
4. **失败容忍**：摘要异常被静默捕获，不影响主对话流程

### 最终 Prompt 结构

```
[system] 你是...参考资料：{RAG检索结果}。
早前对话摘要：{<=300字摘要，无摘要时为空}

[history — 最近 10 条完整消息]
Human: "xxx"
AI: "xxx"
...

[human] 当前问题
```

### 相关配置

```python
# core/config.py
WINDOW_SIZE = 10   # 滑动窗口大小，可调大以适应更大上下文窗口的模型
```

## 配置参考

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `CHAT_MODEL_NAME` | `qwen-max` | 对话模型 |
| `WINDOW_SIZE` | `10` | 滑动窗口消息条数 |
| `CHUNK_SIZE` | `1000` | 文档分段大小 |
| `CHUNK_OVERLAP` | `100` | 分段重叠量 |
| `COLLECTION_NAME` | `rag` | ChromaDB 集合名 |
| `JWT_EXPIRE_HOURS` | `24` | Token 过期时间 |
