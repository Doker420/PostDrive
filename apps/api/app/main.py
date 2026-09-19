from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, HttpUrl
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import settings
from .db import Base, engine, get_db
from .models import ApiKey, LedgerEntry, Organization, Payment, Project, User
from .security import hash_password, issue_token, new_api_key, read_token, verify_password

Base.metadata.create_all(bind=engine)
app = FastAPI(title=settings.app_name, version="0.1.0", description="FlowPay B2B payment orchestration API")
bearer = HTTPBearer(auto_error=False)


class RegisterIn(BaseModel):
    email: str
    password: str = Field(min_length=10)
    organization_name: str = Field(min_length=2, max_length=160)


class LoginIn(BaseModel):
    email: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: str
    role: str
    organization_id: int


class ProjectIn(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    mode: str = Field(default="test", pattern="^(test|live)$")
    webhook_url: HttpUrl | None = None


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    mode: str
    webhook_url: str | None


class ApiKeyIn(BaseModel):
    label: str = Field(default="default", max_length=100)
    mode: str = Field(default="test", pattern="^(test|live)$")


class ApiKeyOut(BaseModel):
    id: int
    label: str
    mode: str
    key: str
    warning: str = "Save this key now. It will not be shown again."


class PaymentIn(BaseModel):
    amount: Decimal = Field(gt=0, max_digits=20, decimal_places=2)
    currency: str = Field(min_length=3, max_length=3)
    order_id: str = Field(min_length=1, max_length=255)
    description: str | None = None
    payment_methods: list[str] = Field(default_factory=list)
    success_url: HttpUrl | None = None
    fail_url: HttpUrl | None = None
    metadata: dict = Field(default_factory=dict)


class PaymentOut(BaseModel):
    id: str
    status: str
    amount: Decimal
    currency: str
    order_id: str
    payment_url: str
    expires_at: datetime
    metadata: dict


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)) -> User:
    user_id = read_token(credentials.credentials) if credentials else None
    user = db.get(User, user_id) if user_id else None
    if not user:
        raise HTTPException(status_code=401, detail="unauthorized")
    return user


def api_context(authorization: str | None, db: Session) -> tuple[ApiKey, Project]:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="unauthorized")
    digest = sha256(authorization[7:].encode()).hexdigest()
    key = db.scalar(select(ApiKey).where(ApiKey.key_hash == digest, ApiKey.revoked_at.is_(None)))
    if not key:
        raise HTTPException(status_code=401, detail="invalid_api_key")
    return key, key.project


def payment_response(payment: Payment) -> PaymentOut:
    return PaymentOut(id=payment.public_id, status=payment.status, amount=payment.amount,
                      currency=payment.currency, order_id=payment.order_id,
                      payment_url=payment.payment_url,
                      expires_at=payment.created_at.replace(tzinfo=timezone.utc),
                      metadata=payment.metadata_json or {})


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "flowpay-api", "environment": settings.environment}


@app.post("/api/v1/auth/register", response_model=TokenOut, status_code=201)
def register(payload: RegisterIn, db: Session = Depends(get_db)):
    email = payload.email.strip().lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "email_already_registered")
    organization = Organization(name=payload.organization_name, kind="merchant")
    user = User(email=email, password_hash=hash_password(payload.password), organization=organization)
    db.add(user)
    db.commit()
    db.refresh(user)
    return TokenOut(access_token=issue_token(user.id))


@app.post("/api/v1/auth/login", response_model=TokenOut)
def login(payload: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == payload.email.strip().lower()))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, "invalid_credentials")
    return TokenOut(access_token=issue_token(user.id))


@app.get("/api/v1/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user


@app.post("/api/v1/projects", response_model=ProjectOut, status_code=201)
def create_project(payload: ProjectIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    project = Project(organization_id=user.organization_id, name=payload.name, mode=payload.mode,
                      webhook_url=str(payload.webhook_url) if payload.webhook_url else None)
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@app.get("/api/v1/projects", response_model=list[ProjectOut])
def list_projects(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return list(db.scalars(select(Project).where(Project.organization_id == user.organization_id)))


@app.post("/api/v1/projects/{project_id}/api-keys", response_model=ApiKeyOut, status_code=201)
def create_api_key(project_id: int, payload: ApiKeyIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    project = db.scalar(select(Project).where(Project.id == project_id, Project.organization_id == user.organization_id))
    if not project:
        raise HTTPException(404, "project_not_found")
    if project.mode != payload.mode:
        raise HTTPException(422, "key_mode_must_match_project_mode")
    raw, digest = new_api_key(payload.mode)
    api_key = ApiKey(project_id=project.id, key_hash=digest, label=payload.label, mode=payload.mode)
    db.add(api_key)
    db.commit()
    db.refresh(api_key)
    return ApiKeyOut(id=api_key.id, label=api_key.label, mode=api_key.mode, key=raw)


@app.post("/api/v1/payments", response_model=PaymentOut, status_code=201)
def create_payment(payload: PaymentIn, authorization: str | None = Header(default=None),
                   idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
                   db: Session = Depends(get_db)):
    if not idempotency_key:
        raise HTTPException(400, "idempotency_key_required")
    _, project = api_context(authorization, db)
    existing = db.scalar(select(Payment).where(Payment.project_id == project.id, Payment.idempotency_key == idempotency_key))
    if existing:
        if existing.order_id != payload.order_id or existing.amount != payload.amount:
            raise HTTPException(409, "idempotency_key_reused")
        return payment_response(existing)
    public_id = "pay_" + uuid4().hex
    payment = Payment(public_id=public_id, project_id=project.id, idempotency_key=idempotency_key,
                      order_id=payload.order_id, amount=payload.amount, currency=payload.currency.upper(),
                      payment_url=f"{settings.app_name.lower().replace(' ', '-')}/pay/{public_id}",
                      success_url=str(payload.success_url) if payload.success_url else None,
                      fail_url=str(payload.fail_url) if payload.fail_url else None,
                      metadata_json=payload.metadata)
    db.add(payment)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(Payment).where(Payment.project_id == project.id, Payment.idempotency_key == idempotency_key))
        if existing:
            return payment_response(existing)
        raise HTTPException(409, "payment_conflict")
    db.refresh(payment)
    return payment_response(payment)


@app.get("/api/v1/payments/{public_id}", response_model=PaymentOut)
def get_payment(public_id: str, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    _, project = api_context(authorization, db)
    payment = db.scalar(select(Payment).where(Payment.public_id == public_id, Payment.project_id == project.id))
    if not payment:
        raise HTTPException(404, "payment_not_found")
    return payment_response(payment)
