import json
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
from uuid import uuid4
import secrets

import httpx
import pyotp
from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, HttpUrl
from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import settings
from .db import Base, SessionLocal, engine, get_db
from .models import (ApiKey, AuthSession, CryptoWallet, LedgerEntry, Organization, Payment,
                      PaymentChannel, PaymentEvent, Payout, Project, SupplierProfile, User,
                      WebhookDelivery)
from .security import (encrypt_secret, hash_password, issue_token, new_api_key, read_token,
                       sign_webhook, token_hash, verify_password)

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
    otp_code: str | None = None


class OtpCodeIn(BaseModel):
    code: str = Field(min_length=6, max_length=12)


class AdminStatusIn(BaseModel):
    status: str = Field(pattern="^(pending|active|blocked|suspended)$")


class AdminChannelStatusIn(BaseModel):
    status: str = Field(pattern="^(active|inactive|blocked)$")


class AdminPaymentStatusIn(BaseModel):
    status: str = Field(pattern="^(pending|processing|succeeded|failed|expired|cancelled)$")


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
    entries = db.scalars(select(LedgerEntry).where(LedgerEntry.organization_id == organization_id,
                                                   LedgerEntry.currency == currency.upper())).all()
    return sum((Decimal(str(entry.amount)) for entry in entries), Decimal("0"))


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


ALLOWED_TRANSITIONS = {
    "pending": {"processing", "failed", "expired", "cancelled", "succeeded"},
    "processing": {"succeeded", "failed", "expired"},
    "succeeded": set(), "failed": set(), "expired": set(), "cancelled": set(),
}


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "flowpay-api", "environment": settings.environment}


@app.post("/api/v1/auth/register", response_model=TokenOut, status_code=201)
def register(payload: RegisterIn, request: Request, db: Session = Depends(get_db)):
    email = payload.email.strip().lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "email_already_registered")
    organization = Organization(name=payload.organization_name, kind="merchant")
    user = User(email=email, password_hash=hash_password(payload.password), organization=organization)
    db.add(user)
    db.commit()
    db.refresh(user)
    token = issue_token(user.id)
    create_session(db, user, token, request)
    db.commit()
    return TokenOut(access_token=token)


@app.post("/api/v1/auth/login", response_model=TokenOut)
def login(payload: LoginIn, request: Request, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == payload.email.strip().lower()))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, "invalid_credentials")
    if user.twofa_enabled:
        valid_totp = bool(payload.otp_code and user.totp_secret and pyotp.TOTP(user.totp_secret).verify(payload.otp_code))
        backup_hash = sha256(payload.otp_code.encode()).hexdigest() if payload.otp_code else ""
        if not valid_totp and backup_hash not in (user.backup_codes or []):
            raise HTTPException(401, "two_factor_code_required")
        if backup_hash in (user.backup_codes or []):
            user.backup_codes.remove(backup_hash)
            db.commit()
    token = issue_token(user.id)
    create_session(db, user, token, request)
    db.commit()
    return TokenOut(access_token=token)


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


@app.post("/api/v1/admin/bootstrap", status_code=201)
def bootstrap_admin(email: str, bootstrap_token: str = Header(alias="X-Admin-Bootstrap-Token"), db: Session = Depends(get_db)):
    if bootstrap_token != settings.admin_bootstrap_token:
        raise HTTPException(403, "invalid_bootstrap_token")
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    if not user:
        raise HTTPException(404, "user_not_found")
    user.role = "admin"
    db.commit()
    return {"status": "ok", "user_id": user.id, "role": user.role}


