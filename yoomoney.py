"""YooMoney P2P payment links and HTTP notification verification.

The payment form itself is public (it only needs the receiver wallet). The
notification endpoint is the authoritative credit path and accepts both the
current HMAC-SHA256 ``sign`` field and the legacy SHA-1 field while YooMoney's
migration is in progress.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Dict, Optional
from urllib.parse import quote, urlencode

try:
    import aiohttp
    from aiohttp import web
except ImportError:  # Keep signature/URL helpers usable in lightweight test tools.
    aiohttp = None
    web = None

logger = logging.getLogger(__name__)

YOOMONEY_CURRENCY = "643"  # RUB, ISO 4217 numeric code used by notifications


def money(value: Any) -> Decimal:
    """Parse an amount without using binary floats for payment comparisons."""
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("invalid monetary amount")


def usd_to_rub(amount_usd: Any, rub_per_usd: Any = 100) -> Decimal:
    """Convert a tariff's USD price to a configurable YooMoney RUB amount."""
    result = money(amount_usd) * Decimal(str(rub_per_usd))
    return result.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def make_label() -> str:
    """Generate a non-guessable label that fits YooMoney's label field."""
    return "PD-" + uuid.uuid4().hex


def build_payment_url(receiver: str, amount_rub: Any, label: str,
                      description: str = "PostDrive subscription",
                      success_url: str = "") -> str:
    """Build a YooMoney QuickPay P2P form URL.

    ``label`` is echoed by the HTTP notification and is the only way to map an
    incoming transfer to a pending user payment, so it is always included.
    """
    amount = money(amount_rub)
    params = {
        "receiver": str(receiver).strip(),
        "quickpay": "shop",
        "paymentType": "AC",  # bank card / YooMoney payment form
        "sum": format(amount, ".2f"),
        "label": str(label),
        "targets": description[:200],
        "short-dest": description[:200],
    }
    if success_url:
        params["successURL"] = success_url
    return "https://yoomoney.ru/quickpay/confirm.xml?" + urlencode(params)


def _legacy_sha1_payload(data: Dict[str, Any], secret: str) -> str:
    fields = (
        "notification_type", "operation_id", "amount", "currency",
        "datetime", "sender", "codepro",
    )
    raw = "&".join(str(data.get(field, "")) for field in fields)
    return hashlib.sha1((raw + "&" + secret + "&" + str(data.get("label", ""))).encode("utf-8")).hexdigest()


def _modern_sign_payload(data: Dict[str, Any]) -> str:
    # YooMoney specifies URL-encoding values, alphabetical parameter order,
    # and key=value pairs separated by ampersands. The sign field itself is
    # excluded; sha1_hash is retained if YooMoney sends it during migration.
    parts = []
    for key in sorted(data):
        if key == "sign":
            continue
        value = str(data.get(key, ""))
        parts.append(f"{key}={quote(value, safe='~-._')}")
    return "&".join(parts)


def verify_notification(data: Dict[str, Any], secret: str) -> bool:
    """Verify a YooMoney notification using the current or legacy signature."""
    if not secret:
        return False
    received_sign = str(data.get("sign", "")).strip().lower()
    if received_sign:
        expected = hmac.new(
            secret.encode("utf-8"),
            _modern_sign_payload(data).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(received_sign, expected)

    received_sha1 = str(data.get("sha1_hash", "")).strip().lower()
    if not received_sha1:
        return False
    return hmac.compare_digest(received_sha1, _legacy_sha1_payload(data, secret))


class YooMoneyOperationVerifier:
    """Optional defense-in-depth check against the wallet history API.

    A valid signed notification is already authenticated. If an OAuth token
    with the ``operation-history`` permission is configured, this verifier
    additionally checks that the operation exists in the receiver wallet. API
    outages are treated as unknown (and are logged); a contradictory API
    result is rejected.
    """

    def __init__(self, token: str):
        self.token = (token or '').strip()

    async def verify(self, operation_id: str, label: str, amount: Any) -> Optional[bool]:
        if not self.token or aiohttp is None:
            return None
        try:
            timeout = aiohttp.ClientTimeout(total=8)
            headers = {"Authorization": f"Bearer {self.token}"}
            payload = {"type": "deposition", "label": label, "records": "100"}
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    "https://yoomoney.ru/api/operation-history",
                    data=payload,
                    headers=headers,
                ) as response:
                    if response.status != 200:
                        logger.warning("YooMoney operation-history returned HTTP %s", response.status)
                        return None
                    body = await response.json(content_type=None)
            if body.get("error"):
                logger.warning("YooMoney operation-history returned an API error")
                return None
            expected = money(amount)
            for operation in body.get("operations", []) or []:
                if str(operation.get("operation_id", "")) != str(operation_id):
                    continue
                if str(operation.get("status", "")).lower() != "success":
                    return False
                if operation.get("label") not in (None, "", label):
                    return False
                try:
                    return money(operation.get("amount")) == expected
                except ValueError:
                    return False
            return False
        except Exception as error:
            logger.warning("YooMoney operation-history check unavailable: %s", error)
            return None


