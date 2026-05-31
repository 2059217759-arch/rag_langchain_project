# RAG 智能助手 <sup>v2.4.0</sup>

基于 LangChain + Streamlit 的 RAG 问答系统，支持文件上传、向量检索、对话记忆和上下文管理。

## 功能

- **用户注册/登录** — JWT 认证 + bcrypt 密码哈希
- **文件上传入库** — 文本/Markdown 文件自动分段 → 向量化 → ChromaDB，支持 MD5 去重，父子块分层存储
- **Agent 智能问答** — ReAct 范式，LLM 自主决定是否检索、检索什么、检索几次，BM25 + 向量混合检索 + CrossEncoder 重排序
- **滑动窗口上下文** — 只保留最近 K 条完整消息，避免上下文爆炸
- **对话摘要** — 超出窗口的历史消息自动压缩为摘要，增量更新，恒定成本
- **历史会话记录** — 侧边栏查看最近 10 轮对话，从 MySQL 持久化读取，跨会话保留

## 技术栈

| 组件 | 技术 |
|------|------|
| 框架 | Streamlit |
| LLM | DeepSeek V4 Pro（对话 + 摘要，OpenAI 兼容 API） |
| Embedding | DashScope text-embedding-v4 |
| 向量库 | ChromaDB（持久化） |
| 数据库 | MySQL 5.7+ |
| 检索 | BM25（jieba）+ ChromaDB 向量 → RRF 融合 |
| 重排序 | BCE-Reranker-Base-V1（本地部署） |
| 认证 | JWT (HS256) + bcrypt |
| Agent 框架 | LangChain ReAct（`create_react_agent` + `AgentExecutor`） |

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
│   ├── ingestion.py          # 父子块切分（Markdown 结构化）→ 向量化入库 + MD5 去重
│   └── vector_store.py       # ChromaDB 向量存储封装
├── storage/
│   └── chat_history.py       # MySQL 对话历史持久化 + 摘要存取
├── data/
│   ├── chroma_db/            # ChromaDB 持久化文件
│   ├── bm25_index.pkl        # BM25 索引磁盘缓存
│   ├── models/               # 本地模型（BCE-Reranker-Base-V1）
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

### document_parents
| 字段 | 类型 | 说明 |
|------|------|------|
| parent_id | VARCHAR(32) PK | 父块 MD5 标识 |
| parent_content | MEDIUMTEXT | 父块完整内容 |
| parent_title | VARCHAR(500) | 章节标题（Markdown 标题行） |
| source | VARCHAR(255) | 来源文件名 |
| child_count | INT | 该父块包含的子块数 |

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
DASHSCOPE_API_KEY=sk-your-key-here      # Embedding 模型：DashScope text-embedding-v4

DEEPSEEK_API_KEY=sk-your-key-here       # 对话模型：DeepSeek V4 Pro
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_CHAT_MODEL=deepseek-v4-pro

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
3. 进入「文件上传」页面上传文本/Markdown 文件（.txt, .md）
4. 进入「智能助手」页面，基于文档内容提问

## 上下文管理机制

为了避免对话变长导致 prompt 超出 LLM 上下文窗口，系统使用 **滑动窗口 + 对话摘要** 双层机制。

### 记忆框架架构

LangChain 提供了两类记忆/对话历史方案：

| 方案 | 所属模块 | 适用场景 |
|------|---------|---------|
| `ConversationBufferMemory` / `ConversationBufferWindowMemory` / `ConversationSummaryBufferMemory` | `langchain.memory`（旧版 API） | `LLMChain` / `ConversationChain` 体系 |
| `BaseChatMessageHistory` + `RunnableWithMessageHistory` | `langchain_core`（LCEL 新架构） | `create_react_agent` + `AgentExecutor` 体系 |

本项目采用 **LCEL 新架构**，不直接使用旧版 `Conversation*Memory` 类，而是通过继承 `BaseChatMessageHistory` 自行实现了等价的三种记忆模式：

```
RunnableWithMessageHistory   ← 框架层：链执行前后自动调用 memory.add_messages / memory.messages
        ↑
BaseChatMessageHistory       ← 抽象接口：add_messages / messages / clear
        ↑
MySQLChatMessageHistory      ← 自定义实现：MySQL 持久化 + 滑动窗口 + 摘要存取
```

三种记忆模式的对应关系：

