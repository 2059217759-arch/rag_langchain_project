# Changelog

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
