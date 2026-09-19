# FlowPay — архитектура v0

## Контуры

```text
Merchant / Supplier UI
          |
       API Gateway
          |
   Auth + Organizations
          |
 Payment API ---- Webhook Dispatcher
          |
 Routing Engine -- Risk Engine
          |
 Ledger / Balances -- Payouts
          |
 PostgreSQL | Redis | Queue | Audit Log
```

## Рекомендуемый стек

- Backend: NestJS + TypeScript, REST, OpenAPI.
- Frontend: Next.js + TypeScript, React Query, i18n RU/EN/UA.
- Данные: PostgreSQL; Redis для rate limit, блокировок и очередей.
- Асинхронность: BullMQ на первом этапе, RabbitMQ при росте нагрузки.
- Инфраструктура: Docker Compose для local/staging, managed PostgreSQL в production.
- Наблюдаемость: structured logs, Sentry, Prometheus/Grafana.

Текущий Python Telegram-бот сохраняется как legacy-компонент до миграции уведомлений. Платёжное ядро не должно зависеть от SQLite и Telegram.

## Доменные модули

- `identity` — пользователи, организации, роли, сессии, 2FA;
- `projects` — проекты магазина и API-ключи;
- `payments` — платежи, попытки, статусная машина;
- `routing` — выбор канала и fallback;
- `ledger` — неизменяемый журнал начислений и комиссий;
- `webhooks` — подпись, доставка, retry, deduplication;
- `risk` — лимиты, правила, ручные проверки;
- `payouts` — заявки, проверки, отправка и подтверждение;
- `notifications` — email, Telegram, in-app;
- `audit` — журнал административных и финансовых действий.

## Правила данных

- Секреты хранятся через KMS/secret manager, локально — только в `.env` вне git.
- Реквизиты каналов шифруются envelope encryption и маскируются в UI.
- Денежные значения хранятся как integer в минимальных единицах (`amount_minor`), не как float.
- Все внешние идентификаторы — opaque IDs, внутренние последовательности не выдаются наружу.
- Уникальный ключ платежа: `(project_id, idempotency_key)`.
- Баланс вычисляется из ledger; прямое редактирование баланса запрещено.

## Статусная машина платежа

```text
created -> pending -> processing -> succeeded
                          |             |
                          v             v
                       failed         refunded
created -> expired
pending -> cancelled
```

Переходы валидируются в одном доменном сервисе. Вебхуки и редиректы не имеют права напрямую менять статус.

## Безопасность

- HMAC-SHA256 для webhook;
- API rate limits и отдельные лимиты для login/payment/webhook;
- TOTP с резервными кодами, 2FA для вывода и смены кошелька;
- RBAC + audit log;
- запрет секретов в логах;
- резервные копии и проверка восстановления;
- security review перед подключением реальных денег.
