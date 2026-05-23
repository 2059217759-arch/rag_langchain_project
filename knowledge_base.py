import os
import config_data as config
import hashlib # 导入hash
from langchain_chroma import Chroma

# dashscopeEmbeddings是这个类是 LangChain 框架与阿里云百炼（DashScope）
# 平台提供的文本嵌入（Embedding）模型之间的连接器
from langchain_community.embeddings import DashScopeEmbeddings

# 导入文本分割器，就是分割一次性输入不完的长文本
from langchain_text_splitters import RecursiveCharacterTextSplitter
from datetime import datetime

import os
os.environ['DASHSCOPE_API_KEY'] = 'sk-2d28f3d1dd5d49958419ff09f101554b'

# 检查传入的md5字符串是否已经传过了
def check_md5(md5_str: str):
    if not os.path.exists(config.md5_path):
     # 文件不存在，创建一个空文件叫md5.text
     open(config.md5_path, "w", encoding="utf-8").close()
     return  False
    else:
        for line in open(config.md5_path, "r", encoding="utf-8").readlines():
          line = line.strip()  # 去掉换行符、空格
          if line == md5_str:
             return True
        return False

# 保存md5
def save_md5(md5_str: str):
   with open(config.md5_path, "a", encoding="utf-8") as f:
     f.write(md5_str + "\n")

# 获取字符串的md5
def get_string_md5(input_str: str, encoding="utf-8"):
    # 将字符串转换成byte数组
    str_bytes = input_str.encode(encoding= encoding)

    # 创建md5对象
    md5_obj= hashlib.md5()   # 创建md5对象
    md5_obj.update(str_bytes)  # 更新md5对象, 传入byte数组
    md5_hex= md5_obj.hexdigest()  # 获取md5的16进制字符串
    return md5_hex

# 知识库类，核心逻辑
class KnowledgeBaseService(object):
    def __init__(self):  # self表示当前对象自身
        #  创建保存向量的目录,存在则不创建
        os.makedirs(config.persist_directory, exist_ok=True)
        # 向量存储的实例对象
        self.chroma=Chroma(  # chroma是一个向量数据库，用于存储向量
             collection_name=config.colloction_name,
             embedding_function=DashScopeEmbeddings(
               model="text-embedding-v4",
             ),
             persist_directory=config.persist_directory  # 向量数据库的保存目录
        )
        # 文本分割器实例
        self.spliter=RecursiveCharacterTextSplitter(
            chunk_size=config.chunk_size,  # 块大小
            chunk_overlap=config.chunk_overlap,  # 连续文本段落之间的重叠长度
            separators=config.separators,  # 段落分隔符
            length_function=len,  # python自带的字符串长度函数
        )

    def upload_by_str(self,data,file_name):
        # 将传入的字符串向量化，存入向量数据库
        # 先获取字符的md5
        md5_hex=get_string_md5(data)

        if check_md5(md5_hex):
           return "[跳过]内容已存在知识库"
        if len(data) < 10:
           return "[失败]内容过短"

        if len(data) > config.max_split_char_number:
            # knowledge_chunks是一个列表，列表中的元素是分好块的字符串
           Knowledge_chunks: list[str] = self.spliter.split_text(data)
        else:
           Knowledge_chunks=[data]

        metadata = {
            "sourse": file_name,
            "create_time":datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "operator": "zhuohao",
        }
        self.chroma.add_texts(  # add_texts是chroma库的核心方法，用于将文本添加到向量数据库中
            Knowledge_chunks,
            # 元数据，是一个列表，列表中的元素是一个字典，字典的键值对是元数据
            metadata=[metadata for _ in Knowledge_chunks]
        )
        save_md5(md5_hex)
        return "[成功]已成功载入向量库"

# 当前模块是主模块时，执行以下代码，__name__是当前模块名称，如果被当作脚本运行，
# 则__name__的值是__main__，如果被导入，则__name__的值是模块名称，如knowledge.py
if __name__ == "__main__":
    service = KnowledgeBaseService()
    r = service.upload_by_str(data="aaaaallllllsssssllllsss",file_name="test.txt")
    print(r)



