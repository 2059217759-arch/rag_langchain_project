# RAG 智能助手 <sup>v2.7.0</sup>

基于 FastAPI + LangChain + Streamlit 的 RAG 高并发问答系统，支持文件上传、向量检索、对话记忆和上下文管理。

## 功能

- **用户注册/登录** — JWT 认证 + bcrypt 密码哈希
- **文件上传入库** — 文本/Markdown 文件自动分段 → 向量化 → ChromaDB，支持 MD5 去重，父子块分层存储
- **Agent 智能问答** — ReAct 范式，LLM 自主决定是否检索、检索什么、检索几次，BM25 + 向量混合检索 + CrossEncoder 重排序
- **滑动窗口上下文** — 只保留最近 K 条完整消息，避免上下文爆炸
- **对话摘要** — 超出窗口的历史消息自动压缩为摘要，增量更新，恒定成本
- **历史会话记录** — 侧边栏查看最近 10 轮对话，从 MySQL 持久化读取，跨会话保留
- **性能监控仪表盘** — 延迟分布、Token 趋势、工具调用统计、缓存命中率，结构化 metrics 持久化到 MySQL
- **高并发架构** — FastAPI async 路由 + 线程池执行同步逻辑 + ChromaDB Server + MySQL 连接池
- **SSE 流式返回** — Agent 问答通过 Server-Sent Events 实时推送，用户无需等待完整响应
- **多会话管理** — 同一用户可创建多个独立会话（`username_uuid`），多端互不干扰

## 技术栈

| 组件 | 技术 |
|------|------|
| 后端 | FastAPI (async) + uvicorn |
| 前端 | Streamlit（纯 UI 层，通过 httpx 调 API） |
| LLM | DeepSeek V4 Pro（对话 + 摘要，OpenAI 兼容 API） |
| Embedding | DashScope text-embedding-v4 |
| 向量库 | ChromaDB（Client/Server 模式，独立进程） |
| 数据库 | MySQL 5.7+（DBUtils 连接池） |
| 检索 | BM25（jieba）+ ChromaDB 向量 → RRF 融合 |
| 重排序 | BCE-Reranker-Base-V1（本地部署） |
| 认证 | JWT (HS256) + bcrypt |
| Agent 框架 | 原生 Function Calling（`ChatOpenAI.bind_tools()` + 自写 Agent 循环） |

## 项目结构

```
rag_project/
├── api/                        # FastAPI 后端（v2.7.0 新增）
│   ├── main.py                 # FastAPI app + lifespan + CORS
│   ├── deps.py                 # 依赖注入（JWT 鉴权、RagService 注入）
│   ├── schemas.py              # Pydantic 请求/响应模型
│   └── routes/
│       ├── auth.py             # POST /api/auth/login, /api/auth/register
│       ├── chat.py             # POST /api/chat/send (SSE), GET history, DELETE clear
│       ├── upload.py           # POST /api/upload
│       └── metrics.py          # GET /api/metrics/summary, /api/metrics/recent
├── app/
│   ├── login_page.py           # 入口：登录 / 注册（调 FastAPI）
│   └── pages/
│       ├── chat_page.py        # 智能助手问答页（httpx SSE 流式调用）
│       ├── upload_page.py      # 文件上传页（httpx 调 FastAPI）
│       └── metrics_page.py     # 性能监控仪表盘（httpx 调 FastAPI）
├── core/
│   ├── config.py               # 全局配置（环境变量 + 常量）
│   ├── database.py             # MySQL 连接池 + 自动建库建表
│   ├── auth.py                 # JWT 签发/解码 + bcrypt 密码管理
│   ├── rag.py                  # RagService 单例 + Agent 循环
│   ├── ingestion.py            # IngestionService 单例 + 父子块切分
│   ├── metrics.py              # 性能指标存取（MySQL 持久化 + 聚合查询）
│   └── vector_store.py         # ChromaDB (HttpClient) + BM25 + Reranker
├── storage/
│   └── chat_history.py         # MySQL 对话历史持久化 + 摘要存取
├── data/
│   ├── chroma_db/              # ChromaDB 持久化目录（由 chroma server 管理）
│   ├── bm25_index.pkl          # BM25 索引磁盘缓存
│   ├── models/                 # 本地模型（BCE-Reranker-Base-V1）
│   ├── uploads/                # 用户上传的原始文件
│   └── md5.text                # 文件去重 MD5 记录
└── .env                        # 环境变量（API Key、数据库连接等）
```

