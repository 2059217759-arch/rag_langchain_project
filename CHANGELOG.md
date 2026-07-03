# Changelog

## [v2.8.0] — 2026-07-03

### 移除

- **对话摘要机制**：删除 `RagService._maybe_update_summary()` 及 `chat_summary` 表。DeepSeek V4 Pro 支持 128K context，项目典型对话场景（15 轮以内）不需要摘要压缩，直接扩大窗口更简单可靠
- **摘要模型实例**：`RagService` 不再初始化独立的 `summarizer_model`，每次对话减少一次 LLM 调用

### 变更

- **滑动窗口扩大**：`WINDOW_SIZE` 从 10 扩至 30（约 15 轮对话），上下文信息保真度更高
- **提前持久化用户消息**：`RagService.invoke()` 在 Agent 循环启动前将 `HumanMessage` 写入 MySQL，防止 Agent 中途崩溃导致用户问题丢失
- **`storage/chat_history.py`**：移除 `get_summary()` / `save_summary()` / `get_messages_in_range()` 三个摘要相关静态方法；`clear()` 不再清理 `chat_summary` 表
- **`core/database.py`**：`_init_db()` 不再创建 `chat_summary` 表
- **`core/config.py`**：`WINDOW_SIZE` 默认值 10 → 30

### 修复

- **静默吞异常**：`_maybe_update_summary()` 中 `except: pass` 随方法一并删除，不再有隐晦的摘要失败
- **会话归属校验**：`GET /api/chat/history` 和 `DELETE /api/chat/clear` 增加 `session_id` 归属检查，防止用户越权访问他人会话（403 Forbidden）

### 新增

- **Redis 三层缓存**：新增 `core/cache.py`，在检索链路关键节点引入缓存，减少重复计算和外部 API 调用：
  - **Layer 1 — EmbeddingCache**（`rag:emb:{md5}`）：缓存 query → 768-dim 向量映射，TTL 24h，命中时跳过 DashScope API 调用
  - **Layer 2 — RerankerCache**（`rag:rerank:{md5}`）：缓存 (query, doc) → 相关性分数，TTL 1h，命中时跳过 CrossEncoder 推理
  - **Layer 3 — SearchResultCache**（`rag:search:v{ver}:{md5}`）：缓存 query → 完整检索上下文，TTL 10min，命中时跳过全部检索链路
  - **文档版本管理**：`rag:doc_version` 原子递增，文档入库后自动使 SearchResultCache 失效
  - **优雅降级**：Redis 不可用时所有缓存自动降级为 no-op，不影响核心问答功能
- **缓存监控端点**：`GET /api/metrics/cache` 返回各层命中率（hits/misses/hit_rate）
- **`api/routes/metrics.py`**：新增 `/api/metrics/cache` 路由
- **`core/config.py`**：新增 Redis 连接配置 + 各层缓存开关/ TTL 配置（均支持环境变量覆盖）
- **`core/vector_store.py`**：`VectorStoreService` 集成 `EmbeddingCache` 和 `RerankerCache`
- **`core/rag.py`**：`RagService` 集成 `SearchResultCache`
- **`core/ingestion.py`**：`upload_by_str()` 成功后调用 `bump_doc_version()` 自动失效缓存
- **`requirements.txt`**：新增 `redis==5.2.1`

### 清理

- **`core/rag.py`**：移除 `summarizer_model`、`_maybe_update_summary()`、`get_connection` import；`SYSTEM_PROMPT` 去掉 `{summary}` 占位符
- **`core/database.py`**：移除 `chat_summary` 建表语句

---

## [v2.7.0] — 2026-06-10

### 新增

- **FastAPI 高并发后端**：`api/` 模块，用 FastAPI 替代 Streamlit 直接调用 core 服务，async 路由 + `asyncio.to_thread` 线程池执行同步 RAG 逻辑，SSE 流式返回问答结果
- **多用户并发支持**：ChromaDB 从嵌入式 SQLite 切换为 Client/Server 模式（`chromadb.HttpClient`），MySQL 引入 `DBUtils.PooledDB` 连接池，RagService / IngestionService 全局单例化
- **会话管理**：新增 `POST /api/chat/sessions` 创建独立会话（`username_uuid`），同一用户支持多端多会话，互不干扰
- **JWT 鉴权中间件**：`api/deps.py`，`HTTPBearer` + `decode_token` 验证所有 `/api/chat/*` 和 `/api/upload` 请求

