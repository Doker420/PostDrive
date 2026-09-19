# FlowPay API — черновой контракт v1

Base URL: `https://api.example.com/api/v1`

## Аутентификация

```http
Authorization: Bearer sk_live_...
Idempotency-Key: 6f2b0c3e-...
```

`Idempotency-Key` обязателен для создания платежа, возврата и выплаты. Повтор запроса с тем же ключом и тем же телом возвращает исходный результат. Использование ключа с другим телом возвращает `409 idempotency_key_reused`.

## Создание платежа

```http
POST /payments
Content-Type: application/json
```

```json
{
  "amount": 10000,
  "currency": "RUB",
  "order_id": "order-123",
  "description": "Order 123",
  "payment_methods": ["sbp", "bank_transfer"],
  "success_url": "https://shop.example/success",
  "fail_url": "https://shop.example/fail",
  "metadata": {"customer_id": "customer-42"}
}
```

```json
{
  "id": "pay_01J...",
  "status": "pending",
  "amount": 10000,
  "currency": "RUB",
  "payment_url": "https://pay.example/p/pay_01J...",
  "expires_at": "2026-09-19T12:00:00Z"
}
```

## Получение платежа

```http
GET /payments/{payment_id}
```

## Отмена

```http
POST /payments/{payment_id}/cancel
```

## Webhook

События: `payment.created`, `payment.pending`, `payment.succeeded`, `payment.failed`, `payment.expired`, `payment.cancelled`, `payment.refunded`, `payout.completed`, `payout.failed`.

Заголовки:

```http
X-FlowPay-Event-Id: evt_01J...
X-FlowPay-Signature: t=...,v1=...
```

Подпись считается по `timestamp + "." + raw_body`. Магазин должен ответить HTTP 2xx только после сохранения `event_id`; повторное событие с тем же ID не обрабатывается повторно.

## Коды ошибок

- `400 invalid_request` — неверное тело;
- `401 unauthorized` — ключ недействителен;
- `403 forbidden` — недостаточно прав;
- `404 not_found` — объект не найден;
- `409 idempotency_key_reused` — ключ использован с другим телом;
- `422 limit_exceeded` — превышен лимит;
- `429 rate_limited` — превышена частота запросов;
- `500 internal_error` — внутренний сбой, повторить по `request_id`.

## Версионирование

Изменения выполняются через `/v2`, если меняется семантика существующего поля. Новые необязательные поля добавляются обратно совместимо. Документация должна генерироваться из OpenAPI-схемы.
