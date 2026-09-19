from fastapi import APIRouter
from ..main import *

router = APIRouter(prefix="/api/v1", tags=["supplier"])

@router.post("/api/v1/supplier", status_code=201)
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


@router.post("/api/v1/supplier/channels", response_model=ChannelOut, status_code=201)
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


@router.get("/api/v1/supplier/channels", response_model=list[ChannelOut])
def list_channels(user: User = Depends(current_user), db: Session = Depends(get_db)):
    supplier = db.scalar(select(SupplierProfile).where(SupplierProfile.organization_id == user.organization_id))
    if not supplier:
        raise HTTPException(404, "supplier_profile_not_found")
    return list(db.scalars(select(PaymentChannel).where(PaymentChannel.supplier_id == supplier.id)))