@app.get("/api/v1/export/payments.csv")
def merchant_payments_csv(authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    _, project = api_context(authorization, db)
    rows = db.scalars(select(Payment).where(Payment.project_id == project.id).order_by(Payment.created_at.desc())).all()
    lines = ["id,order_id,amount,currency,status,platform_fee,supplier_fee,merchant_net,created_at"]
    lines += [f"{p.public_id},{p.order_id},{p.amount},{p.currency},{p.status},{p.platform_fee},{p.supplier_fee},{p.merchant_net},{p.created_at.isoformat()}" for p in rows]
    return Response(content="\n".join(lines), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=flowpay-payments.csv"})


@app.get("/api/v1/admin/statistics")
def admin_statistics(_: User = Depends(admin_user), days: int = Query(default=30, ge=1, le=365), db: Session = Depends(get_db)):
    since = datetime.now(timezone.utc) - __import__("datetime").timedelta(days=days)
    payments = db.scalars(select(Payment).where(Payment.created_at >= since)).all()
    succeeded = [p for p in payments if p.status == "succeeded"]
    return {"period_days": days, "payments": len(payments), "succeeded": len(succeeded),
            "pending": sum(p.status == "pending" for p in payments),
            "failed": sum(p.status == "failed" for p in payments),
            "gross": str(sum((p.amount for p in succeeded), Decimal("0"))),
            "platform_fees": str(sum((p.platform_fee for p in succeeded), Decimal("0"))),
            "supplier_fees": str(sum((p.supplier_fee for p in succeeded), Decimal("0"))),
            "merchant_net": str(sum((p.merchant_net for p in succeeded), Decimal("0"))),
            "conversion_percent": round((len(succeeded) / len(payments) * 100), 2) if payments else 0}


@app.get("/api/v1/admin/overview")
def admin_overview(_: User = Depends(admin_user), db: Session = Depends(get_db)):
    return {
        "organizations": db.query(Organization).count(),
        "users": db.query(User).count(),
        "projects": db.query(Project).count(),
        "suppliers": db.query(SupplierProfile).count(),
        "channels": db.query(PaymentChannel).count(),
        "payments": db.query(Payment).count(),
        "pending_payments": db.query(Payment).filter(Payment.status == "pending").count(),
    }


@app.get("/api/v1/admin/suppliers")
def admin_suppliers(_: User = Depends(admin_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(SupplierProfile).order_by(SupplierProfile.created_at.desc())).all()
    return [{"id": row.id, "organization_id": row.organization_id, "display_name": row.display_name,
             "status": row.status, "commission_percent": row.commission_percent,
             "channels": db.query(PaymentChannel).filter(PaymentChannel.supplier_id == row.id).count()}
            for row in rows]


@app.patch("/api/v1/admin/suppliers/{supplier_id}")
def admin_supplier_status(supplier_id: int, payload: AdminStatusIn, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    supplier = db.get(SupplierProfile, supplier_id)
    if not supplier:
        raise HTTPException(404, "supplier_not_found")
    supplier.status = payload.status
    if payload.status != "active":
        db.query(PaymentChannel).filter(PaymentChannel.supplier_id == supplier.id).update({"status": "inactive"})
    db.commit()
    return {"id": supplier.id, "status": supplier.status}


@app.get("/api/v1/admin/channels")
def admin_channels(_: User = Depends(admin_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(PaymentChannel).order_by(PaymentChannel.created_at.desc())).all()
    return [{"id": row.id, "supplier_id": row.supplier_id, "name": row.name, "method": row.method,
             "currency": row.currency, "min_amount": row.min_amount, "max_amount": row.max_amount,
             "daily_limit": row.daily_limit, "used_today": row.used_today, "status": row.status}
            for row in rows]


@app.patch("/api/v1/admin/channels/{channel_id}")
def admin_channel_status(channel_id: int, payload: AdminChannelStatusIn, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    channel = db.get(PaymentChannel, channel_id)
    if not channel:
        raise HTTPException(404, "channel_not_found")
    channel.status = payload.status
    db.commit()
    return {"id": channel.id, "status": channel.status}


@app.patch("/api/v1/admin/payments/{public_id}/status")
def admin_payment_status(public_id: str, payload: AdminPaymentStatusIn,
                         background_tasks: BackgroundTasks,
                         _: User = Depends(admin_user), db: Session = Depends(get_db)):
    payment = db.scalar(select(Payment).where(Payment.public_id == public_id))
    if not payment:
        raise HTTPException(404, "payment_not_found")
    if payload.status not in ALLOWED_TRANSITIONS.get(payment.status, set()):
        raise HTTPException(409, f"invalid_status_transition:{payment.status}->{payload.status}")
    old_status = payment.status
    payment.status = payload.status
    if payload.status == "succeeded":
        project = db.get(Project, payment.project_id)
        platform_fee = (payment.amount * settings.platform_fee_percent / Decimal("100")).quantize(Decimal("0.01"))
        supplier_fee = Decimal("0")
        supplier_org_id = None
        if payment.channel_id:
            channel = db.get(PaymentChannel, payment.channel_id)
            supplier = db.get(SupplierProfile, channel.supplier_id) if channel else None
            if supplier:
                supplier_fee = (payment.amount * supplier.commission_percent / Decimal("100")).quantize(Decimal("0.01"))
                supplier_org_id = supplier.organization_id
        merchant_net = payment.amount - platform_fee - supplier_fee
        if merchant_net < 0:
            raise HTTPException(422, "fees_exceed_payment_amount")
        payment.platform_fee, payment.supplier_fee, payment.merchant_net = platform_fee, supplier_fee, merchant_net
        db.add(LedgerEntry(organization_id=project.organization_id, payment_id=payment.id, amount=merchant_net,
                           currency=payment.currency, entry_type="payment_credit",
                           description=f"Net payment {payment.public_id}"))
        if supplier_org_id and supplier_fee:
            db.add(LedgerEntry(organization_id=supplier_org_id, payment_id=payment.id, amount=supplier_fee,
                               currency=payment.currency, entry_type="supplier_commission",
                               description=f"Commission for {payment.public_id}"))
    event = emit_payment_event(db, payment, f"payment.{payload.status}")
    db.commit()
    delivery = db.scalar(select(WebhookDelivery).where(WebhookDelivery.event_id == event.event_id))
    if delivery:
        background_tasks.add_task(deliver_webhook, delivery.id)
    return {"id": payment.public_id, "old_status": old_status, "status": payment.status}


@app.post("/api/v1/admin/webhook-deliveries/{delivery_id}/retry")
def admin_retry_webhook(delivery_id: int, background_tasks: BackgroundTasks,
                        _: User = Depends(admin_user), db: Session = Depends(get_db)):
    delivery = db.get(WebhookDelivery, delivery_id)
    if not delivery:
        raise HTTPException(404, "webhook_delivery_not_found")
    if delivery.status == "delivered":
        return {"id": delivery.id, "status": delivery.status}
    delivery.status = "pending"
    delivery.last_error = None
    db.commit()
    background_tasks.add_task(deliver_webhook, delivery.id)
    return {"id": delivery.id, "status": "queued"}


@app.get("/api/v1/admin/webhook-deliveries")
def admin_webhook_deliveries(_: User = Depends(admin_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(WebhookDelivery).order_by(WebhookDelivery.created_at.desc()).limit(100)).all()
    return [{"id": row.id, "event_id": row.event_id, "project_id": row.project_id,
             "url": row.url, "status": row.status, "attempts": row.attempts,
             "last_error": row.last_error, "created_at": row.created_at} for row in rows]


@app.get("/api/v1/admin/payouts")
def admin_payouts(_: User = Depends(admin_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Payout).order_by(Payout.created_at.desc()).limit(100)).all()
    return [{"id": row.public_id, "organization_id": row.organization_id, "amount": row.amount,
             "currency": row.currency, "crypto_currency": row.crypto_currency,
             "network": row.network, "address": row.address, "status": row.status,
             "tx_hash": row.tx_hash, "created_at": row.created_at} for row in rows]


@app.patch("/api/v1/admin/payouts/{public_id}/status")
def admin_payout_status(public_id: str, payload: PayoutStatusIn,
                        _: User = Depends(admin_user), db: Session = Depends(get_db)):
    payout = db.scalar(select(Payout).where(Payout.public_id == public_id))
    if not payout:
        raise HTTPException(404, "payout_not_found")
    if payout.status in {"completed", "failed", "cancelled"}:
        raise HTTPException(409, "payout_already_final")
    payout.status, payout.tx_hash = payload.status, payload.tx_hash
    if payload.status in {"failed", "cancelled"}:
        db.add(LedgerEntry(organization_id=payout.organization_id, amount=payout.amount,
                           currency=payout.currency, entry_type="payout_reversal",
                           description=f"Reversal for {payout.public_id}"))
    db.commit()
    return {"id": payout.public_id, "status": payout.status, "tx_hash": payout.tx_hash}


@app.get("/api/v1/admin/payments")
def admin_payments(_: User = Depends(admin_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Payment).order_by(Payment.created_at.desc()).limit(100)).all()
    return [{"id": row.public_id, "project_id": row.project_id, "channel_id": row.channel_id,
             "order_id": row.order_id, "amount": row.amount, "currency": row.currency,
             "status": row.status, "created_at": row.created_at} for row in rows]


@app.post("/api/v1/supplier", status_code=201)
def create_supplier(payload: SupplierIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    existing = db.scalar(select(SupplierProfile).where(SupplierProfile.organization_id == user.organization_id))
    if existing:
        raise HTTPException(409, "supplier_profile_exists")
    profile = SupplierProfile(organization_id=user.organization_id, display_name=payload.display_name,
                              commission_percent=payload.commission_percent, status="active")
    user.organization.kind = "supplier"
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return {"id": profile.id, "display_name": profile.display_name, "status": profile.status,
            "commission_percent": profile.commission_percent}


@app.post("/api/v1/supplier/channels", response_model=ChannelOut, status_code=201)
def create_channel(payload: ChannelIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if payload.max_amount < payload.min_amount:
        raise HTTPException(422, "max_amount_below_min_amount")
    supplier = db.scalar(select(SupplierProfile).where(
        SupplierProfile.organization_id == user.organization_id,
        SupplierProfile.status == "active"))
    if not supplier:
        raise HTTPException(403, "active_supplier_profile_required")
    channel = PaymentChannel(supplier_id=supplier.id, name=payload.name, method=payload.method,
                            currency=payload.currency.upper(), min_amount=payload.min_amount,
                            max_amount=payload.max_amount, daily_limit=payload.daily_limit,
                            encrypted_details=encrypt_secret(json.dumps(payload.details, ensure_ascii=False)),
                            status="active")
    db.add(channel)
    db.commit()
    db.refresh(channel)
    return channel


@app.get("/api/v1/supplier/channels", response_model=list[ChannelOut])
def list_channels(user: User = Depends(current_user), db: Session = Depends(get_db)):
    supplier = db.scalar(select(SupplierProfile).where(SupplierProfile.organization_id == user.organization_id))
    if not supplier:
        raise HTTPException(404, "supplier_profile_not_found")
    return list(db.scalars(select(PaymentChannel).where(PaymentChannel.supplier_id == supplier.id)))


@app.post("/api/v1/payments", response_model=PaymentOut, status_code=201)
def create_payment(background_tasks: BackgroundTasks, payload: PaymentIn,
                   authorization: str | None = Header(default=None),
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
    methods = payload.payment_methods or ["sbp", "bank_transfer", "card"]
    channel_query = select(PaymentChannel).join(SupplierProfile).where(
        PaymentChannel.status == "active",
        PaymentChannel.currency == payload.currency.upper(),
        PaymentChannel.min_amount <= payload.amount,
        PaymentChannel.max_amount >= payload.amount,
        PaymentChannel.used_today + payload.amount <= PaymentChannel.daily_limit,
        SupplierProfile.status == "active",
        PaymentChannel.method.in_(methods),
    )
    channel = db.scalars(channel_query).first()
    if channel:
        channel.used_today += payload.amount
    public_id = "pay_" + uuid4().hex
    payment = Payment(public_id=public_id, project_id=project.id, idempotency_key=idempotency_key,
                      channel_id=channel.id if channel else None,
                      order_id=payload.order_id, amount=payload.amount, currency=payload.currency.upper(),
                      payment_url=f"{settings.app_name.lower().replace(' ', '-')}/pay/{public_id}",
                      success_url=str(payload.success_url) if payload.success_url else None,
                      fail_url=str(payload.fail_url) if payload.fail_url else None,
                      metadata_json=payload.metadata)
    db.add(payment)
    db.flush()
    event = emit_payment_event(db, payment, "payment.pending")
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(Payment).where(Payment.project_id == project.id, Payment.idempotency_key == idempotency_key))
        if existing:
            return payment_response(existing)
        raise HTTPException(409, "payment_conflict")
    db.refresh(payment)
    delivery = db.scalar(select(WebhookDelivery).where(WebhookDelivery.event_id == event.event_id))
    if delivery:
        background_tasks.add_task(deliver_webhook, delivery.id)
    return payment_response(payment)


@app.get("/api/v1/statistics")
def merchant_statistics(authorization: str | None = Header(default=None),
                       days: int = Query(default=30, ge=1, le=365), db: Session = Depends(get_db)):
    _, project = api_context(authorization, db)
    since = datetime.now(timezone.utc) - __import__("datetime").timedelta(days=days)
    query = select(Payment).where(Payment.project_id == project.id, Payment.created_at >= since)
    payments = db.scalars(query).all()
    succeeded = [p for p in payments if p.status == "succeeded"]
    return {"period_days": days, "payments": len(payments), "succeeded": len(succeeded),
            "failed": sum(p.status == "failed" for p in payments),
            "conversion_percent": round((len(succeeded) / len(payments) * 100), 2) if payments else 0,
            "gross": str(sum((p.amount for p in succeeded), Decimal("0"))),
            "platform_fees": str(sum((p.platform_fee for p in succeeded), Decimal("0"))),
            "supplier_fees": str(sum((p.supplier_fee for p in succeeded), Decimal("0"))),
            "merchant_net": str(sum((p.merchant_net for p in succeeded), Decimal("0"))),
            "average_check": str((sum((p.amount for p in succeeded), Decimal("0")) / len(succeeded)).quantize(Decimal("0.01"))) if succeeded else "0.00"}


@app.get("/api/v1/balance")
def merchant_balance(authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    _, project = api_context(authorization, db)
    balance = organization_balance(db, project.organization_id, "RUB")
    return {"available": str(balance), "currency": "RUB"}


@app.post("/api/v1/wallet", status_code=201)
def save_wallet(payload: WalletIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    wallet = db.scalar(select(CryptoWallet).where(CryptoWallet.organization_id == user.organization_id))
    if wallet:
        wallet.currency, wallet.network, wallet.address, wallet.status = payload.currency, payload.network, payload.address, "pending"
    else:
        wallet = CryptoWallet(organization_id=user.organization_id, currency=payload.currency,
                              network=payload.network, address=payload.address, status="pending")
        db.add(wallet)
    db.commit()
    return {"id": wallet.id, "currency": wallet.currency, "network": wallet.network,
            "address": wallet.address, "status": wallet.status}


@app.post("/api/v1/payouts", status_code=201)
def create_payout(payload: PayoutIn, authorization: str | None = Header(default=None),
                  idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
                  db: Session = Depends(get_db)):
    if not idempotency_key:
        raise HTTPException(400, "idempotency_key_required")
    _, project = api_context(authorization, db)
    available = organization_balance(db, project.organization_id, payload.currency)
    if payload.amount > available:
        raise HTTPException(422, "insufficient_balance")
    payout_id = "po_" + uuid4().hex
    payout = Payout(public_id=payout_id, organization_id=project.organization_id, amount=payload.amount,
                    currency=payload.currency.upper(), crypto_currency=payload.crypto_currency,
                    network=payload.network, address=payload.address, status="pending")
    db.add(payout)
    db.flush()
    db.add(LedgerEntry(organization_id=project.organization_id, amount=-payload.amount,
                       currency=payload.currency.upper(), entry_type="payout_reserve",
                       description=f"Payout {payout_id}"))
    db.commit()
    return {"id": payout.public_id, "amount": str(payout.amount), "currency": payout.currency,
            "crypto_currency": payout.crypto_currency, "network": payout.network,
            "address": payout.address, "status": payout.status}


@app.get("/api/v1/payments/{public_id}", response_model=PaymentOut)
def get_payment(public_id: str, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    _, project = api_context(authorization, db)
    payment = db.scalar(select(Payment).where(Payment.public_id == public_id, Payment.project_id == project.id))
    if not payment:
        raise HTTPException(404, "payment_not_found")
    return payment_response(payment)
