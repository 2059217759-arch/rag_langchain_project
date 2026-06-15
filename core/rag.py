import json
import logging
import threading
import time

from langchain_community.embeddings import DashScopeEmbeddings
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI

from core import config
from core.database import get_connection, get_parents_by_ids
from core.metrics import save_metrics
from core.vector_store import VectorStoreService
from storage.chat_history import MySQLChatMessageHistory

# 导入message_to_dict 函数可以看看invoke转换的jsnon格式。
from langchain_core.messages import message_to_dict 

logger = logging.getLogger(__name__) # 创建日志记录器

SYSTEM_PROMPT = (
    "你是一个智能对话助手。{summary}\n\n"
    "当需要查找具体信息、数据或参考资料时，使用 search_knowledge_base 工具搜索内部知识库。\n"
    "不需要检索时（闲聊、问候等），直接回答用户问题。\n"
    "用中文回答。"
)


class RagService:
    def __init__(self):
        # 初始化各类模块
        self.vector_service = VectorStoreService(
            embedding=DashScopeEmbeddings(model="text-embedding-v4")
        )
        self.chat_model = ChatOpenAI(
            model=config.DEEPSEEK_CHAT_MODEL,
            api_key=config.DEEPSEEK_API_KEY,
            base_url=config.DEEPSEEK_BASE_URL,
        )
        self.summarizer_model = ChatOpenAI(
            model=config.DEEPSEEK_CHAT_MODEL,
            api_key=config.DEEPSEEK_API_KEY,
            base_url=config.DEEPSEEK_BASE_URL,
        )

        # 定义了json格式的工具调用规范，供 Agent 使用。未来可扩展更多工具。
        # Agent 会根据对话上下文自主决定是否调用工具。每次调用后，Agent 会等待工具结果返回，
        # 再继续下一轮对话或工具调用。
        self._tool_schemas = [
            {
                "type": "function",
                "function": {
                    "name": "search_knowledge_base",
                    "description": (
                        "搜索内部知识库，获取与查询相关的文档资料。"
                        "输入应为简洁的搜索查询语句，系统将返回最相关的文档内容。"
                        "当需要查找具体信息、数据或参考资料时使用此工具。"
                    ),
                    # 调用工具时使用的参数
                    "parameters": {
                        "type": "object", # 参数类型为object
                        "properties": { # 定义参数属性
                            "query": { # 查询参数
                                "type": "string",
                                "description": "搜索查询语句",
                            }
                        },
                        "required": ["query"], # 必须提供查询参数
                    },
                },
            }
        ]

    def _search_knowledge_base(self, query: str) -> str:
        """检索 + 重排序 + 拼接 context，返回给 Agent 使用。"""
        docs = self.vector_service.hybrid_search(query)
        if not docs:
            return "未找到相关参考资料"

        seen = set()
        parent_ids = []
        for doc in docs:
            pid = doc.metadata.get("parent_id")
            if pid and pid not in seen:
                seen.add(pid)
                parent_ids.append(pid)

        parent_map = get_parents_by_ids(parent_ids)

        if len(parent_ids) > 1:
            docs_for_rerank = []
            valid_pids = []
            for pid in parent_ids:
                p = parent_map.get(pid)
                if not p:
                    continue
                text = f"{p.get('parent_title', '')}\n{p.get('parent_content', '')[:2000]}"
                docs_for_rerank.append(text)
                valid_pids.append(pid)

            if docs_for_rerank:
                scores = self.vector_service.rerank(query, docs_for_rerank)
                ranked = sorted(zip(valid_pids, scores), key=lambda x: x[1], reverse=True)
                parent_ids = [pid for pid, _ in ranked[:config.TOP_K_PARENTS]]
        else:
            parent_ids = parent_ids[:config.TOP_K_PARENTS]

        formatted = []
        for pid in parent_ids:
            p = parent_map.get(pid)
            if not p:
                continue
            title = p.get("parent_title", "")
            content = p.get("parent_content", "")
            if title:
                formatted.append(f"{title}\n{content}")
            else:
                formatted.append(content)
        return "\n\n---\n\n".join(formatted) if formatted else "未找到相关参考资料"

    def invoke(self, question: str, session_id: str) -> str:
        """执行一次问答。Agent 自主决定是否检索知识库。"""
        t0 = time.time() # 记录开始时间

        retrieval_ms_total = 0
        llm_ms_total = 0
        total_input_tokens = 0
        total_output_tokens = 0
        cache_read_tokens = 0
        reasoning_tokens = 0

        history = MySQLChatMessageHistory(session_id=session_id)
        chat_messages = history.messages 

        summary = MySQLChatMessageHistory.get_summary(session_id)
        summary_text = f"早前对话摘要：\n{summary}" if summary else ""

        # llm遵循严格的时间序列
        # SystemMessage是系统指令,即对话背景
        messages = [
            SystemMessage(content=SYSTEM_PROMPT.format(summary=summary_text)),
        ]
        messages.extend(chat_messages)
        messages.append(HumanMessage(content=question))

        # .bind_tools(...): 这是 LangChain 的一个方法。它不会立即调用模型，
        # 而是返回一个新的、配置好的模型对象（llm_with_tools）。就是加入了工具调用能力的模型。
        # 真正调用模型是在后面 response = llm_with_tools.invoke(messages) 这一行。
        llm_with_tools = self.chat_model.bind_tools(self._tool_schemas)

        tool_call_count = 0
        tool_logs = [] # 工具调用日志
        final_output = None
        debug_lines = [] # 调试日志

        for i in range(config.MAX_ITERATIONS):  # 最大迭代次数
            if time.time() - t0 > config.MAX_EXECUTION_TIME:  # 超时
                debug_lines.append(f"iter{i}: TIMEOUT at {time.time()-t0:.1f}s")
                break

            # invoke(messages):这是 LangChain 的标准调用方法。它将 Python 的
            # messages 列表序列化为 JSON，通过 API 发送给 DeepSeek 服务器。
            # 返回的 response 是一个包含模型输出的 LangChain 的 BaseMessage 对象。
            # 实际我们在调试文件中可以看到原始的api返回的json格式，langchain做了封装
            llm_t0 = time.time()
            response = llm_with_tools.invoke(messages)
            llm_ms_total += int((time.time() - llm_t0) * 1000)
            messages.append(response)

            # 从 response 中提取 token 用量
            usage = response.usage_metadata
            if usage:
                total_input_tokens += usage.get("input_tokens", 0)
                total_output_tokens += usage.get("output_tokens", 0)
                cache_read_tokens += usage.get("input_token_details", {}).get("cache_read", 0)
                reasoning_tokens += usage.get("output_token_details", {}).get("reasoning", 0)

            content_preview = (response.content or "")[:100] # 模型输出的预览
            raw_tc = response.tool_calls # 模型输出的 tool_calls
            finish = response.response_metadata.get("finish_reason", "?") # 模型结束的原因

            # 调试日志：记录每次迭代的模型响应详情（排查工具调用问题）
            with open("/home/zhuohao/rag_project/data/agent_debug.log", "a") as f:
                f.write(f"--- iter{i} session={session_id}, question={question[:80]} ---\n")
                f.write(f"  finish={finish}, content_preview={repr(content_preview)}\n")
                f.write(f"  tool_calls={raw_tc}\n")
                f.write(f"  additional_kwargs={json.dumps(response.additional_kwargs, ensure_ascii=False, default=str)}\n")
                response_json = json.dumps(
                    message_to_dict(response), ensure_ascii=False, indent=2, default=str
                )
                f.write(f"  response_dict:\n")
                for line in response_json.split("\n"):
                    f.write(f"    {line}\n")
                f.write("\n")

            debug_lines.append(
                f"iter{i}: finish={finish}, content={repr(content_preview)}, "
                f"tool_calls={raw_tc}, additional_kwargs={json.dumps(response.additional_kwargs, ensure_ascii=False, default=str)}"
            )

            # 核心逻辑，根据模型返回的 response 判断是否有工具调用。执行不同的分支。
            if raw_tc:
                for tc in raw_tc:
                    tool_name = tc.get("name", "")
                    tool_args = tc.get("args", {})

                    # tool_args 可能是字符串（JSON格式），也可能已经是解析后的字典。需要兼容处理。
                    if isinstance(tool_args, str):
                        tool_args = json.loads(tool_args)

                    tc_id = tc.get("id", "")

                    if tool_name == "search_knowledge_base":
                        query = tool_args.get("query", "")
                        ret_t0 = time.time()
                        result = self._search_knowledge_base(query)  # 调用检索函数
                        retrieval_ms_total += int((time.time() - ret_t0) * 1000)
                        tool_logs.append(f"tool={tool_name}, input={query[:80]}")
                    else:
                        result = f"未知工具: {tool_name}"
                        tool_logs.append(f"tool={tool_name}(unknown)")

                    tool_call_count += 1
                    debug_lines.append(f"iter{i}: executed {tool_name}, result_len={len(result)}")
                    
                    # 将工具结果result作为 ToolMessage 添加到消息列表中，供下一轮模型调用使用。
                    messages.append(ToolMessage(content=result, tool_call_id=tc_id))
            else:
                final_output = response.content or ""
                break

        t1 = time.time()

        if final_output is None:
            for msg in reversed(messages):
                if isinstance(msg, ToolMessage) and "未找到" not in msg.content:
                    final_output = (
                        f"抱歉，处理超时。以下是我检索到的部分信息：\n\n{msg.content[:500]}"
                    )
                    break
            if final_output is None:
                final_output = "抱歉，处理请求时超时了，请换个方式提问或稍后重试。"

        # 调试日志：写入每次 invoke 的汇总信息
        with open("/home/zhuohao/rag_project/data/agent_debug.log", "a") as f:
            f.write(f"--- invoke summary session={session_id} ---\n")
            f.write(f"  question={question[:80]}\n")
            f.write(f"  elapsed={t1 - t0:.1f}s, tool_calls={tool_call_count}\n")
            for dl in debug_lines:
                f.write(f"  {dl}\n")
            f.write(f"  final_output={repr(final_output[:200] if final_output else None)}\n\n")

        save_metrics(
            session_id=session_id,
            question=question,
            total_ms=int((t1 - t0) * 1000),
            retrieval_ms=retrieval_ms_total,
            llm_ms=llm_ms_total,
            tool_call_count=tool_call_count,
            tool_details=tool_logs,
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
            cache_read_tokens=cache_read_tokens,
            reasoning_tokens=reasoning_tokens,
        )

        history.add_messages(
            [HumanMessage(content=question), AIMessage(content=final_output)]
        )

        self._maybe_update_summary(session_id)
        return final_output

    def _maybe_update_summary(self, session_id: str) -> None:
        try:
            total = MySQLChatMessageHistory.count_messages(session_id)
            if total <= config.WINDOW_SIZE:
                return

            overflow_count = total - config.WINDOW_SIZE
            conn = None
            try:
                conn = get_connection()
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id FROM chat_history WHERE session_id = %s "
                        "ORDER BY id LIMIT 1 OFFSET %s",
                        (session_id, overflow_count - 1),
                    )
                    row = cur.fetchone()
                if not row:
                    return
                last_overflow_id = row["id"]
            finally:
                if conn:
                    conn.close()

            conn = None
            try:
                conn = get_connection()
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT last_summarized_msg_id FROM chat_summary WHERE session_id = %s",
                        (session_id,),
                    )
                    row = cur.fetchone()
                last_summarized = row["last_summarized_msg_id"] if row else 0
            finally:
                if conn:
                    conn.close()

            new_msgs = MySQLChatMessageHistory.get_messages_in_range(
                session_id, last_summarized, last_overflow_id
            )
            if not new_msgs:
                return

            lines = []
            for msg in new_msgs:
                role = "用户" if msg.type == "human" else "助手"
                lines.append(f"{role}：{msg.content}")
            new_text = "\n".join(lines)

            existing_summary = MySQLChatMessageHistory.get_summary(session_id)

            summary_prompt = f"""你是一个对话摘要助手。请将以下对话历史总结为简洁的摘要，控制在300字以内。摘要应包含：
1. 用户讨论了哪些主题和问题
2. 关键的回答要点和重要信息
3. 有助于后续对话的上下文

现有摘要：
{existing_summary if existing_summary else "（无）"}

新的对话内容：
{new_text}

请生成更新后的综合摘要（保留旧摘要中的关键信息，并融入新对话内容，总字数不超过300字）："""

            new_summary = self.summarizer_model.invoke(summary_prompt).content
            MySQLChatMessageHistory.save_summary(session_id, new_summary, last_overflow_id)
        except Exception:
            pass


_rag_instance = None
_rag_lock = threading.Lock()


def get_rag_service() -> RagService:
    """获取 RagService 全局单例，线程安全。"""
    global _rag_instance
    if _rag_instance is None:
        with _rag_lock:
            if _rag_instance is None:
                _rag_instance = RagService()
    return _rag_instance
