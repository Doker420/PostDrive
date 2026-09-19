import json
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
from uuid import uuid4
import secrets
import time
from collections import defaultdict, deque

import httpx
import pyotp
from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, HttpUrl
from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import settings
from .db import Base, SessionLocal, engine, get_db
from .models import (ApiKey, AuthSession, CryptoWallet, LedgerEntry, Organization, Payment,
                      PaymentChannel, PaymentEvent, Payout, Project, RiskEvent, SupplierProfile,
                      NotificationSetting, TelegramIntegration, User, WebhookDelivery)
from .security import (decrypt_secret, encrypt_secret, hash_password, issue_token, new_api_key, read_token,
                       sign_webhook, token_hash, verify_password)
from .routes.health import router as health_router
from .services.risk import score_payment
from .services.ledger import balance as ledger_balance

Base.metadata.create_all(bind=engine)
app = FastAPI(title=settings.app_name, version="0.1.0", description="FlowPay B2B payment orchestration API")
app.mount("/web", StaticFiles(directory="apps/web"), name="web")
app.include_router(health_router)
bearer = HTTPBearer(auto_error=False)
_rate_windows: dict[str, deque[float]] = defaultdict(deque)


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    if request.url.path in {"/health", "/health/ready"} or request.url.path.startswith("/docs"):
        return await call_next(request)
    client = request.client.host if request.client else "unknown"
    group = "auth" if "/auth/" in request.url.path else "api"
    limit = 20 if group == "auth" else settings.rate_limit_per_minute
    key = f"{client}:{group}"
    now = time.monotonic()
    window = _rate_windows[key]
    while window and window[0] <= now - 60:
        window.popleft()
    if len(window) >= limit:
        return Response(status_code=429, content='{"detail":"rate_limited"}', media_type="application/json",
                        headers={"Retry-After": "60"})
    window.append(now)
    response = await call_next(request)
    response.headers["X-RateLimit-Limit"] = str(limit)
    response.headers["X-RateLimit-Remaining"] = str(max(0, limit - len(window)))
    return response


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


class AdminStatusIn(BaseModel):
    status: str = Field(pattern="^(pending|active|blocked|suspended)$")


class AdminChannelStatusIn(BaseModel):
    status: str = Field(pattern="^(active|inactive|blocked)$")


class AdminPaymentStatusIn(BaseModel):
    status: str = Field(pattern="^(pending|processing|succeeded|failed|expired|cancelled)$")


class NotificationSettingsIn(BaseModel):
    enabled_events: list[str] = Field(default_factory=list)
    telegram_enabled: bool = True
    email_enabled: bool = False


class TelegramIn(BaseModel):
    bot_token: str = Field(min_length=20, max_length=300)
    chat_id: str = Field(min_length=1, max_length=80)


class WalletIn(BaseModel):
    currency: str = Field(default="USDT", pattern="^(USDT|USDC)$")
    network: str = Field(pattern="^(TRC20|ERC20|POLYGON)$")
    address: str = Field(min_length=20, max_length=160)


class PayoutIn(BaseModel):
    amount: Decimal = Field(gt=0, decimal_places=2)
    currency: str = Field(default="RUB", min_length=3, max_length=3)
    crypto_currency: str = Field(default="USDT", pattern="^(USDT|USDC)$")
    network: str = Field(pattern="^(TRC20|ERC20|POLYGON)$")
    address: str = Field(min_length=20, max_length=160)


class PayoutStatusIn(BaseModel):
    status: str = Field(pattern="^(processing|completed|failed|cancelled)$")
    tx_hash: str | None = Field(default=None, max_length=160)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: str
    role: str
    organization_id: int
    twofa_enabled: bool


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
    webhook_secret: str | None = None


class SupplierIn(BaseModel):
    display_name: str = Field(min_length=2, max_length=160)
    commission_percent: Decimal = Field(default=Decimal("0"), ge=0, le=100, decimal_places=4)


