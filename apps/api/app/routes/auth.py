import secrets
from datetime import datetime, timezone
from hashlib import sha256

import pyotp
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import AuthSession, Organization, User
from ..security import hash_password, issue_token, token_hash, verify_password

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
bearer = None

class RegisterIn(BaseModel):
    email: str
    password: str = Field(min_length=10)
    organization_name: str = Field(min_length=2, max_length=160)

class LoginIn(BaseModel):
    email: str
    password: str
    otp_code: str | None = None

class OtpCodeIn(BaseModel):
    code: str = Field(min_length=6, max_length=12)

class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


def dependencies():
    # Imported only when router is attached, after main has initialized dependencies.
    from ..main import bearer as auth_bearer, create_session, current_user
    return auth_bearer, create_session, current_user


@router.post("/register", response_model=TokenOut, status_code=201)
def register(payload: RegisterIn, request: Request, db: Session = Depends(get_db)):
    _, create_session, _ = dependencies()
    email = payload.email.strip().lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "email_already_registered")
    user = User(email=email, password_hash=hash_password(payload.password),
                organization=Organization(name=payload.organization_name, kind="merchant"))
    db.add(user); db.commit(); db.refresh(user)
    token = issue_token(user.id); create_session(db, user, token, request); db.commit()
    return TokenOut(access_token=token)


@router.post("/login", response_model=TokenOut)
def login(payload: LoginIn, request: Request, db: Session = Depends(get_db)):
    _, create_session, _ = dependencies()
    user = db.scalar(select(User).where(User.email == payload.email.strip().lower()))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, "invalid_credentials")
    if user.twofa_enabled:
        valid = bool(payload.otp_code and user.totp_secret and pyotp.TOTP(user.totp_secret).verify(payload.otp_code))
        backup = sha256(payload.otp_code.encode()).hexdigest() if payload.otp_code else ""
        if not valid and backup not in (user.backup_codes or []):
            raise HTTPException(401, "two_factor_code_required")
    token = issue_token(user.id); create_session(db, user, token, request); db.commit()
    return TokenOut(access_token=token)
