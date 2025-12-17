import os
from typing import Optional
from jose import jwt, JWTError
from fastapi import Header, HTTPException, Request
from starlette.status import HTTP_401_UNAUTHORIZED

# Конфигурация JWT
SECRET_KEY = os.environ.get("JWT_SECRET_KEY")
ALGORITHM = "HS256"

if not SECRET_KEY:
    raise ValueError("JWT_SECRET_KEY не установлен в переменных окружения.")


def decode_access_token(token: str) -> Optional[dict]:
    """Декодирует и проверяет JWT-токен."""
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None


def get_current_user_id(
    request: Request,
    Authorization: Optional[str] = Header(None, description="Bearer <token>")
) -> int:
    """
    Возвращает user_id из JWT.
    OPTIONS-запросы пропускаются для CORS preflight.
    """

    # 🔥 КЛЮЧЕВОЙ ФИКС
    if request.method == "OPTIONS":
        return 0  # фиктивное значение, не используется

    if not Authorization or not Authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="Неверный формат токена. Ожидается 'Bearer <token>'.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = Authorization.split(" ", 1)[1]
    payload = decode_access_token(token)

    if payload is None:
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="Недействительный или просроченный токен.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("user_id")

    if user_id is None:
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="Токен не содержит user_id.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user_id
