import os
import sys
import asyncio
import logging
import configparser
from aiohttp import web
from aiogram import Bot, Dispatcher, types
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from sqliter import DBConnection, get_db_sync
from user import AccountSessionManager
from handlers import register_all_handlers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("mirrors.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

config_path = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), 'config.ini')
config = configparser.ConfigParser()
config.read(config_path)

WEBHOOK_DOMAIN = os.environ.get('WEBHOOK_DOMAIN', config['WEBHOOK'].get('DOMAIN', 'yourdomain.com'))
WEBHOOK_PORT = int(os.environ.get('WEBHOOK_PORT', config['WEBHOOK'].get('PORT', '8443')))
WEBHOOK_PATH = os.environ.get('WEBHOOK_PATH', config['WEBHOOK'].get('PATH', '/webhook'))

ADMIN = int(os.environ.get('BOT_ADMIN', config['BOT']['ADMIN']))
USERNAME = os.environ.get('BOT_USERNAME', config['BOT'].get('USERNAME', 'bot')).strip("'\"")
API_ID = int(os.environ.get('USER_API_ID', config['USER']['API_ID']))
API_HASH = os.environ.get('USER_API_HASH', config['USER']['API_HASH'])
CRYPTO_BOT_TOKEN = os.environ.get('CRYPTOBOT_TOKEN', config.get('CRYPTOBOT', 'TOKEN', fallback=''))
TESTNET = os.environ.get('CRYPTOBOT_TESTNET', config.get('CRYPTOBOT', 'TESTNET', fallback='False')).lower() in ('true', '1', 'yes')

db = get_db_sync()
account_manager = AccountSessionManager(API_ID, API_HASH)

# Mark interrupted tasks from previous process
db.mark_all_running_tasks_interrupted()

mirror_bots = {}
mirror_dps = {}

async def handle_webhook(request):
    token = request.match_info.get('token')

    if token not in mirror_bots:
        logger.warning(f"Unknown token: {token[:10]}...")
        return web.Response(status=404, text="Not Found")

    bot = mirror_bots[token]
    dp = mirror_dps[token]

    try:
        request_body = await request.json()
        update = types.Update(**request_body)
        await dp.feed_update(bot=bot, update=update)
    except Exception as e:
        logger.error(f"Error processing update: {e}")
        return web.Response(status=500, text="Internal Server Error")

    return web.Response(text="OK")

async def on_startup(app):
    mirrors = db.get_all_mirrors()
    active_mirrors = [m for m in mirrors if m['is_active'] == 1]

    bot_config = {
        'ADMIN': ADMIN,
        'CRYPTO_BOT_TOKEN': CRYPTO_BOT_TOKEN,
        'TESTNET': TESTNET,
        'account_manager': account_manager,
        'USERNAME': USERNAME
    }

    for mirror in active_mirrors:
        token = mirror['bot_token']
        try:
            bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
            dp = Dispatcher(storage=MemoryStorage())

            register_all_handlers(dp, bot, bot_config)

            webhook_url = f"https://{WEBHOOK_DOMAIN}{WEBHOOK_PATH}/{token}"
            await bot.set_webhook(url=webhook_url)

            mirror_bots[token] = bot
            mirror_dps[token] = dp

            logger.info(f"Mirror @{mirror.get('bot_username', 'unknown')} registered")
        except Exception as e:
            logger.error(f"Failed to register mirror {mirror['id']}: {e}")

    logger.info(f"Webhook server started with {len(mirror_bots)} active mirrors")

async def on_shutdown(app):
    logger.info("Initiating graceful shutdown...")
    # Graceful shutdown of session manager
    await account_manager.graceful_shutdown()
    for token, bot in mirror_bots.items():
        try:
            await bot.delete_webhook()
            await bot.session.close()
        except:
            pass
    logger.info("Webhook server stopped")

def create_app():
    app = web.Application()
    app.router.add_post(f'{WEBHOOK_PATH}/{{token}}', handle_webhook)
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    return app

if __name__ == '__main__':
    print("=" * 60)
    print("🤖 Mirror Webhook Server")
    print(f"🌐 Domain: {WEBHOOK_DOMAIN}")
    print(f"📡 Port: {WEBHOOK_PORT}")
    print("=" * 60)

    app = create_app()
    web.run_app(app, host='0.0.0.0', port=WEBHOOK_PORT)
