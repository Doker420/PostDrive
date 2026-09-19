# API routers

`health.py` уже вынесен и подключается через `app.include_router`.

Следующие переносы выполняются по одному bounded context, чтобы не менять публичный контракт:

1. `auth.py` — регистрация, login, 2FA и сессии;
2. `notifications.py` — Telegram и notification preferences;
3. `payments.py` — создание, checkout, webhook events;
4. `payouts.py` — баланс, wallet и payout;
5. `supplier.py` — профили и каналы;
6. `admin.py` — управление, risk и statistics.

Dependency functions и Pydantic-схемы будут перенесены в `dependencies.py` и `schemas/` после завершения текущего переходного этапа.
