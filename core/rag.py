from langchain_community.embeddings import DashScopeEmbeddings
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_community.chat_models.tongyi import ChatTongyi
from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables.history import RunnableWithMessageHistory
from operator import itemgetter

from core import config
from core.vector_store import VectorStoreService
from storage.chat_history import FileChatMessageHistory


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
                    "简洁和专业的回答用户的问题。参考资料：{context}。",
                ),
                MessagesPlaceholder(variable_name="history"),
                ("human", "{question}"),
            ]
        )
        self.chat_model = ChatTongyi(model=config.CHAT_MODEL_NAME)

        retriever = self.vector_service.get_retriever()

        def format_docs(docs: list[Document]) -> str:
            if not docs:
                return "无相关参考资料"
            formatted_list = [
                f"文档片段：{doc.page_content}\n文档元数据：{doc.metadata}"
                for doc in docs
            ]
            return "\n\n".join(formatted_list)

        base_chain = (
            {
                "question": itemgetter("question"),
                "context": itemgetter("question") | retriever | format_docs,
                "history": itemgetter("history"),
            }
            | self.prompt_template
            | self.chat_model
            | StrOutputParser()
        )

        def get_file_history(session_id: str):
            return FileChatMessageHistory(
                session_id=session_id,
                storage_path=config.DATA_DIR + "/chat_history",
            )

        self.chain = RunnableWithMessageHistory(
            base_chain,
            get_session_history=get_file_history,
            input_messages_key="question",
            history_messages_key="history",
        )

    def get_chain(self):
        return self.chain
