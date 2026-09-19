from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..models import LedgerEntry


def balance(db: Session, organization_id: int, currency: str) -> Decimal:
    entries = db.scalars(select(LedgerEntry).where(
        LedgerEntry.organization_id == organization_id,
        LedgerEntry.currency == currency.upper())).all()
    return sum((Decimal(str(item.amount)) for item in entries), Decimal("0"))
