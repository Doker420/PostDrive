# Webhook guide

FlowPay отправляет JSON POST на URL проекта.

Заголовки:

```text
X-FlowPay-Event-Id: evt_...
X-FlowPay-Signature: t=unix_timestamp,v1=hex_hmac_sha256
```

Подпись:

```text
HMAC_SHA256(webhook_secret, timestamp + "." + raw_request_body)
```

Правила:

- не парсите и не пересобирайте JSON перед проверкой подписи;
- отклоняйте timestamp старше 5 минут;
- сохраняйте `event_id` до бизнес-обработки;
- повторное событие не должно повторно начислять деньги;
- HTTP 2xx означает успешную обработку;
- 4xx/5xx запускают retry.
