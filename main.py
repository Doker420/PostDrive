import os
import sys
import asyncio
import logging
import configparser
import signal

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

import dbconfig
from sqliter import DBConnection, get_db_sync
from user import AccountSessionManager
from handlers import register_all_handlers
from telegram_transport import ResilientAiohttpSession
from yoomoney import start_webhook, stop_webhook

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# ── Config with env overrides ─────────────────────────────────────
config_path = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), 'config.ini')
config = configparser.ConfigParser()
config.read(config_path)

def _safe_int(raw, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(raw))
    except (TypeError, ValueError):
        return default


TOKEN = os.environ.get('BOT_TOKEN', config['BOT']['TOKEN'])
ADMIN = int(os.environ.get('BOT_ADMIN', config['BOT']['ADMIN']))
USERNAME = os.environ.get('BOT_USERNAME', config['BOT'].get('USERNAME', 'bot')).strip("'\"")
API_ID = int(os.environ.get('USER_API_ID', config['USER']['API_ID']))
API_HASH = os.environ.get('USER_API_HASH', config['USER']['API_HASH'])
CRYPTO_BOT_TOKEN = os.environ.get('CRYPTOBOT_TOKEN', config.get('CRYPTOBOT', 'TOKEN', fallback=''))
TESTNET = os.environ.get('CRYPTOBOT_TESTNET', config.get('CRYPTOBOT', 'TESTNET', fallback='False')).lower() in ('true', '1', 'yes')
TELEGRAM_API_TIMEOUT = _safe_int(
    os.environ.get('TELEGRAM_API_TIMEOUT', config.get('LIMITS', 'TELEGRAM_API_TIMEOUT', fallback='75')),
    75,
    30,
)

# Optional Redis FSM storage
REDIS_URL = os.environ.get('REDIS_URL', '')
_fsm_storage = None
if REDIS_URL:
    try:
        from aiogram.fsm.storage.redis import RedisStorage
        import redis.asyncio as aioredis
        redis_client = aioredis.from_url(REDIS_URL)
        _fsm_storage = RedisStorage(redis=redis_client)
        logger.info(f"Redis FSM storage enabled at {REDIS_URL}")
    except ImportError:
        logger.warning("REDIS_URL set but aiogram[redis] not installed. Using MemoryStorage.")
    except Exception as e:
        logger.warning(f"Failed to connect to Redis: {e}. Using MemoryStorage.")

if _fsm_storage is None:
    _fsm_storage = MemoryStorage()