### 变更

- **`core/vector_store.py`**：ChromaDB 切为 `chromadb.HttpClient`，BM25 重建加 `threading.Lock` 双重检查保护
- **`core/database.py`**：`get_connection()` 从每次新建连接改为 `PooledDB` 连接池（min=2, max=10），池构造时指定 `database` 参数
- **`core/rag.py`**：新增 `get_rag_service()` 模块级单例（双重检查锁），所有请求共享同一套 embedding / reranker / LLM 客户端
- **`core/ingestion.py`**：新增 `get_ingestion_service()` 单例，切 `chromadb.HttpClient`
- **`core/config.py`**：新增 `CHROMA_HOST` / `CHROMA_PORT` / `API_BASE_URL` / `MYSQL_POOL_MIN` / `MYSQL_POOL_MAX`
- **`app/pages/*`**：四个 Streamlit 页面改为通过 `httpx` 调用 FastAPI HTTP 接口，Streamlit 退化为纯 UI 层
- **`requirements.txt`**：新增 `fastapi` / `DBUtils`

### 架构

```
用户浏览器 → Streamlit (UI) → httpx → FastAPI (async)
                                          │
                                   asyncio.to_thread
                                          │
                                   RagService (单例/进程)
                                   ├── ChromaDB Server (独立进程)
                                   ├── MySQL 连接池
                                   └── DeepSeek API
```

---


### 新增

- **性能监控体系**：`core/metrics.py` 结构化记录每次查询的延迟、token 消耗、工具调用详情到 MySQL `metrics` 表
- **Streamlit 性能仪表盘**：`app/pages/metrics_page.py`，KPI 卡片（总查询数、平均/P50/P95/P99 延迟、缓存命中率）+ 延迟分布直方图 + Token 消耗趋势折线图 + 工具调用分布图 + 最近查询明细表

### 变更

- **`core/rag.py`**：检索和 LLM 调用分开计时（`retrieval_ms` / `llm_ms`），从 `response.usage_metadata` 提取 token 用量（含 `cache_read`、`reasoning`），每次 `invoke()` 末尾写入 metrics
- **`core/database.py`**：新增 `metrics` 表（`total_latency_ms` / `retrieval_latency_ms` / `llm_latency_ms` / `tool_call_count` / `tool_details` / `input_tokens` / `output_tokens` / `cache_read_tokens` / `reasoning_tokens`）
- **`app/pages/chat_page.py`**：sidebar 新增「📊 性能监控」入口
- **移除 `agent.log`**：功能已被 `metrics` 表完全覆盖，仅保留 `agent_debug.log` 用于排查工具调用问题

---

## [v2.5.0] — 2026-06-01

### 变更

- **原生 Function Calling 替代文本模拟 ReAct**：移除 `langchain_classic` 的 `create_react_agent` + `AgentExecutor`，改用 `ChatOpenAI.bind_tools()` + 自写 Agent 循环，LLM 通过结构化 JSON (`tool_calls`) 决策工具调用，消除正则解析脆弱性
- **`core/rag.py` 重构**：
  - 移除 `PromptTemplate`（ReAct 格式指令）、`StructuredTool`、`_format_chat_history()`
  - 新增 OpenAI 兼容 tool schema 定义（`_tool_schemas`），直接传 `bind_tools()`
  - 历史消息改用原生 `HumanMessage`/`AIMessage` 对象列表，不再拼接为文本
  - `invoke()` 自写 while 循环替代 `AgentExecutor`：检查 `response.tool_calls` → 执行工具 → 追加 `ToolMessage` → 下一轮
  - 新增 `data/agent_debug.log` 调试日志，记录每轮 LLM 响应的 `finish_reason`、`tool_calls` 结构
