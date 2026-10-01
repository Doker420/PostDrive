"""Конфигурация «Рупор». Значения берутся из переменных окружения или файла .env."""
import os
import secrets

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_dotenv() -> None:
    """Мини-парсер .env — без внешних зависимостей."""
    path = os.path.join(_BASE_DIR, ".env")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip().strip("'\"")
            os.environ.setdefault(key, value)


_load_dotenv()


def env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def env_bool(key: str, default: bool = False) -> bool:
    return env(key, str(default)).lower() in ("1", "true", "yes", "on")


# ── Приложение ────────────────────────────────────────────────────
APP_NAME = "Рупор"
APP_TAGLINE = "Биржа рекламы для Telegram и VK"
BASE_URL = env("BASE_URL", "http://localhost:8000").rstrip("/")
PORT = int(env("PORT", "8000"))
SECRET_KEY = env("SECRET_KEY", "") or secrets.token_hex(32)  # в проде задаётся явно!
DB_PATH = env("DB_PATH", os.path.join(_BASE_DIR, "data", "rupor.db"))

# Первый зарегистрированный пользователь становится админом,
# если в ADMIN_EMAILS ничего не указано.
ADMIN_EMAILS = [e.lower() for e in env("ADMIN_EMAILS").split(",") if e.strip()]

# ── Экономика ─────────────────────────────────────────────────────
COMMISSION_PCT = float(env("COMMISSION_PCT", "10"))       # комиссия площадки, %
MIN_DEPOSIT_RUB = int(env("MIN_DEPOSIT_RUB", "100"))      # мин. пополнение, ₽
MAX_DEPOSIT_RUB = int(env("MAX_DEPOSIT_RUB", "500000"))   # макс. пополнение, ₽
USDT_RUB_RATE = float(env("USDT_RUB_RATE", "95"))         # курс USDT→₽ для крипто-пополнений

# ── Платёжные провайдеры ──────────────────────────────────────────
# Если токен провайдера не задан — включается демо-режим (для локальной
# разработки и тестов: «оплата» подтверждается кнопкой на сайте).
CRYPTOBOT_TOKEN = env("CRYPTOBOT_TOKEN")
CRYPTOBOT_TESTNET = env_bool("CRYPTOBOT_TESTNET", False)
XROCKET_TOKEN = env("XROCKET_TOKEN")
XROCKET_API_URL = env("XROCKET_API_URL", "https://pay.xrocket.eu/api")
YOOMONEY_PURSE = env("YOOMONEY_PURSE")          # номер кошелька ЮMoney (4100...)
YOOMONEY_SECRET = env("YOOMONEY_SECRET")        # секрет уведомлений ЮMoney

CRYPTO_ASSET = env("CRYPTO_ASSET", "USDT")

DEMO_PAYMENTS = env_bool("DEMO_PAYMENTS", not any(
    [CRYPTOBOT_TOKEN, XROCKET_TOKEN, YOOMONEY_PURSE]
))


def provider_available(provider: str) -> bool:
    """Провайдер доступен в боевом режиме, если заданы его ключи."""
    return {
        "cryptobot": bool(CRYPTOBOT_TOKEN),
        "xrocket": bool(XROCKET_TOKEN),
        "yoomoney": bool(YOOMONEY_PURSE and YOOMONEY_SECRET),
    }.get(provider, False)
