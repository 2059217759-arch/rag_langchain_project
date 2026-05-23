from vector_stores import VectorStoreService
from langchain_community.embeddings import DashScopeEmbeddings
from langchain_core.prompts import ChatPromptTemplate,MessagesPlaceholder
from langchain_community.chat_models.tongyi import ChatTongyi
import config_data as config
from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
# 使用 RunnableWithMessageHistory 包装后，无需修改底层 Prompt 
# 或 Chain 的逻辑，即可赋予其记忆能力。会返回增强链 
from langchain_core.runnables.history import RunnableWithMessageHistory
from file_history_store import FileChatMessageHistory
from operator import itemgetter # 获取字典的键对应的值

class RagService(object):

    def __init__(self):
        self.vector_service = VectorStoreService(
            embedding=DashScopeEmbeddings(model="text-embedding-v4"))
        
        self.prompt_template = ChatPromptTemplate.from_messages(
            [
                ("system", "你是一个智能对话助手，以我提供的已知资料为主，"
                 "简洁和专业的回答用户的问题。参考资料：{context}。"),
                MessagesPlaceholder(variable_name="history"),
                ("human", "{question}"),
            ])
        self.chat_model = ChatTongyi(model=config.chat_model_name)
        # 但是不代表他是字符串，只有调用对象的invoke方法时，才会生成字符串
        # self.chain = self.get_chain() 初始化时暂时不创建链
    def get_chain(self):
        # 获取链
        # 调用 retriever，获取相关文档
        retriever = self.vector_service.get_retriever()

        # 这个函数将 Document 对象列表转换成字符串，并返回
        def format_docs(docs: list[Document]) -> str:
            if not docs:
               return "无相关参考资料"
            # 使用 join 替代循环 +=，大幅提升内存效率

            formatted_list = [
              f"文档片段：{doc.page_content}\n文档元数据：{doc.metadata}" 
              for doc in docs
            ]
            return "\n\n".join(formatted_list) # join会合并字串
        
        base_chain = (
            # StrOutputParser()：这是流水线的最后一环。它的作用非常单纯，
            # 就是从大模型返回的复杂 AIMessage 对象中，精准地提取出核心的
            # 回答文本（即 .content 属性），并将其转换为标准的 Python str 字符串。
            {
                "question":itemgetter("question"),
                "context":itemgetter("question")|retriever| format_docs,
                "history":itemgetter("history")
            } | self.prompt_template | self.chat_model | StrOutputParser()
         )
        
        def get_file_history(session_id: str):
            return FileChatMessageHistory(session_id=session_id, storage_path="./chat_history")


        # 增强链
        conversation_chain = RunnableWithMessageHistory(
            base_chain,
            get_session_history=get_file_history, # 调用 get_history 函数获取历史记录
            input_messages_key="question", # 告诉它哪个字段是新问题
            history_messages_key="history",
        )

        return conversation_chain
        
if __name__ == "__main__":
    service = RagService()
    
    # 第一次提问
    res1 = service.get_chain().invoke(
        {"question": "斗破苍穹的修炼体系是什么？"},
        config={"configurable": {"session_id": "user_001"}}
    )
    print("回答1:", res1)
    
    # 第二次提问（依赖历史）
    res2 = service.get_chain().invoke(
        {"question": "上一个问题是什么"},
        config={"configurable": {"session_id": "user_001"}}
    )
    print("回答2:", res2)