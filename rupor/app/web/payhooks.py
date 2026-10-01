"""Вебхуки платёжных провайдеров + демо-оплата."""
import logging

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse

from .. import db, payments
from ..auth import flash, login_required
from .helpers import redirect, render, validate_csrf_or_flash, read_form

log = logging.getLogger("rupor.payhooks")
router = APIRouter()


@router.post("/pay/cryptobot/webhook")
async def cryptobot_webhook(request: Request):
    update = await request.json()
    conn = db.get_db()
    try:
        await payments.handle_cryptobot_webhook(conn, update)
    except Exception:  # noqa: BLE001
        log.exception("CryptoBot webhook error")
    finally:
        conn.close()
    return PlainTextResponse("ok")


@router.post("/pay/xrocket/webhook")
async def xrocket_webhook(request: Request):
    body = await request.json()
    conn = db.get_db()
    try:
        payments.handle_xrocket_webhook(conn, body)
    except Exception:  # noqa: BLE001
        log.exception("xRocket webhook error")
    finally:
        conn.close()
    return PlainTextResponse("ok")


@router.post("/pay/yoomoney/notify")
async def yoomoney_notify(request: Request):
    """HTTP-уведомление ЮMoney (форма). Проверяем sha1 и зачисляем по label."""
    from .. import config
    form = dict(await request.form())
    conn = db.get_db()
    try:
        params = dict(form)
        params["notification_secret"] = config.YOOMONEY_SECRET
        if not payments.verify_yoomoney_notification(params):
            log.warning("YooMoney notification hash mismatch: %s", form.get("operation_id"))
            return PlainTextResponse("forbidden", status_code=403)
        label = str(form.get("label", ""))
        if label.startswith("rupor-deposit-"):
            tx_id = int(label.split("-")[-1])
            payments.credit_deposit(conn, tx_id, str(form.get("operation_id", "")))
    except Exception:  # noqa: BLE001
        log.exception("YooMoney notify error")
    finally:
        conn.close()
    return PlainTextResponse("ok")


# ── Демо-оплата (когда ключи провайдера не настроены) ─────────────

@router.get("/pay/demo/{tx_id}")
@login_required
def demo_pay(request: Request, tx_id: int):
    user = request.state.user
    conn = db.get_db()
    try:
        tx = db.q1(conn, "SELECT * FROM transactions WHERE id=? AND user_id=? AND kind='deposit'",
                   (tx_id, user["id"]))
    finally:
        conn.close()
    if not tx:
        return redirect("/lk/balance", "Пополнение не найдено", "error")
    if tx["status"] != "pending":
        return redirect("/lk/balance", "Пополнение уже обработано", "warn")
    provider = payments.PROVIDERS.get(tx["provider"], {})
    return render(request, "pay/demo.html", tx=tx, provider=provider)


@router.post("/pay/demo/{tx_id}/confirm")
@login_required
async def demo_confirm(request: Request, tx_id: int):
    user = request.state.user
    form = await read_form(request)
    fail = validate_csrf_or_flash(request, form, f"/pay/demo/{tx_id}")
    if fail:
        return fail
    conn = db.get_db()
    try:
        tx = db.q1(conn, "SELECT * FROM transactions WHERE id=? AND user_id=? AND kind='deposit'",
                   (tx_id, user["id"]))
        if not tx or tx["status"] != "pending":
            return redirect("/lk/balance", "Пополнение уже обработано", "warn")
        if not payments.is_demo(tx["provider"]):
            return redirect("/lk/balance", "Провайдер работает в боевом режиме — оплатите по инвойсу", "error")
        payments.credit_deposit(conn, tx_id, "demo")
    finally:
        conn.close()
    return redirect("/lk/balance", "Демо-оплата проведена: баланс пополнен", "ok")
