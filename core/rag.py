from langchain_community.embeddings import DashScopeEmbeddings
from langchain_core.prompts import PromptTemplate
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.tools import StructuredTool
from langchain_classic.agents import create_react_agent, AgentExecutor

from core import config
from core.database import get_connection, get_parents_by_ids
from core.vector_store import VectorStoreService
from storage.chat_history import MySQLChatMessageHistory


def _format_chat_history(messages: list) -> str:
    if not messages:
        return "（无）"
    lines = []
    for msg in messages:
        role = "用户" if msg.type == "human" else "助手"
        lines.append(f"{role}: {msg.content}")
    return "\n".join(lines)


class RagService:
    def __init__(self):
        self.vector_service = VectorStoreService(
            embedding=DashScopeEmbeddings(model="text-embedding-v4")
        )
        # 模型用于 Agent 的对话和决策，支持工具调用和复杂交互
        self.chat_model = ChatOpenAI(
            model=config.DEEPSEEK_CHAT_MODEL,
            api_key=config.DEEPSEEK_API_KEY,
            base_url=config.DEEPSEEK_BASE_URL,
        )
        # 总结超出滑动窗口的摘要
        self.summarizer_model = ChatOpenAI(
            model=config.DEEPSEEK_CHAT_MODEL,
            api_key=config.DEEPSEEK_API_KEY,
            base_url=config.DEEPSEEK_BASE_URL,
        )
        
        self._search_tool = StructuredTool.from_function(
            func=self._search_knowledge_base,
            name="search_knowledge_base",
            description=(
                "搜索内部知识库，获取与查询相关的文档资料。"
                "输入应为简洁的搜索查询语句，系统将返回最相关的文档内容。"
                "当需要查找具体信息、数据或参考资料时使用此工具。"
            ),
        )

        self._agent_prompt = PromptTemplate.from_template(
            "你是一个智能对话助手。{summary}\n\n"
            "你可以使用以下工具：\n"
            "{tools}\n\n"
            "请严格遵循以下 ReAct 格式：\n\n"
            "Question: 用户提出的问题\n"
            "Thought: 分析问题，判断是否需要使用工具，如果需要，想清楚搜索什么关键词\n"
            "Action: 工具名称，可选 [{tool_names}]\n"
            "Action Input: 传给工具的具体参数\n"
            "Observation: 工具返回的结果\n"
            "... (Thought/Action/Action Input/Observation 可重复多次，直到获取足够信息)\n"
            "Thought: 整合所有信息，我现在可以给出最终答案\n"
            "Final Answer: 最终回复\n\n"
            "注意：\n"
            "- 对于简单问候或闲聊，跳过 Action，直接给出 Final Answer\n"
            "- 检索不到资料时，在 Final Answer 中如实告知\n"
            "- Final Answer 用中文回答\n\n"
            "历史对话：\n"
            "{chat_history}\n\n"
            "Question: {input}\n"
            "{agent_scratchpad}"
        )

        agent = create_react_agent(
            self.chat_model, [self._search_tool], self._agent_prompt
        )
        # # 核心，负责协调LLM和工具的调用，执行Agent的决策流程 
        self._executor = AgentExecutor(
            agent=agent,
            tools=[self._search_tool],
            verbose=False,
            max_iterations=5,
            handle_parsing_errors=True, # 忽略解析错误
            return_intermediate_steps=True, # 返回中间步骤
        )

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
        import time

        history = MySQLChatMessageHistory(session_id=session_id)
        chat_history = _format_chat_history(history.messages)

        summary = MySQLChatMessageHistory.get_summary(session_id)
        summary_text = f"早前对话摘要：\n{summary}" if summary else ""

        t0 = time.time()
        result = self._executor.invoke(
            {
                "input": question,
                "chat_history": chat_history,
                "summary": summary_text,
            }
        )
        t1 = time.time()

        steps = result.get("intermediate_steps", [])
        log_line = f"[Agent] 耗时={t1-t0:.1f}s, tool调用={len(steps)}次, question={question[:50]}"
        for i, (action, _) in enumerate(steps):
            log_line += f" | step{i+1}: tool={action.tool}, input={str(action.tool_input)[:80]}"
        with open("/home/zhuohao/rag_project/data/agent.log", "a") as f:
            f.write(log_line + "\n")

        output = result["output"]

        history.add_messages(
            [HumanMessage(content=question), AIMessage(content=output)]
        )

        self._maybe_update_summary(session_id)
        return output

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
