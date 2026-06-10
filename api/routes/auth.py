from fastapi import APIRouter, HTTPException

from api.schemas import LoginRequest, RegisterRequest, AuthResponse
from core.auth import login_user, register_user

# APIRouter是子路由管理器
# prefix是路由的前缀，tags是路由的标签，规定该模块下的所有接口
# #都以 /api/auth 开头，并在文档中显示为 auth 组。
router = APIRouter(prefix="/api/auth", tags=["auth"])

# 声明是POST /api/auth/login，AuthResponse是接口成功返回的数据结构对象
@router.post("/login", response_model=AuthResponse)
def login(req: LoginRequest):
    # 执行登录core里面的登录方法，返回结果
    ok, msg, token = login_user(req.username, req.password)
    if ok and token:
        return AuthResponse(success=True, message=msg, token=token)
    raise HTTPException(status_code=401, detail=msg)


@router.post("/register", response_model=AuthResponse)
def register(req: RegisterRequest):
    ok, msg = register_user(req.username, req.password)
    if ok:
        return AuthResponse(success=True, message=msg)
    raise HTTPException(status_code=400, detail=msg)
