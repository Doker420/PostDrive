"""Unit tests for YooMoney labels, signatures and idempotent crediting."""
import hashlib
import pathlib
import sys
import tempfile
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from sqliter import DBConnection
from yoomoney import build_payment_url, verify_notification


def _modern_payload():
    # Example from YooMoney's notification documentation.
    return {
        "notification_type": "p2p-incoming",
        "operation_id": "441361714955017004",
        "amount": "98.00",
        "withdraw_amount": "100.00",
        "currency": "643",
        "datetime": "2013-12-26T08:28:34Z",
        "sender": "41000000000",
        "codepro": "false",
        "label": "ML23045",
        "unaccepted": "false",
        "sha1_hash": "ac13833bd6ba9eff1fa9e4bed76f3d6ebb57f6c0",
        "sign": "a452af731650e2c5b39abcdc7c28dd27db7b3b654c2230ad2c386e64afb98605",
    }


def test_current_hmac_signature_and_tamper_rejection():
    payload = _modern_payload()
    assert verify_notification(payload, "secret123")
    payload["amount"] = "98.01"
    assert not verify_notification(payload, "secret123")


def test_legacy_sha1_signature_is_only_a_fallback():
    payload = _modern_payload()
    payload.pop("sign")
    raw = "&".join(payload.get(k, "") for k in (
        "notification_type", "operation_id", "amount", "currency",
        "datetime", "sender", "codepro",
    ))
    payload["sha1_hash"] = hashlib.sha1(
        (raw + "&legacy-secret&" + payload["label"]).encode()
    ).hexdigest()
    assert verify_notification(payload, "legacy-secret")
    payload["sign"] = "not-a-valid-current-signature"
    assert not verify_notification(payload, "legacy-secret")


def test_payment_url_contains_receiver_amount_and_unique_label():
    url = build_payment_url("4100118544926615", "123.45", "PD-unique-label", "PostDrive Pro")
    values = parse_qs(urlparse(url).query)
    assert url.startswith("https://yoomoney.ru/quickpay/confirm.xml?")
    assert values["receiver"] == ["4100118544926615"]
    assert values["sum"] == ["123.45"]
    assert values["label"] == ["PD-unique-label"]


def test_credit_is_amount_checked_and_idempotent():
    path = tempfile.mktemp(suffix=".db")
    db = DBConnection(path)
    try:
        user_id = 901
        db.get_or_create_user(user_id)
        tariff = next(t for t in db.get_tariffs() if float(t["price_usd"]) > 0)
        db.create_yoomoney_payment(user_id, tariff["id"], "123.45", "PD-one")
        db.create_yoomoney_payment(user_id, tariff["id"], "123.45", "PD-two")

        bad = db.mark_yoomoney_payment_paid("PD-one", "operation-1", "123.46", "643")
        wrong_currency = db.mark_yoomoney_payment_paid("PD-one", "operation-1", "123.45", "RUB")
        assert bad["status"] == "amount_mismatch"
        assert wrong_currency["status"] == "amount_mismatch"
        assert db.get_yoomoney_payment_by_label("PD-one")["status"] == "pending"

        first = db.mark_yoomoney_payment_paid("PD-one", "operation-1", "123.45", "643")
        second = db.mark_yoomoney_payment_paid("PD-one", "operation-1", "123.45", "643")
        duplicate_operation = db.mark_yoomoney_payment_paid("PD-two", "operation-1", "123.45", "643")
        assert first["credited"] is True
        assert second["status"] == "already_paid"
        assert duplicate_operation["status"] == "duplicate_operation"
    finally:
        db.close()
        pathlib.Path(path).unlink(missing_ok=True)


if __name__ == "__main__":
    test_current_hmac_signature_and_tamper_rejection()
    test_legacy_sha1_signature_is_only_a_fallback()
    test_payment_url_contains_receiver_amount_and_unique_label()
    test_credit_is_amount_checked_and_idempotent()
    print("YOOMONEY TESTS PASSED")
