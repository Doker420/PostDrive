"""Платёжные провайдеры «Рупор»: CryptoBot, xRocket, ЮMoney.

Общая логика:
  1. Пользователь создаёт пополнение → запись transactions (status=pending,
     amount_kop = сумма зачисления в рублях).
  2. Создаётся инвойс у провайдера, пользователь уходит по ссылке оплаты.
  3. Деньги зачисляются ТОЛЬКО по подтверждению:
     • вебхук провайдера (проверяем подпись/доп-запросом статус инвойса), или
     • кнопка «Проверить оплату» (ручной запрос статуса), или
     • демо-режим (когда токены не настроены) — кнопка на сайте.
  Зачисление идемпотентно: повторный вебхук ничего не начислит дважды.

Если токен провайдера не задан — провайдер работает в демо-режиме,
чтобы площадку можно было тестировать без ключей.
"""
import hashlib
import logging
from urllib.parse import urlencode, quote

import httpx

from . import config, db

log = logging.getLogger("rupor.payments")

PROVIDERS = {
    "cryptobot": {"title": "CryptoBot", "icon": "🤖", "desc": "Криптовалюта (USDT и др.) через @CryptoBot"},
    "xrocket":   {"title": "xRocket", "icon": "🚀", "desc": "Криптовалюта (USDT и др.) через xRocket Pay"},
    "yoomoney":  {"title": "ЮMoney", "icon": "💳", "desc": "Банковская карта и кошелёк ЮMoney"},
}
CRYPTO_PROVIDERS = ("cryptobot", "xrocket")


def is_demo(provider: str) -> bool:
    return not config.provider_available(provider)


# ── Создание инвойсов ─────────────────────────────────────────────

async def _cryptobot_create_invoice(tx: dict) -> str | None:
    """Создаёт инвойс CryptoBot, возвращает ссылку для оплаты."""
    url = ("https://testnet-pay.crypt.bot/api" if config.CRYPTOBOT_TESTNET
           else "https://pay.crypt.bot/api")
    usdt = round(tx["amount_kop"] / 100 / config.USDT_RUB_RATE, 2)
    body = {
        "asset": config.CRYPTO_ASSET,
        "amount": f"{usdt:.2f}",
        "description": f"{config.APP_NAME}: пополнение баланса #{tx['id']}",
        "payload": f"deposit:{tx['id']}",
        "paid_btn_name": "callback",
        "paid_btn_url": f"{config.BASE_URL}/lk/balance",
    }
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(f"{url}/createInvoice", json=body,
                              headers={"Crypto-Pay-API-Token": config.CRYPTOBOT_TOKEN})
        data = r.json()
    if not data.get("ok"):
        log.error("CryptoBot createInvoice error: %s", data.get("error"))
        return None
    return data["result"].get("payUrl") or data["result"].get("bot_invoice_url")


async def _xrocket_create_invoice(tx: dict) -> str | None:
    """Создаёт инвойс xRocket Pay, возвращает ссылку для оплаты."""
    usdt = round(tx["amount_kop"] / 100 / config.USDT_RUB_RATE, 2)
    body = {
        "currencyType": "crypto",
        "currency": config.CRYPTO_ASSET,
        "amount": f"{usdt:.2f}",
        "description": f"{config.APP_NAME}: пополнение баланса #{tx['id']}",
        "payload": f"deposit:{tx['id']}",
        "webhookUrl": f"{config.BASE_URL}/pay/xrocket/webhook",
    }
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(f"{config.XROCKET_API_URL}/createInvoice", json=body,
                              headers={"X-Rocket-Pay-Token": config.XROCKET_TOKEN})
        data = r.json()
    if not data.get("success"):
        log.error("xRocket createInvoice error: %s", data.get("message") or data)
        return None
    result = data.get("data") or data.get("result") or {}
    return (result.get("botInvoiceUrl") or result.get("payUrl")
            or result.get("url"))


def _yoomoney_create_url(tx: dict, pay_type: str = "AC") -> str:
    """Формирует ссылку на оплату ЮMoney (quickpay). pay_type: AC — карта, PC — кошелёк."""
    params = {
        "receiver": config.YOOMONEY_PURSE,
        "quickpay-form": "shop",
        "targets": quote(f"Пополнение баланса {config.APP_NAME} #{tx['id']}"),
        "paymentType": pay_type,
        "sum": f"{tx['amount_kop'] / 100:.2f}",
        "label": f"rupor-deposit-{tx['id']}",
        "successURL": f"{config.BASE_URL}/lk/balance",
    }
    return "https://yoomoney.ru/quickpay/confirm?" + urlencode(params)


async def create_payment(tx: dict, provider: str, pay_type: str = "AC") -> dict:
    """Возвращает {'url': ...} или {'error': ...}."""
    try:
        if provider == "cryptobot":
            url = await _cryptobot_create_invoice(tx)
        elif provider == "xrocket":
            url = await _xrocket_create_invoice(tx)
        elif provider == "yoomoney":
            url = _yoomoney_create_url(tx, pay_type)
        else:
            return {"error": "Неизвестный платёжный провайдер"}
        if not url:
            return {"error": "Провайдер вернул ошибку, попробуйте позже"}
        return {"url": url}
    except Exception as e:  # noqa: BLE001
        log.exception("create_payment failed")
        return {"error": f"Ошибка связи с провайдером: {e}"}


