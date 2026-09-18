# Мини-апп для оплаты (Telegram Web App)

Мини-апп — это витрина тарифов внутри Telegram: удобнее длинного списка кнопок,
показывает сравнение тарифов таблицей и текущие лимиты пользователя.

## Статус

В боте подготовлена интеграция: если включить мини-апп, в разделе «💳 Подписка»
появляется кнопка «🛒 Открыть магазин тарифов», которая открывает ваш веб-интерфейс
и передаёт `uid` пользователя. Сам фронтенд разворачивается отдельно — это
статический сайт, боту он не принадлежит.

## Включение

```ini
[PAYMENTS]
MINIAPP_ENABLED = true
MINIAPP_URL = https://pay.example.com/
```

Требования Telegram: домен обязательно **HTTPS** с валидным сертификатом.

## Как это работает

1. Пользователь нажимает кнопку → Telegram открывает `MINIAPP_URL?uid=<user_id>`.
2. Фронтенд подключает `https://telegram.org/js/telegram-web-app.js` и читает
   `Telegram.WebApp.initData`.
3. **Бэкенд обязан проверить подпись `initData`** секретом, производным от токена
   бота — иначе любой сможет выдать себе подписку. Никогда не доверяйте `uid`
   из query-строки без проверки подписи.
4. Для оплаты звёздами фронтенд вызывает ваш бэкенд, тот создаёт инвойс через
   `createInvoiceLink` (currency `XTR`) и возвращает ссылку, которую фронтенд
   открывает через `Telegram.WebApp.openInvoice(link)`.
5. Начисление подписки происходит в боте по событию `successful_payment` —
   этот обработчик уже реализован в `handlers.py`.

## Проверка подписи initData (пример)

```python
import hmac, hashlib
from urllib.parse import parse_qsl

def verify_init_data(init_data: str, bot_token: str) -> dict | None:
    parsed = dict(parse_qsl(init_data, strict_parsing=True))
    received_hash = parsed.pop('hash', None)
    check_string = '\n'.join(f'{k}={v}' for k, v in sorted(parsed.items()))
    secret = hmac.new(b'WebAppData', bot_token.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    return parsed if hmac.compare_digest(calc, received_hash or '') else None
```

## Почему оплата звёздами уже работает без мини-аппа

Telegram Stars реализованы нативно в боте: инвойс отправляется прямо в чат,
подтверждение приходит в `pre_checkout_query` и `successful_payment`. Мини-апп
нужен только для более удобной витрины, а не для самой оплаты.
