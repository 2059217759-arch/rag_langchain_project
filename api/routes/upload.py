import os
import logging

from fastapi import APIRouter, Depends, File, UploadFile, HTTPException

from api.deps import get_current_user
from api.schemas import UploadResponse
from core import config
from core.ingestion import get_ingestion_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/upload", tags=["upload"])


@router.post("", response_model=UploadResponse)
async def upload_file(
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
):
    """上传 Markdown/TXT 文件到知识库。"""
    ext = os.path.splitext(file.filename or "")[-1].lower()
    if ext not in (".txt", ".md"):
        raise HTTPException(status_code=400, detail="仅支持 .txt 和 .md 文件")

    content = await file.read()
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        logger.warning("文件编码错误 file=%s user=%s", file.filename, user["username"])
        raise HTTPException(status_code=400, detail="文件编码不支持，请使用 UTF-8")

    logger.info("收到上传请求 file=%s size=%d user=%s", file.filename, len(text), user["username"])
    service = get_ingestion_service()
    result = service.upload_by_str(data=text, file_name=file.filename or "unknown")

    if "失败" in result:
        raise HTTPException(status_code=400, detail=result)

    # 刷新 BM25 索引
    from core.rag import get_rag_service
    rag = get_rag_service()
    rag.vector_service.refresh_bm25()

    return UploadResponse(
        success=True,
        message=result,
    )
