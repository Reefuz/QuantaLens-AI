import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator
from sqlalchemy import delete, select

from app.core.auth import (
    SESSION_COOKIE,
    CurrentUser,
    DbSession,
    clear_session_cookie,
    create_session,
    require_csrf_header,
)
from app.core.passwords import check_password
from app.core.rate_limit import client_ip, limiter
from app.core.security import hash_password, hash_token, needs_rehash, verify_password
from app.models import AuthSession, User, UserSettings

router = APIRouter(prefix="/auth", tags=["auth"], dependencies=[Depends(require_csrf_header)])

MIN_PASSWORD = 10


class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(max_length=128)

    @field_validator("email")
    @classmethod
    def normalise_email(cls, v: str) -> str:
        return v.strip().lower()


class RegisterRequest(Credentials):
    display_name: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def check_strength(self) -> "RegisterRequest":
        problem = check_password(self.password, self.email)
        if problem:
            raise ValueError(problem)
        return self


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str | None


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, request: Request, response: Response, db: DbSession) -> User:
    limiter.check(f"register:{client_ip(request)}", limit=5, window_seconds=3600)
    if db.scalar(select(User.id).where(User.email == body.email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists.")
    user = User(email=body.email, password_hash=hash_password(body.password), display_name=body.display_name)
    db.add(user)
    db.flush()
    db.add(UserSettings(user_id=user.id, preferences={}))
    db.commit()
    create_session(db, user, request, response)
    return user


@router.post("/login", response_model=UserOut)
def login(body: Credentials, request: Request, response: Response, db: DbSession) -> User:
    limiter.check(f"login-ip:{client_ip(request)}", limit=20, window_seconds=900)
    limiter.check(f"login-email:{body.email}", limit=8, window_seconds=900)
    user = db.scalar(select(User).where(User.email == body.email))
    if not verify_password(user.password_hash if user else None, body.password) or user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password.")
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
        db.commit()
    create_session(db, user, request, response)
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, db: DbSession) -> Response:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        db.execute(delete(AuthSession).where(AuthSession.token_hash == hash_token(token)))
        db.commit()
    clear_session_cookie(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> User:
    return user
