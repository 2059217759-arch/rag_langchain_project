import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import auth, chat, upload, metrics
from core.logging_config import setup_logging

setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动/关闭时的生命周期管理。"""
    logger.info("FastAPI 服务启动，预热 RagService 单例...")
    from core.rag import get_rag_service
    get_rag_service()
    logger.info("RagService 单例就绪")
    yield
    logger.info("FastAPI 服务关闭")


app = FastAPI(
    title="RAG 智能助手 API",
    version="3.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(upload.router)
app.include_router(metrics.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
