from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..db import get_db
from ..models import NotificationSetting, TelegramIntegration, User
from ..security import encrypt_secret

router = APIRouter(prefix="/api/v1", tags=["notifications"])

class NotificationSettingsIn(BaseModel):
    enabled_events: list[str] = Field(default_factory=list)
    telegram_enabled: bool = True
    email_enabled: bool = False

class TelegramIn(BaseModel):
    bot_token: str = Field(min_length=20, max_length=300)
    chat_id: str = Field(min_length=1, max_length=80)

def current_user():
    from ..main import current_user as dependency
    return dependency

@router.get("/notifications")
def get_settings(user: User = Depends(current_user()), db: Session = Depends(get_db)):
    row = db.scalar(select(NotificationSetting).where(NotificationSetting.organization_id == user.organization_id))
    if not row:
        row = NotificationSetting(organization_id=user.organization_id); db.add(row); db.commit()
    return {"enabled_events": row.enabled_events, "telegram_enabled": row.telegram_enabled, "email_enabled": row.email_enabled}

@router.patch("/notifications")
def update_settings(payload: NotificationSettingsIn, user: User = Depends(current_user()), db: Session = Depends(get_db)):
    row = db.scalar(select(NotificationSetting).where(NotificationSetting.organization_id == user.organization_id))
    if not row: row = NotificationSetting(organization_id=user.organization_id); db.add(row)
    row.enabled_events, row.telegram_enabled, row.email_enabled = payload.enabled_events, payload.telegram_enabled, payload.email_enabled
    db.commit()
    return {"enabled_events": row.enabled_events, "telegram_enabled": row.telegram_enabled, "email_enabled": row.email_enabled}

@router.post("/telegram", status_code=201)
def connect(payload: TelegramIn, user: User = Depends(current_user()), db: Session = Depends(get_db)):
    row = db.scalar(select(TelegramIntegration).where(TelegramIntegration.organization_id == user.organization_id))
    if not row:
        row = TelegramIntegration(organization_id=user.organization_id, bot_token_encrypted=encrypt_secret(payload.bot_token), chat_id=payload.chat_id)
        db.add(row)
    else:
        row.bot_token_encrypted, row.chat_id, row.status = encrypt_secret(payload.bot_token), payload.chat_id, "active"
    db.commit()
    return {"id": row.id, "chat_id": row.chat_id, "status": row.status}

@router.delete("/telegram")
def disconnect(user: User = Depends(current_user()), db: Session = Depends(get_db)):
    row = db.scalar(select(TelegramIntegration).where(TelegramIntegration.organization_id == user.organization_id))
    if not row: raise HTTPException(404, "telegram_not_connected")
    row.status = "disabled"; db.commit(); return {"status": "disabled"}
