import json

from langchain_core.chat_history import BaseChatMessageHistory
from langchain_core.messages import BaseMessage, message_to_dict, messages_from_dict
from typing import Sequence

from core import config
from core.database import get_connection


class MySQLChatMessageHistory(BaseChatMessageHistory):
    def __init__(self, session_id: str):
        self.session_id = session_id

      # 这个add_messages方法会被RunnableWithMessageHistory调用，传入新消息列表，我们需要把它们追加到数据库中 
      # 实际上这个方法是重写了BaseChatMessageHistory中的抽象方法 
      # 关于其时机：这个“追加”动作具体发生在大模型生成完回复之后，且在系统将最终结果返回给用户之前。 
      # 在 RunnableWithMessageHistory 的内部源码机制中，它通过监听链的执行状态来精确控制这一时机。 
      # 当你调用带有记忆的链（例如执行 .invoke() 或 .stream()）时，RunnableWithMessageHistory  
      # 会在底层自动绑定一个名为 _exit（或 _exit_history）的后置回调函数。这个函数的触发条件就是： 
      # 当内部被包装的基础链（你的 base_chain）完全执行结束，并且成功拿到了大模型的输出结果时。
    def add_messages(self, messages: Sequence[BaseMessage]) -> None:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO chat_history (session_id, message) VALUES (%s, %s)",
                    [(self.session_id, json.dumps(message_to_dict(msg))) for msg in messages],
                )
            conn.commit()
        finally:
            conn.close()
            
      # 如果说“追加保存”是后置钩子（调用后），那么读取 messages 的时机 
      # 则是严格的前置动作（调用前），具体步骤做总结如下： 
      # 1. 当你调用带有记忆的链（例如执行 .invoke() 或 .stream()）时， 
      # RunnableWithMessageHistory 会从传入的配置参数（config）中提取出当前的 session_id 
      # 2. 在链执行的最开始阶段，RunnableWithMessageHistory 会调用你提供的 get_session_history（id） 函数， 
      # 从而获取到对应的历史记录对象。接着，它会直接访问该对象的 .messages 属性。
    @property
    def messages(self) -> list[BaseMessage]:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT message FROM chat_history WHERE session_id = %s "
                    "ORDER BY id DESC LIMIT %s", #限制窗口大小
                    (self.session_id, config.WINDOW_SIZE),
                )
                rows = list(cur.fetchall())
            rows.reverse()  # DESC → ASC，LangChain 期望时间正序
            return messages_from_dict([json.loads(row["message"]) for row in rows])
        finally:
            conn.close()

    def clear(self) -> None:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM chat_history WHERE session_id = %s",
                    (self.session_id,),
                )
                cur.execute(
                    "DELETE FROM chat_summary WHERE session_id = %s",
                    (self.session_id,),
                )
            conn.commit()
        finally:
            conn.close()

    # ── Summary helpers (static, callable from RagService) ──
    # 这些方法不依赖实例状态，可以直接通过类调用，方便 RagService 在处理对话时进行摘要相关的操作
    @staticmethod
    def get_summary(session_id: str) -> str | None:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT summary FROM chat_summary WHERE session_id = %s",
                    (session_id,),
                )
                row = cur.fetchone()
            return row["summary"] if row else None
        finally:
            conn.close()

    @staticmethod
    def save_summary(session_id: str, summary: str, last_msg_id: int) -> None:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO chat_summary (session_id, summary, last_summarized_msg_id)
                       VALUES (%s, %s, %s)
                       ON DUPLICATE KEY UPDATE
                           summary = VALUES(summary),
                           last_summarized_msg_id = VALUES(last_summarized_msg_id)""",
                    (session_id, summary, last_msg_id),
                )
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def count_messages(session_id: str) -> int:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) AS cnt FROM chat_history WHERE session_id = %s",
                    (session_id,),
                )
                return cur.fetchone()["cnt"]
        finally:
            conn.close()

    @staticmethod
    def get_messages_in_range(session_id: str, after_id: int, to_id: int) -> list[BaseMessage]:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT message FROM chat_history WHERE session_id = %s "
                    "AND id > %s AND id <= %s ORDER BY id",
                    (session_id, after_id, to_id),
                )
                rows = cur.fetchall() # 获取所有行
            # 返回消息列表
            return messages_from_dict([json.loads(row["message"]) for row in rows]) 
        finally:
            conn.close()
