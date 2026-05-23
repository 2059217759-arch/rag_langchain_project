import os
from langchain_core.chat_history import BaseChatMessageHistory
from typing import Sequence
from langchain_core.messages import BaseMessage,message_to_dict,messages_from_dict
import json


class FileChatMessageHistory(BaseChatMessageHistory): # 继承BaseChatMessageHistory
    
    def __init__(self, session_id,storage_path):
        self.session_id = session_id # 会话id
        self.storage_path = storage_path #不同会话id的文件保存位置
        # 1. 确保目录存在，否则 open 写入文件时会报错
        if not os.path.exists(self.storage_path):
            os.makedirs(self.storage_path, exist_ok=True)
        # 完整文件路径
        self.file_path = os.path.join(self.storage_path, f"{session_id}.json")


    
    
    # messages这个参数，是序列，里面每个元素是BaseMessage对象
    def add_messages(self, messages: Sequence[BaseMessage]) -> None:
    
        all_messages = list(self.messages) # 已有的消息列表
        all_messages.extend(messages) # 添加新消息
    
        # 遍历合并后的所有消息对象，m_t_d函数将每个BaseMessage对象转换为字典，
        # 并保存到new_messages列表中。
        new_messages = [message_to_dict(message) for message in all_messages]

        # 将new_messages列表写入文件，这里每次添加消息都会重新写入文件，而不是追加。
        # 但这没办法，因为要写入的是json格式
        with open(self.file_path, "w",encoding="utf-8") as f:
            json.dump(new_messages, f) # 以json格式保存
            
    # 从文件中读取并反序列化历史聊天消息
    @property  # @property装饰器，将messages方法变为属性
    def messages(self) -> list[BaseMessage]:

        # try...except异常处理，如果文件不存在，则返回空列表。
        try:
            with open(self.file_path, "r",encoding="utf-8") as f:
                messages_data = json.load(f)
                return messages_from_dict(messages_data)
            
        except FileNotFoundError:
            return []
    
    def clear(self) -> None:
        with open(self.file_path, "w",encoding="utf-8") as f:
            json.dump([], f)
    
