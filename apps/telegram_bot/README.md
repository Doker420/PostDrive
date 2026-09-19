# FlowPay Telegram Operations Bot

Операционный бот не хранит платёжные реквизиты и не выполняет выплаты. Финансовые действия подтверждаются в кабинете с 2FA.

Запуск:

```bash
export TELEGRAM_BOT_TOKEN=...
export FLOWPAY_API_URL=http://localhost:3000/api/v1
export FLOWPAY_ADMIN_TOKEN=...
python -m apps.telegram_bot.bot
```

Команды:

- `/start` — справка;
- `/stats` — статистика за текущий день;
- `/health` — состояние API.
