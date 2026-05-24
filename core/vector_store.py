from langchain_chroma import Chroma

from core import config


class VectorStoreService:
    def __init__(self, embedding):
        self.embedding = embedding
        self.vector_store = Chroma(
            collection_name=config.COLLECTION_NAME,
            persist_directory=config.PERSIST_DIRECTORY,
            embedding_function=embedding,
        )

    def get_retriever(self):
        return self.vector_store.as_retriever(
            search_type="similarity",
            search_kwargs={"k": 2},
        )