- **`core/config.py`**：新增 `MAX_ITERATIONS = 8` / `MAX_EXECUTION_TIME = 120`（原 `AgentExecutor` 构造参数硬编码值提取为常量）
- **依赖清理**：`langchain_classic` 包不再需要

### 修复

- 工具调用决策由模型训练内化，不再依赖 prompt 格式指令，告别 `OutputParserException` 重试

---

## [v2.4.0] — 2026-05-31

### 新增

- **历史会话记录**：侧边栏新增"最近 10 轮对话"，`MySQLChatMessageHistory.get_recent_rounds()` 从 MySQL 查询历史问答对，expander 折叠展示，跨会话持久化
- **记忆框架架构文档**：README 新增记忆框架架构说明，阐述为什么用 `BaseChatMessageHistory` + `RunnableWithMessageHistory`（LCEL）而非旧版 `Conversation*Memory` 类

### 变更

- **`core/rag.py` — Agent 稳定性**
  - ReAct prompt 精简，明确"每行一个标记，不要混在同一行"，减少格式解析失败
  - `max_iterations` 5 → 8，新增 `max_execution_time=120` 秒硬超时
  - `invoke()` 新增降级处理：超出迭代/时间限制时，尝试返回已检索的部分信息而非裸露错误
- **`storage/chat_history.py`**：新增 `get_recent_rounds()` 静态方法，返回最近 N 轮 user+assistant 配对消息

### 修复

- **前端可读性**：移除 chat_page / upload_page / login_page 的自定义颜色和背景覆盖，修复暗色调文字被遮挡问题，统一使用 Streamlit 浅色主题
- **Agent `tool_names` 缺失**：修复 prompt 精简后遗漏 `{tool_names}` 占位符导致 `ValueError: Prompt missing required variables`

---

## [v2.3.0] — 2026-05-31

### 新增

- **Agent 范式（ReAct）**：从纯链式结构升级为 Agent，`create_react_agent` + `AgentExecutor` 替代 `RunnableWithMessageHistory`，LLM 自主决策是否检索、检索什么、检索几次，显式 Thought → Action → Observation 推理链
- **DeepSeek V4 Pro 模型**：对话模型从通义千问 qwen-max 切换为 DeepSeek V4 Pro（OpenAI 兼容 API），`ChatOpenAI` 替代 `ChatTongyi`
- **检索 Tool 化**：`_retrieve_and_format` 重构为 `_search_knowledge_base`，通过 `StructuredTool` 包装，由 Agent 按需调用
- **Agent 诊断日志**：`data/agent.log` 记录每次调用的耗时和工具调用次数

### 变更

- **`core/rag.py`**：整体重构，移除 `RunnableParallel` / `RunnableWithMessageHistory` / `ChatTongyi`，引入 `PromptTemplate`（ReAct 格式）+ `create_react_agent` + `AgentExecutor` + `ChatOpenAI`，历史管理改为手动 load/save
- **`core/config.py`**：新增 `DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL` / `DEEPSEEK_CHAT_MODEL`
- **`.env`**：新增 DeepSeek 相关环境变量
- **`requirements.txt`**：新增 `langchain-openai`

### 修复

- 简单问候不再浪费检索调用（Agent 跳过 Action 直接 Final Answer）

---

## [v2.2.0] — 2026-05-29

### 新增

- **BM25 + RRF 混合检索**：在向量检索之外增加 BM25 稀疏检索（jieba 分词），双路结果通过 RRF（k=60）融合排序，互补语义匹配和关键词匹配的优势
- **本地 CrossEncoder 重排序**：部署 BCE-Reranker-Base-V1（278M 参数）对候选父块二次精排，懒加载模式避免阻塞 Streamlit 启动
- **BM25 磁盘缓存**：BM25 索引通过 pickle 持久化到 `data/bm25_index.pkl`，文档数量未变时直接复用，避免重复构建

### 变更

