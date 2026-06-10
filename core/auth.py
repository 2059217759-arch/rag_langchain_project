import datetime

import jwt
import bcrypt # bcrypt是一个用于密码加密的库

from core import config
from core.database import get_connection

# 定义密码哈希函数
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

# 定义密码验证函数
def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))

# 创建令牌，
def create_token(user_id: int, username: str) -> str:
    # 核心数据部分
    payload = {
        "user_id": user_id,
        "username": username,
        # 过期时间
        "exp": datetime.datetime.utcnow()
        + datetime.timedelta(hours=config.JWT_EXPIRE_HOURS),
        # 签发时间
        "iat": datetime.datetime.utcnow(),
    }
    return jwt.encode(payload, config.JWT_SECRET_KEY, algorithm="HS256")

# 解码令牌
def decode_token(token: str) -> dict:
    return jwt.decode(token, config.JWT_SECRET_KEY, algorithms=["HS256"])


def register_user(username: str, password: str) -> tuple[bool, str]:
    if not username or not password:
        return False, "用户名和密码不能为空"
    if len(username) < 3:
        return False, "用户名至少3个字符"
    if len(password) < 6:
        return False, "密码至少6个字符"

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE username = %s", (username,))
            if cur.fetchone():
                return False, "用户名已存在"

            cur.execute(
                "INSERT INTO users (username, password) VALUES (%s, %s)",
                (username, hash_password(password)),
            )
        conn.commit()
        return True, "注册成功"
    finally:
        conn.close()


def login_user(username: str, password: str) -> tuple[bool, str, str | None]:
    """Returns (success, message, token_or_none)."""
    if not username or not password:
        return False, "用户名和密码不能为空", None

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, username, password FROM users WHERE username = %s",
                (username,),
            )
            row = cur.fetchone()

        if not row:
            return False, "用户名或密码错误", None

        if not verify_password(password, row["password"]):
            return False, "用户名或密码错误", None

        token = create_token(row["id"], row["username"])
        return True, "登录成功", token
    finally:
        conn.close()
