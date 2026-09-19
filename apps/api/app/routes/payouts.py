from fastapi import APIRouter
from ..main import *

router = APIRouter(tags=["payouts", "analytics"])

@router.get("/api/v1/statistics")
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


@router.get("/api/v1/balance")
def merchant_balance(authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    _, project = api_context(authorization, db)
    balance = organization_balance(db, project.organization_id, "RUB")
    return {"available": str(balance), "currency": "RUB"}


@router.post("/api/v1/wallet", status_code=201)
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


@router.post("/api/v1/payouts", status_code=201)
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