## 并发架构（v2.7.0）

```mermaid
graph TB
    subgraph Clients["👤 客户端"]
        Alice["Alice 提问"]
        Bob["Bob 提问"]
        Charlie["Charlie 上传"]
    end

    Alice -->|"httpx SSE"| API_Layer
    Bob -->|"httpx SSE"| API_Layer
    Charlie -->|"httpx"| API_Layer

    subgraph FastAPI["⚡ FastAPI :8000 (uvicorn --workers N)"]
        API_Layer["Async 路由层<br/>━━━━━━━━━━━━<br/>/api/auth/* · /api/chat/* · /api/upload · /api/metrics/*"]

        subgraph Worker["Worker 进程 (×N)"]
            direction TB
            EL["🔄 async 事件循环<br/><i>主线程，永不阻塞</i>"]
            Pool["ThreadPoolExecutor<br/>8~12 线程并发"]
            RS["RagService 单例<br/>━━━━━━━━━━<br/>DashScopeEmbeddings<br/>BCE-Reranker-Base-V1<br/>BM25Okapi 索引<br/>ChatOpenAI 客户端"]

            EL -->|"await asyncio.to_thread()<br/>提交任务 → 协程挂起<br/>事件循环继续处理其他请求"| Pool
            Pool -->|"多线程并发调用<br/>各线程独立栈/局部变量"| RS
        end

        API_Layer --> EL
    end

    subgraph External["☁️ 外部服务"]
        ChromaDB[("ChromaDB Server<br/>:8001<br/>HTTP 并发读写")]
        MySQL[("MySQL 5.7+<br/>DBUtils 连接池<br/>min=2 · max=10")]
        DeepSeek["DeepSeek V4 Pro<br/>对话 + 摘要"]
        DashScope["DashScope API<br/>text-embedding-v4"]
    end

    RS -->|"HttpClient"| ChromaDB
    RS -->|"PooledDB"| MySQL
    RS -->|"OpenAI 兼容 API"| DeepSeek
    RS -->|"Embedding API"| DashScope
```

  多用户请求通过 httpx 打到 FastAPI。async 路由不阻塞事件循环，通过 `asyncio.to_thread` 将同步的 RagService 调用丢入线程池执行，同时主线程还可执行事件循环，接收其他的http请求。

  每个 worker 进程内 RagService 是全局单例（`threading.Lock` 双重检查），所有请求共享同一套 embedding / reranker / BM25 索引 / LLM 客户端。ChromaDB 作为独立进程运行（`:8001`），HTTP 接口天然支持并发读写。MySQL 通过 `DBUtils.PooledDB` 连接池复用连接。

  **这里提出一个问题，项目的RagService是全局单例，假如我fastapi只开一个worker进程，那如果有多 用户同时聊天调用了ragservice，会阻塞吗？**

答：不会阻塞。注意区别单例和线程池，多个用户同时发请求时，各自的 rag.invoke() 会在线程池的不同线程中并发执行。

  具体原理：

  1. 事件循环（主线程）不会卡住：await asyncio.to_thread(rag.invoke, ...) 只是把rag.invoke 这个同步任务提交ThreadPoolExecutor
        的队列里，然后当前协程挂起，事件循环立刻回头去处理其他请求（比如用户 B的请求）。
  2. 线程池允许多线程并发：Python 默认线程池大小为 min(32, cpu_count + 4)，通常8~12 个线程。每个 rag.invoke()
      跑在独立线程上，各有自己的调用栈和局部变量，互不阻塞。
    3. 单例 RagService 只是个容器对象，多线程同时调用它没有问题，关键在于它内部各组件是否线程安全：

  简单说：单 worker 进程下，事件循环负责快速调度，线程池负责并发执行同步的 RAG调用。只要并发用户数不超过线程池大小（默认
  8~12），所有用户都能同时得到服务；超过后排队等待，但事件循环本身始终不会阻塞。

