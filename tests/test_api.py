from uuid import uuid4

import pyotp
from fastapi.testclient import TestClient

from apps.api.app.main import app


client = TestClient(app)


def account():
    email = f"test-{uuid4().hex}@example.com"
    response = client.post("/api/v1/auth/register", json={
        "email": email,
        "password": "long-secure-password",
        "organization_name": "Test Shop",
    })
    assert response.status_code == 201
    return email, response.json()["access_token"]


def project_key(token):
    headers = {"Authorization": f"Bearer {token}"}
    project = client.post("/api/v1/projects", headers=headers, json={"name": "Test", "mode": "test"})
    assert project.status_code == 201
    key = client.post(f"/api/v1/projects/{project.json()['id']}/api-keys", headers=headers,
                      json={"mode": "test"})
    assert key.status_code == 201
    return key.json()["key"]


def test_health_and_registration():
    assert client.get("/health").json()["status"] == "ok"
    email, token = account()
    me = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == email


def test_payment_idempotency():
    _, token = account()
    api_key = project_key(token)
    headers = {"Authorization": f"Bearer {api_key}", "Idempotency-Key": "same-order"}
    payload = {"amount": "100.00", "currency": "RUB", "order_id": "same-order"}
    first = client.post("/api/v1/payments", headers=headers, json=payload)
    second = client.post("/api/v1/payments", headers=headers, json=payload)
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]


def test_two_factor_login():
    email, token = account()
    headers = {"Authorization": f"Bearer {token}"}
    setup = client.post("/api/v1/auth/2fa/setup", headers=headers)
    assert setup.status_code == 200
    secret = setup.json()["secret"]
    confirm = client.post("/api/v1/auth/2fa/confirm", headers=headers,
                          json={"code": pyotp.TOTP(secret).now()})
    assert confirm.status_code == 200
    denied = client.post("/api/v1/auth/login", json={"email": email, "password": "long-secure-password"})
    assert denied.status_code == 401
    accepted = client.post("/api/v1/auth/login", json={
        "email": email, "password": "long-secure-password", "otp_code": pyotp.TOTP(secret).now()
    })
    assert accepted.status_code == 200


def test_api_key_is_required():
    response = client.post("/api/v1/payments", json={"amount": "1", "currency": "RUB", "order_id": "x"})
    assert response.status_code == 401
