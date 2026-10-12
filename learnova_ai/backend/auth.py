"""
Sign-up / sign-in.

Passwords are hashed with bcrypt (passlib). Sessions are stateless JWTs
(PyJWT) — the frontend stores the token and sends it as a Bearer header
on every request. SECRET_KEY must be set to a real random value in
production (.env) — the default here is only for local dev.
"""

import os
import datetime
from typing import Optional

import jwt
import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from backend.database import get_db
from backend import models

SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-insecure-key-change-me")
ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = int(os.environ.get("TOKEN_EXPIRE_HOURS", "168"))  # 1 week

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(user_id: str) -> str:
    expire = datetime.datetime.utcnow() + datetime.timedelta(hours=TOKEN_EXPIRE_HOURS)
    payload = {"sub": user_id, "exp": expire}
    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    # PyJWT < 2.0 returns bytes instead of str — this would otherwise fail to
    # JSON-serialize in the response and surface as an opaque 500 error.
    if isinstance(token, bytes):
        token = token.decode("utf-8")
    return token


def _decode_token(token: str) -> Optional[str]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload.get("sub")
    except jwt.PyJWTError:
        return None


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> models.User:
    user_id = _decode_token(token)
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired session — please sign in again.")
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User no longer exists.")
    return user
