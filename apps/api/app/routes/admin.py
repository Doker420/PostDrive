from fastapi import APIRouter
from ..main import *

router = APIRouter(tags=["admin"])

@router.post("/api/v1/admin/bootstrap", status_code=201)
def bootstrap_admin(email: str, bootstrap_token: str = Header(alias="X-Admin-Bootstrap-Token"), db: Session = Depends(get_db)):
    if bootstrap_token != settings.admin_bootstrap_token:
        raise HTTPException(403, "invalid_bootstrap_token")
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    if not user:
        raise HTTPException(404, "user_not_found")
    user.role = "admin"
    db.commit()
    return {"status": "ok", "user_id": user.id, "role": user.role}


@router.get("/api/v1/export/payments.csv")
def merchant_payments_csv(authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    _, project = api_context(authorization, db)
    rows = db.scalars(select(Payment).where(Payment.project_id == project.id).order_by(Payment.created_at.desc())).all()
    lines = ["id,order_id,amount,currency,status,platform_fee,supplier_fee,merchant_net,created_at"]
    lines += [f"{p.public_id},{p.order_id},{p.amount},{p.currency},{p.status},{p.platform_fee},{p.supplier_fee},{p.merchant_net},{p.created_at.isoformat()}" for p in rows]
    return Response(content="\n".join(lines), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=flowpay-payments.csv"})


@router.get("/api/v1/admin/statistics")
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


@router.get("/api/v1/admin/overview")
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


@router.get("/api/v1/admin/suppliers")
def admin_suppliers(_: User = Depends(admin_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(SupplierProfile).order_by(SupplierProfile.created_at.desc())).all()
    return [{"id": row.id, "organization_id": row.organization_id, "display_name": row.display_name,
             "status": row.status, "commission_percent": row.commission_percent,
             "channels": db.query(PaymentChannel).filter(PaymentChannel.supplier_id == row.id).count()}
            for row in rows]


@router.patch("/api/v1/admin/suppliers/{supplier_id}")
def admin_supplier_status(supplier_id: int, payload: AdminStatusIn, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    supplier = db.get(SupplierProfile, supplier_id)
    if not supplier:
        raise HTTPException(404, "supplier_not_found")
    supplier.status = payload.status
    if payload.status != "active":
        db.query(PaymentChannel).filter(PaymentChannel.supplier_id == supplier.id).update({"status": "inactive"})
    db.commit()
    return {"id": supplier.id, "status": supplier.status}


@router.get("/api/v1/admin/channels")
def admin_channels(_: User = Depends(admin_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(PaymentChannel).order_by(PaymentChannel.created_at.desc())).all()
    return [{"id": row.id, "supplier_id": row.supplier_id, "name": row.name, "method": row.method,
             "currency": row.currency, "min_amount": row.min_amount, "max_amount": row.max_amount,
             "daily_limit": row.daily_limit, "used_today": row.used_today, "status": row.status}
            for row in rows]


@router.patch("/api/v1/admin/channels/{channel_id}")
def admin_channel_status(channel_id: int, payload: AdminChannelStatusIn, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    channel = db.get(PaymentChannel, channel_id)
    if not channel:
        raise HTTPException(404, "channel_not_found")
    channel.status = payload.status
    db.commit()
    return {"id": channel.id, "status": channel.status}


@router.patch("/api/v1/admin/payments/{public_id}/status")
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
    background_tasks.add_task(send_telegram, project.organization_id,
                              f"FlowPay: платеж {payment.public_id} → {payment.status}\\nСумма: {payment.amount} {payment.currency}")
    return {"id": payment.public_id, "old_status": old_status, "status": payment.status}


@router.post("/api/v1/admin/webhook-deliveries/{delivery_id}/retry")
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


@router.get("/api/v1/admin/webhook-deliveries")
def admin_webhook_deliveries(_: User = Depends(admin_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(WebhookDelivery).order_by(WebhookDelivery.created_at.desc()).limit(100)).all()
    return [{"id": row.id, "event_id": row.event_id, "project_id": row.project_id,
             "url": row.url, "status": row.status, "attempts": row.attempts,
             "last_error": row.last_error, "created_at": row.created_at} for row in rows]


@router.get("/api/v1/admin/payouts")
def admin_payouts(_: User = Depends(admin_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Payout).order_by(Payout.created_at.desc()).limit(100)).all()
    return [{"id": row.public_id, "organization_id": row.organization_id, "amount": row.amount,
             "currency": row.currency, "crypto_currency": row.crypto_currency,
             "network": row.network, "address": row.address, "status": row.status,
             "tx_hash": row.tx_hash, "created_at": row.created_at} for row in rows]


@router.patch("/api/v1/admin/payouts/{public_id}/status")
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


@router.get("/api/v1/admin/payments")
def admin_payments(_: User = Depends(admin_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Payment).order_by(Payment.created_at.desc()).limit(100)).all()
    return [{"id": row.public_id, "project_id": row.project_id, "channel_id": row.channel_id,
             "order_id": row.order_id, "amount": row.amount, "currency": row.currency,
             "status": row.status, "created_at": row.created_at} for row in rows]



