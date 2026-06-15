import asyncio
import json
import uuid
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from api.deps import get_current_user, get_rag
from api.schemas import ChatRequest, ClearRequest, StatusResponse
from core.rag import RagService
from storage.chat_history import MySQLChatMessageHistory

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("/send")

# async def代表异步函数，ChatRequest 定义在 schemas.py 中,FastAPI 会自动从 HTTP 请求的 
# JSON Body中提取数据，并校验是否符合 ChatRequest 的结构（包含 question 和 session_id）
# user...是 FastAPI 强大的依赖注入系统,执行前先调用get_current_user，这个是验证token
async def send_message(req: ChatRequest, user: dict = Depends(get_current_user)):
    """SSE 流式问答。Agent 思考过程中持续推送事件。"""
    rag: RagService = get_rag() 

    async def event_stream():
        try:
            # 在线程池中执行同步的 RAG invoke，避免阻塞事件循环，核心！
            # 这里得好好讲讲底层是如何实现的，首先FastAPI (Uvicorn) 启动时，Python 的 asyncio 库会在主线程之外，
            # 预先创建一个固定大小的线程池，主线程 (Main Thread)：运行着事件循环 (Event Loop)。它的主要工作是监听网络 socket，
            # 处理 HTTP 协议的解析，以及调度协程，事件循环在主线程中接收到 /api/chat/send 请求。
            # 它执行到 await asyncio.to_thread(rag.invoke, ...)。
            # 事件循环不会在这里卡住等待，而是做一个动作：把 rag.invoke 这个函数打包成一个任务，扔进那个预创建的线程池队列里。
            # 然后，事件循环立刻返回去处理其他事情（比如接收用户 B 的请求）

            # 而async def声明了这是一个协程，协程（coroutine）是一种比线程更轻量级的“并发”执行单元，它允许函数在执行过程中
            # 挂起（暂停），让出控制权给其他协程，再在以后某个时间点 恢复执行。用一句话理解就是：协程是 可以中途暂停、稍后继续执行的函数。
            # 这里await 阻塞了当前协程，等线程池中的线程执行rag.invoke这个函数，再继续执行这个协程。这实际上是单线程并发
            answer = await asyncio.to_thread(
                rag.invoke, req.question, req.session_id
            )
            # 这边yield实现的是伪流式，是为了配合StreamingResponse，返回给前端的是json格式的
            yield f"data: {json.dumps({'type': 'answer', 'content': answer}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
        except Exception as e:
            logger.error(f"Chat error: {e}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),# 这里返回异步生成器对象，对应上面的yield
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/history")
def get_history(session_id: str, user: dict = Depends(get_current_user)):
    """获取指定会话的最近对话轮次。"""
    rounds = MySQLChatMessageHistory.get_recent_rounds(session_id, rounds=20)
    return {"session_id": session_id, "rounds": rounds}


@router.delete("/clear", response_model=StatusResponse)
def clear_session(req: ClearRequest, user: dict = Depends(get_current_user)):
    """清空指定会话的聊天记录。"""
    history = MySQLChatMessageHistory(session_id=req.session_id)
    history.clear()
    return StatusResponse(success=True, message="对话已清空")


@router.post("/sessions")
def create_session(user: dict = Depends(get_current_user)):
    """创建新的会话，返回唯一的 session_id。"""
    session_id = f"{user['username']}_{uuid.uuid4().hex[:8]}"
    return {"session_id": session_id, "username": user["username"]}
