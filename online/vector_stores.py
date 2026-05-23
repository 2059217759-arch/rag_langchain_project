from langchain_chroma import Chroma
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
import config_data as config
os.environ['DASHSCOPE_API_KEY'] = 'sk-2d28f3d1dd5d49958419ff09f101554b'

class VectorStoreService(object):
    def __init__(self,embedding): # embedding: 传入的嵌入模型
        self.embedding = embedding
        self.vector_store = Chroma(
            collection_name=config.colloction_name,
            persist_directory=config.persist_directory,
            embedding_function=embedding
        )

    # 获取向量检索器,as_retriever()是langchain中向量数据库对象的方法
    # 它返回一个向量检索器对象，标准化的文档列表，langchain里面的检索器实际上
    # 是一种混合检索器，融合了多种检索算法
    def get_retriever(self):
        return self.vector_store.as_retriever(
            search_type="similarity",
            search_kwargs={"k": 2}  # k表示返回的向量个数，返回2个相关文档
        )

if __name__ == '__main__':
    from langchain_community.embeddings import DashScopeEmbeddings
    model = DashScopeEmbeddings(model="text-embedding-v4")
    vector_store = VectorStoreService(model)
    retriever = vector_store.get_retriever()

    res=retriever.invoke("给我介绍一下斗破苍穹修炼体系")
    print(res)