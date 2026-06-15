from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from core.auth import decode_token
from core.rag import get_rag_service

security = HTTPBearer()

# 依赖注入模块dependency
def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    """验证 JWT token，返回当前用户信息。"""
    try:
        payload = decode_token(credentials.credentials)
        return {"user_id": payload["user_id"], "username": payload["username"]}
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效或过期的 token",
        )


def get_rag():
    """获取 RagService 单例。"""
    return get_rag_service()
