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

from sqliter import DBConnection, get_db_sync
from user import AccountSessionManager
from handlers import register_all_handlers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# ── Config with env overrides ─────────────────────────────────────
config_path = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), 'config.ini')
config = configparser.ConfigParser()
config.read(config_path, encoding='utf-8')

TOKEN = os.environ.get('BOT_TOKEN', config['BOT']['TOKEN'])
ADMIN = int(os.environ.get('BOT_ADMIN', config['BOT']['ADMIN']))
USERNAME = os.environ.get('BOT_USERNAME', config['BOT'].get('USERNAME', 'bot')).strip("'\"")
API_ID = int(os.environ.get('USER_API_ID', config['USER']['API_ID']))
API_HASH = os.environ.get('USER_API_HASH', config['USER']['API_HASH'])
CRYPTO_BOT_TOKEN = os.environ.get('CRYPTOBOT_TOKEN', config.get('CRYPTOBOT', 'TOKEN', fallback=''))
TESTNET = os.environ.get('CRYPTOBOT_TESTNET', config.get('CRYPTOBOT', 'TESTNET', fallback='False')).lower() in ('true', '1', 'yes')

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

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=_fsm_storage)

# Use shared DB singleton
db = get_db_sync()
account_manager = AccountSessionManager(API_ID, API_HASH)

bot_config = {
    'ADMIN': ADMIN,
    'CRYPTO_BOT_TOKEN': CRYPTO_BOT_TOKEN,
    'TESTNET': TESTNET,
    'account_manager': account_manager,
    'USERNAME': USERNAME
}

register_all_handlers(dp, bot, bot_config)

# ── Mark interrupted tasks from previous process ──────────────────
db.mark_all_running_tasks_interrupted()
interrupted = db.get_interrupted_tasks()
if interrupted:
    logger.info(f"Found {len(interrupted)} interrupted tasks from previous run (marked as 'interrupted')")

# ── Graceful shutdown handler ─────────────────────────────────────
_shutdown_event = asyncio.Event()

async def _shutdown():
    """Graceful shutdown: cancel tasks, stop clients, close DB."""
    logger.info("Initiating graceful shutdown...")

    # Stop polling
    await dp.stop_polling()

    # Graceful shutdown of session manager (cancels tasks, stops clients)
    await account_manager.graceful_shutdown()

    # Close bot session
    try:
        await bot.session.close()
    except:
        pass

    logger.info("Graceful shutdown complete.")

def _signal_handler(sig, frame):
    logger.info(f"Received signal {sig}, initiating shutdown...")
    _shutdown_event.set()

# Register signal handlers
signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)

async def main():
    print("=" * 60)
    print("🤖 Autoposter Multi-Account Bot v5.0")
    print("=" * 60)
    print(f"📊 Limits: max_clients={account_manager.MAX_ACTIVE_CLIENTS} "
          f"max_tasks_per_user={account_manager.MAX_TASKS_PER_USER} "
          f"max_global_tasks={account_manager.MAX_GLOBAL_TASKS}")
    print("=" * 60)

    # Start cleanup loop in background
    account_manager._cleanup_task = asyncio.create_task(account_manager.start_cleanup_loop())

    # Start polling in background
    polling_task = asyncio.create_task(dp.start_polling(bot, skip_updates=True))

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