class YooMoneyWebhook:
    """Small aiohttp endpoint used by the main bot process."""

    def __init__(self, db, bot, receiver: str, secret: str,
                 path: str = "/yoomoney/webhook", oauth_token: str = ""):
        if web is None:
            raise RuntimeError("aiohttp is required for the YooMoney webhook")
        self.db = db
        self.bot = bot
        self.receiver = receiver
        self.secret = secret
        self.operation_verifier = YooMoneyOperationVerifier(oauth_token)
        self.path = "/" + path.strip("/")
        self.app = web.Application(client_max_size=64 * 1024)
        self.app.router.add_post(self.path, self.handle)
        self.app.router.add_get(self.path, self.health)

    async def health(self, _request):
        return web.Response(text="ok", content_type="text/plain")

    async def handle(self, request: web.Request):
        try:
            form = await request.post()
            data = {str(key): str(value) for key, value in form.items()}
        except Exception as error:
            logger.warning("YooMoney webhook body parse failed: %s", error)
            return web.Response(status=400, text="bad request")

        if not verify_notification(data, self.secret):
            logger.warning(
                "YooMoney webhook signature rejected: operation=%s label=%s",
                data.get("operation_id", ""), data.get("label", "")
            )
            return web.Response(status=403, text="invalid signature")

        # Test notifications must be acknowledged but never credit a user.
        if data.get("test_notification", "").lower() == "true":
            return web.Response(status=200, text="ok")

        notification_type = data.get("notification_type", "")
        if notification_type not in ("p2p-incoming", "card-incoming"):
            logger.info("YooMoney notification ignored: type=%s", notification_type)
            return web.Response(status=200, text="ignored")
        if data.get("unaccepted", "false").lower() == "true":
            logger.warning("YooMoney transfer is unaccepted: operation=%s", data.get("operation_id"))
            return web.Response(status=200, text="pending")
        if data.get("codepro", "false").lower() == "true":
            logger.warning("YooMoney protected transfer ignored: operation=%s", data.get("operation_id"))
            return web.Response(status=200, text="ignored")
        if data.get("currency", "") != YOOMONEY_CURRENCY:
            logger.warning("YooMoney notification has unsupported currency=%s", data.get("currency", ""))
            return web.Response(status=200, text="unsupported currency")

        label = data.get("label", "").strip()
        operation_id = data.get("operation_id", "").strip()
        amount = data.get("amount", "").strip()
        if not label or not operation_id or not amount:
            logger.warning("YooMoney notification has no label/operation/amount")
            return web.Response(status=200, text="ignored")

        api_verification = await self.operation_verifier.verify(operation_id, label, amount)
        if api_verification is False:
            logger.warning("YooMoney operation-history rejected operation=%s", operation_id)
            return web.Response(status=200, text="operation rejected")
        if api_verification is None and self.operation_verifier.token:
            logger.warning("YooMoney operation-history unavailable; using valid signed notification")

        result = self.db.mark_yoomoney_payment_paid(
            label=label,
            operation_id=operation_id,
            amount=amount,
            currency=data.get("currency", ""),
        )
        if result.get("status") == "amount_mismatch":
            logger.error(
                "YooMoney amount mismatch for label=%s: received=%s expected=%s",
                label, amount, result.get("expected_amount")
            )
            return web.Response(status=200, text="amount mismatch")
        if result.get("status") == "unknown_label":
            logger.warning("YooMoney notification for unknown label=%s", label)
            return web.Response(status=200, text="unknown label")
        if result.get("status") == "duplicate_operation":
            return web.Response(status=200, text="duplicate")

        if result.get("credited"):
            await self._notify_paid(result)
        return web.Response(status=200, text="ok")

    async def _notify_paid(self, result: Dict[str, Any]):
        user_id = result.get("user_id")
        if not user_id or not self.bot:
            return
        try:
            until = result.get("subscription_until")
            try:
                until_text = datetime.fromtimestamp(int(until), tz=timezone.utc).strftime("%d.%m.%Y")
            except (TypeError, ValueError, OverflowError, OSError):
                until_text = "обновлено"
            await asyncio.wait_for(
                self.bot.send_message(
                    user_id,
                    "🎉 <b>Оплата через ЮMoney получена!</b>\n\n"
                    f"Тариф: <b>{result.get('tariff_name', 'PostDrive')}</b>\n"
                    f"Зачислено: <b>{result.get('amount', '')} ₽</b>\n"
                    f"Подписка активна до: <b>{until_text}</b>",
                ),
                timeout=5,
            )
        except Exception as error:
            # Credit is already persisted; a Bot API outage must not make
            # YooMoney resend the same payment.
            logger.warning("Could not notify user %s about YooMoney payment: %s", user_id, error)

        # Keep the existing 30% referral commission behaviour for this payment
        # rail. It runs after the idempotent credit, so a webhook retry cannot
        # produce a second commission.
        try:
            partner = self.db.get_partner_by_referral_user(user_id)
            tariff = self.db.get_tariff(result.get("tariff_id"))
            if partner and tariff:
                commission = float(tariff.get("price_usd") or 0) * 0.30
                self.db.add_partner_earning(
                    partner["user_id"], commission,
                    f"Комиссия 30% (ЮMoney) от реферала {user_id}"
                )
                await asyncio.wait_for(
                    self.bot.send_message(
                        partner["user_id"],
                        "💰 <b>Партнёрское вознаграждение!</b>\n\n"
                        f"Начислено: <b>${commission:.2f}</b>",
                    ),
                    timeout=5,
                )
        except Exception as error:
            logger.warning("YooMoney partner commission failed: %s", error)


async def start_webhook(db, bot, receiver: str, secret: str,
                        host: str, port: int, path: str, oauth_token: str = ""):
    service = YooMoneyWebhook(db, bot, receiver, secret, path, oauth_token)
    runner = web.AppRunner(service.app, access_log=logger)
    await runner.setup()
    site = web.TCPSite(runner, host=host, port=port)
    await site.start()
    logger.info("YooMoney webhook listening on %s:%s%s", host, port, service.path)
    return runner


async def stop_webhook(runner):
    if runner:
        await runner.cleanup()