class ChannelIn(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    method: str = Field(pattern="^(sbp|bank_transfer|card)$")
    currency: str = Field(min_length=3, max_length=3)
    min_amount: Decimal = Field(gt=0, decimal_places=2)
    max_amount: Decimal = Field(gt=0, decimal_places=2)
    daily_limit: Decimal = Field(gt=0, decimal_places=2)
    details: dict = Field(min_length=1)


class ChannelOut(BaseModel):
    id: int
    name: str
    method: str
    currency: str
    min_amount: Decimal
    max_amount: Decimal
    daily_limit: Decimal
    used_today: Decimal
    status: str


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
    platform_fee: Decimal = Decimal("0")
    supplier_fee: Decimal = Decimal("0")
    merchant_net: Decimal = Decimal("0")


def create_session(db: Session, user: User, token: str, request: Request | None = None) -> None:
    db.add(AuthSession(user_id=user.id, token_hash=token_hash(token),
                       ip_address=request.client.host if request and request.client else None,
                       user_agent=request.headers.get("user-agent") if request else None))


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
                 request: Request = None, db: Session = Depends(get_db)) -> User:
    token = credentials.credentials if credentials else None
    user_id = read_token(token) if token else None
    session = db.scalar(select(AuthSession).where(AuthSession.token_hash == token_hash(token) if token else False,
                                                  AuthSession.revoked_at.is_(None)))
    user = db.get(User, user_id) if user_id and session else None
    if not user:
        raise HTTPException(status_code=401, detail="unauthorized")
    session.last_seen_at = datetime.now(timezone.utc)
    return user


def admin_user(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="admin_role_required")
    return user


def organization_balance(db: Session, organization_id: int, currency: str) -> Decimal:
    return ledger_balance(db, organization_id, currency)


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
                      metadata=payment.metadata_json or {}, platform_fee=payment.platform_fee,
                      supplier_fee=payment.supplier_fee, merchant_net=payment.merchant_net)


def emit_payment_event(db: Session, payment: Payment, event_type: str) -> PaymentEvent:
    event_id = "evt_" + secrets.token_urlsafe(18)
    payload = {
        "id": event_id,
        "type": event_type,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "data": {"id": payment.public_id, "status": payment.status,
                 "amount": str(payment.amount), "currency": payment.currency,
                 "order_id": payment.order_id, "metadata": payment.metadata_json or {}},
    }
    event = PaymentEvent(event_id=event_id, payment_id=payment.id, event_type=event_type, payload=payload)
    db.add(event)
    project = db.get(Project, payment.project_id)
    if project and project.webhook_url:
        db.add(WebhookDelivery(event_id=event_id, project_id=project.id, url=project.webhook_url,
                               payload=payload))
    return event


async def deliver_webhook(delivery_id: int) -> None:
    db = SessionLocal()
    try:
        delivery = db.get(WebhookDelivery, delivery_id)
        if not delivery or delivery.status == "delivered":
            return
        project = db.get(Project, delivery.project_id)
        if not project or not project.webhook_url:
            return
        body = json.dumps(delivery.payload, separators=(",", ":"), ensure_ascii=False)
        timestamp = str(int(datetime.now(timezone.utc).timestamp()))
        signature = sign_webhook(project.webhook_secret, timestamp, body)
        delivery.attempts += 1
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
                response = await client.post(delivery.url, content=body.encode(), headers={
                    "Content-Type": "application/json",
                    "User-Agent": "FlowPay-Webhook/1.0",
                    "X-FlowPay-Event-Id": delivery.event_id,
                    "X-FlowPay-Signature": f"t={timestamp},v1={signature}",
                })
            if 200 <= response.status_code < 300:
                delivery.status = "delivered"
                delivery.last_error = None
            else:
                delivery.status = "failed" if delivery.attempts >= 5 else "pending"
                delivery.last_error = f"http_{response.status_code}"
        except Exception as exc:
            delivery.status = "failed" if delivery.attempts >= 5 else "pending"
            delivery.last_error = str(exc)[:500]
        db.commit()
    finally:
        db.close()