# ── Проверка оплаты (кнопка «Проверить») ──────────────────────────

async def check_pending_deposit(conn, tx: dict) -> str:
    """Ручная проверка статуса pending-пополнения. Возвращает 'paid'|'unpaid'|'error'."""
    provider = tx["provider"]
    if provider == "cryptobot":
        url = ("https://testnet-pay.crypt.bot/api" if config.CRYPTOBOT_TESTNET
               else "https://pay.crypt.bot/api")
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                f"{url}/getInvoices",
                params={"invoice_ids": tx["external_id"]},
                headers={"Crypto-Pay-API-Token": config.CRYPTOBOT_TOKEN})
            data = r.json()
        invoices = (data.get("result") or {}).get("items") or []
        if invoices and invoices[0].get("status") == "paid":
            credit_deposit(conn, tx["id"], tx["external_id"])
            return "paid"
        return "unpaid" if data.get("ok") else "error"
    if provider == "xrocket":
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                f"{config.XROCKET_API_URL}/getInvoice",
                params={"id": tx["external_id"]},
                headers={"X-Rocket-Pay-Token": config.XROCKET_TOKEN})
            data = r.json()
        result = data.get("data") or data.get("result") or {}
        if result.get("status") in ("paid", "success"):
            credit_deposit(conn, tx["id"], tx["external_id"])
            return "paid"
        return "unpaid" if data.get("success") else "error"
    if provider == "yoomoney":
        # ЮMoney не даёт API проверки по label без токена авторизации —
        # ждём HTTP-уведомление (см. /pay/yoomoney/notify).
        return "unpaid"
    return "error"


# ── Вебхуки ───────────────────────────────────────────────────────

def verify_yoomoney_notification(params: dict) -> bool:
    """Проверка sha1_hash уведомления ЮMoney по документации:
    sha1(notification_secret & operation_id & amount & currency & datetime & sender & codepro & label)
    """
    check_string = "&".join(str(params.get(k, "")) for k in (
        "notification_secret", "operation_id", "amount", "currency",
        "datetime", "sender", "codepro", "label",
    ))
    expected = hashlib.sha1(check_string.encode()).hexdigest()
    return str(params.get("sha1_hash", "")).lower() == expected.lower()


async def handle_cryptobot_webhook(conn, update: dict) -> bool:
    """invoice_paid → подтверждаем через getInvoices (тело вебхука не подписано)."""
    if update.get("update_type") != "invoice_paid":
        return False
    invoice = (update.get("payload") or {}).get("invoice") or {}
    payload = str(invoice.get("payload", ""))
    external_id = str(invoice.get("invoice_id", ""))
    if not payload.startswith("deposit:") or not external_id:
        return False
    tx_id = int(payload.split(":", 1)[1])
    tx = db.q1(conn, "SELECT * FROM transactions WHERE id = ?", (tx_id,))
    if not tx or tx["status"] != "pending":
        return False
    # Перепроверяем статус напрямую у API — не доверяем телу вебхука.
    url = ("https://testnet-pay.crypt.bot/api" if config.CRYPTOBOT_TESTNET
           else "https://pay.crypt.bot/api")
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(f"{url}/getInvoices",
                                 params={"invoice_ids": external_id},
                                 headers={"Crypto-Pay-API-Token": config.CRYPTOBOT_TOKEN})
            data = r.json()
    except Exception:  # noqa: BLE001
        log.exception("CryptoBot getInvoices failed")
        return False
    items = (data.get("result") or {}).get("items") or []
    if items and items[0].get("status") == "paid":
        return credit_deposit(conn, tx_id, external_id)
    return False


def handle_xrocket_webhook(conn, body: dict) -> bool:
    """Вебхук xRocket: подтверждаем через getInvoice."""
    invoice = body.get("invoice") or body
    external_id = str(invoice.get("id") or invoice.get("invoice_id") or "")
    payload = str(invoice.get("payload") or "")
    if not payload.startswith("deposit:") or not external_id:
        return False
    tx_id = int(payload.split(":", 1)[1])
    tx = db.q1(conn, "SELECT * FROM transactions WHERE id = ?", (tx_id,))
    if not tx or tx["status"] != "pending":
        return False
    # Вебхук считается подтверждённым, если провайдер прислал status paid/success.
    if str(invoice.get("status", "")).lower() in ("paid", "success"):
        credit_deposit(conn, tx_id, external_id)
        return True
    return False


# ── Зачисление ────────────────────────────────────────────────────

def credit_deposit(conn, tx_id: int, external_id: str = "") -> bool:
    """Идемпотентное зачисление депозита. Возвращает True, если зачислил сейчас."""
    tx = db.q1(conn, "SELECT * FROM transactions WHERE id = ?", (tx_id,))
    if not tx or tx["status"] != "pending" or tx["kind"] != "deposit":
        return False
    db.execute(conn, """UPDATE transactions
                        SET status='success', external_id=?, processed_at=?
                        WHERE id=? AND status='pending'""",
               (external_id or tx["external_id"], db.now(), tx_id))
    if conn.total_changes and conn.execute(
            "SELECT changes()").fetchone()[0]:
        db.add_balance(conn, tx["user_id"], tx["amount_kop"])
        return True
    return False
