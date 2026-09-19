# Следующий архитектурный срез

```text
apps/api       HTTP API и OpenAPI
apps/web       merchant/supplier/admin UI
apps/worker    durable webhook/retry jobs
packages       shared SDK/UI/contracts
```

API остаётся stateless. Долгие задачи (webhook retry, payout provider, blockchain confirmations, отчёты) выполняются worker-процессом. Следующий рефакторинг переносит обработчики из `main.py` в routers и services без изменения публичного API.