- **`core/vector_store.py`**：新增 `_build_bm25()` / `hybrid_search()` / `rerank()` 方法，`VectorStoreService` 从纯向量检索升级为混合检索引擎
- **`core/rag.py`**：`_retrieve_and_format()` 集成 reranker，候选父块按 CrossEncoder 分数重新排序后取 top-k
- **`core/config.py`**：新增 `TOP_K_BM25` / `RRF_K` / `RERANKER_MODEL` / `BM25_INDEX_PATH`
- **`requirements.txt`**：新增 `rank-bm25` / `jieba` / `sentence-transformers` / `torch`

### 修复

- **聊天历史顺序错误**：`MySQLChatMessageHistory.messages` 的 `ORDER BY id DESC` 后漏掉 `.reverse()`，导致历史消息逆序传给 LLM，模型混淆对话时序，反复出现"您的上个问题是…"等串话现象

---

## [v2.1.0] — 2026-05-27

### 新增

- **父子块分层策略**：父块按 Markdown 标题 → 段落边界 → 句子截断三级切分，子块在父块内按句子切分（300 字符），用小粒度做精准检索、大粒度给 LLM 提供完整上下文
- **`document_parents` 表**：父块存入 MySQL（`MEDIUMTEXT`），子块存入 ChromaDB，双层存储各司其职
- **Markdown 文件上传**：上传页面支持 `.md` 文件，Markdown 标题自动识别为父块边界
- **检索链重构**：top-8 子块 → `parent_id` 去重 → top-4 父块 → MySQL 查完整内容 → 拼入 prompt

### 变更

- **`core/ingestion.py`**：`RecursiveCharacterTextSplitter` 替换为自定义 `ParentChildSplitter`
- **`core/rag.py`**：`format_docs` 改为 parent 去重 + MySQL 查询拼接逻辑
- **`core/database.py`**：新增 `insert_parents()` / `get_parents_by_ids()` 函数
- **`core/config.py`**：删除 `CHUNK_SIZE` / `CHUNK_OVERLAP` / `SEPARATORS` / `MAX_SPLIT_CHAR_NUMBER`，新增 `PARENT_MAX_SIZE` / `CHILD_CHUNK_SIZE` / `CHILD_CHUNK_OVERLAP` / `TOP_K_CHILDREN` / `TOP_K_PARENTS`
- **`core/vector_store.py`**：top-k 从 2 提升到 8
- **`app/pages/upload_page.py`**：文件类型从 `["txt"]` 扩展为 `["txt", "md"]`

### 注意

- 旧 ChromaDB 数据需清空重新摄入（collection 结构不兼容）

---

## [v2.0.0] — 2026-05-25

### 新增

- **滑动窗口上下文管理**：`MySQLChatMessageHistory.messages` 只返回最近 `WINDOW_SIZE`（默认 10）条消息，避免对话变长导致 prompt 超出 LLM 上下文窗口
- **对话摘要机制**：超出窗口的历史消息自动压缩为 300 字以内的摘要，增量更新，恒定 O(1) 成本，不影响主对话流程
- **`chat_summary` 表**：按 session 存储摘要文本和增量进度标记
- **`RagService.invoke()`**：统一入口，内部自动完成 chain 调用 + 摘要更新，UI 层零感知

### 变更

- **Prompt 模板重构**：system prompt 新增 `{summary}` 占位符，chain 改用 `RunnableParallel` 并行注入检索结果和摘要
- **对话历史存储**：从本地 JSON 文件迁移到 MySQL `chat_history` 表
- **配置**：新增 `WINDOW_SIZE = 10`

---

## [v1.0.0] — 2026-05-24

### 新增

- **用户系统**：注册/登录，JWT (HS256) 签发 + bcrypt 密码哈希
- **RAG 问答**：LangChain `RunnableWithMessageHistory` 全链路，DashScope text-embedding-v4 向量化，通义千问 qwen-max 生成，ChromaDB 持久化存储
- **文件上传**：文本文件上传 → `RecursiveCharacterTextSplitter` 分段 → 向量化入库，MD5 去重
- **对话记忆**：`BaseChatMessageHistory` 实现，本地 JSON 文件持久化
- **Streamlit UI**：登录页、文件上传页、智能助手页三页面
- **MySQL**：自动建库建表（`users`、`chat_history`），连接池 + 双重检查锁定