bot_session = ResilientAiohttpSession(
    timeout=TELEGRAM_API_TIMEOUT,
    max_network_retries=1,
    retry_delay=0.75,
)
bot = Bot(
    token=TOKEN,
    session=bot_session,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher(storage=_fsm_storage)

# Use shared DB singleton
db = get_db_sync()
account_manager = AccountSessionManager(API_ID, API_HASH)

# ── Payments / legal / miniapp ────────────────────────────────────
def _cfg(section, key, fallback=''):
    try:
        return config.get(section, key, fallback=fallback).strip()
    except Exception:
        return fallback

def _flag(value: str, default: bool = False) -> bool:
    if not value:
        return default
    return value.lower() in ('1', 'true', 'yes', 'on')


def _int_setting(env_name: str, section: str, key: str, default: int) -> int:
    """Parse an optional integer without making the whole bot unstartable."""
    raw = os.environ.get(env_name, _cfg(section, key, str(default)))
    try:
        return int(raw)
    except (TypeError, ValueError):
        logger.error("Invalid %s=%r; using %s", env_name, raw, default)
        return default

STARS_ENABLED = _flag(os.environ.get('STARS_ENABLED', _cfg('PAYMENTS', 'STARS_ENABLED', 'true')), True)
STARS_PER_USD = int(os.environ.get('STARS_PER_USD', _cfg('PAYMENTS', 'STARS_PER_USD', '50')))
MINIAPP_ENABLED = _flag(os.environ.get('MINIAPP_ENABLED', _cfg('PAYMENTS', 'MINIAPP_ENABLED', 'false')))
MINIAPP_URL = os.environ.get('MINIAPP_URL', _cfg('PAYMENTS', 'MINIAPP_URL', ''))

# YooMoney is enabled only when both the receiver and notification secret are
# present. Tokens are never displayed or sent to Telegram; the token is kept
# available for optional operation-history checks in the payment service.
YOOMONEY_RECEIVER = os.environ.get('YOOMONEY_RECEIVER', _cfg('YOOMONEY', 'RECEIVER', '')).strip()
YOOMONEY_NOTIFICATION_SECRET = os.environ.get(
    'YOOMONEY_NOTIFICATION_SECRET', _cfg('YOOMONEY', 'NOTIFICATION_SECRET', '')
).strip()
YOOMONEY_TOKEN = os.environ.get('YOOMONEY_TOKEN', _cfg('YOOMONEY', 'TOKEN', '')).strip()
YOOMONEY_RUB_PER_USD = os.environ.get('YOOMONEY_RUB_PER_USD', _cfg('YOOMONEY', 'RUB_PER_USD', '100')).strip()
YOOMONEY_WEBHOOK_HOST = os.environ.get('YOOMONEY_WEBHOOK_HOST', _cfg('YOOMONEY', 'WEBHOOK_HOST', '0.0.0.0')).strip() or '0.0.0.0'
YOOMONEY_WEBHOOK_PORT = _int_setting('YOOMONEY_WEBHOOK_PORT', 'YOOMONEY', 'WEBHOOK_PORT', 8012)
YOOMONEY_WEBHOOK_PATH = os.environ.get('YOOMONEY_WEBHOOK_PATH', _cfg('YOOMONEY', 'WEBHOOK_PATH', '/yoomoney/webhook')).strip() or '/yoomoney/webhook'
YOOMONEY_SUCCESS_URL = os.environ.get('YOOMONEY_SUCCESS_URL', _cfg('YOOMONEY', 'SUCCESS_URL', '')).strip()
YOOMONEY_ENABLED = bool(YOOMONEY_RECEIVER and YOOMONEY_NOTIFICATION_SECRET)

bot_config = {
    'ADMIN': ADMIN,
    'CRYPTO_BOT_TOKEN': CRYPTO_BOT_TOKEN,
    'TESTNET': TESTNET,
    'account_manager': account_manager,
    'USERNAME': USERNAME,
    'STARS_ENABLED': STARS_ENABLED,
    'STARS_PER_USD': STARS_PER_USD,
    'MINIAPP_ENABLED': MINIAPP_ENABLED,
    'MINIAPP_URL': MINIAPP_URL,
    'YOOMONEY_ENABLED': YOOMONEY_ENABLED,
    'YOOMONEY_RECEIVER': YOOMONEY_RECEIVER,
    'YOOMONEY_TOKEN': YOOMONEY_TOKEN,
    'YOOMONEY_RUB_PER_USD': YOOMONEY_RUB_PER_USD,
    'YOOMONEY_SUCCESS_URL': YOOMONEY_SUCCESS_URL,
    'SESSION_CHECK_CONCURRENCY': max(1, int(os.environ.get(
        'SESSION_CHECK_CONCURRENCY', _cfg('LIMITS', 'SESSION_CHECK_CONCURRENCY', '4')
    ))),
    'TERMS_URL': os.environ.get('TERMS_URL', _cfg('LEGAL', 'TERMS_URL', '')),
    'PRIVACY_URL': os.environ.get('PRIVACY_URL', _cfg('LEGAL', 'PRIVACY_URL', '')),
    'SUPPORT': os.environ.get('SUPPORT_CONTACT', _cfg('LEGAL', 'SUPPORT', '@support')),
}

register_all_handlers(dp, bot, bot_config)

# ── Mark interrupted tasks from previous process ──────────────────
db.mark_all_running_tasks_interrupted()
interrupted = db.get_interrupted_tasks()
if interrupted:
    logger.info(f"Found {len(interrupted)} interrupted tasks from previous run (marked as 'interrupted')")

# ── Graceful shutdown handler ─────────────────────────────────────
_shutdown_event = asyncio.Event()
_yoomoney_runner = None
_yoomoney_start_task = None

async def _shutdown():
    """Graceful shutdown: cancel tasks, stop clients, close DB."""
    global _yoomoney_runner, _yoomoney_start_task
    logger.info("Initiating graceful shutdown...")

    # Stop polling
    await dp.stop_polling()

    # Webhook startup is deliberately isolated from polling. If a port or
    # proxy configuration is wrong, commands must still work normally.
    if _yoomoney_start_task is not None and not _yoomoney_start_task.done():
        _yoomoney_start_task.cancel()
        try:
            await _yoomoney_start_task
        except asyncio.CancelledError:
            pass
    _yoomoney_start_task = None

    if _yoomoney_runner is not None:
        try:
            await stop_webhook(_yoomoney_runner)
        except Exception as e:
            logger.warning("YooMoney webhook shutdown failed: %s", e)
        _yoomoney_runner = None

    # Graceful shutdown of session manager (cancels tasks, stops clients)
    await account_manager.graceful_shutdown()

    # Close bot session
    try:
        await bot.session.close()
    except:
        pass

    # Close DB pool
    try:
        logger.info(f"DB pool stats before shutdown: {db.pool_stats()}")
        db.close()
    except Exception as e:
        logger.warning(f"DB pool close failed: {e}")

    logger.info("Graceful shutdown complete.")

def _signal_handler(sig, frame):
    logger.info(f"Received signal {sig}, initiating shutdown...")
    _shutdown_event.set()

# Register signal handlers
signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)


