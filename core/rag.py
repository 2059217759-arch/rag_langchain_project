from langchain_community.embeddings import DashScopeEmbeddings
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_community.chat_models.tongyi import ChatTongyi
from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnableLambda, RunnableParallel
from langchain_core.runnables.config import RunnableConfig
from langchain_core.runnables.history import RunnableWithMessageHistory
from operator import itemgetter

from core import config
from core.database import get_connection, get_parents_by_ids
from core.vector_store import VectorStoreService
from storage.chat_history import MySQLChatMessageHistory


class RagService:
    def __init__(self):
        self.vector_service = VectorStoreService(
            embedding=DashScopeEmbeddings(model="text-embedding-v4")
        )

        self.prompt_template = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你是一个智能对话助手，以我提供的已知资料为主，"
                    "简洁和专业的回答用户的问题。参考资料：{context}。"
                    "{summary}",
                ),
                MessagesPlaceholder(variable_name="history"),
                ("human", "{question}"),
            ]
        )
        self.chat_model = ChatTongyi(model=config.CHAT_MODEL_NAME)
        self.summarizer_model = ChatTongyi(model="qwen-max")

        def _fetch_summary(input_dict: dict, config: RunnableConfig) -> str:
            session_id = config["configurable"]["session_id"]
            summary = MySQLChatMessageHistory.get_summary(session_id)
            if summary:
                return f"\n\n早前对话摘要：\n{summary}"
            return ""

        base_chain = (
            RunnableParallel(
                {
                    "question": itemgetter("question"),
                    "context": RunnableLambda(self._retrieve_and_format),
                    "history": itemgetter("history"),
                    "summary": RunnableLambda(_fetch_summary),
                }
            )
            | self.prompt_template
            | self.chat_model
            | StrOutputParser()
        )

        def get_history(session_id: str):
            return MySQLChatMessageHistory(session_id=session_id)

        self.chain = RunnableWithMessageHistory(
            base_chain,
            get_session_history=get_history,
            input_messages_key="question",
            history_messages_key="history",
        )

    def _retrieve_and_format(self, input_dict: dict) -> str:
        """检索 + 重排序 + 拼接 context。"""
        question = input_dict["question"]
        docs = self.vector_service.hybrid_search(question)
        if not docs:
            return "无相关参考资料"

        # 按 parent_id 去重，保留首次出现（RRF 分数最高）
        seen = set()
        parent_ids = []
        for doc in docs:
            pid = doc.metadata.get("parent_id")
            if pid and pid not in seen:
                seen.add(pid)
                parent_ids.append(pid)

        parent_map = get_parents_by_ids(parent_ids)

        # Rerank：构造文档列表，用 CrossEncoder 重新打分
        if len(parent_ids) > 1:
            docs_for_rerank = []
            valid_pids = []
            for pid in parent_ids:
                p = parent_map.get(pid)
                if not p:
                    continue
                # 用 title + content 前 2000 字符作为输入，控制 token 量
                text = f"{p.get('parent_title', '')}\n{p.get('parent_content', '')[:2000]}"
                docs_for_rerank.append(text)
                valid_pids.append(pid)

            if docs_for_rerank:
                scores = self.vector_service.rerank(question, docs_for_rerank)
                ranked = sorted(zip(valid_pids, scores), key=lambda x: x[1], reverse=True)
                parent_ids = [pid for pid, _ in ranked[:config.TOP_K_PARENTS]]
        else:
            parent_ids = parent_ids[:config.TOP_K_PARENTS]

        # 按 rerank 顺序拼接
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

        return "\n\n---\n\n".join(formatted) if formatted else "无相关参考资料"

    def invoke(self, question: str, session_id: str) -> str:
        """执行一次问答，自动管理滑动窗口和摘要。"""
        res = self.chain.invoke(
            {"question": question},
            config={"configurable": {"session_id": session_id}},
        )
        self._maybe_update_summary(session_id)
        return res
    # 增量摘要
    def _maybe_update_summary(self, session_id: str) -> None:
        try:
            total = MySQLChatMessageHistory.count_messages(session_id)
            if total <= config.WINDOW_SIZE:
                return

            # 找到刚滑出窗口的最后一条消息 ID
            overflow_count = total - config.WINDOW_SIZE
            conn = get_connection()
            try:
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
                conn.close()

            # 查当前已摘要到的位置
            conn = get_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT last_summarized_msg_id FROM chat_summary WHERE session_id = %s",
                        (session_id,),
                    )
                    row = cur.fetchone()
                last_summarized = row["last_summarized_msg_id"] if row else 0
            finally:
                conn.close()

            # 取新溢出消息，在两个端之间
            new_msgs = MySQLChatMessageHistory.get_messages_in_range(
                session_id, last_summarized, last_overflow_id
            )
            if not new_msgs:
                return

            # 格式化为文本
            lines = []
            for msg in new_msgs:
                role = "用户" if msg.type == "human" else "助手"
                lines.append(f"{role}：{msg.content}")
            new_text = "\n".join(lines)  # 这里的new_text长度是个增量

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
            pass  # 摘要失败不影响主流程