| 组件 | 旧架构问题 | v2.7.0 方案 |
|------|-----------|------------|
| **请求处理** | Streamlit 单进程，阻塞式 | FastAPI async 路由，`asyncio.to_thread` 线程池 |
| **RagService** | 每用户创建实例，内存爆炸 | 全局单例，每 worker 进程仅一份 |
| **ChromaDB** | 嵌入式 SQLite，并发写 `database is locked` | **Client/Server 模式，独立进程，主服务线程池每个线程会发起独立 HTTP 请求** |
| **BM25 索引** | 多实例同时写 pickle 文件，竞态损坏 | `threading.Lock` 保护重建路径 |
| **MySQL** | 每次请求新建连接 | **`DBUtils.PooledDB` 连接池，每次 get_connection() 从池里拿独立连接** |
| **会话隔离** | `session_id = username`，同用户串消息 | `username_uuid` 独立会话 |



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
| session_id | VARCHAR(128) INDEX | 会话 ID（`username_uuid`） |
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

### metrics
| 字段 | 类型 | 说明 |
|------|------|------|
| id | BIGINT PK | 指标 ID |
| session_id | VARCHAR(128) INDEX | 会话 ID |
| total_latency_ms | INT | 端到端延迟（ms） |
| retrieval_latency_ms | INT | 检索耗时（ms） |
| llm_latency_ms | INT | LLM 调用耗时（ms） |
| tool_call_count | INT | 工具调用次数 |
| tool_details | JSON | 工具调用详情 |
| input_tokens | INT | 输入 token 数 |
| output_tokens | INT | 输出 token 数 |
| cache_read_tokens | INT | 缓存命中 token 数 |
| reasoning_tokens | INT | 推理 token 数 |

## API 文档

FastAPI 启动后访问 `http://localhost:8000/docs` 查看 Swagger UI。

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/auth/login` | 登录，返回 JWT token |
| POST | `/api/auth/register` | 注册 |
| POST | `/api/chat/send` | 问答（SSE 流式返回） |
| GET | `/api/chat/history?session_id=xx` | 获取会话历史 |
| DELETE | `/api/chat/clear` | 清空会话 |
| POST | `/api/chat/sessions` | 创建新会话 |
| POST | `/api/upload` | 上传文件到知识库 |
| GET | `/api/metrics/summary?days=7` | 性能指标汇总 |
| GET | `/api/metrics/recent?limit=50` | 最近查询明细 |

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
# Embedding
DASHSCOPE_API_KEY=sk-your-key-here

# 对话模型
DEEPSEEK_API_KEY=sk-your-key-here
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_CHAT_MODEL=deepseek-v4-pro

# MySQL
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=rag_user
MYSQL_PASSWORD=Rag@123456
MYSQL_DATABASE=rag_db

# ChromaDB Server
CHROMA_HOST=127.0.0.1
CHROMA_PORT=8001

# JWT
JWT_SECRET_KEY=your-secret-key-change-in-production
JWT_EXPIRE_HOURS=24
```

### 4. 启动