| LangChain 旧版类 | 本项目等价实现 | 机制 |
|-----------------|--------------|------|
| `ConversationBufferMemory` | `MySQLChatMessageHistory.messages`（不加 LIMIT 即为全量） | 存储完整对话历史 |
| `ConversationBufferWindowMemory`（K 轮） | `WINDOW_SIZE = 10`，SQL `LIMIT 10`（约 5 轮） | 只保留最近 K 条消息 |
| `ConversationSummaryBufferMemory` | `_maybe_update_summary()` + `chat_summary` 表 | 超长历史用 LLM 增量摘要压缩 |

采用 LCEL 架构的优势：

- **持久化自由** — 旧版 Memory 默认存内存，重启即丢；本项目直接写入 MySQL，跨会话持久化
- **摘要与对话解耦** — `{summary}` 和 `{chat_history}` 是独立占位符，提示词模板更清晰
- **增量摘要** — `last_summarized_msg_id` 标记实现增量更新，每次只摘要新溢出消息，旧版无此能力
- **Agent 原生兼容** — 旧版 Memory 对接 `create_react_agent` + `AgentExecutor` 需要额外适配层

### 滑动窗口

`MySQLChatMessageHistory.messages` 只返回最近 `WINDOW_SIZE`（默认 10）条消息，等效于 5 轮问答。这部分以完整的 LangChain 消息格式注入 prompt 的 `history` 占位符。

### 对话摘要

窗口之外的旧消息不会直接丢弃，而是通过 `RagService._maybe_update_summary()` 自动压缩：

1. **触发时机**：每次 `invoke()` 完成后自动执行，无需 UI 层关心
2. **增量更新**：只取新溢出窗口的消息，与已有摘要合并，LLM 生成 300 字以内的综合摘要
3. **恒定成本**：摘要长度上限 300 字，不论对话多长，每次摘要调用成本 O(1)
4. **失败容忍**：摘要异常被静默捕获，不影响主对话流程

### Agent 推理流程（v2.3.0）

系统采用 ReAct 范式，检索不再是固定步骤，而是 LLM 可自主调用的 Tool：

```
Question: 用户问题
Thought: 分析是否需要检索 → 不需要则直接 Final Answer
Action: search_knowledge_base
Action Input: 搜索关键词
Observation: [BM25 + 向量混合检索 → RRF 融合 → CrossEncoder 重排序 → top-4 父块]
Thought: 我已获得足够信息，可以回答
Final Answer: 基于资料的回复
```

对于简单问候，Agent 跳过 Action 直接回复，避免不必要的检索开销。

### 相关配置

```python
# core/config.py
WINDOW_SIZE = 10   # 滑动窗口大小，可调大以适应更大上下文窗口的模型
```

## 文档分块策略（v2.1.0）

系统采用 **父子块（Parent-Child）分层策略**：

- **父块切分**：优先按 Markdown 标题（`#` ~ `######`）识别章节边界；无标题时按段落空行切分；超长段落按句子边界强制截断。父块目标大小 ≤ 4000 字符，存入 MySQL `document_parents` 表。
- **子块切分**：在每个父块内部按句子边界切分为 300 字符的小块，存入 ChromaDB 用于向量检索。
- **检索流程（v2.2.0）**：query → 向量路（top-8）+ BM25 路（top-8）→ RRF 融合 → 按父块去重 → CrossEncoder 重排序 → 取 top-4 父块 → MySQL 查完整父块内容 → 拼入 LLM prompt。

## 配置参考

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `DEEPSEEK_CHAT_MODEL` | `deepseek-chat` | 对话模型 |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | DeepSeek API 地址 |
| `WINDOW_SIZE` | `10` | 滑动窗口消息条数 |
| `PARENT_MAX_SIZE` | `4000` | 父块目标大小上限（字符） |
| `CHILD_CHUNK_SIZE` | `300` | 子块大小（用于向量检索） |
| `CHILD_CHUNK_OVERLAP` | `50` | 子块重叠量 |
| `TOP_K_CHILDREN` | `8` | 向量检索子块数 |
| `TOP_K_BM25` | `8` | BM25 检索子块数 |
| `TOP_K_PARENTS` | `4` | 最终返回父块给 LLM 的数量 |
| `RRF_K` | `60` | RRF 融合常数 |
| `RERANKER_MODEL` | `data/models/bce-reranker-base_v1` | 本地重排序模型路径 |
| `BM25_INDEX_PATH` | `data/bm25_index.pkl` | BM25 磁盘缓存路径 |
| `COLLECTION_NAME` | `rag` | ChromaDB 集合名 |
| `JWT_EXPIRE_HOURS` | `24` | Token 过期时间 |
