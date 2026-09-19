# Инструкция для магазина

## 1. Создайте проект

В кабинете откройте **Проекты** и создайте test-проект. Для production создайте отдельный live-проект.

## 2. Создайте API-ключ

Ключ показывается один раз. Сохраните его в secret manager, а не в frontend-коде.

## 3. Создайте платеж

```bash
curl -X POST https://api.example.com/api/v1/payments \
  -H 'Authorization: Bearer fp_test_...' \
  -H 'Idempotency-Key: order-123' \
  -H 'Content-Type: application/json' \
  -d '{"amount":"100.00","currency":"RUB","order_id":"order-123","payment_methods":["sbp"],"success_url":"https://shop.example/success","fail_url":"https://shop.example/fail"}'
```

Пользователя нужно направить на `payment_url`. Финальный результат принимайте только серверным webhook.

## 4. Webhook

Проверяйте `X-FlowPay-Signature` по алгоритму из [API-контракта](API_CONTRACT.md), сохраняйте `event_id` и отвечайте HTTP 2xx после успешной обработки.

## 5. Выплата

Подключите криптокошелёк, включите 2FA и создайте payout-заявку только после сверки баланса.