```bash
# 1. 启动 ChromaDB Server（独立进程）
chroma run --path data/chroma_db --port 8001 &

# 2. 启动 FastAPI
uvicorn api.main:app --host 0.0.0.0 --port 8000 --workers 4

# 3. 启动 Streamlit（纯前端 UI）
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

### Agent 推理流程（v2.5.0）

系统采用原生 Function Calling 替代文本模拟 ReAct，LLM 通过结构化 JSON 决定是否调用工具：

```mermaid
flowchart TD
    Start(["💬 用户提问"]) --> BuildMsg["构建消息列表<br/>SystemMessage + 历史消息 + HumanMessage"]
    BuildMsg --> BindTools["ChatOpenAI.bind_tools<br/>search_knowledge_base"]
    BindTools --> LLMCall["LLM 调用 (DeepSeek V4 Pro)"]

    LLMCall --> CheckTC{"AIMessage.tool_calls?"}

    CheckTC -- "为空 → 直接回复" --> Final["✉️ 返回 response.content<br/>最终回答"]
    CheckTC -- "非空" --> ExecTool["🔧 执行 search_knowledge_base"]

    ExecTool --> Search["BM25 + 向量混合检索<br/>→ RRF 融合<br/>→ CrossEncoder 重排序<br/>→ top-4 父块"]

    Search --> ToolMsg["追加 ToolMessage 到消息列表"]
    ToolMsg --> CheckIter{"iter &lt; MAX_ITERATIONS<br/>且未超时?"}
    CheckIter -- "是 → 继续" --> LLMCall
    CheckIter -- "否 → 超时兜底" --> Timeout["返回超时兜底回答"]

    Final --> SaveHistory["💾 保存对话到 MySQL<br/>chat_history 表"]
    Timeout --> SaveHistory

    SaveHistory --> CheckWindow{"消息数 &gt; WINDOW_SIZE?"}
    CheckWindow -- "是" --> UpdateSummary["📝 LLM 增量更新摘要<br/>写入 chat_summary 表"]
    CheckWindow -- "否" --> Done(["✅ 完成"])

    UpdateSummary --> Done

    style Start fill:#4CAF50,color:#fff
    style Final fill:#2196F3,color:#fff
    style Done fill:#4CAF50,color:#fff
    style Search fill:#FF9800,color:#fff
    style SaveHistory fill:#9C27B0,color:#fff
    style UpdateSummary fill:#FF5722,color:#fff
```

对于简单问候，LLM 自动跳过工具调用直接回复，避免不必要的检索开销。

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

```mermaid
flowchart TD
    Query(["🔍 用户查询 query"]) --> Tokenize["结巴分词<br/>jieba.lcut_for_search"]

    Tokenize --> VecPath["向量路<br/>ChromaDB similarity_search"]
    Tokenize --> BM25Path["BM25 路<br/>BM25Okapi.get_scores"]

    VecPath --> VecTop["top-8 子块<br/>(cosine 相似度)"]
    BM25Path --> BM25Filter["过滤 score > 0"]
    BM25Filter --> BM25Top["top-8 子块<br/>(BM25 得分)"]

    VecTop --> RRF["🔀 RRF 融合<br/>score = Σ 1/(K + rank)<br/>K = 60"]
    BM25Top --> RRF

    RRF --> Dedup["按 parent_id 去重"]
    Dedup --> Rerank["🎯 CrossEncoder 重排序<br/>BCE-Reranker-Base-V1"]
    Rerank --> TopK["取 top-4 父块"]
    TopK --> MySQL["MySQL 查完整父块内容<br/>document_parents 表"]
    MySQL --> Context(["📋 拼接为 context<br/>返回给 LLM"])

    style Query fill:#4CAF50,color:#fff
    style RRF fill:#FF9800,color:#fff
    style Rerank fill:#E91E63,color:#fff
    style Context fill:#2196F3,color:#fff
```

## 配置参考

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `DEEPSEEK_CHAT_MODEL` | `deepseek-v4-pro` | 对话模型 |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | DeepSeek API 地址 |
| `MAX_ITERATIONS` | `8` | Agent 最大工具调用轮数 |
| `MAX_EXECUTION_TIME` | `120` | Agent 最大执行时间（秒） |
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
| `CHROMA_HOST` | `127.0.0.1` | ChromaDB Server 地址 |
| `CHROMA_PORT` | `8001` | ChromaDB Server 端口 |
| `MYSQL_POOL_MIN` | `2` | 连接池最小连接数 |
| `MYSQL_POOL_MAX` | `10` | 连接池最大连接数 |
| `JWT_EXPIRE_HOURS` | `24` | Token 过期时间 |