async def send_telegram(organization_id: int, text: str, event_type: str | None = None) -> None:
    db = SessionLocal()
    try:
        preference = db.scalar(select(NotificationSetting).where(NotificationSetting.organization_id == organization_id))
        if preference and (not preference.telegram_enabled or (event_type and event_type not in (preference.enabled_events or []))):
            return
        integration = db.scalar(select(TelegramIntegration).where(
            TelegramIntegration.organization_id == organization_id,
            TelegramIntegration.status == "active"))
        if not integration:
            return
        token = decrypt_secret(integration.bot_token_encrypted)
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(url, json={"chat_id": integration.chat_id, "text": text})
    except Exception:
        pass
    finally:
        db.close()


ALLOWED_TRANSITIONS = {
    "pending": {"processing", "failed", "expired", "cancelled", "succeeded"},
    "processing": {"succeeded", "failed", "expired"},
    "succeeded": set(), "failed": set(), "expired": set(), "cancelled": set(),
}


@app.get("/api/v1/auth/sessions")
def list_sessions(credentials: HTTPAuthorizationCredentials = Depends(bearer),
                  user: User = Depends(current_user), db: Session = Depends(get_db)):
    current_hash = token_hash(credentials.credentials)
    rows = db.scalars(select(AuthSession).where(AuthSession.user_id == user.id,
                                                AuthSession.revoked_at.is_(None))).all()
    return [{"id": row.id, "current": row.token_hash == current_hash, "ip_address": row.ip_address,
             "user_agent": row.user_agent, "created_at": row.created_at,
             "last_seen_at": row.last_seen_at} for row in rows]


@app.delete("/api/v1/auth/sessions/{session_id}")
def revoke_session(session_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    session = db.scalar(select(AuthSession).where(AuthSession.id == session_id, AuthSession.user_id == user.id,
                                                 AuthSession.revoked_at.is_(None)))
    if not session:
        raise HTTPException(404, "session_not_found")
    session.revoked_at = datetime.now(timezone.utc)
    db.commit()
    return {"status": "revoked", "session_id": session.id}


@app.post("/api/v1/auth/logout-all")
def logout_all(credentials: HTTPAuthorizationCredentials = Depends(bearer),
               user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.query(AuthSession).filter(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None)).update(
        {"revoked_at": datetime.now(timezone.utc)})
    db.commit()
    return {"status": "ok"}


@app.post("/api/v1/auth/2fa/setup")
def setup_2fa(user: User = Depends(current_user), db: Session = Depends(get_db)):
    secret = pyotp.random_base32()
    user.totp_secret = secret
    user.twofa_enabled = False
    db.commit()
    return {"secret": secret, "otpauth_url": pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name="FlowPay")}


@app.post("/api/v1/auth/2fa/confirm")
def confirm_2fa(payload: OtpCodeIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not user.totp_secret or not pyotp.TOTP(user.totp_secret).verify(payload.code):
        raise HTTPException(400, "invalid_two_factor_code")
    user.twofa_enabled = True
    codes = [secrets.token_hex(5) for _ in range(8)]
    user.backup_codes = [sha256(code.encode()).hexdigest() for code in codes]
    db.commit()
    return {"enabled": True, "backup_codes": codes}


@app.post("/api/v1/auth/2fa/disable")
def disable_2fa(payload: OtpCodeIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not user.twofa_enabled or not user.totp_secret or not pyotp.TOTP(user.totp_secret).verify(payload.code):
        raise HTTPException(400, "invalid_two_factor_code")
    user.twofa_enabled = False
    user.totp_secret = None
    user.backup_codes = []
    db.commit()
    return {"enabled": False}


@app.get("/api/v1/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user


@app.post("/api/v1/projects", response_model=ProjectOut, status_code=201)
def create_project(payload: ProjectIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    project = Project(organization_id=user.organization_id, name=payload.name, mode=payload.mode,
                      webhook_url=str(payload.webhook_url) if payload.webhook_url else None,
                      webhook_secret="whsec_" + secrets.token_urlsafe(32))
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




from .routes.payments import router as payments_router
app.include_router(payments_router)

from .routes.auth import router as auth_router
app.include_router(auth_router)
from .routes.notifications import router as notifications_router
app.include_router(notifications_router)

from .routes.payouts import router as payouts_router
app.include_router(payouts_router)
from .routes.supplier import router as supplier_router
app.include_router(supplier_router)
from .routes.admin import router as admin_router
app.include_router(admin_router)