async def _start_yoomoney_webhook():
    """Start the optional HTTP endpoint without blocking Telegram polling."""
    global _yoomoney_runner
    try:
        _yoomoney_runner = await asyncio.wait_for(
            start_webhook(
                db=db,
                bot=bot,
                receiver=YOOMONEY_RECEIVER,
                secret=YOOMONEY_NOTIFICATION_SECRET,
                host=YOOMONEY_WEBHOOK_HOST,
                port=YOOMONEY_WEBHOOK_PORT,
                path=YOOMONEY_WEBHOOK_PATH,
                oauth_token=YOOMONEY_TOKEN,
            ),
            timeout=5,
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        # Keep the detailed failure in logs, but never let an optional
        # payment endpoint stop the main bot from accepting commands.
        logger.exception("YooMoney webhook could not start")
        _yoomoney_runner = None


async def main():
    global _yoomoney_start_task
    print("=" * 60)
    print("🤖 Autoposter Multi-Account Bot v5.0")
    print("=" * 60)
    print(f"🗄  DB: {dbconfig.describe()}")
    print(f"📊 Limits: max_clients={account_manager.MAX_ACTIVE_CLIENTS} "
          f"max_tasks_per_user={account_manager.MAX_TASKS_PER_USER} "
          f"max_global_tasks={account_manager.MAX_GLOBAL_TASKS}")
    print("=" * 60)

    # Start cleanup loop in background
    account_manager._cleanup_task = asyncio.create_task(account_manager.start_cleanup_loop())

    # Start polling first. The optional YooMoney listener is launched as a
    # bounded background task so a bind/DNS/proxy issue cannot block /start or
    # any other Telegram command.
    polling_task = asyncio.create_task(dp.start_polling(bot, skip_updates=True))
    if YOOMONEY_ENABLED:
        _yoomoney_start_task = asyncio.create_task(_start_yoomoney_webhook())
    else:
        logger.info("YooMoney payments disabled: receiver or notification secret is not configured")

    # Wait for shutdown signal
    await _shutdown_event.wait()

    # Cancel polling and run shutdown
    polling_task.cancel()
    try:
        await polling_task
    except asyncio.CancelledError:
        pass

    await _shutdown()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Бот остановлен")
    except Exception as e:
        print(f"❌ Фатальная ошибка: {e}")
        import traceback
        traceback.print_exc()
