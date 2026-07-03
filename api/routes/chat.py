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
            logger.info("收到问答请求 session=%s question=%s", req.session_id, req.question[:80])
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
    if not session_id.startswith(f"{user['username']}_"):
        raise HTTPException(status_code=403, detail="无权访问此会话")
    rounds = MySQLChatMessageHistory.get_recent_rounds(session_id, rounds=20)
    return {"session_id": session_id, "rounds": rounds}


@router.delete("/clear", response_model=StatusResponse)
def clear_session(req: ClearRequest, user: dict = Depends(get_current_user)):
    """清空指定会话的聊天记录。"""
    if not req.session_id.startswith(f"{user['username']}_"):
        raise HTTPException(status_code=403, detail="无权访问此会话")
    history = MySQLChatMessageHistory(session_id=req.session_id)
    history.clear()
    return StatusResponse(success=True, message="对话已清空")


@router.post("/sessions")
def create_session(user: dict = Depends(get_current_user)):
    """创建新的会话，返回唯一的 session_id。"""
    session_id = f"{user['username']}_{uuid.uuid4().hex[:8]}"
    logger.info("会话创建 session=%s user=%s", session_id, user["username"])
    return {"session_id": session_id, "username": user["username"]}
