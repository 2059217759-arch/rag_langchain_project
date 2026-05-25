# Changelog

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
