from fastapi import APIRouter
from ..main import *  # shared dependencies are initialized before router registration

router = APIRouter(tags=["payments"])

@router.post("/api/v1/payments", response_model=PaymentOut, status_code=201)
def create_payment(background_tasks: BackgroundTasks, payload: PaymentIn,
                   authorization: str | None = Header(default=None),
                   idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
                   db: Session = Depends(get_db)):
    _, project = api_context(authorization, db)
    if not idempotency_key:
        raise HTTPException(400, "idempotency_key_required")
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
                      payment_url=f"/web/checkout.html?payment={public_id}",
                      success_url=str(payload.success_url) if payload.success_url else None,
                      fail_url=str(payload.fail_url) if payload.fail_url else None,
                      metadata_json=payload.metadata)
    score, reasons = score_payment(payload.amount, bool(channel))
    payment.risk_score = score
    payment.risk_status = "review" if score >= 50 else "clear"
    db.add(payment)
    db.flush()
    if score:
        db.add(RiskEvent(payment_id=payment.id, organization_id=project.organization_id,
                         score=score, status="open", reason=",".join(reasons)))
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
    background_tasks.add_task(send_telegram, project.organization_id,
                              f"FlowPay: создан платеж {payment.public_id}\\nСумма: {payment.amount} {payment.currency}")
    return payment_response(payment)


@router.get("/api/v1/checkout/{public_id}")
def checkout(public_id: str, db: Session = Depends(get_db)):
    payment = db.scalar(select(Payment).where(Payment.public_id == public_id))
    if not payment:
        raise HTTPException(404, "payment_not_found")
    details, method_label = {}, "Payment channel"
    if payment.channel_id:
        channel = db.get(PaymentChannel, payment.channel_id)
        if channel:
            method_label = {"sbp": "СБП", "card": "Банковская карта", "bank_transfer": "Банковский перевод"}.get(channel.method, channel.method)
            try:
                details = json.loads(decrypt_secret(channel.encrypted_details))
            except Exception:
                details = {}
    return {"id": payment.public_id, "amount": str(payment.amount), "currency": payment.currency,
            "order_id": payment.order_id, "status": payment.status, "method_label": method_label,
            "details": details, "success_url": payment.success_url, "fail_url": payment.fail_url}


@router.post("/api/v1/checkout/{public_id}/check")
def checkout_check(public_id: str, db: Session = Depends(get_db)):
    payment = db.scalar(select(Payment).where(Payment.public_id == public_id))
    if not payment:
        raise HTTPException(404, "payment_not_found")
    return {"id": payment.public_id, "status": payment.status}


@router.get("/api/v1/payments/{public_id}", response_model=PaymentOut)
def get_payment(public_id: str, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    _, project = api_context(authorization, db)
    payment = db.scalar(select(Payment).where(Payment.public_id == public_id, Payment.project_id == project.id))
    if not payment:
        raise HTTPException(404, "payment_not_found")
    return payment_response(payment)

