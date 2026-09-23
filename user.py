import asyncio
import random
import time
import os
import sys
import json
import re
import logging
import configparser
import aiohttp
from typing import Optional, Dict, Any, List, Tuple
from pyrogram import Client, enums, filters
from pyrogram import utils
from pyrogram.handlers import MessageHandler
from pyrogram.types import MessageEntity

# ── Telegram error taxonomy ───────────────────────────────────────
# Имена классов различаются между версиями Pyrogram, поэтому импортируем
# устойчиво: отсутствующие классы заменяются на заглушку, которая никогда
# не поймается (важно, чтобы бот не падал на ImportError при обновлении).
class _NeverRaised(Exception):
    """Заглушка для отсутствующих в данной версии Pyrogram классов ошибок."""


def _err(name: str):
    try:
        import pyrogram.errors as _pe
        return getattr(_pe, name, _NeverRaised)
    except Exception:
        return _NeverRaised


FloodWait = _err('FloodWait')
SlowmodeWait = _err('SlowmodeWait')
FloodPremiumWait = _err('FloodPremiumWait')
PeerFlood = _err('PeerFlood')
UserDeactivated = _err('UserDeactivated')
UserDeactivatedBan = _err('UserDeactivatedBan')
AuthKeyUnregistered = _err('AuthKeyUnregistered')
AuthKeyDuplicated = _err('AuthKeyDuplicated')
SessionRevoked = _err('SessionRevoked')
SessionExpired = _err('SessionExpired')
UserBannedInChannel = _err('UserBannedInChannel')
ChatWriteForbidden = _err('ChatWriteForbidden')
ChatAdminRequired = _err('ChatAdminRequired')
UserBlocked = _err('UserBlocked')
UserIsBlocked = _err('UserIsBlocked')
ChannelPrivate = _err('ChannelPrivate')
UsernameNotOccupied = _err('UsernameNotOccupied')
InviteHashExpired = _err('InviteHashExpired')
UserAlreadyParticipant = _err('UserAlreadyParticipant')
UserPrivacyRestricted = _err('UserPrivacyRestricted')

# Ждём и повторяем
FLOOD_ERRORS = tuple({FloodWait, SlowmodeWait, FloodPremiumWait} - {_NeverRaised})
# Аккаунт под спам-блоком: останавливаем задачи, но сессия жива
SPAMBLOCK_ERRORS = tuple({PeerFlood, UserBannedInChannel} - {_NeverRaised})
# Сессия мертва: нужен повторный вход
DEAD_SESSION_ERRORS = tuple({
    UserDeactivated, UserDeactivatedBan, AuthKeyUnregistered,
    AuthKeyDuplicated, SessionRevoked, SessionExpired,
} - {_NeverRaised})
# Проблема конкретного чата, а не аккаунта: пропускаем цель, задачу продолжаем
SKIP_TARGET_ERRORS = tuple({
    ChatWriteForbidden, ChatAdminRequired, ChannelPrivate, UsernameNotOccupied,
    InviteHashExpired, UserPrivacyRestricted, UserBlocked, UserIsBlocked,
} - {_NeverRaised})


class AccountBlockedError(Exception):
    """Аккаунт нельзя использовать дальше (спам-блок или мёртвая сессия)."""

    def __init__(self, message: str, kind: str = 'restricted'):
        super().__init__(message)
        self.kind = kind          # 'restricted' | 'banned'


class TargetSkipError(Exception):
    """Цель (чат/пользователь) недоступна — пропускаем её, задача продолжается."""



from sqliter import DBConnection, get_db_sync

config = configparser.ConfigParser()
config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.ini')
config.read(config_path)

# Максимальное ожидание FloodWait, которое имеет смысл пересидеть внутри задачи.
MAX_FLOOD_WAIT = int(config.get('LIMITS', 'MAX_FLOOD_WAIT', fallback='1800'))

# ID владельца бота. Фоновые задачи периодически перепроверяют подписку, и без
# admin_id проверка для админа проваливалась: аккаунт владельца останавливался
# с «Подписка истекла», хотя у него безлимитный доступ.
try:
    ADMIN_ID = int(os.environ.get('BOT_ADMIN') or config.get('BOT', 'ADMIN', fallback='0') or 0)
except (ValueError, TypeError):
    ADMIN_ID = 0

# ── Патч диапазонов ID каналов в Pyrogram ────────────────────────
# Pyrogram 2.0.106 считает валидными ID каналов только до -1002147483647
# (32-битный предел). Telegram давно выдаёт ID вплоть до -1997852516352
# (https://core.telegram.org/api/bots/ids), поэтому все новые супергруппы
# и каналы (-1002.../-1003.../-1004...) падали с ValueError: Peer id invalid.
# Из-за этого чат не резолвился, и рассылка/нейрокомментинг его пропускали.
def _patch_pyrogram_peer_ranges():
    from pyrogram import utils as _pu

    # Официальные границы Bot API dialog ID
    _MIN_CHANNEL_ID = -1997852516352
    _MIN_CHAT_ID = -999999999999
    _MAX_USER_ID = 0xFFFFFFFFFF   # 2^40 - 1

    if getattr(_pu, '_postdrive_patched', False):
        return

    _pu.MIN_CHANNEL_ID = _MIN_CHANNEL_ID
    _pu.MIN_CHAT_ID = _MIN_CHAT_ID
    _pu.MAX_USER_ID = _MAX_USER_ID

    def get_peer_type(peer_id: int) -> str:
        if peer_id < 0:
            if _MIN_CHAT_ID <= peer_id:
                return "chat"
            if _MIN_CHANNEL_ID <= peer_id < _pu.MAX_CHANNEL_ID:
                return "channel"
        elif 0 < peer_id <= _MAX_USER_ID:
            return "user"
        raise ValueError(f"Peer id invalid: {peer_id}")

    _pu.get_peer_type = get_peer_type

    # Те же функции импортированы по значению в другие модули Pyrogram —
    # подменяем и там, иначе патч не подействует.
    import sys
    for mod_name, mod in list(sys.modules.items()):
        if not mod_name.startswith('pyrogram') or mod is None:
            continue
        if getattr(mod, 'get_peer_type', None) is not None:
            try:
                mod.get_peer_type = get_peer_type
            except Exception:
                pass
        for const, val in (('MIN_CHANNEL_ID', _MIN_CHANNEL_ID),
                           ('MIN_CHAT_ID', _MIN_CHAT_ID),
                           ('MAX_USER_ID', _MAX_USER_ID)):
            if getattr(mod, const, None) is not None:
                try:
                    setattr(mod, const, val)
                except Exception:
                    pass

    _pu._postdrive_patched = True
    logging.info("🔧 Pyrogram: диапазоны ID каналов расширены до -1997852516352")


_patch_pyrogram_peer_ranges()

_original_handle_updates = Client.handle_updates

async def _safe_handle_updates(self, updates):
    try:
        return await _original_handle_updates(self, updates)
    except ValueError as e:
        if "Peer id invalid" in str(e):
            logging.warning(f"⚠️ Invalid peer update ignored: {e}")
            return
        raise
    except KeyError as e:
        if "ID not found" in str(e):
            logging.warning(f"⚠️ Missing peer update ignored: {e}")
            return
        raise

Client.handle_updates = _safe_handle_updates
AI_MODEL = config.get('AI', 'MODEL', fallback='openai/gpt-oss-20b').strip()

# Актуальные модели Groq (проверено по console.groq.com/docs/deprecations).
# ВАЖНО: llama-3.1-70b-versatile / llama-3.3-70b-versatile / llama-3.1-8b-instant /
# mixtral-8x7b-32768 / gemma2-9b-it ОТКЛЮЧЕНЫ Groq и возвращают model_decommissioned.
GROQ_MODELS = [
    'openai/gpt-oss-20b',      # быстрый и дешёвый, дефолт для коротких комментариев
    'openai/gpt-oss-120b',     # умнее, чуть медленнее
    'qwen/qwen3.6-27b',
]
# Карта автозамены снятых с обслуживания моделей
GROQ_DECOMMISSIONED = {
    'llama-3.1-70b-versatile': 'openai/gpt-oss-120b',
    'llama-3.3-70b-versatile': 'openai/gpt-oss-120b',
    'llama-3.1-8b-instant': 'openai/gpt-oss-20b',
    'mixtral-8x7b-32768': 'openai/gpt-oss-120b',
    'gemma2-9b-it': 'openai/gpt-oss-20b',
    'qwen/qwen3-32b': 'openai/gpt-oss-120b',
    'meta-llama/llama-4-scout-17b-16e-instruct': 'openai/gpt-oss-120b',
}
OPENAI_API_KEY = config.get('AI', 'OPENAI_API_KEY', fallback='').strip()
ANTHROPIC_API_KEY = config.get('AI', 'ANTHROPIC_API_KEY', fallback='').strip()
GEMINI_API_KEY = config.get('AI', 'GEMINI_API_KEY', fallback='').strip()
GROQ_API_KEY = config.get('AI', 'GROQ_API_KEY', fallback='').strip()
OPENROUTER_API_KEY = config.get('AI', 'OPENROUTER_API_KEY', fallback='').strip()

# ── g4f (бесплатный фолбэк без ключей) ───────────────────────────
G4F_ENABLED = config.get('AI', 'G4F_ENABLED', fallback='true').strip().lower() in ('1', 'true', 'yes', 'on')
G4F_TIMEOUT = int(config.get('AI', 'G4F_TIMEOUT', fallback='45'))
# Явные провайдеры перебираются первыми: они не требуют манифеста с g4f.dev,
# из-за недоступности которого g4f 8.x падает целиком.
# Имена провайдеров в g4f меняются от версии к версии, поэтому список
# из конфига фильтруется по реально существующим классам, а если ничего
# не осталось — провайдеры ищутся автоматически (см. _g4f_providers).
# ВАЖНО: только провайдеры, работающие БЕЗ ключа и БЕЗ оплаты.
# PollinationsAI/OpenAIFM убраны: перешли на платную модель (402 No cake credits).
G4F_PROVIDERS = [p.strip() for p in config.get(
    'AI', 'G4F_PROVIDERS',
    fallback='Yqcloud,ChatGptOss,GLM,Qwen,TeachAnything,PhindAi,Cloudflare,DeepAI,OperaAria,You'
).split(',') if p.strip()]
# Пусто = использовать default_model каждого провайдера (надёжнее, чем
# навязывать имя модели, которого у провайдера может не быть).
G4F_MODELS = [m.strip() for m in config.get(
    'AI', 'G4F_MODELS', fallback=''
).split(',') if m.strip()]


class _ModelGoneError(RuntimeError):
    """Модель снята с обслуживания провайдером (нужно взять следующую из списка)."""
    pass


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("bot_debug.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

db = get_db_sync()

def parse_proxy_string(proxy_str: str) -> Optional[Dict[str, Any]]:
    if not proxy_str or not proxy_str.strip():
        return None
    
    proxy_str = proxy_str.strip()
    scheme = "socks5"
    
    if "://" in proxy_str:
        scheme_part, rest = proxy_str.split("://", 1)
        scheme = scheme_part.lower()
        if scheme not in ["socks5", "socks4", "http", "https"]:
            scheme = "socks5"
        proxy_str = rest

    # Pattern 1: user:pass@host:port
    if "@" in proxy_str:
        auth_part, host_part = proxy_str.split("@", 1)
        user_pass = auth_part.split(":", 1)
        username = user_pass[0]
        password = user_pass[1] if len(user_pass) > 1 else ""
        host_port = host_part.split(":", 1)
        hostname = host_port[0]
        port = int(host_port[1]) if len(host_port) > 1 else 1080
        return {
            "scheme": scheme,
            "hostname": hostname,
            "port": port,
            "username": username,
            "password": password
        }

    # Pattern 2: host:port:user:pass
    parts = proxy_str.split(":")
    if len(parts) == 4:
        return {
            "scheme": scheme,
            "hostname": parts[0],
            "port": int(parts[1]),
            "username": parts[2],
            "password": parts[3]
        }
    elif len(parts) == 2:
        return {
            "scheme": scheme,
            "hostname": parts[0],
            "port": int(parts[1])
        }
    return None


def convert_pyrogram_entities_to_json(entities) -> Optional[str]:
    if not entities:
        return None
    try:
        entities_data = []
        for ent in entities:
            entity_type = None
            extra = {}
            if ent.type == enums.MessageEntityType.BOLD:
                entity_type = 'bold'
            elif ent.type == enums.MessageEntityType.ITALIC:
                entity_type = 'italic'
            elif ent.type == enums.MessageEntityType.UNDERLINE:
                entity_type = 'underline'
            elif ent.type == enums.MessageEntityType.STRIKETHROUGH:
                entity_type = 'strikethrough'
            elif ent.type == enums.MessageEntityType.SPOILER:
                entity_type = 'spoiler'
            elif ent.type == enums.MessageEntityType.CODE:
                entity_type = 'code'
            elif ent.type == enums.MessageEntityType.PRE:
                entity_type = 'pre'
                if getattr(ent, 'language', None):
                    extra['language'] = ent.language
            elif ent.type == enums.MessageEntityType.TEXT_LINK:
                entity_type = 'text_link'
                if getattr(ent, 'url', None):
                    extra['url'] = ent.url
            elif ent.type == enums.MessageEntityType.TEXT_MENTION:
                entity_type = 'text_mention'
                if getattr(ent, 'user', None):
                    extra['user_id'] = ent.user.id
            elif ent.type == enums.MessageEntityType.CUSTOM_EMOJI:
                entity_type = 'custom_emoji'
                if getattr(ent, 'custom_emoji_id', None):
                    extra['custom_emoji_id'] = ent.custom_emoji_id
            elif ent.type == enums.MessageEntityType.URL:
                entity_type = 'url'
            elif ent.type == enums.MessageEntityType.MENTION:
                entity_type = 'mention'
            elif ent.type == enums.MessageEntityType.HASHTAG:
                entity_type = 'hashtag'
            elif ent.type == enums.MessageEntityType.CASHTAG:
                entity_type = 'cashtag'
            elif ent.type == enums.MessageEntityType.BOT_COMMAND:
                entity_type = 'bot_command'
            elif ent.type == enums.MessageEntityType.EMAIL:
                entity_type = 'email'
            elif ent.type == enums.MessageEntityType.PHONE_NUMBER:
                entity_type = 'phone_number'
            elif ent.type == enums.MessageEntityType.BLOCKQUOTE:
                entity_type = 'blockquote'
            else:
                continue
            entities_data.append({
                'type': entity_type,
                'offset': ent.offset,
                'length': ent.length,
                **extra
            })
        return json.dumps(entities_data, ensure_ascii=False)
    except Exception as err:
        print(f"⚠️ Ошибка сохранения entities: {err}")
        return None


async def convert_entities_to_pyrogram(entities_json: str, client: Client = None) -> Optional[List[MessageEntity]]:
    if not entities_json:
        return None
    try:
        entities_data = json.loads(entities_json)
        entities = []
        
        type_map = {
            'bold': enums.MessageEntityType.BOLD,
            'italic': enums.MessageEntityType.ITALIC,
            'underline': enums.MessageEntityType.UNDERLINE,
            'strikethrough': enums.MessageEntityType.STRIKETHROUGH,
            'spoiler': enums.MessageEntityType.SPOILER,
            'code': enums.MessageEntityType.CODE,
            'pre': enums.MessageEntityType.PRE,
            'text_link': enums.MessageEntityType.TEXT_LINK,
            'text_mention': enums.MessageEntityType.TEXT_MENTION,
            'custom_emoji': enums.MessageEntityType.CUSTOM_EMOJI,
            'url': enums.MessageEntityType.URL,
            'mention': enums.MessageEntityType.MENTION,
            'hashtag': enums.MessageEntityType.HASHTAG,
            'cashtag': enums.MessageEntityType.CASHTAG,
            'bot_command': enums.MessageEntityType.BOT_COMMAND,
            'email': enums.MessageEntityType.EMAIL,
            'phone_number': enums.MessageEntityType.PHONE_NUMBER,
            'blockquote': enums.MessageEntityType.BLOCKQUOTE,
        }
        
        for e in entities_data:
            entity_type = e.get('type')
            offset = e.get('offset', 0)
            length = e.get('length', 0)
            pyro_type = type_map.get(entity_type)
            if not pyro_type:
                continue
            
            kwargs = {
                'type': pyro_type,
                'offset': offset,
                'length': length
            }
            if entity_type == 'text_link' and e.get('url'):
                kwargs['url'] = e['url']
            elif entity_type == 'text_mention' and e.get('user_id'):
                if client:
                    try:
                        user = await client.get_users(e['user_id'])
                        kwargs['user'] = user
                    except Exception:
                        pass
            elif entity_type == 'custom_emoji' and e.get('custom_emoji_id'):
                kwargs['custom_emoji_id'] = int(e['custom_emoji_id'])
            elif entity_type == 'pre' and e.get('language'):
                kwargs['language'] = e['language']
            
            entities.append(MessageEntity(**kwargs))
        return entities if entities else None
    except Exception as err:
        print(f"⚠️ Ошибка конвертации entities: {err}")
        return None
    except Exception as err:
        print(f"⚠️ Ошибка конвертации entities: {err}")
        return None

AR_HISTORY: Dict[int, Dict] = {}  # account_id -> {user_id: timestamp}
_AR_HISTORY_TTL = 86400  # 24 hours — auto-evict entries older than this

def cleanup_ar_history():
    """Remove AR_HISTORY entries older than TTL. Called periodically."""
    now = time.time()
    expired = []
    for account_id, users in AR_HISTORY.items():
        expired_users = [uid for uid, ts in users.items() if now - ts > _AR_HISTORY_TTL]
        for uid in expired_users:
            del users[uid]
        if not users:
            expired.append(account_id)
    for aid in expired:
        del AR_HISTORY[aid]

async def autoresponder_callback(client: Client, message):
    try:
        if not client.name.startswith("acc_"):
            return
        account_id_str = client.name.split('_')[1]
        if not account_id_str.isdigit():
            return
        account_id = int(account_id_str)
        
        account = db.get_account(account_id)
        if not account or not account.get('autoresponder_enabled'):
            return
            
        user_id = message.from_user.id if message.from_user else None
        if not user_id:
            return
            
        if account_id not in AR_HISTORY:
            AR_HISTORY[account_id] = {}
            
        if user_id in AR_HISTORY[account_id]:
            return # Deduplication
            
        # Store timestamp for TTL cleanup
        AR_HISTORY[account_id][user_id] = time.time()
            
        text = account.get('autoresponder_text')
        ar_entities_json = account.get('autoresponder_entities')
        media_path = account.get('autoresponder_media_path')
        media_type = account.get('autoresponder_media_type')
        
        # Spin text if text is present
        if text:
            try:
                import re
                import random
                def spin(m):
                    return random.choice(m.group(1).split('|'))
                text = re.sub(r'\{([^}]+)\}', spin, text)
            except Exception:
                pass
        
        # ⭐ КОПИРУЕМ ENTITIES из БД
        entities = None
        if ar_entities_json:
            try:
                converted = await convert_entities_to_pyrogram(ar_entities_json, client)
                if converted:
                    entities = converted
            except Exception:
                pass
        
        sent = False
        import os
        if media_path and os.path.exists(media_path):
            try:
                if media_type == 'photo':
                    await message.reply_photo(media_path, caption=text, caption_entities=entities)
                    sent = True
                elif media_type == 'video':
                    await message.reply_video(media_path, caption=text, caption_entities=entities)
                    sent = True
                elif media_type == 'document':
                    await message.reply_document(media_path, caption=text, caption_entities=entities)
                    sent = True
                elif media_type == 'voice':
                    await message.reply_voice(media_path, caption=text, caption_entities=entities)
                    sent = True
                elif media_type == 'sticker':
                    await message.reply_sticker(media_path)
                    if text:
                        await message.reply_text(text, entities=entities)
                    sent = True
            except Exception as e:
                logger.error(f"Failed to send AR media: {e}")
                
        if not sent and text:
            await message.reply_text(text, entities=entities)
            
        AR_HISTORY[account_id][user_id] = time.time()
        logger.info(f"Autoresponder fired for account #{account_id} to user {user_id}")
    except Exception as e:
        logger.error(f"Error in autoresponder_callback: {e}")

class AccountSessionManager:
    # ── Configurable limits ───────────────────────────────────────
    MAX_ACTIVE_CLIENTS = int(os.environ.get('MAX_ACTIVE_CLIENTS', '5000'))    # max Pyrogram clients in memory
    MAX_TASKS_PER_USER = int(os.environ.get('MAX_TASKS_PER_USER', '50'))     # concurrent tasks per user
    MAX_GLOBAL_TASKS   = int(os.environ.get('MAX_GLOBAL_TASKS', '5000'))      # global concurrent task limit
    CLIENT_IDLE_TTL    = int(os.environ.get('CLIENT_IDLE_TTL', '18000'))     # 30 min idle before eviction

    def __init__(self, api_id: int, api_hash: str):
        self.api_id = api_id
        self.api_hash = api_hash
        self.active_clients: Dict[int, Client] = {}
        self._client_last_used: Dict[int, float] = {}           # account_id -> last access timestamp
        self._client_owner: Dict[int, int] = {}                 # account_id -> user_id
        self.active_spam_tasks: Dict[int, asyncio.Task] = {}
        self.active_spam_task_ids: Dict[int, int] = {}  # account_id -> task_id in DB
        self.active_join_tasks: Dict[int, asyncio.Task] = {}
        self.active_leave_tasks: Dict[int, asyncio.Task] = {}
        self.active_parse_tasks: Dict[int, asyncio.Task] = {}
        self.active_comment_tasks: Dict[int, asyncio.Task] = {}
        self.active_comment_task_ids: Dict[int, int] = {}  # account_id -> task_id in DB
        self.comment_listeners: Dict[int, Dict[str, int]] = {}
        self.temp_auth_clients: Dict[int, Dict[str, Any]] = {}
        self._client_locks: Dict[int, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()
        self._max_concurrent_tasks = self.MAX_GLOBAL_TASKS
        self._running_tasks = 0
        self._task_semaphore = asyncio.Semaphore(self._max_concurrent_tasks)
        self._last_bot_message: Dict[int, float] = {}
        self._bot_message_interval = 1.0
        self._spam_progress: Dict[int, Dict] = {}  # account_id -> {success, errors, total, running}
        self._user_task_counts: Dict[int, int] = {}  # user_id -> active task count
        self._user_task_lock = asyncio.Lock()
        self._cleanup_task: Optional[asyncio.Task] = None

    def create_client(self, session_string: str, proxy_str: str = "", name: str = "session") -> Client:
        proxy_dict = parse_proxy_string(proxy_str) if proxy_str else None
        client = Client(
            name=name,
            api_id=self.api_id,
            api_hash=self.api_hash,
            session_string=session_string,
            in_memory=True,
            proxy=proxy_dict
        )
        client.add_handler(MessageHandler(autoresponder_callback, filters.private & ~filters.me))
        return client

    async def _safe_bot_message(self, bot, user_id: int, text: str):
        now = time.time()
        last = self._last_bot_message.get(user_id, 0)
        if now - last < self._bot_message_interval:
            return
        self._last_bot_message[user_id] = now
        try:
            await bot.send_message(user_id, text)
        except Exception:
            pass

    async def _run_limited(self, coro):
        async with self._task_semaphore:
            self._running_tasks += 1
            try:
                return await coro
            finally:
                self._running_tasks -= 1

    async def run_limited(self, coro):
        return await self._run_limited(coro)

    # ── Per-user task quota enforcement ────────────────────────────
    async def _acquire_user_quota(self, user_id: int) -> bool:
        """Returns True if the user can start a new task, False if quota exceeded.
        Must be called BEFORE creating the task."""
        async with self._user_task_lock:
            current = self._user_task_counts.get(user_id, 0)
            if current >= self.MAX_TASKS_PER_USER:
                return False
            self._user_task_counts[user_id] = current + 1
            return True

    async def _release_user_quota(self, user_id: int):
        """Called when a task finishes. Decrements the user's task count."""
        async with self._user_task_lock:
            current = self._user_task_counts.get(user_id, 0)
            if current > 0:
                self._user_task_counts[user_id] = current - 1

    def _is_account_busy(self, account_id: int) -> bool:
        """Check if an account has active tasks (spam, parse, comment, join, leave)."""
        for task_dict in [self.active_spam_tasks, self.active_parse_tasks,
                          self.active_comment_tasks, self.active_join_tasks,
                          self.active_leave_tasks]:
            task = task_dict.get(account_id)
            if task and not task.done():
                return True
        return False

    async def _evict_idle_clients(self):
        """Evict Pyrogram clients that have been idle for longer than CLIENT_IDLE_TTL.
        Never evicts clients with active tasks."""
        now = time.time()
        to_evict = []
        for account_id, last_used in self._client_last_used.items():
            if now - last_used < self.CLIENT_IDLE_TTL:
                continue
            if self._is_account_busy(account_id):
                continue
            if account_id in self.active_clients:
                to_evict.append(account_id)

        evicted = 0
        for account_id in to_evict:
            client = self.active_clients.pop(account_id, None)
            self._client_last_used.pop(account_id, None)
            self._client_owner.pop(account_id, None)
            self._client_locks.pop(account_id, None)
            if client:
                try:
                    await client.stop()
                    evicted += 1
                except Exception as e:
                    logger.warning(f"Failed to stop idle client {account_id}: {e}")

        if evicted:
            logger.info(f"Evicted {evicted} idle clients (idle > {self.CLIENT_IDLE_TTL}s)")

    async def _enforce_client_limit(self):
        """If active clients exceed MAX_ACTIVE_CLIENTS, evict the oldest idle ones."""
        if len(self.active_clients) <= self.MAX_ACTIVE_CLIENTS:
            return
        candidates = sorted(
            self._client_last_used.items(),
            key=lambda x: x[1]
        )
        for account_id, _ in candidates:
            if len(self.active_clients) <= self.MAX_ACTIVE_CLIENTS:
                break
            if self._is_account_busy(account_id):
                continue
            client = self.active_clients.pop(account_id, None)
            self._client_last_used.pop(account_id, None)
            self._client_owner.pop(account_id, None)
            self._client_locks.pop(account_id, None)
            if client:
                try:
                    await client.stop()
                    logger.info(f"Evicted client {account_id} to enforce limit ({len(self.active_clients)}/{self.MAX_ACTIVE_CLIENTS})")
                except Exception as e:
                    logger.warning(f"Failed to stop client {account_id}: {e}")

    async def start_cleanup_loop(self):
        """Background task that periodically cleans up idle clients and AR_HISTORY."""
        while True:
            try:
                await asyncio.sleep(300)  # every 5 minutes
                cleanup_ar_history()
                await self._evict_idle_clients()
                await self._enforce_client_limit()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Cleanup loop error: {e}")

    async def graceful_shutdown(self):
        """Stop all active Pyrogram clients and cancel background tasks."""
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()

        # Cancel all active tasks
        for task_dict in [self.active_spam_tasks, self.active_parse_tasks,
                          self.active_comment_tasks, self.active_join_tasks,
                          self.active_leave_tasks]:
            for account_id, task in list(task_dict.items()):
                if task and not task.done():
                    task.cancel()
                    logger.info(f"Cancelled task for account {account_id}")
                task_dict.pop(account_id, None)

        # Stop all clients
        for account_id, client in list(self.active_clients.items()):
            try:
                await client.stop()
                logger.info(f"Stopped client for account {account_id}")
            except Exception as e:
                logger.warning(f"Error stopping client {account_id}: {e}")
        self.active_clients.clear()
        self._client_last_used.clear()
        self._client_owner.clear()
        self._client_locks.clear()
        self.active_spam_task_ids.clear()
        self.active_comment_task_ids.clear()

        # Disconnect temp auth clients
        for user_id, auth_data in list(self.temp_auth_clients.items()):
            client = auth_data.get("client")
            if client:
                try:
                    await client.disconnect()
                except:
                    pass
        self.temp_auth_clients.clear()

        logger.info("AccountSessionManager graceful shutdown complete")

    def _get_client_lock(self, account_id: int) -> asyncio.Lock:
        if account_id not in self._client_locks:
            self._client_locks[account_id] = asyncio.Lock()
        return self._client_locks[account_id]

    async def test_session_string(self, session_string: str, proxy_str: str = "") -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
        try:
            client = self.create_client(session_string, proxy_str, name="temp_test")
            await client.start()
            me = await client.get_me()
            info = {
                "id": me.id,
                "first_name": me.first_name or "",
                "last_name": me.last_name or "",
                "username": me.username or "",
                "phone": me.phone_number or ""
            }
            await client.stop()
            return True, info, None
        except Exception as e:
            return False, None, str(e)

    # ==================== INTERACTIVE PHONE AUTH ====================
    async def start_phone_auth(self, user_id: int, phone: str, proxy_str: str = "") -> Tuple[bool, Optional[str], Optional[str]]:
        """Sends verification code to Telegram phone."""
        try:
            proxy_dict = parse_proxy_string(proxy_str) if proxy_str else None
            temp_client = Client(
                name=f"auth_{user_id}_{int(time.time())}",
                api_id=self.api_id,
                api_hash=self.api_hash,
                in_memory=True,
                proxy=proxy_dict
            )
            await temp_client.connect()
            sent_code = await temp_client.send_code(phone)
            self.temp_auth_clients[user_id] = {
                "client": temp_client,
                "phone": phone,
                "phone_code_hash": sent_code.phone_code_hash,
                "proxy": proxy_str
            }
            return True, sent_code.phone_code_hash, None
        except Exception as e:
            return False, None, str(e)

    async def submit_phone_code(self, user_id: int, code: str) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]], bool, Optional[str]]:
        """
        Submits SMS/Telegram code.
        Returns: (success, session_string, user_info, is_2fa_needed, error_message)
        """
        auth_data = self.temp_auth_clients.get(user_id)
        if not auth_data:
            return False, None, None, False, "Сессия авторизации не найдена или истекла."

        client: Client = auth_data["client"]
        phone = auth_data["phone"]
        phone_code_hash = auth_data["phone_code_hash"]

        try:
            signed_in = await client.sign_in(phone, phone_code_hash, code)
            session_str = await client.export_session_string()
            me = await client.get_me()
            info = {
                "id": me.id,
                "first_name": me.first_name or "",
                "last_name": me.last_name or "",
                "username": me.username or "",
                "phone": me.phone_number or phone
            }
            await client.disconnect()
            del self.temp_auth_clients[user_id]
            return True, session_str, info, False, None
        except Exception as e:
            err_str = str(e)
            if "SESSION_PASSWORD_NEEDED" in err_str or "PASSWORD_HASH_INVALID" in err_str:
                return False, None, None, True, "Требуется пароль двухфакторной аутентификации (2FA Cloud Password)"
            return False, None, None, False, err_str

    async def submit_2fa_password(self, user_id: int, password: str) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]], Optional[str]]:
        auth_data = self.temp_auth_clients.get(user_id)
        if not auth_data:
            return False, None, None, "Сессия авторизации не найдена или истекла."

        client: Client = auth_data["client"]
        try:
            await client.check_password(password)
            session_str = await client.export_session_string()
            me = await client.get_me()
            info = {
                "id": me.id,
                "first_name": me.first_name or "",
                "last_name": me.last_name or "",
                "username": me.username or "",
                "phone": me.phone_number or auth_data.get("phone", "")
            }
            await client.disconnect()
            del self.temp_auth_clients[user_id]
            return True, session_str, info, None
        except Exception as e:
            return False, None, None, str(e)

    async def start_qr_login(self, user_id: int, proxy_str: str = ""):
        try:
            proxy_dict = parse_proxy_string(proxy_str) if proxy_str else None
            temp_client = Client(
                name=f"qr_{user_id}_{int(time.time())}",
                api_id=self.api_id,
                api_hash=self.api_hash,
                in_memory=True,
                proxy=proxy_dict
            )
            await temp_client.connect()
            from pyrogram.raw import functions
            login_token = await temp_client.invoke(
                functions.auth.ExportLoginToken(
                    api_id=self.api_id,
                    api_hash=self.api_hash,
                    except_ids=[]
                )
            )
            import base64
            token_bytes = login_token.token
            qr_url = "tg://login?token=" + base64.urlsafe_b64encode(token_bytes).decode('utf-8').rstrip('=')
            self.temp_auth_clients[user_id] = {
                "client": temp_client,
                "proxy": proxy_str,
                "qr_file_id": None,
                "qr_text": qr_url,
                "qr_bytes": None,
                "login_token": login_token,
                "qr_url": qr_url
            }
            try:
                import qrcode
                import io
                img = qrcode.make(qr_url)
                buf = io.BytesIO()
                img.save(buf, format='PNG')
                buf.seek(0)
                self.temp_auth_clients[user_id]["qr_bytes"] = buf.getvalue()
                logger.info(f"✅ QR-код сгенерирован для user_id={user_id} ({len(buf.getvalue())} bytes)")
                return {"qr_file_id": None, "qr_text": qr_url, "qr_bytes": buf.getvalue()}
            except Exception as img_err:
                logger.error(f"❌ Ошибка генерации QR-кода: {type(img_err).__name__}: {img_err}")
                return {"qr_file_id": None, "qr_text": qr_url, "qr_bytes": None}
        except Exception as e:
            return {"error": str(e)}

    async def submit_qr_2fa_password(self, user_id: int, password: str):
        auth_data = self.temp_auth_clients.get(user_id)
        if not auth_data:
            return False, None, None, "QR-сессия не найдена или истекла."
        client: Client = auth_data["client"]
        try:
            from pyrogram.raw import functions
            from pyrogram.raw import types as raw_types
            from pyrogram.errors import SessionPasswordNeeded

            try:
                logger.info(f"QR 2FA: вызов check_password для user_id={user_id}")
                await client.check_password(password)
                logger.info(f"QR 2FA: check_password успешно для user_id={user_id}")
            except SessionPasswordNeeded:
                return False, None, None, "Неверный пароль 2FA."
            except Exception as e:
                return False, None, None, f"Ошибка проверки пароля: {e}"

            login_token = auth_data.get("login_token")
            if not login_token:
                return False, None, None, "Токен не найден. Запустите вход заново."

            try:
                resp = await asyncio.wait_for(
                    client.invoke(
                        functions.auth.ImportLoginToken(token=login_token.token)
                    ),
                    timeout=15
                )
            except Exception as e:
                return False, None, None, f"Ошибка импорта токена: {e}"

            if isinstance(resp, raw_types.auth.LoginTokenMigrateTo):
                try:
                    resp = await client.invoke(
                        functions.auth.ImportLoginToken(token=resp.token)
                    )
                except Exception as e:
                    return False, None, None, f"Ошибка импорта токена (миграция): {e}"

            if not isinstance(resp, raw_types.auth.LoginTokenSuccess):
                return False, None, None, "Токен не был принят."

            try:
                me = await client.get_me()
            except Exception as e:
                return False, None, None, f"Ошибка получения данных пользователя: {e}"

            session_str = await client.export_session_string()
            info = {
                "id": me.id,
                "first_name": me.first_name or "",
                "last_name": me.last_name or "",
                "username": me.username or "",
                "phone": me.phone_number or ""
            }
            await client.disconnect()
            del self.temp_auth_clients[user_id]
            return True, session_str, info, None
        except Exception as e:
            return False, None, None, str(e)

    async def finish_qr_login_stream(self, user_id: int, proxy_str: str = "", bot=None):
        """Генератор: возвращает (обновление_QR, is_final) или (результат, True)."""
        auth_data = self.temp_auth_clients.get(user_id)
        if not auth_data:
            yield (False, None, None, "QR-сессия не найдена или истекла. Запустите вход заново."), True
            return
        client: Client = auth_data["client"]
        try:
            from pyrogram.raw import functions
            from pyrogram.raw import types as raw_types
            from pyrogram.errors import SessionPasswordNeeded, AuthTokenExpired, AuthTokenInvalid, AuthKeyUnregistered

            deadline = time.time() + 180
            last_token_bytes = auth_data.get("login_token").token if auth_data.get("login_token") else None
            qr_update_count = 0
            import_attempted = False
            while time.time() < deadline:
                if last_token_bytes and not import_attempted:
                    try:
                        logger.info(f"QR: пробуем ImportLoginToken для user_id={user_id}")
                        resp = await asyncio.wait_for(
                            client.invoke(
                                functions.auth.ImportLoginToken(token=last_token_bytes)
                            ),
                            timeout=15
                        )
                        import_attempted = True
                        if isinstance(resp, raw_types.auth.LoginTokenSuccess):
                            try:
                                me = await client.get_me()
                            except Exception as e:
                                yield (False, None, None, f"Ошибка получения данных пользователя: {e}"), True
                                return
                            session_str = await client.export_session_string()
                            info = {
                                "id": me.id,
                                "first_name": me.first_name or "",
                                "last_name": me.last_name or "",
                                "username": me.username or "",
                                "phone": me.phone_number or ""
                            }
                            await client.disconnect()
                            del self.temp_auth_clients[user_id]
                            logger.info(f"✅ QR-вход успешно завершён для user_id={user_id}")
                            yield (True, session_str, info, None), True
                            return
                        if isinstance(resp, raw_types.auth.LoginTokenMigrateTo):
                            try:
                                resp = await client.invoke(
                                    functions.auth.ImportLoginToken(token=resp.token)
                                )
                            except Exception as e:
                                yield (False, None, None, f"Ошибка импорта токена (миграция): {e}"), True
                                return
                            if isinstance(resp, raw_types.auth.LoginTokenSuccess):
                                try:
                                    me = await client.get_me()
                                except Exception as e:
                                    yield (False, None, None, f"Ошибка получения данных пользователя: {e}"), True
                                    return
                                session_str = await client.export_session_string()
                                info = {
                                    "id": me.id,
                                    "first_name": me.first_name or "",
                                    "last_name": me.last_name or "",
                                    "username": me.username or "",
                                    "phone": me.phone_number or ""
                                }
                                await client.disconnect()
                                del self.temp_auth_clients[user_id]
                                logger.info(f"✅ QR-вход успешно завершён (миграция) для user_id={user_id}")
                                yield (True, session_str, info, None), True
                                return
                    except SessionPasswordNeeded:
                        logger.warning(f"QR: требуется пароль 2FA для user_id={user_id}")
                        yield (None, None, None, "Требуется пароль 2FA (Cloud Password)"), True
                        return
                    except (AuthTokenExpired, AuthTokenInvalid, AuthKeyUnregistered) as e:
                        logger.info(f"QR: токен ещё не принят ({type(e).__name__}), продолжаем опрос")
                        import_attempted = False
                    except Exception as e:
                        logger.warning(f"QR: ImportLoginToken ошибка: {type(e).__name__}: {e}")
                        import_attempted = False

                try:
                    resp = await asyncio.wait_for(
                        client.invoke(
                            functions.auth.ExportLoginToken(
                                api_id=self.api_id,
                                api_hash=self.api_hash,
                                except_ids=[]
                            )
                        ),
                        timeout=15
                    )
                except asyncio.TimeoutError:
                    logger.warning(f"QR: таймаут ExportLoginToken для user_id={user_id}")
                    await asyncio.sleep(3)
                    continue
                except (AuthTokenExpired, AuthTokenInvalid, AuthKeyUnregistered) as e:
                    logger.info(f"QR: ExportLoginToken - токен ещё не принят ({type(e).__name__})")
                    await asyncio.sleep(2)
                    continue
                except Exception as e:
                    logger.warning(f"QR: ExportLoginToken ошибка: {type(e).__name__}: {e}")
                    await asyncio.sleep(3)
                    continue

                if isinstance(resp, raw_types.auth.LoginTokenSuccess):
                    try:
                        me = await client.get_me()
                    except Exception as e:
                        yield (False, None, None, f"Ошибка получения данных пользователя: {e}"), True
                        return
                    session_str = await client.export_session_string()
                    info = {
                        "id": me.id,
                        "first_name": me.first_name or "",
                        "last_name": me.last_name or "",
                        "username": me.username or "",
                        "phone": me.phone_number or ""
                    }
                    await client.disconnect()
                    del self.temp_auth_clients[user_id]
                    logger.info(f"✅ QR-вход успешно завершён для user_id={user_id}")
                    yield (True, session_str, info, None), True
                    return

                if isinstance(resp, raw_types.auth.LoginTokenMigrateTo):
                    logger.info(f"QR: миграция токена на DC{resp.dc_id} для user_id={user_id}")
                    try:
                        resp = await client.invoke(
                            functions.auth.ImportLoginToken(token=resp.token)
                        )
                    except Exception as e:
                        yield (False, None, None, f"Ошибка импорта токена (миграция): {e}"), True
                        return
                    if isinstance(resp, raw_types.auth.LoginTokenSuccess):
                        try:
                            me = await client.get_me()
                        except Exception as e:
                            yield (False, None, None, f"Ошибка получения данных пользователя: {e}"), True
                            return
                        session_str = await client.export_session_string()
                        info = {
                            "id": me.id,
                            "first_name": me.first_name or "",
                            "last_name": me.last_name or "",
                            "username": me.username or "",
                            "phone": me.phone_number or ""
                        }
                        await client.disconnect()
                        del self.temp_auth_clients[user_id]
                        logger.info(f"✅ QR-вход успешно завершён (миграция) для user_id={user_id}")
                        yield (True, session_str, info, None), True
                        return
                    await asyncio.sleep(2)
                    continue

                if isinstance(resp, raw_types.auth.LoginToken):
                    current_bytes = resp.token
                    if current_bytes != last_token_bytes or qr_update_count == 0:
                        last_token_bytes = current_bytes
                        qr_update_count += 1
                        try:
                            import qrcode
                            import io
                            import base64
                            qr_url = "tg://login?token=" + base64.urlsafe_b64encode(resp.token).decode('utf-8').rstrip('=')
                            img = qrcode.make(qr_url)
                            buf = io.BytesIO()
                            img.save(buf, format='PNG')
                            buf.seek(0)
                            self.temp_auth_clients[user_id]["qr_bytes"] = buf.getvalue()
                            self.temp_auth_clients[user_id]["qr_text"] = qr_url
                            self.temp_auth_clients[user_id]["login_token"] = resp
                            self.temp_auth_clients[user_id]["qr_update_count"] = qr_update_count
                            logger.info(f"🔄 QR-код обновлён #{qr_update_count} для user_id={user_id}")
                            yield {
                                "qr_bytes": buf.getvalue(),
                                "qr_text": qr_url
                            }, False
                        except Exception as img_err:
                            logger.error(f"❌ Ошибка генерации QR: {img_err}")
                    await asyncio.sleep(2)
                    continue

                await asyncio.sleep(2)

            yield (False, None, None, "Время ожидания сканирования QR-кода истекло. Попробуйте ещё раз."), True
        except SessionPasswordNeeded:
            yield (False, None, None, "Требуется пароль 2FA. Используйте phone-авторизацию."), True
        except Exception as e:
            yield (False, None, None, str(e)), True

    def cancel_phone_auth(self, user_id: int):
        auth_data = self.temp_auth_clients.pop(user_id, None)
        if auth_data and "client" in auth_data:
            try:
                asyncio.create_task(auth_data["client"].disconnect())
            except:
                pass

    # ==================== CLIENT MANAGEMENT ====================
    async def change_account_bio(self, account_id: int, new_bio: str) -> Tuple[bool, str]:
        client, err = await self.get_or_start_client(account_id)
        if not client:
            return False, err
        try:
            await client.update_profile(bio=new_bio)
            return True, "BIO успешно изменено!"
        except Exception as e:
            logger.error(f"Error changing bio for acc {account_id}: {e}")
            return False, str(e)

    async def get_or_start_client(self, account_id: int, user_id: int = None) -> Tuple[Optional[Client], Optional[str]]:
        async with self._get_client_lock(account_id):
            # Update last-used timestamp
            self._client_last_used[account_id] = time.time()
            if user_id:
                self._client_owner[account_id] = user_id
            
            if account_id in self.active_clients:
                client = self.active_clients[account_id]
                try:
                    await client.get_me()
                    return client, None
                except Exception:
                    try:
                        await client.start()
                        return client, None
                    except Exception as start_err:
                        err_str = str(start_err).lower()
                        if "already" in err_str or "started" in err_str:
                            return client, None
                        self.active_clients.pop(account_id, None)

            account = db.get_account(account_id)
            if not account:
                return None, "Аккаунт не найден в базе данных"

            try:
                client = self.create_client(
                    session_string=account['session_string'],
                    proxy_str=account.get('proxy', ''),
                    name=f"acc_{account_id}"
                )
                await client.start()
                self.active_clients[account_id] = client
                # Enforce client limit after adding new client
                await self._enforce_client_limit()
                return client, None
            except Exception as e:
                err_str = str(e).lower()
                if "already" in err_str or "started" in err_str:
                    self.active_clients[account_id] = client
                    # Enforce client limit after adding new client
                    await self._enforce_client_limit()
                    return client, None
                db.update_account_status(account_id, 'error')
                return None, f"Ошибка запуска сессии аккаунта: {e}"

    async def get_last_10_pms(self, account_id: int):
        client, err = await self.get_or_start_client(account_id)
        if not client:
            return None, err
        
        try:
            pms = []
            async for dialog in client.get_dialogs():
                if dialog.chat.type == enums.ChatType.PRIVATE:
                    if dialog.chat.is_bot or dialog.chat.is_verified or dialog.chat.is_support:
                        continue
                    pms.append({
                        'chat_id': dialog.chat.id,
                        'first_name': dialog.chat.first_name or "",
                        'last_name': dialog.chat.last_name or "",
                        'username': dialog.chat.username or "",
                        'last_message': dialog.top_message.text or "Media/File",
                        'date': dialog.top_message.date
                    })
                    if len(pms) >= 10:
                        break
            return pms, None
        except Exception as e:
            return None, str(e)

    async def stop_client(self, account_id: int):
        client = self.active_clients.pop(account_id, None)
        if client:
            try:
                await client.stop()
            except Exception:
                pass

    async def sync_peer_cache(self, account_id: int, chat_ids: list = None):
        client, err = await self.get_or_start_client(account_id)
        if not client:
            return False, err
        try:
            async for dialog in client.get_dialogs(limit=200):
                try:
                    chat = dialog.chat
                    if chat and hasattr(chat, 'id'):
                        await client.resolve_peer(chat.id)
                except Exception:
                    continue
            if chat_ids:
                for cid in chat_ids:
                    try:
                        await client.resolve_peer(cid)
                    except Exception:
                        continue
            return True, "Кеш синхронизирован"
        except Exception as e:
            return False, str(e)

    # Шаблон системного промта. {instruction} — то, что пользователь пишет в настройках
    # (например: "дополнительно призыв глянуть профиль или био").
    # Максимальная длина комментария. Живой подписчик не пишет простыни,
    # а длинный текст мгновенно выдаёт бота и ловит бан.
    MAX_COMMENT_CHARS = 320

    AI_SYSTEM_TEMPLATE = (
        "Ты — живой человек, читающий Telegram-канал, а не бот. "
        "Напиши ОДИН короткий комментарий (максимум 2 предложения, "
        "не длиннее 300 символов) к посту ниже на языке поста.\n"
        "Правила:\n"
        "- пиши естественно и по теме поста, как обычный подписчик;\n"
        "- без приветствий, без кавычек, без хештегов, без markdown;\n"
        "- НИКАКИХ списков, таблиц, заголовков, пунктов и разметки;\n"
        "- не давай советов, анализа и инструкций, если об этом не просили;\n"
        "- не пересказывай пост и не повторяй его дословно;\n"
        "- не упоминай, что ты ИИ, и не объясняй свой ответ;\n"
        "- в ответе только текст комментария, одним абзацем.\n"
        "{instruction_block}"
    )

    @staticmethod
    def build_comment_messages(instruction: str, post_text: str = "") -> list:
        """Собирает messages для LLM.

        instruction — пожелание пользователя (тематика + доп. указания, например
        призыв заглянуть в профиль). Оно идёт ОТДЕЛЬНЫМ блоком требований, а не
        просто подклеивается к тексту, поэтому модель выполняет его как инструкцию,
        а не считает частью поста.
        """
        instruction = (instruction or '').strip()
        if instruction:
            instruction_block = (
                "\nДополнительные требования от заказчика (обязательно учти их в комментарии):\n"
                f"{instruction}\n"
            )
        else:
            instruction_block = ""

        system = AccountSessionManager.AI_SYSTEM_TEMPLATE.format(instruction_block=instruction_block)
        messages = [{"role": "system", "content": system}]
        # Пример диалога: показываем модели ожидаемый формат ответа.
        # Без этого reasoning-модели (gpt-oss и подобные) отвечают развёрнутым
        # разбором с таблицами вместо живой реплики.
        messages.append({"role": "user", "content":
                         "Текст поста:\nСегодня рынок снова удивил: активы прибавили 5% за сутки."})
        messages.append({"role": "assistant", "content":
                         "Вот это скачок, давно такого не было. Интересно, удержится ли."})
        if post_text:
            messages.append({"role": "user", "content": f"Текст поста:\n{post_text[:1500]}"})
        else:
            messages.append({"role": "user", "content": "Напиши комментарий по требованиям выше."})
        return messages

    @staticmethod
    def _clean_ai_output(text: str) -> str:
        """Убирает типовой мусор LLM: кавычки-обёртки, префиксы, markdown, лишние строки."""
        if not text:
            return ""
        result = text.strip()
        # срезаем reasoning-блоки некоторых моделей
        if '</think>' in result:
            result = result.split('</think>')[-1].strip()
        # первая непустая строка-абзац (модель иногда даёт варианты списком)
        for prefix in ('Комментарий:', 'Ответ:', 'Comment:', 'Answer:'):
            if result.lower().startswith(prefix.lower()):
                result = result[len(prefix):].strip()
        if len(result) > 1 and result[0] in '"\u00ab\u201c\'' and result[-1] in '"\u00bb\u201d\'':
            result = result[1:-1].strip()
        result = result.replace('**', '').replace('__', '')

        # ── Обрезаем «простыни» ──
        # Модели вроде gpt-oss любят отвечать разбором с таблицами и списками.
        # Для комментария это мгновенный признак бота, поэтому берём только
        # связный текст и ограничиваем длину.
        lines = []
        for raw_line in result.split('\n'):
            line = raw_line.strip()
            if not line:
                if lines:
                    break          # первый абзац закончился — дальше не нужно
                continue
            # таблицы, заголовки, списки, нумерация — мусор для комментария
            if line.startswith('|') or set(line) <= set('|-: '):
                break
            if line.startswith('#') or line.startswith('---'):
                break
            if re.match(r'^([-*•]|\d+[.)])\s+', line):
                break
            lines.append(line)
        if lines:
            result = ' '.join(lines).strip()

        limit = AccountSessionManager.MAX_COMMENT_CHARS
        if len(result) > limit:
            cut = result[:limit]
            # обрезаем по границе предложения, иначе по последнему пробелу
            marks = [cut.rfind(m) for m in ('. ', '! ', '? ', '…')]
            best = max(marks)
            if best > limit * 0.4:
                result = cut[:best + 1]
            else:
                sp = cut.rfind(' ')
                result = (cut[:sp] if sp > limit * 0.4 else cut).rstrip(' ,;:—-') + '…'
        return result.strip()

    # ==================== TELEGRAM CALL GUARD (FloodWait & bans) ====================
    async def tg_call(self, factory, *, account_id: int = None, bot=None, user_id: int = None,
                      description: str = '', max_retries: int = 3,
                      notify: bool = True, raise_on_skip: bool = False):
        """Выполняет вызов Telegram API с обработкой FloodWait и банов.

        factory — функция без аргументов, возвращающая корутину. Именно функция,
        а не готовая корутина: при повторе нужно создать вызов заново
        (корутину нельзя переиспользовать после await).

        Поведение:
          • FloodWait/SlowmodeWait  — ждём указанное время (+джиттер) и повторяем;
            если ждать дольше MAX_FLOOD_WAIT — ставим аккаунт на паузу и прерываем задачу;
          • PeerFlood / бан в канале — AccountBlockedError(kind='restricted'), задача встаёт;
          • мёртвая сессия          — AccountBlockedError(kind='banned');
          • проблема конкретного чата — TargetSkipError (или None, если raise_on_skip=False).

        Возвращает результат вызова либо None, если цель пропущена.
        """
        label = description or 'telegram call'
        last_err = None

        for attempt in range(1, max_retries + 1):
            try:
                result = await factory()
                # Успешный вызов после флуда — снимаем пометку кулдауна
                if account_id and attempt > 1:
                    try:
                        db.clear_account_health(account_id)
                    except Exception:
                        pass
                return result

            except asyncio.CancelledError:
                raise

            except FLOOD_ERRORS as e:
                wait = int(getattr(e, 'value', None) or getattr(e, 'x', None) or 60)
                last_err = e
                if account_id:
                    try:
                        db.record_flood_wait(account_id, wait)
                    except Exception:
                        pass

                if wait > MAX_FLOOD_WAIT:
                    msg = (f"FloodWait {wait} сек. ({wait // 60} мин.) — это дольше лимита "
                           f"{MAX_FLOOD_WAIT} сек., задача остановлена.")
                    logging.error(f"🛑 [acc {account_id}] {label}: {msg}")
                    if notify and bot and user_id:
                        await self._safe_bot_message(
                            bot, user_id,
                            f"🛑 Аккаунт #{account_id} получил длительное ограничение Telegram "
                            f"({wait // 60} мин.).\n\nЗадача остановлена. Дайте аккаунту отдохнуть "
                            f"и увеличьте интервалы между сообщениями."
                        )
                    raise AccountBlockedError(msg, kind='restricted')

                sleep_for = wait + random.uniform(1.0, 3.0)
                logging.warning(
                    f"⏳ [acc {account_id}] {label}: FloodWait {wait}s "
                    f"(попытка {attempt}/{max_retries}), жду {sleep_for:.0f}s"
                )
                if notify and bot and user_id and wait >= 60:
                    await self._safe_bot_message(
                        bot, user_id,
                        f"⏳ Telegram просит подождать {wait} сек. (аккаунт #{account_id}). "
                        f"Задача продолжится автоматически."
                    )
                await asyncio.sleep(sleep_for)
                continue

            except SPAMBLOCK_ERRORS as e:
                msg = f"{type(e).__name__}: аккаунт ограничен Telegram за спам"
                logging.error(f"🚫 [acc {account_id}] {label}: {msg}")
                if account_id:
                    try:
                        db.set_account_health(account_id, db.HEALTH_RESTRICTED, msg)
                    except Exception:
                        pass
                if notify and bot and user_id:
                    await self._safe_bot_message(
                        bot, user_id,
                        f"🚫 <b>Аккаунт #{account_id} получил спам-блок Telegram.</b>\n\n"
                        f"Все задачи по нему остановлены, чтобы не усугубить ограничение.\n\n"
                        f"Что делать:\n"
                        f"• не запускайте рассылки на этом аккаунте 24–48 часов;\n"
                        f"• напишите @SpamBot и запросите снятие ограничения;\n"
                        f"• увеличьте задержки и используйте разный текст (спинтакс)."
                    )
                raise AccountBlockedError(msg, kind='restricted')

            except DEAD_SESSION_ERRORS as e:
                msg = f"{type(e).__name__}: сессия недействительна"
                logging.error(f"💀 [acc {account_id}] {label}: {msg}")
                if account_id:
                    try:
                        db.set_account_health(account_id, db.HEALTH_BANNED, msg)
                        db.update_account_status(account_id, 'banned')
                    except Exception:
                        pass
                if notify and bot and user_id:
                    await self._safe_bot_message(
                        bot, user_id,
                        f"💀 <b>Аккаунт #{account_id} недоступен.</b>\n\n"
                        f"Причина: {type(e).__name__}. Сессия отозвана или аккаунт заблокирован "
                        f"Telegram — требуется переподключение."
                    )
                raise AccountBlockedError(msg, kind='banned')

            except SKIP_TARGET_ERRORS as e:
                logging.info(f"⏭ [acc {account_id}] {label}: {type(e).__name__} — цель пропущена")
                if raise_on_skip:
                    raise TargetSkipError(f"{type(e).__name__}") from e
                return None

            except (AccountBlockedError, TargetSkipError):
                raise

            except (ValueError, KeyError) as e:
                # «Peer id invalid» / «ID not found»: чат не в локальном кэше
                # пиров — обычная ситуация, а не сбой. Уровень INFO, чтобы
                # не заливать лог ошибками при обходе сотен чатов.
                txt = str(e)
                if 'Peer id invalid' in txt or 'ID not found' in txt:
                    logging.info(f"⏭ [acc {account_id}] {label}: пир неизвестен — пропуск")
                    if raise_on_skip:
                        raise TargetSkipError(txt) from e
                    return None
                logging.error(f"❌ [acc {account_id}] {label}: {type(e).__name__}: {txt[:200]}")
                raise

            except Exception as e:
                last_err = e
                # Сетевые сбои имеет смысл повторить, прикладные ошибки — нет
                transient = isinstance(e, (asyncio.TimeoutError, ConnectionError, OSError))
                if transient and attempt < max_retries:
                    backoff = min(30, 2 ** attempt) + random.uniform(0, 1.5)
                    logging.warning(
                        f"🔁 [acc {account_id}] {label}: {type(e).__name__}: {str(e)[:120]} — "
                        f"повтор через {backoff:.1f}s ({attempt}/{max_retries})"
                    )
                    await asyncio.sleep(backoff)
                    continue
                logging.error(f"❌ [acc {account_id}] {label}: {type(e).__name__}: {str(e)[:200]}")
                raise

        if last_err:
            raise last_err
        return None

    async def generate_ai_comment(self, prompt: str, post_text: str = "") -> str:
        """Генерирует комментарий. Перебирает провайдеров, пока кто-то не ответит."""
        messages = self.build_comment_messages(prompt, post_text)
        logging.info(f"🤖 AI comment | model={AI_MODEL} | instruction_len={len(prompt or '')} | post_len={len(post_text)}")

        errors = []

        # ── 1. Groq (быстрый, щедрый бесплатный лимит) ───────────────
        if GROQ_API_KEY and not GROQ_API_KEY.startswith(('ЗАМЕНИТЕ', 'REPLACE')):
            # Подменяем снятые с обслуживания модели на актуальные
            requested = GROQ_DECOMMISSIONED.get(AI_MODEL, AI_MODEL)
            if AI_MODEL in GROQ_DECOMMISSIONED:
                logging.warning(
                    f"⚠️ Модель Groq '{AI_MODEL}' снята с обслуживания, использую '{requested}'. "
                    f"Обновите MODEL в config.ini."
                )
            candidates = [requested] + [m for m in GROQ_MODELS if m != requested]
            for groq_model in candidates[:3]:
                try:
                    result = await self._groq_chat(groq_model, messages)
                    if result:
                        cleaned = self._clean_ai_output(result)
                        if cleaned:
                            logging.info(f"🤖 Groq:{groq_model} → {cleaned[:80]}")
                            return cleaned
                except _ModelGoneError as e:
                    logging.warning(f"⚠️ Groq модель {groq_model} недоступна: {e}; пробую следующую")
                    errors.append(f"groq:{groq_model}")
                    continue
                except Exception as e:
                    logging.error(f"❌ Groq {groq_model}: {type(e).__name__}: {str(e)[:200]}")
                    errors.append(f"groq:{groq_model}")
                    break

        # ── 2. Google Gemini ─────────────────────────────────────────
        if GEMINI_API_KEY and not GEMINI_API_KEY.startswith(('ЗАМЕНИТЕ', 'REPLACE')):
            try:
                import google.generativeai as genai
                genai.configure(api_key=GEMINI_API_KEY)
                model_name = AI_MODEL if 'gemini' in AI_MODEL.lower() else 'gemini-2.0-flash'
                model = genai.GenerativeModel(model_name)
                full_prompt = "\n\n".join([m['content'] for m in messages])
                response = await asyncio.to_thread(
                    model.generate_content,
                    full_prompt,
                    generation_config=genai.types.GenerationConfig(max_output_tokens=200, temperature=0.8)
                )
                cleaned = self._clean_ai_output(response.text)
                if cleaned:
                    logging.info(f"🤖 Gemini → {cleaned[:80]}")
                    return cleaned
            except Exception as e:
                logging.error(f"❌ Gemini: {type(e).__name__}: {str(e)[:200]}")
                errors.append('gemini')

        # ── 3. OpenRouter ────────────────────────────────────────────
        if OPENROUTER_API_KEY and not OPENROUTER_API_KEY.startswith(('ЗАМЕНИТЕ', 'REPLACE')):
            try:
                import httpx
                async with httpx.AsyncClient(timeout=30.0) as http_client:
                    response = await http_client.post(
                        "https://openrouter.ai/api/v1/chat/completions",
                        headers={
                            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                            "Content-Type": "application/json",
                            "HTTP-Referer": "https://t.me/poster_bot",
                            "X-Title": "PostDrive"
                        },
                        json={"model": AI_MODEL, "messages": messages, "max_tokens": 160, "temperature": 0.9}
                    )
                    response.raise_for_status()
                    data = response.json()
                    cleaned = self._clean_ai_output(data["choices"][0]["message"]["content"])
                    if cleaned:
                        logging.info(f"🤖 OpenRouter → {cleaned[:80]}")
                        return cleaned
            except Exception as e:
                logging.error(f"❌ OpenRouter: {type(e).__name__}: {str(e)[:200]}")
                errors.append('openrouter')

        # ── 4. OpenAI ────────────────────────────────────────────────
        if OPENAI_API_KEY and not OPENAI_API_KEY.startswith(('ЗАМЕНИТЕ', 'REPLACE')):
            try:
                from openai import AsyncOpenAI
                oai = AsyncOpenAI(api_key=OPENAI_API_KEY)
                model_name = AI_MODEL if AI_MODEL.startswith('gpt') else 'gpt-4o-mini'
                response = await oai.chat.completions.create(
                    model=model_name, messages=messages, max_tokens=160, temperature=0.9
                )
                cleaned = self._clean_ai_output(response.choices[0].message.content)
                if cleaned:
                    logging.info(f"🤖 OpenAI → {cleaned[:80]}")
                    return cleaned
            except Exception as e:
                logging.error(f"❌ OpenAI: {type(e).__name__}: {str(e)[:200]}")
                errors.append('openai')

        # ── 5. g4f (бесплатно, без ключей, но нестабильно) ───────────
        if G4F_ENABLED:
            cleaned = await self._g4f_chat(messages)
            if cleaned:
                return cleaned
            errors.append('g4f')

        logging.warning(
            f"⚠️ Все AI-провайдеры недоступны ({', '.join(errors) or 'нет провайдеров'}). "
            f"Добавьте GROQ_API_KEY в config.ini — это бесплатно и надёжнее g4f."
        )
        return ""

    async def _groq_chat(self, model: str, messages: list) -> Optional[str]:
        """Один запрос к Groq. Бросает _ModelGoneError, если модель снята с обслуживания."""
        import json as json_mod
        payload = {"model": model, "messages": messages, "max_tokens": 160, "temperature": 0.9}
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}

        try:
            import httpx
            async with httpx.AsyncClient(timeout=30.0) as http_client:
                resp = await http_client.post(url, headers=headers, json=payload)
                if resp.status_code == 200:
                    return resp.json()["choices"][0]["message"]["content"]
                body = resp.text[:300]
                if resp.status_code in (400, 404) and ('decommission' in body or 'does not exist' in body):
                    raise _ModelGoneError(body)
                if resp.status_code == 429:
                    raise RuntimeError(f"rate limit: {body}")
                raise RuntimeError(f"HTTP {resp.status_code}: {body}")
        except ImportError:
            def _urllib_request():
                import urllib.request, urllib.error
                req = urllib.request.Request(
                    url, data=json_mod.dumps(payload).encode('utf-8'), headers=headers, method='POST'
                )
                try:
                    with urllib.request.urlopen(req, timeout=30.0) as r:
                        return json_mod.loads(r.read().decode('utf-8'))["choices"][0]["message"]["content"]
                except urllib.error.HTTPError as he:
                    body = he.read().decode('utf-8', 'ignore')[:300]
                    if he.code in (400, 404) and ('decommission' in body or 'does not exist' in body):
                        raise _ModelGoneError(body)
                    raise RuntimeError(f"HTTP {he.code}: {body}")
            return await asyncio.to_thread(_urllib_request)

    _g4f_provider_cache = None
    # Провайдеры, которые начали требовать оплату (402 / credits / proof-of-work).
    # Пополняется на лету и больше не опрашивается до перезапуска бота.
    _g4f_paid = set()

    # Провайдеры, заведомо требующие ключ/оплату или проксирующие платные API.
    # Держим отдельным списком, чтобы не тратить на них попытки.
    G4F_PAID_PROVIDERS = {
        'PollinationsAI', 'Pollinations', 'PollinationsImage', 'PollinationsAudio',
        'OpenaiChat', 'OpenaiAccount', 'OpenAIFM', 'Copilot', 'CopilotApp',
        'MetaAI', 'Gemini', 'GeminiPro', 'Claude', 'Perplexity', 'Groq',
        'Nvidia', 'HuggingSpace', 'LMArena', 'OpenRouterFree', 'Custom',
    }

    @staticmethod
    def _is_paid_error(e) -> bool:
        """Похоже ли исключение на требование оплаты/регистрации."""
        name = type(e).__name__
        if name in ('PaymentRequiredError', 'MissingAuthError', 'ModelNotAllowedError'):
            return True
        txt = str(e).lower()
        markers = ('402', 'payment required', 'no cake credits', 'proof-of-work',
                   'credits', 'sign up', 'api key', 'unauthorized', '401',
                   'quota', 'subscription', 'insufficient')
        return any(m in txt for m in markers)


    @classmethod
    def _g4f_providers(cls):
        """Список (класс_провайдера, имя) для перебора.

        g4f НЕ требует API-ключа — это обёртка над публичными провайдерами.
        Имена классов меняются от версии к версии (в 8.5.1 больше нет Blackbox,
        DDG, ChatGptEs, Free2GPT, Liaobots), поэтому:
          1) берём из конфига только реально существующие классы;
          2) если не осталось ничего — сканируем пакет и находим все рабочие
             провайдеры, не требующие авторизации.

        Сканирование идёт по подмодулям напрямую: обращение к некоторым
        атрибутам g4f.Provider дёргает загрузку манифеста с g4f.dev, и при
        недоступности домена падает вся генерация.
        """
        if cls._g4f_provider_cache is not None:
            return cls._g4f_provider_cache

        import g4f.Provider as G4FProviders
        found = []

        for name in G4F_PROVIDERS:
            if name in cls.G4F_PAID_PROVIDERS or name in cls._g4f_paid:
                continue
            try:
                provider = getattr(G4FProviders, name, None)
            except Exception:
                provider = None
            if provider is not None and getattr(provider, 'working', False):
                found.append((provider, name))

        if not found:
            logging.warning(
                "⚠️ g4f: провайдеры из config.ini не найдены в установленной "
                "версии g4f — ищу доступные автоматически"
            )
            try:
                import importlib, pkgutil, inspect
                seen = set()
                for mod_info in pkgutil.iter_modules(G4FProviders.__path__):
                    if mod_info.name.startswith('_'):
                        continue
                    try:
                        mod = importlib.import_module(f"g4f.Provider.{mod_info.name}")
                    except Exception:
                        continue
                    for cname, cls_ in inspect.getmembers(mod, inspect.isclass):
                        if cname.startswith('_') or cname in seen:
                            continue
                        if not cls_.__module__.startswith('g4f.'):
                            continue
                        if not (getattr(cls_, 'working', False) and not getattr(cls_, 'needs_auth', False)):
                            continue
                        # Отсеиваем картиночные/аудио и поисковые провайдеры —
                        # для генерации текста они непригодны
                        low = cname.lower()
                        if any(k in low for k in (
                            'image', 'flux', 'audio', 'sd35', 'stability',
                            'search', 'cached', 'custom', 'ollama'
                        )):
                            continue
                        if cname in ('provider', 'Provider', 'BaseProvider'):
                            continue
                        # платные/требующие регистрации — мимо
                        if cname in cls.G4F_PAID_PROVIDERS or cname in cls._g4f_paid:
                            continue
                        seen.add(cname)
                        found.append((cls_, cname))
            except Exception as e:
                logging.warning(f"⚠️ g4f: автопоиск провайдеров не удался: {e}")

        if found:
            logging.info(f"🤖 g4f: доступно провайдеров — {len(found)}: "
                         f"{', '.join(n for _, n in found[:8])}")
        cls._g4f_provider_cache = found
        return found

    async def _g4f_chat(self, messages: list) -> str:
        """g4f-фолбэк. Ключ не нужен: это доступ к публичным провайдерам.

        В g4f 8.x клиент при первом вызове тянет список провайдеров с g4f.dev.
        Если сети до него нет (или домен лежит), падает вся генерация — поэтому
        работаем через прямой перебор провайдеров и жёсткий таймаут.
        """
        try:
            import g4f
            from g4f.client import Client as G4FClient
        except ImportError:
            logging.warning("⚠️ g4f не установлен (pip install -U g4f)")
            return ""

        try:
            g4f.debug.logging = False
            g4f.check_version = False   # не ходить в сеть за версией
        except Exception:
            pass

        def _sync_call(provider, model):
            kwargs = {"messages": messages, "max_tokens": 160}
            if model:
                kwargs["model"] = model
            client = G4FClient(provider=provider) if provider else G4FClient()
            resp = client.chat.completions.create(**kwargs)
            return resp.choices[0].message.content

        attempts = list(self._g4f_providers())
        if not attempts:
            logging.error("❌ g4f: не найдено ни одного рабочего провайдера")
            return ""

        for provider, label in attempts:
            if label in self._g4f_paid:
                continue          # уже просил денег — не тратим время
            # Если модели в конфиге не заданы — берём default_model провайдера
            models = G4F_MODELS or [getattr(provider, 'default_model', None) or None]
            for model in models:
                try:
                    result = await asyncio.wait_for(
                        asyncio.to_thread(_sync_call, provider, model),
                        timeout=G4F_TIMEOUT
                    )
                    cleaned = self._clean_ai_output(result)
                    if cleaned:
                        logging.info(f"🤖 g4f:{label}/{model or 'default'} → {cleaned[:80]}")
                        return cleaned
                except asyncio.TimeoutError:
                    logging.warning(f"⚠️ g4f {label}/{model or 'default'}: таймаут {G4F_TIMEOUT}s")
                except Exception as e:
                    if self._is_paid_error(e):
                        # Провайдер перешёл на платную модель (402 / credits /
                        # proof-of-work). Бесплатным он уже не станет — исключаем
                        # его до перезапуска, чтобы не долбиться в стену.
                        self._g4f_paid.add(label)
                        logging.warning(
                            f"💰 g4f {label}: требует оплату — исключён из бесплатного пула"
                        )
                        break
                    logging.warning(f"⚠️ g4f {label}/{model or 'default'}: "
                                    f"{type(e).__name__}: {str(e)[:120]}")
        if self._g4f_paid:
            logging.error(
                "❌ g4f: бесплатные провайдеры не ответили "
                f"(платные, исключены: {', '.join(sorted(self._g4f_paid))}). "
                "Для стабильной работы добавьте бесплатный GROQ_API_KEY в config.ini."
            )
        else:
            logging.error("❌ g4f: все провайдеры недоступны")
        return ""

    async def start_neurocomment(self, account_id: int, bot, user_id: int):
        logging.info(f"🟢 start_neurocomment called for account {account_id}")
        if account_id in self.active_comment_tasks:
            logging.warning(f"⚠️ Neurocomment already running for account {account_id}")
            return False, "Нейрокомментинг уже запущен"
        account = db.get_account(account_id)
        if not account:
            logging.error(f"❌ Account {account_id} not found")
            return False, "Аккаунт не найден"
        usable, reason = db.is_account_usable(account_id)
        if not usable:
            logging.warning(f"⛔ Account {account_id} unusable: {reason}")
            return False, reason
        nc = db.get_neurocomment_settings(account_id)
        logging.info(f"📊 Neurocomment settings: {nc}")
        if not nc or not nc.get('enabled'):
            logging.warning(f"⚠️ Neurocomment not enabled for account {account_id}")
            return False, "Нейрокомментинг не включен в настройках"
        mode = nc.get('mode', 'prompt')
        target_channels = nc.get('target_channels', '')
        if mode == 'prompt' and not nc.get('prompt'):
            logging.warning(f"⚠️ Prompt not set for account {account_id}")
            return False, "Промт не задан"
        if mode == 'custom' and not nc.get('custom_comments'):
            logging.warning(f"⚠️ Custom comments not set for account {account_id}")
            return False, "Комментарии не заданы"
        if mode == 'post_prompt' and not nc.get('post_prompt'):
            logging.warning(f"⚠️ Post prompt not set for account {account_id}")
            return False, "Промт для постов не задан"
        if not target_channels:
            logging.warning(f"⚠️ Target channels not set for account {account_id}")
            return False, "Целевые каналы не заданы"
        channels = [c.strip() for c in target_channels.split(',') if c.strip()]
        if not channels:
            logging.warning(f"⚠️ No valid channels for account {account_id}")
            return False, "Целевые каналы не заданы"
        if self._running_tasks >= self._max_concurrent_tasks:
            return False, f"Достигнут глобальный лимит одновременных задач ({self._max_concurrent_tasks}). Попробуйте позже."
        if not await self._acquire_user_quota(user_id):
            return False, f"Превышен лимит одновременных задач ({self.MAX_TASKS_PER_USER}). Дождитесь завершения или отмените другие задачи."
        logging.info(f"✅ Starting neurocomment for account {account_id} on channels: {channels}")
        self.comment_listeners[account_id] = {}
        task_id = db.register_task(user_id, account_id, 'neurocomment', 'starting')
        self.active_comment_task_ids[account_id] = task_id
        task = asyncio.create_task(self._run_limited(self._neurocomment_worker(account_id, bot, user_id, nc, task_id)))
        self.active_comment_tasks[account_id] = task
        return True, f"Нейрокомментинг запущен на {len(channels)} каналах"

    async def stop_neurocomment(self, account_id: int, user_id: int = None):
        # Note: quota is released in _neurocomment_worker's finally block
        task = self.active_comment_tasks.pop(account_id, None)
        task_id = self.active_comment_task_ids.pop(account_id, None)
        if task and not task.done():
            task.cancel()
        self.comment_listeners.pop(account_id, None)
        if task_id:
            db.cancel_task(task_id)

    async def _neurocomment_worker(self, account_id: int, bot, user_id: int, nc: dict, task_id: int = None):
        from pyrogram.raw import types as raw_types
        from pyrogram import utils as pyrogram_utils
        
        # ⭐ ДОБАВЛЯЕМ ФУНКЦИЮ НОРМАЛИЗАЦИИ
        def normalize_chat_id(chat_id):
            """Приводит ID к единому формату (без префиксов)"""
            try:
                if isinstance(chat_id, str):
                    if chat_id.startswith('-100'):
                        return int(chat_id[4:])
                    elif chat_id.startswith('-'):
                        return int(chat_id[1:])
                    else:
                        return int(chat_id)
                else:
                    return int(chat_id)
            except:
                return chat_id
        
        account = db.get_account(account_id)
        if not account:
            logging.error(f"❌ Account {account_id} not found in worker")
            return
        
        acc_name = account.get('account_name') or f"Аккаунт #{account_id}"
        notifications_hidden = account.get('notifications_hidden', 0) == 1
        
        logging.info(f"🧠 Starting neurocomment worker for {acc_name} | user_id={user_id} | notifications_hidden={notifications_hidden}")
        
        client, err = await self.get_or_start_client(account_id)
        if not client:
            logging.error(f"❌ [{acc_name}] Failed to start client: {err}")
            if bot and not notifications_hidden:
                await bot.send_message(user_id, f"❌ [{acc_name}] Не удалось запустить сессию: {err}")
            return
        
        logging.info(f"✅ [{acc_name}] Client started successfully")
        if bot and not notifications_hidden:
            await bot.send_message(user_id, f"🧠 [{acc_name}] Нейрокомментинг запущен! Проверяю каналы...")
        
        try:
            target_channels = [c.strip() for c in nc.get('target_channels', '').split(',') if c.strip()]
            logging.info(f"📋 [{acc_name}] Target channels from settings: {target_channels}")
            
            valid_channels = []
            channel_cache = {}  # ⭐ КЕШ ДЛЯ ОБЪЕКТОВ КАНАЛОВ
            
            discussion_cache = {}  # channel -> discussion_chat_id
            for channel in target_channels:
                try:
                    chat_id = int(channel) if channel.lstrip('-').isdigit() else channel
                    logging.info(f"🔍 [{acc_name}] Checking channel: {channel} (chat_id={chat_id})")
                    # Если аккаунт не в канале — вступаем; также вступаем в чат комментариев
                    ok_access, discussion_id, access_msg = await self.ensure_channel_access(account_id, channel)
                    if not ok_access:
                        logging.warning(f"⚠️ [{acc_name}] {channel}: {access_msg}")
                        if bot and not notifications_hidden:
                            await bot.send_message(user_id, f"⚠️ [{acc_name}] {channel}: {access_msg}")
                        continue
                    chat = await client.get_chat(chat_id)
                    valid_channels.append(channel)
                    channel_cache[channel] = chat  # ⭐ СОХРАНЯЕМ В КЕШ
                    discussion_cache[channel] = discussion_id
                    logging.info(f"✅ [{acc_name}] Channel {channel} ok (id={chat.id}, discussion={discussion_id})")
                    if bot and not notifications_hidden:
                        await bot.send_message(user_id, f"✅ [{acc_name}] Канал {channel} доступен (комментарии: {discussion_id})")
                except Exception as e:
                    logging.warning(f"⚠️ [{acc_name}] Channel {channel} not accessible: {type(e).__name__}: {e}")
                    if bot and not notifications_hidden:
                        await bot.send_message(user_id, f"⚠️ [{acc_name}] Канал {channel} недоступен: {str(e)[:100]}")
            
            logging.info(f"📊 [{acc_name}] Channel validation complete: {len(valid_channels)}/{len(target_channels)} valid")
            
            if not valid_channels:
                logging.warning(f"⚠️ [{acc_name}] No valid channels found, stopping worker")
                if bot and not notifications_hidden:
                    await bot.send_message(user_id, f"❌ [{acc_name}] Нет доступных каналов! Проверьте настройки.")
                return
            
            loop_count = 0
            mode = nc.get('mode', 'prompt')
            prompt = nc.get('prompt', '')
            custom_comments_raw = nc.get('custom_comments', '') or '[]'
            custom_comments = json.loads(custom_comments_raw)
            post_prompt = nc.get('post_prompt', '')
            comment_delay = int(nc.get('comment_delay', 60) or 60)

            # ⭐ ИНИЦИАЛИЗИРУЕМ last_seen ПОСЛЕДНИМИ СООБЩЕНИЯМИ ЧТОБЫ НЕ КОММЕНТИРОВАТЬ СТАРЫЕ ПОСТЫ ПРИ СТАРТЕ
            for channel in valid_channels:
                try:
                    chat_id = int(channel) if channel.lstrip('-').isdigit() else channel
                    async for msg in client.get_chat_history(chat_id, limit=1):
                        if msg:
                            self.comment_listeners.setdefault(account_id, {})[str(channel)] = msg.id
                            logging.info(f"🔧 [{acc_name}] Initialized last_seen for {channel} = {msg.id} (no comment on startup)")
                except Exception as e:
                    logging.warning(f"⚠️ [{acc_name}] Failed to initialize last_seen for {channel}: {e}")
            
            while True:
                loop_count += 1
                logging.info(f"🔄 [{acc_name}] Cycle #{loop_count} start | channels={len(valid_channels)} | mode={mode} | delay={comment_delay}s")
                
                if not db.is_user_subscribed(user_id, ADMIN_ID):
                    logging.warning(f"⚠️ [{acc_name}] Subscription expired for user {user_id}, stopping")
                    await self.stop_neurocomment(account_id)
                    if bot and not notifications_hidden:
                        await bot.send_message(user_id, f"⚠️ [{acc_name}] Подписка истекла! Нейрокомментинг остановлен.")
                    break
                
                nc_chk = db.get_neurocomment_settings(account_id)
                if not nc_chk or not nc_chk.get('enabled'):
                    logging.info(f"🛑 [{acc_name}] Neurocomment disabled in settings, stopping")
                    if bot and not notifications_hidden:
                        await bot.send_message(user_id, f"🛑 [{acc_name}] Нейрокомментинг выключен.")
                    break
                
                mode = nc_chk.get('mode', 'prompt')
                prompt = nc_chk.get('prompt', '')
                custom_comments_raw = nc_chk.get('custom_comments', '') or '[]'
                custom_comments = json.loads(custom_comments_raw)
                post_prompt = nc_chk.get('post_prompt', '')
                comment_delay = int(nc_chk.get('comment_delay', 60) or 60)
                
                logging.info(f"🔄 [{acc_name}] Cycle #{loop_count} - checking {len(valid_channels)} channels | mode={mode}")
                channel_posts_found = 0
                
                for channel in valid_channels:
                    try:
                        chat_id = int(channel) if channel.lstrip('-').isdigit() else channel
                        chat_obj = channel_cache.get(channel)  # ⭐ БЕРЁМ ИЗ КЕША
                        
                        if not chat_obj:
                            try:
                                chat_obj = await client.get_chat(chat_id)
                                channel_cache[channel] = chat_obj
                            except Exception as e:
                                logging.warning(f"⚠️ [{acc_name}] Failed to get chat {channel}: {e}")
                                continue
                        
                        logging.debug(f"📥 [{acc_name}] Fetching last message from {channel}")
                        async for msg in client.get_chat_history(chat_id, limit=1):
                            if not msg:
                                logging.debug(f"📭 [{acc_name}] No messages in {channel}")
                                continue
                            
                            post_text = msg.text or msg.caption or ''
                            logging.debug(f"📩 [{acc_name}] Got message id={msg.id} date={msg.date} text_len={len(post_text)} in {channel}")
                            
                            if mode != 'custom' and not post_text:
                                logging.debug(f"⏭️ [{acc_name}] Skipping empty post in {channel} (mode={mode})")
                                continue
                            
                            post_age = time.time() - msg.date.timestamp()
                            if post_age < comment_delay:
                                logging.debug(f"⏳ [{acc_name}] Post too recent ({post_age:.0f}s < {comment_delay}s) in {channel}")
                                continue
                            
                            last_seen = self.comment_listeners.get(account_id, {}).get(str(channel), 0)
                            logging.debug(f"🔎 [{acc_name}] last_seen={last_seen} msg.id={msg.id} in {channel}")
                            
                            if msg.id <= last_seen:
                                logging.debug(f"✅ [{acc_name}] Already commented on post {msg.id} in {channel}")
                                continue
                            
                            logging.info(f"💬 [{acc_name}] Found new post in {channel}: {post_text[:100]}...")
                            channel_posts_found += 1
                            
                            # ── Проверка дневной квоты AI (только для AI-режимов) ──
                            if mode in ('prompt', 'post_prompt'):
                                ok_quota, used_q, limit_q = db.consume_ai_quota(user_id, amount=1)
                                if not ok_quota:
                                    logging.warning(f"🚫 [{acc_name}] AI-квота исчерпана: {used_q}/{limit_q}")
                                    self.comment_listeners.setdefault(account_id, {})[str(channel)] = msg.id
                                    if bot and not notifications_hidden:
                                        await bot.send_message(
                                            user_id,
                                            f"🚫 [{acc_name}] Дневной лимит AI-комментариев исчерпан "
                                            f"({used_q}/{limit_q}).\n\nПовысьте тариф или докупите AI-пакет "
                                            f"в разделе «💳 Подписка»."
                                        )
                                    continue

                            comment_text = ""
                            if mode == 'prompt':
                                logging.debug(f"🧠 [{acc_name}] Generating prompt-based comment for {channel}")
                                comment_text = await self.generate_ai_comment(prompt, post_text)
                                # Fallback: если AI не сработал, пробуем свои комментарии
                                if not comment_text and custom_comments:
                                    logging.info(f"🔄 [{acc_name}] AI failed, falling back to custom comments")
                                    base_comment = random.choice(custom_comments)
                                    variants = [v.strip() for v in base_comment.split('|') if v.strip()]
                                    comment_text = random.choice(variants) if variants else base_comment
                            elif mode == 'custom' and custom_comments:
                                # Поддержка рандомизации через | (например: "вариант 1|вариант 2|вариант 3")
                                base_comment = random.choice(custom_comments)
                                variants = [v.strip() for v in base_comment.split('|') if v.strip()]
                                comment_text = random.choice(variants) if variants else base_comment
                                logging.debug(f"📝 [{acc_name}] Chosen custom comment ({len(comment_text)} chars)")
                            elif mode == 'post_prompt':
                                logging.debug(f"🧠 [{acc_name}] Generating post-prompt comment for {channel}")
                                comment_text = await self.generate_ai_comment(post_prompt, post_text)
                                # Fallback: если AI не сработал, пробуем свои комментарии
                                if not comment_text and custom_comments:
                                    logging.info(f"🔄 [{acc_name}] AI failed, falling back to custom comments")
                                    base_comment = random.choice(custom_comments)
                                    variants = [v.strip() for v in base_comment.split('|') if v.strip()]
                                    comment_text = random.choice(variants) if variants else base_comment
                            
                            # ⭐ ВСЕГДА ОБНОВЛЯЕМ last_seen, ЧТОБЫ НЕ ЗАЦИКЛИВАТЬСЯ НА ОДНОМ ПОСТЕ
                            self.comment_listeners.setdefault(account_id, {})[str(channel)] = msg.id
                            
                            if not comment_text:
                                logging.warning(f"⚠️ [{acc_name}] Failed to generate comment for {channel} (no fallback)")
                                if bot and not notifications_hidden:
                                    await bot.send_message(user_id, f"⚠️ [{acc_name}] Не удалось сгенерировать комментарий (нет fallback)")
                                continue
                            
                            try:
                                comment_sent = False
                                chat_username = getattr(chat_obj, 'username', None)

                                # ⭐ ЧАТ ОБСУЖДЕНИЙ (берём из кеша, иначе ищем и вступаем)
                                discussion_chat_id = discussion_cache.get(channel)
                                if not discussion_chat_id:
                                    ok_access, discussion_chat_id, access_msg = await self.ensure_channel_access(account_id, channel)
                                    if ok_access and discussion_chat_id:
                                        discussion_cache[channel] = discussion_chat_id
                                    else:
                                        logging.warning(f"⚠️ [{acc_name}] No discussion chat for {channel}: {access_msg}")
                                        if bot and not notifications_hidden:
                                            await bot.send_message(user_id, f"⚠️ [{acc_name}] Нет чата обсуждений в {channel}")
                                        continue

                                # ⭐ КЛЮЧЕВОЙ МОМЕНТ: НОРМАЛИЗУЕМ ID КАНАЛА НА ИСХОДЕ ИЗ chat_obj.id (а не channel string)
                                normalized_channel_id = normalize_chat_id(chat_obj.id)
                                logging.debug(f"🔍 [{acc_name}] chat_obj.id={chat_obj.id}, normalized={normalized_channel_id}, channel={channel}, chat_id={chat_id}")
                                
                                # ⭐ ИЩЕМ ФОРВАРД ИЗ КАНАЛА
                                try:
                                    # Ищем форвард в обсуждениях - увеличиваем лимит до 200
                                    fwd_count = 0
                                    async for fwd in client.get_chat_history(discussion_chat_id, limit=200):
                                        fwd_count += 1
                                        is_fwd = getattr(fwd, 'forward_date', None)
                                        fwd_chat = getattr(fwd, 'forward_from_chat', None)
                                        fwd_msg_id = getattr(fwd, 'forward_from_message_id', None)
                                        
                                        if is_fwd:
                                            # Метод 1: сравнение по chat_id из forward_from_chat
                                            if fwd_chat:
                                                fwd_chat_id_val = getattr(fwd_chat, 'id', None)
                                                fwd_chat_username = getattr(fwd_chat, 'username', None)
                                                logging.debug(f"🔍 [{acc_name}] Fwd msg_id={fwd.id} from_chat_id={fwd_chat_id_val} username={fwd_chat_username} fwd_from_msg_id={fwd_msg_id}")
                                                
                                                if fwd_chat_id_val is not None:
                                                    normalized_fwd_id = normalize_chat_id(fwd_chat_id_val)
                                                    if normalized_fwd_id == normalized_channel_id:
                                                        logging.info(f"🔍 [{acc_name}] Found matching forward (by id): fwd.id={fwd.id}, channel_msg_id={msg.id}")
                                                        await self.tg_call(
                                                            lambda: client.send_message(
                                                                discussion_chat_id, comment_text,
                                                                reply_to_message_id=fwd.id),
                                                            account_id=account_id, bot=bot, user_id=user_id,
                                                            description=f'comment -> {channel}',
                                                            notify=not notifications_hidden)
                                                        comment_sent = True
                                                        logging.info(f"✅ [{acc_name}] Comment sent to discussion chat {discussion_chat_id} (reply to fwd msg_id={fwd.id})")
                                                        break
                                                elif chat_username and fwd_chat_username and fwd_chat.username:
                                                    if fwd_chat.username.lower() == chat_username.lower():
                                                        logging.info(f"🔍 [{acc_name}] Found matching forward (by username): fwd.id={fwd.id}")
                                                        await self.tg_call(
                                                            lambda: client.send_message(
                                                                discussion_chat_id, comment_text,
                                                                reply_to_message_id=fwd.id),
                                                            account_id=account_id, bot=bot, user_id=user_id,
                                                            description=f'comment -> {channel}',
                                                            notify=not notifications_hidden)
                                                        comment_sent = True
                                                        logging.info(f"✅ [{acc_name}] Comment sent to discussion chat {discussion_chat_id} (reply to fwd by username)")
                                                        break
                                            
                                            # Метод 2: сравнение по forward_from_message_id (совпадение с msg.id канала)
                                            if not comment_sent and fwd_msg_id and hasattr(msg, 'id') and fwd_msg_id == msg.id:
                                                logging.info(f"🔍 [{acc_name}] Found matching forward (by msg_id={msg.id}): fwd.id={fwd.id}")
                                                await self.tg_call(
                                                            lambda: client.send_message(
                                                                discussion_chat_id, comment_text,
                                                                reply_to_message_id=fwd.id),
                                                            account_id=account_id, bot=bot, user_id=user_id,
                                                            description=f'comment -> {channel}',
                                                            notify=not notifications_hidden)
                                                comment_sent = True
                                                logging.info(f"✅ [{acc_name}] Comment sent to discussion chat {discussion_chat_id} (reply to fwd by msg_id)")
                                                break
                                    
                                    logging.debug(f"🔍 [{acc_name}] Scanned {fwd_count} messages in discussion chat {discussion_chat_id}")
                                except Exception as disc_err:
                                    logging.warning(f"⚠️ [{acc_name}] Discussion chat error: {disc_err}")

                                if not comment_sent:
                                    logging.warning(f"⚠️ [{acc_name}] Forward from channel not found in discussion chat {discussion_chat_id} - SKIPPING (comment must be reply to forward)")
                                
                                if comment_sent:
                                    self.comment_listeners.setdefault(account_id, {})[str(channel)] = msg.id
                                    if bot and not notifications_hidden:
                                        await bot.send_message(user_id, f"✅ [{acc_name}] Прокомментирован пост в {channel}")
                                
                            except Exception as send_err:
                                logging.error(f"❌ [{acc_name}] Failed to send comment to {channel}: {type(send_err).__name__}: {send_err}")
                                if bot and not notifications_hidden:
                                    await bot.send_message(user_id, f"⚠️ [{acc_name}] Ошибка отправки в {channel}: {str(send_err)[:100]}")
                    
                    except Exception as e:
                        logging.error(f"❌ [{acc_name}] Error processing channel {channel}: {type(e).__name__}: {e}")
                        if bot and not notifications_hidden:
                            await bot.send_message(user_id, f"⚠️ [{acc_name}] Ошибка проверки канала {channel}: {str(e)[:100]}")
                
                logging.info(f"🔄 [{acc_name}] Cycle #{loop_count} end | posts_found={channel_posts_found} | sleeping {comment_delay}s")
                await asyncio.sleep(comment_delay)
        
        except asyncio.CancelledError:
            logging.info(f"🛑 [{acc_name}] Neurocomment task cancelled")
        except AccountBlockedError as e:
            logging.error(f"🚫 [{acc_name}] Нейрокомментинг остановлен: {e}")
        except Exception as e:
            logging.error(f"❌ [{acc_name}] Critical error in neurocomment worker: {e}")
            if bot and not notifications_hidden:
                try:
                    await bot.send_message(user_id, f"❌ [{acc_name}] Критическая ошибка: {str(e)[:200]}")
                except:
                    pass
        finally:
            logging.info(f"🧠 [{acc_name}] Neurocomment worker stopped")
            db.update_neurocomment_settings(account_id, enabled=0)
            self.active_comment_tasks.pop(account_id, None)
            self.comment_listeners.pop(account_id, None)
            if task_id:
                db.finish_task(task_id, status='finished')
            self.active_comment_task_ids.pop(account_id, None)
            await self._release_user_quota(user_id)

    # ==================== NEUROCOMMENT: CHANNEL DISCOVERY & ACCESS ====================
    async def get_channel_discussion_id(self, client, chat_obj, chat_ref=None):
        """Возвращает id чата обсуждений (комментариев) канала или None."""
        try:
            linked = getattr(chat_obj, 'linked_chat', None)
            if linked is not None and getattr(linked, 'id', None):
                return linked.id
            for attr in ('linked_chat_id', 'discussion_chat_id'):
                val = getattr(chat_obj, attr, None)
                if val:
                    return val
        except Exception:
            pass
        try:
            from pyrogram.raw import functions as raw_functions
            peer = await client.resolve_peer(chat_ref if chat_ref is not None else chat_obj.id)
            full = await client.invoke(raw_functions.channels.GetFullChannel(channel=peer))
            linked_id = getattr(getattr(full, 'full_chat', None), 'linked_chat_id', None)
            if linked_id:
                from pyrogram import utils as pyro_utils
                return pyro_utils.get_channel_id(linked_id)
        except Exception as e:
            logging.debug(f"GetFullChannel failed for discussion lookup: {e}")
        return None

    async def ensure_channel_access(self, account_id: int, channel: str) -> Tuple[bool, Optional[int], str]:
        """Гарантирует доступ аккаунта к каналу и его чату комментариев.

        Если аккаунт не состоит в канале — пробует вступить. Затем находит связанный
        чат обсуждений и вступает в него (без этого комментировать нельзя).

        Возвращает (успех, discussion_chat_id, сообщение).
        """
        client, err = await self.get_or_start_client(account_id)
        if not client:
            return False, None, f"Ошибка подключения: {err}"

        ref = channel.strip()
        if ref.startswith('https://t.me/') or ref.startswith('t.me/'):
            ref = ref.split('t.me/')[-1].strip('/')
            if not ref.startswith('+') and not ref.startswith('joinchat'):
                ref = '@' + ref.lstrip('@')
        chat_ref = int(ref) if ref.lstrip('-').isdigit() else ref

        chat_obj = None
        try:
            chat_obj = await client.get_chat(chat_ref)
        except Exception as e:
            # Не состоим в канале / не резолвится — пробуем вступить
            logging.info(f"🔐 [acc {account_id}] No access to {channel} ({type(e).__name__}), trying to join")
            try:
                chat_obj = await self.tg_call(
                    lambda: client.join_chat(chat_ref),
                    account_id=account_id, description=f"join {channel}",
                    notify=False, max_retries=2
                )
                if chat_obj is None:
                    return False, None, f"Канал {channel} недоступен для вступления"
            except AccountBlockedError as join_err:
                return False, None, str(join_err)
            except Exception as join_err:
                return False, None, f"Не удалось вступить в {channel}: {str(join_err)[:120]}"

        # Если состоим только как «превью» — join всё равно безопасен (уже участник → исключение игнорируем)
        try:
            if not getattr(chat_obj, 'is_member', True):
                await client.join_chat(chat_ref)
                chat_obj = await client.get_chat(chat_ref)
        except Exception:
            pass

        discussion_id = await self.get_channel_discussion_id(client, chat_obj, chat_ref)
        if not discussion_id:
            return False, None, f"У канала {channel} нет открытых комментариев"

        try:
            await self.tg_call(
                lambda: client.join_chat(discussion_id),
                account_id=account_id, description=f"join discussion {discussion_id}",
                notify=False, max_retries=2
            )
            logging.info(f"✅ [acc {account_id}] Joined discussion chat {discussion_id} of {channel}")
        except Exception as e:
            # USER_ALREADY_PARTICIPANT и подобное — не ошибка
            logging.debug(f"ℹ️ [acc {account_id}] join discussion {discussion_id}: {e}")

        return True, discussion_id, "OK"

    async def list_commentable_channels(self, account_id: int, refresh: bool = False) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """Каналы аккаунта, у которых открыты комментарии.

        Раньше на каждый канал делался get_chat — при сотне каналов это сотня
        запросов, Telegram отвечал FloodWait, и поиск растягивался на минуты.
        Теперь каналы запрашиваются пачками по 100 через raw channels.GetChannels
        (1 запрос вместо 100), а признак обсуждений берётся из флага has_link.
        """
        client, err = await self.get_or_start_client(account_id)
        if not client:
            return [], f"Ошибка подключения: {err}"

        if refresh or not db.get_account_chats(account_id, chat_types=('channel',)):
            await self.fetch_and_sync_chats(account_id)

        channels = db.get_account_chats(account_id, chat_types=('channel',))
        if not channels:
            return [], None

        from pyrogram.raw import functions as raw_functions
        from pyrogram.raw import types as raw_types

        # 1. Собираем InputChannel из сохранённых access_hash — без сетевых вызовов
        wanted = {}
        need_resolve = []
        for ch in channels:
            cid = ch['chat_id']
            if not cid.lstrip('-').isdigit():
                continue
            raw_id = utils.get_channel_id(int(cid)) if int(cid) < 0 else int(cid)
            ah = (ch.get('access_hash') or '').strip()
            wanted[cid] = ch
            if ah:
                try:
                    need_resolve.append((cid, raw_types.InputChannel(
                        channel_id=abs(int(raw_id)), access_hash=int(ah))))
                    continue
                except (ValueError, TypeError):
                    pass
            need_resolve.append((cid, None))

        result = []
        CHUNK = 100

        async def _fetch_chunk(pairs):
            """Один GetChannels на пачку каналов."""
            inputs, ids = [], []
            for cid, inp in pairs:
                if inp is None:
                    # access_hash нет — пробуем через resolve_peer (из локального кэша)
                    try:
                        inp = await client.resolve_peer(int(cid))
                    except Exception as e:
                        logging.debug(f"resolve_peer {cid}: {type(e).__name__}: {e}")
                        continue
                inputs.append(inp)
                ids.append(cid)
            if not inputs:
                return []
            try:
                res = await self.tg_call(
                    lambda: client.invoke(raw_functions.channels.GetChannels(id=inputs)),
                    account_id=account_id,
                    description=f"GetChannels x{len(inputs)}",
                    notify=False, max_retries=2
                )
            except AccountBlockedError:
                raise
            except Exception as e:
                logging.warning(f"GetChannels chunk failed: {type(e).__name__}: {e}")
                return []
            return list(getattr(res, 'chats', []) or []) if res else []

        try:
            for i in range(0, len(need_resolve), CHUNK):
                chunk = need_resolve[i:i + CHUNK]
                for ch_obj in await _fetch_chunk(chunk):
                    if not getattr(ch_obj, 'broadcast', False):
                        continue          # супергруппы тут не нужны
                    # has_link = к каналу привязан чат обсуждений
                    if not getattr(ch_obj, 'has_link', False):
                        continue
                    cid = str(utils.get_channel_id(ch_obj.id))
                    meta = wanted.get(cid) or {}
                    result.append({
                        'chat_id': cid,
                        'title': getattr(ch_obj, 'title', None) or meta.get('chat_title') or cid,
                        'username': getattr(ch_obj, 'username', None) or meta.get('chat_username') or '',
                        # реальный id обсуждения выясняем лениво, при вступлении
                        'discussion_id': None,
                    })
                await asyncio.sleep(0.3)   # мягкая пауза между пачками
        except AccountBlockedError as e:
            return [], str(e)

        result.sort(key=lambda c: (c['title'] or '').lower())
        logging.info(f"[acc {account_id}] каналов с комментариями: {len(result)} из {len(channels)}")
        return result, None

    # ==================== CHAT LIST & SYNC ====================
    async def fetch_and_sync_chats(self, account_id: int) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        client, err = await self.get_or_start_client(account_id)
        if not client:
            return [], err

        from pyrogram.raw.functions.messages import GetDialogs
        from pyrogram.raw.types import InputPeerEmpty, InputPeerChannel, InputPeerChat, InputPeerUser
        from pyrogram.raw.types import Channel, Chat, ChannelForbidden, ChatForbidden, ChatEmpty
        from pyrogram import utils

        chats_map = {}

        try:
            # 1. MTProto raw GetDialogs with pagination (completely bypasses CHANNEL_PRIVATE errors in channels.GetMessages)
            offset_date = 0
            offset_id = 0
            offset_peer = InputPeerEmpty()
            limit = 100

            for _ in range(25):  # Up to 2500 dialogs
                try:
                    res = await client.invoke(
                        GetDialogs(
                            offset_date=offset_date,
                            offset_id=offset_id,
                            offset_peer=offset_peer,
                            limit=limit,
                            hash=0
                        )
                    )
                except Exception as chunk_err:
                    print(f"⚠️ Chunk GetDialogs #{account_id}: {chunk_err}")
                    break

                if not hasattr(res, 'chats') or not res.chats:
                    break

                for ch in res.chats:
                    if isinstance(ch, (ChannelForbidden, ChatForbidden, ChatEmpty)):
                        continue
                    if getattr(ch, 'left', False) or getattr(ch, 'deactivated', False) or getattr(ch, 'kicked', False):
                        continue

                    if isinstance(ch, Channel):
                        full_id = str(utils.get_channel_id(ch.id))
                        title = ch.title or (f"@{ch.username}" if getattr(ch, 'username', None) else f"Канал/Чат {ch.id}")
                        username = getattr(ch, 'username', None) or ""
                        # megagroup / gigagroup = супергруппа (чат), иначе broadcast-канал
                        is_group = bool(getattr(ch, 'megagroup', False) or getattr(ch, 'gigagroup', False))
                        chats_map[full_id] = {
                            'id': full_id,
                            'title': title,
                            'username': username,
                            'chat_type': 'group' if is_group else 'channel',
                            # access_hash — чтобы потом не дёргать get_chat на каждый канал
                            'access_hash': getattr(ch, 'access_hash', '') or '',
                            # has_link = у канала есть привязанный чат обсуждений
                            'has_link': bool(getattr(ch, 'has_link', False)),
                        }
                    elif isinstance(ch, Chat):
                        full_id = str(-ch.id)
                        title = ch.title or f"Группа {ch.id}"
                        chats_map[full_id] = {
                            'id': full_id,
                            'title': title,
                            'username': "",
                            'chat_type': 'group'
                        }

                # Detect private chats from dialogs
                if hasattr(res, 'dialogs') and hasattr(res, 'users'):
                    for dialog in res.dialogs:
                        peer = dialog.peer
                        if hasattr(peer, 'user_id'):
                            user_id = peer.user_id
                            user_obj = next((u for u in res.users if getattr(u, 'id', None) == user_id), None)
                            if user_obj:
                                full_id = str(user_id)
                                title = f"{user_obj.first_name or ''} {user_obj.last_name or ''}".strip() or f"User {user_id}"
                                username = getattr(user_obj, 'username', None) or ""
                                chats_map[full_id] = {
                                    'id': full_id,
                                    'title': title,
                                    'username': username,
                                    'chat_type': 'bot' if getattr(user_obj, 'bot', False) else 'private'
                                }

                if not hasattr(res, 'dialogs') or not res.dialogs or len(res.dialogs) < limit:
                    break

                last_dialog = res.dialogs[-1]
                last_msg_id = last_dialog.top_message
                last_msg_date = 0
                if hasattr(res, 'messages'):
                    for m in res.messages:
                        if getattr(m, 'id', None) == last_msg_id:
                            last_msg_date = getattr(m, 'date', 0)
                            break

                peer = last_dialog.peer
                if hasattr(peer, 'channel_id'):
                    ch_obj = next((c for c in res.chats if getattr(c, 'id', None) == peer.channel_id), None)
                    access_hash = getattr(ch_obj, 'access_hash', 0) if ch_obj else 0
                    offset_peer = InputPeerChannel(channel_id=peer.channel_id, access_hash=access_hash)
                elif hasattr(peer, 'chat_id'):
                    offset_peer = InputPeerChat(chat_id=peer.chat_id)
                elif hasattr(peer, 'user_id'):
                    u_obj = next((u for u in getattr(res, 'users', []) if getattr(u, 'id', None) == peer.user_id), None)
                    access_hash = getattr(u_obj, 'access_hash', 0) if u_obj else 0
                    offset_peer = InputPeerUser(user_id=peer.user_id, access_hash=access_hash)
                else:
                    offset_peer = InputPeerEmpty()

                offset_date = last_msg_date
                offset_id = last_msg_id

            # 2. Also check folder_id = 1 (Archived / Folders)
            try:
                res_arch = await client.invoke(
                    GetDialogs(
                        offset_date=0,
                        offset_id=0,
                        offset_peer=InputPeerEmpty(),
                        limit=limit,
                        hash=0,
                        folder_id=1
                    )
                )
                if hasattr(res_arch, 'chats'):
                    for ch in res_arch.chats:
                        if isinstance(ch, (ChannelForbidden, ChatForbidden, ChatEmpty)):
                            continue
                        if getattr(ch, 'left', False) or getattr(ch, 'deactivated', False):
                            continue
                        if isinstance(ch, Channel):
                            full_id = str(utils.get_channel_id(ch.id))
                            title = ch.title or (f"@{ch.username}" if getattr(ch, 'username', None) else f"Канал/Чат {ch.id}")
                            username = getattr(ch, 'username', None) or ""
                            is_group = bool(getattr(ch, 'megagroup', False) or getattr(ch, 'gigagroup', False))
                            chats_map[full_id] = {'id': full_id, 'title': title, 'username': username,
                                                  'chat_type': 'group' if is_group else 'channel',
                                                  'access_hash': getattr(ch, 'access_hash', '') or ''}
                        elif isinstance(ch, Chat):
                            full_id = str(-ch.id)
                            title = ch.title or f"Группа {ch.id}"
                            chats_map[full_id] = {'id': full_id, 'title': title, 'username': "", 'chat_type': 'group'}
                
                if hasattr(res_arch, 'dialogs') and hasattr(res_arch, 'users'):
                    for dialog in res_arch.dialogs:
                        peer = dialog.peer
                        if hasattr(peer, 'user_id'):
                            user_id = peer.user_id
                            user_obj = next((u for u in res_arch.users if getattr(u, 'id', None) == user_id), None)
                            if user_obj:
                                full_id = str(user_id)
                                title = f"{user_obj.first_name or ''} {user_obj.last_name or ''}".strip() or f"User {user_id}"
                                username = getattr(user_obj, 'username', None) or ""
                                chats_map[full_id] = {'id': full_id, 'title': title, 'username': username, 'chat_type': 'bot' if getattr(user_obj, 'bot', False) else 'private'}
            except Exception:
                pass

            chat_list = list(chats_map.values())
            print(f"📋 Аккаунт #{account_id}: успешно получено {len(chat_list)} диалогов")
            db.sync_account_chats(account_id, chat_list)
            chats = db.get_account_chats(account_id)
            return chats, None

        except Exception as e:
            print(f"❌ Ошибка fetch_and_sync_chats #{account_id}: {e}")
            # If raw fails, fallback to standard get_dialogs with exception catching
            try:
                chat_list = []
                async for dialog in client.get_dialogs():
                    try:
                        chat = dialog.chat
                        chat_type = 'unknown'
                        if chat.type == enums.ChatType.PRIVATE:
                            chat_type = 'private'
                        elif chat.type == enums.ChatType.BOT:
                            chat_type = 'bot'
                        elif chat.type in [enums.ChatType.SUPERGROUP, enums.ChatType.GROUP]:
                            chat_type = 'group'
                        elif chat.type == enums.ChatType.CHANNEL:
                            chat_type = 'channel'
                        chat_list.append({
                            'id': str(chat.id),
                            'title': chat.title or str(chat.id),
                            'username': chat.username or "",
                            'chat_type': chat_type
                        })
                    except Exception:
                        continue
                db.sync_account_chats(account_id, chat_list)
                chats = db.get_account_chats(account_id)
                return chats, None
            except Exception as fb_err:
                return [], str(fb_err)



    # ==================== JOIN CHATS (Batch & Chatlists/Folders) ====================
    async def join_chatlist_invite(self, client: Client, link_or_slug: str) -> Tuple[bool, int, str]:
        """Joins all chats in a Telegram Chatlist / Shared Folder link (e.g. t.me/addlist/slug)."""
        slug = link_or_slug.strip()
        if "addlist/" in slug:
            slug = slug.split("addlist/")[-1]
        if "tg://addlist?slug=" in slug:
            slug = slug.split("slug=")[-1]
        if "?" in slug:
            slug = slug.split("?")[0]
        if "&" in slug:
            slug = slug.split("&")[0]
        slug = slug.strip("/").strip()

        from pyrogram.raw.functions.chatlists import CheckChatlistInvite, JoinChatlistInvite
        from pyrogram.raw.types import InputPeerChannel, InputPeerChat, InputPeerUser
        from pyrogram.raw.types.chatlists import ChatlistInvite, ChatlistInviteAlready

        try:
            check_res = await client.invoke(CheckChatlistInvite(slug=slug))

            if isinstance(check_res, ChatlistInviteAlready):
                if check_res.missing_peers:
                    input_peers = []
                    chats_map = {c.id: c for c in check_res.chats}
                    for p in check_res.missing_peers:
                        ch_id = getattr(p, 'channel_id', getattr(p, 'chat_id', getattr(p, 'user_id', None)))
                        if ch_id and ch_id in chats_map:
                            ch = chats_map[ch_id]
                            if hasattr(ch, 'access_hash'):
                                input_peers.append(InputPeerChannel(channel_id=ch.id, access_hash=ch.access_hash))
                            else:
                                input_peers.append(InputPeerChat(chat_id=ch.id))
                    if input_peers:
                        await client.invoke(JoinChatlistInvite(slug=slug, peers=input_peers))
                        return True, len(input_peers), f"Успешно вступил в {len(input_peers)} новых чатов из папки"
                return True, 0, "Аккаунт уже состоит во всех чатах этой папки"

            elif isinstance(check_res, ChatlistInvite):
                input_peers = []
                chats_map = {c.id: c for c in check_res.chats}
                for p in check_res.peers:
                    ch_id = getattr(p, 'channel_id', getattr(p, 'chat_id', getattr(p, 'user_id', None)))
                    if ch_id and ch_id in chats_map:
                        ch = chats_map[ch_id]
                        if hasattr(ch, 'access_hash'):
                            input_peers.append(InputPeerChannel(channel_id=ch.id, access_hash=ch.access_hash))
                        else:
                            input_peers.append(InputPeerChat(chat_id=ch.id))

                if not input_peers and check_res.chats:
                    for ch in check_res.chats:
                        if hasattr(ch, 'access_hash'):
                            input_peers.append(InputPeerChannel(channel_id=ch.id, access_hash=ch.access_hash))
                        else:
                            input_peers.append(InputPeerChat(chat_id=ch.id))

                if not input_peers:
                    return False, 0, "Не найдены доступные чаты для вступления в папке"

                await client.invoke(JoinChatlistInvite(slug=slug, peers=input_peers))
                folder_title = getattr(check_res, 'title', 'Папка чатов')
                return True, len(input_peers), f"Успешно вступил в {len(input_peers)} чатов из папки '{folder_title}'"
            else:
                return False, 0, "Неизвестный формат папки чатов"
        except Exception as e:
            return False, 0, str(e)

    async def join_chats_batch(self, account_id: int, chat_links: List[str], bot, user_id: int):
        client, err = await self.get_or_start_client(account_id)
        if not client:
            if bot:
                await bot.send_message(user_id, f"❌ Ошибка подключения аккаунта #{account_id}: {err}")
            return

        total = len(chat_links)
        joined = 0
        failed = 0
        account = db.get_account(account_id)
        acc_name = account.get('account_name') or f"ID {account_id}"

        if bot:
            await bot.send_message(user_id, f"🚀 [{acc_name}] Начинаю обработку {total} ссылок/папок чатов...")

        for idx, link_raw in enumerate(chat_links, 1):
            link = link_raw.strip()
            if not link:
                continue

            try:
                if "addlist" in link:
                    # Telegram Chatlist / Shared Folder invite
                    ok, count, msg = await self.join_chatlist_invite(client, link)
                    if ok:
                        joined += max(1, count)
                        if bot:
                            await bot.send_message(user_id, f"✅ [{acc_name}] {msg}")
                    else:
                        failed += 1
                        if bot:
                            await bot.send_message(user_id, f"❌ [{acc_name}] Ошибка папки ({link}): {msg}")
                else:
                    clean_link = link.replace("https://t.me/", "").replace("https://t.me/+", "+").strip()
                    if clean_link.startswith('+'):
                        # Private chat invite link - try multiple methods
                        try:
                            await client.join_chat(clean_link)
                        except Exception:
                            try:
                                await client.join_chat_by_invite_link(clean_link)
                            except Exception:
                                await client.join_chat(link)
                    else:
                        await client.join_chat(clean_link)
                    joined += 1
                    if bot:
                        await bot.send_message(user_id, f"✅ [{acc_name}] Успешно вступил: {clean_link}")
            except Exception as e:
                failed += 1
                if bot:
                    await bot.send_message(user_id, f"❌ [{acc_name}] Не удалось вступить ({link}): {str(e)[:100]}")

            await asyncio.sleep(random.randint(5, 10))

            if idx % 5 == 0 and idx < total:
                if bot:
                    await bot.send_message(user_id, f"⏳ [{acc_name}] Пауза 2 минуты между пачками...")
                await asyncio.sleep(120)

        # Sync chats after join
        try:
            await self.fetch_and_sync_chats(account_id)
        except:
            pass

        if bot:
            await bot.send_message(user_id, f"🏁 [{acc_name}] Вступление завершено!\n✅ Вступил: {joined}\n❌ Ошибок: {failed}")


    # ==================== MASS LEAVE CHATS ====================
    async def leave_chats_batch(self, account_id: int, chat_ids: List[str], bot, user_id: int):
        client, err = await self.get_or_start_client(account_id)
        if not client:
            if bot:
                await bot.send_message(user_id, f"❌ Ошибка подключения аккаунта #{account_id}: {err}")
            return

        total = len(chat_ids)
        left = 0
        failed = 0
        account = db.get_account(account_id)
        acc_name = account.get('account_name') or f"ID {account_id}"

        if bot:
            await bot.send_message(user_id, f"🚪 [{acc_name}] Начинаю выход из {total} выбранных чатов...")

        for idx, cid in enumerate(chat_ids, 1):
            try:
                chat_target = int(cid) if cid.startswith("-") or cid.isdigit() else cid
                await client.leave_chat(chat_target)
                db.remove_account_chat(account_id, cid)
                left += 1
            except Exception as e:
                failed += 1
                print(f"⚠️ Ошибка выхода из {cid}: {e}")

            if idx % 10 == 0 and bot:
                await bot.send_message(user_id, f"⏳ [{acc_name}] Вышел из {left}/{total} чатов...")

            await asyncio.sleep(random.randint(2, 5))

        if bot:
            await bot.send_message(user_id, f"✅ [{acc_name}] Массовый выход завершён!\n🚪 Покинуто чатов: {left}\n❌ Ошибок: {failed}")

    # ==================== PER-ACCOUNT SPAM ENGINE ====================
    def is_account_spamming(self, account_id: int) -> bool:
        task = self.active_spam_tasks.get(account_id)
        return task is not None and not task.done()

    async def start_account_spam(self, account_id: int, bot, user_id: int):
        if self.is_account_spamming(account_id):
            return True, "Рассылка уже запущена"
        usable, reason = db.is_account_usable(account_id)
        if not usable:
            return False, reason
        if not await self._acquire_user_quota(user_id):
            return False, f"Превышен лимит одновременных задач ({self.MAX_TASKS_PER_USER}). Дождитесь завершения или отмените другие задачи."
        if self._running_tasks >= self._max_concurrent_tasks:
            await self._release_user_quota(user_id)
            return False, f"Достигнут глобальный лимит одновременных задач ({self._max_concurrent_tasks}). Попробуйте позже."
        db.set_account_spam_status(account_id, 1)
        task_id = db.register_task(user_id, account_id, 'spam', 'starting')
        self.active_spam_task_ids[account_id] = task_id
        task = asyncio.create_task(self._run_limited(self._spam_worker(account_id, bot, user_id, task_id)))
        self.active_spam_tasks[account_id] = task
        return True, "Рассылка успешно запущена"

    async def stop_account_spam(self, account_id: int, user_id: int = None):
        # Note: quota is released in _spam_worker's finally block
        db.set_account_spam_status(account_id, 0)
        task = self.active_spam_tasks.pop(account_id, None)
        task_id = self.active_spam_task_ids.pop(account_id, None)
        if task and not task.done():
            task.cancel()
        if task_id:
            db.cancel_task(task_id)
        return True

    async def _spam_worker(self, account_id: int, bot, user_id: int, task_id: int = None):
        account = db.get_account(account_id)
        if not account:
            return

        acc_name = account.get('account_name') or f"Аккаунт #{account_id}"
        notifications_hidden = account.get('notifications_hidden', 0) == 1
        client, err = await self.get_or_start_client(account_id)
        if not client:
            db.set_account_spam_status(account_id, 0)
            if bot:
                await bot.send_message(user_id, f"❌ [{acc_name}] Не удалось запустить сессию: {err}")
            return

        cycle_count = 0
        report_id = db.create_account_report(account_id, user_id, account.get('post_text', ''), account.get('post_photo', ''))
        chats_added = set()
        
        if bot and not notifications_hidden:
            await bot.send_message(user_id, f"🚀 [{acc_name}] Рассылка запущена!")

        try:
            while True:
                # Re-check subscription & status
                if not db.is_user_subscribed(user_id, ADMIN_ID):
                    db.set_account_spam_status(account_id, 0)
                    if bot and not notifications_hidden:
                        await bot.send_message(user_id, f"⚠️ [{acc_name}] Подписка истекла! Рассылка остановлена.")
                    break

                acc_data = db.get_account(account_id)
                if not acc_data or acc_data.get('spam_status') != 1:
                    break

                post_text = acc_data.get('post_text', '')
                post_photo = acc_data.get('post_photo', '')
                post_entities_json = acc_data.get('post_entities')
                post_parse_mode = acc_data.get('post_parse_mode', 'HTML')
                timeout_minutes = max(1, acc_data.get('timeout', 5))

                if not post_text:
                    db.set_account_spam_status(account_id, 0)
                    if bot and not notifications_hidden:
                        await bot.send_message(user_id, f"❌ [{acc_name}] Текст поста не установлен! Настройте пост в меню.")
                    break

                # Get only enabled chats
                # Постинг по чатам = только группы/супергруппы (каналы, боты и ЛС исключены)
                spam_chats = db.get_account_chats(account_id, spam_only=True, chat_types=db.GROUP_CHAT_TYPES)
                if not spam_chats:
                    # Try syncing if empty
                    await self.fetch_and_sync_chats(account_id)
                    spam_chats = db.get_account_chats(account_id, spam_only=True, chat_types=db.GROUP_CHAT_TYPES)

                if not spam_chats:
                    db.set_account_spam_status(account_id, 0)
                    if bot and not notifications_hidden:
                        await bot.send_message(user_id, f"❌ [{acc_name}] Нет выбранных чатов для рассылки!")
                    break

                cycle_count += 1
                if bot and not notifications_hidden:
                    await bot.send_message(user_id, f"🔄 [{acc_name}] Цикл #{cycle_count} (Чатов: {len(spam_chats)})")

                for idx, chat in enumerate(spam_chats, 1):
                    # Check if stopped mid-cycle
                    acc_chk = db.get_account(account_id)
                    if not acc_chk or acc_chk.get('spam_status') != 1:
                        return

                    chat_id_val = int(chat['chat_id']) if (chat['chat_id'].startswith("-") or chat['chat_id'].isdigit()) else chat['chat_id']
                    chat_title = chat.get('chat_title') or str(chat_id_val)
                    addit = chat.get('additional_text') or ''
                    
                    full_text = f"{post_text}{addit}"

                    # Stealth mention
                    mention_msg = None
                    try:
                        me = await client.get_me()

                        async def _scan_history():
                            async for hist in client.get_chat_history(chat_id_val, limit=15):
                                if hist.from_user and hist.from_user.id != me.id:
                                    return hist
                            return None

                        mention_msg = await self.tg_call(
                            _scan_history,
                            account_id=account_id, bot=bot, user_id=user_id,
                            description=f"get_chat_history {chat_title}",
                            notify=False, max_retries=2
                        )
                    except AccountBlockedError:
                        raise
                    except Exception:
                        pass

                    entities = []
                    if post_entities_json:
                        converted = await convert_entities_to_pyrogram(post_entities_json, client)
                        if converted:
                            entities = converted
                    
                    # Spin text
                    try:
                        import re
                        import random
                        def spin(m):
                            return random.choice(m.group(1).split('|'))
                        post_text_before = post_text
                        post_text = re.sub(r'\{([^}]+)\}', spin, post_text)
                        spin_diff = len(post_text) - len(post_text_before)
                        if spin_diff and entities:
                            for ent in entities:
                                ent.offset = max(0, ent.offset + spin_diff)
                        full_text = f"{post_text}{addit}"
                    except Exception as e:
                        print(f"⚠️ Ошибка рандомизации текста: {e}")

                    if mention_msg:
                        try:
                            hidden_mention = MessageEntity(
                                type=enums.MessageEntityType.TEXT_MENTION,
                                offset=0,
                                length=1,
                                user=mention_msg.from_user
                            )
                            full_text = "\u200b" + full_text
                            for ent in entities:
                                ent.offset += 1
                            entities.insert(0, hidden_mention)
                        except Exception as m_err:
                            pass

                    # Send post - только entities, без parse_mode
                    try:
                        if post_photo and os.path.exists(post_photo):
                            _sent = await self.tg_call(
                                lambda: client.send_photo(
                                    chat_id_val,
                                    post_photo,
                                    caption=full_text,
                                    caption_entities=entities if entities else None
                                ),
                                account_id=account_id, bot=bot, user_id=user_id,
                                description=f"send_photo -> {chat_title}",
                                notify=not notifications_hidden
                            )
                        else:
                            _sent = await self.tg_call(
                                lambda: client.send_message(
                                    chat_id_val,
                                    full_text,
                                    entities=entities if entities else None
                                ),
                                account_id=account_id, bot=bot, user_id=user_id,
                                description=f"send_message -> {chat_title}",
                                notify=not notifications_hidden
                            )
                        if _sent is None:
                            # Чат недоступен для записи — фиксируем и идём дальше
                            print(f"⏭ [{acc_name}] Пропущен {chat_title} (нет доступа на запись)")
                            if chat_id_val not in chats_added:
                                db.add_report_chat(report_id, str(chat_id_val), chat_title,
                                                   error='Нет доступа на запись')
                                chats_added.add(chat_id_val)
                            else:
                                db.update_report_stats(report_id, error_delta=1)
                            await asyncio.sleep(random.randint(5, 12))
                            continue
                        print(f"✅ [{acc_name}] Отправлено в {chat_title}")
                        if bot and not notifications_hidden:
                            await bot.send_message(user_id, f"✅ [{acc_name}] Отправлено в {chat_title}")
                        
                        if chat_id_val not in chats_added:
                            db.add_report_chat(report_id, str(chat_id_val), chat_title, sent=1)
                            chats_added.add(chat_id_val)
                        else:
                            db.update_report_stats(report_id, sent_delta=1)
                    except Exception as send_err:
                        print(f"⚠️ [{acc_name}] Ошибка отправки в {chat_title}: {send_err}")
                        if bot and not notifications_hidden:
                            try:
                                await bot.send_message(user_id, f"⚠️ [{acc_name}] Ошибка в {chat_title}: {str(send_err)[:100]}")
                            except:
                                pass
                        
                        if chat_id_val not in chats_added:
                            db.add_report_chat(report_id, str(chat_id_val), chat_title, error=str(send_err)[:100])
                            chats_added.add(chat_id_val)
                        else:
                            db.update_report_stats(report_id, error_delta=1)

                    delay = random.randint(120, 200)
                    await asyncio.sleep(delay)

                if bot:
                    await bot.send_message(user_id, f"⏳ [{acc_name}] Цикл #{cycle_count} завершен. Пауза {timeout_minutes} мин...")
                await asyncio.sleep(timeout_minutes * 60)

        except asyncio.CancelledError:
            print(f"🛑 Задача спама [{acc_name}] отменена")
        except AccountBlockedError as e:
            # Аккаунт ограничен/забанен — пользователь уже уведомлён в tg_call
            print(f"🚫 Рассылка [{acc_name}] остановлена: {e}")
            db.set_account_spam_status(account_id, 0)
        except Exception as e:
            print(f"❌ Критическая ошибка спама [{acc_name}]: {e}")
            if bot:
                try:
                    await bot.send_message(user_id, f"❌ [{acc_name}] Ошибка рассылки: {e}")
                except:
                    pass
        finally:
            db.finish_report(report_id)
            db.set_account_spam_status(account_id, 0)
            if task_id:
                db.finish_task(task_id, status='finished')
            self.active_spam_task_ids.pop(account_id, None)
            await self._release_user_quota(user_id)

    async def parse_chat_users(self, account_id: int, chat_id: str, bot, user_id: int,
                               limit: int = 10000, progress_callback=None,
                               history_limit: int = 5000, include_members: bool = True):
        """Парсинг участников чата.

        limit           — максимум пользователей, которых нужно собрать.
        history_limit   — сколько сообщений истории просканировать (для групп со скрытыми участниками).
        include_members — сначала попытаться взять открытый список участников (быстро),
                          затем добрать из истории сообщений.
        """
        account = db.get_account(account_id)
        if not account:
            return None, "Аккаунт не найден"

        acc_name = account.get('account_name') or f"Аккаунт #{account_id}"
        client, err = await self.get_or_start_client(account_id)
        if not client:
            return None, f"Ошибка подключения: {err}"

        users = []
        seen_ids = set()
        seen_usernames = set()

        def _add_user(u, username_override=None):
            """Добавляет пользователя в результат. Возвращает True, если он новый."""
            username = username_override
            user_id_val = 0
            first_name = last_name = phone = ''
            if u is not None:
                if getattr(u, 'is_bot', False):
                    return False
                if getattr(u, 'is_self', False):
                    return False
                if getattr(u, 'is_deleted', False):
                    return False
                user_id_val = getattr(u, 'id', 0) or 0
                first_name = getattr(u, 'first_name', '') or ''
                last_name = getattr(u, 'last_name', '') or ''
                phone = getattr(u, 'phone_number', '') or ''
                username = username or getattr(u, 'username', None)
            if not username and not user_id_val:
                return False
            key_u = username.lower() if username else None
            if key_u and key_u in seen_usernames:
                return False
            if user_id_val and user_id_val in seen_ids:
                return False
            if key_u:
                seen_usernames.add(key_u)
            if user_id_val:
                seen_ids.add(user_id_val)
            users.append({
                'id': user_id_val,
                'username': username or '',
                'first_name': first_name,
                'last_name': last_name,
                'phone': phone
            })
            return True

        stats = {'members': 0, 'from_history': 0, 'scanned': 0, 'mentions': 0}
        try:
            target = int(chat_id) if chat_id.lstrip('-').isdigit() else chat_id

            try:
                chat = await client.get_chat(target)
                chat_id_resolved = chat.id
                logging.info(f"📥 [{acc_name}] parse_chat_users chat={chat_id_resolved} "
                             f"title={getattr(chat, 'title', chat_id)} limit={limit} history_limit={history_limit}")
            except Exception as e:
                logging.error(f"❌ [{acc_name}] parse_chat_users get_chat failed: {e}")
                return None, f"Не удалось открыть чат: {e}"

            # ── 1. Открытый список участников (если он доступен) ──────────────
            if include_members:
                try:
                    async for member in client.get_chat_members(chat_id_resolved, limit=limit):
                        if len(users) >= limit:
                            break
                        if _add_user(getattr(member, 'user', None)):
                            stats['members'] += 1
                            if progress_callback and len(users) % 50 == 0:
                                try:
                                    await progress_callback(len(users))
                                except Exception:
                                    pass
                    logging.info(f"👥 [{acc_name}] members list: {stats['members']} users")
                except Exception as e:
                    # ChatAdminRequired / участники скрыты — это нормально, идём в историю
                    logging.info(f"ℹ️ [{acc_name}] Members list unavailable ({type(e).__name__}), "
                                 f"parsing message history instead")

            # ── 2. История сообщений (для чатов со скрытыми участниками) ──────
            if len(users) < limit and history_limit > 0:
                import re
                mention_re = re.compile(r'@([a-zA-Z0-9_]{5,32})')
                try:
                    async for msg in client.get_chat_history(chat_id_resolved, limit=history_limit):
                        stats['scanned'] += 1
                        if len(users) >= limit:
                            break
                        try:
                            u = getattr(msg, 'from_user', None)
                            if u is not None:
                                if _add_user(u):
                                    stats['from_history'] += 1
                            # Упоминания @username в тексте — тоже потенциальные участники
                            text = (getattr(msg, 'text', None) or getattr(msg, 'caption', None) or '')
                            if text and len(users) < limit:
                                for mention in mention_re.findall(text):
                                    if len(users) >= limit:
                                        break
                                    if _add_user(None, username_override=mention):
                                        stats['mentions'] += 1
                            if progress_callback and stats['scanned'] % 200 == 0:
                                try:
                                    await progress_callback(len(users), stats['scanned'])
                                except Exception:
                                    pass
                        except Exception:
                            continue
                except asyncio.CancelledError:
                    raise
                except Exception as hist_err:
                    logging.warning(f"⚠️ [{acc_name}] History parse error: {hist_err}")

            logging.info(
                f"📊 [{acc_name}] parse done: total={len(users)} members={stats['members']} "
                f"history={stats['from_history']} mentions={stats['mentions']} scanned={stats['scanned']}"
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logging.error(f"❌ [{acc_name}] parse_chat_users error: {e}")
            return None, f"Ошибка парсинга: {e}"

        if not users:
            return [], "Пользователей не найдено (участники скрыты и в истории нет отправителей)"

        try:
            db.clear_parsed_users(account_id, user_id)
            saved = db.save_parsed_users(account_id, user_id, users, source_chat_id=str(chat_id))
            if saved and saved < len(users):
                logging.info(f"[{acc_name}] сохранено {saved} из {len(users)} (остальные — дубликаты)")
        except Exception as save_err:
            logging.error(f"❌ [{acc_name}] Failed to save parsed users: {save_err}")
            return users, f"Найдено {len(users)} пользователей (ошибка сохранения: {save_err})"

        return users, (
            f"Найдено {len(users)} пользователей\n"
            f"• из списка участников: {stats['members']}\n"
            f"• из истории сообщений: {stats['from_history']}\n"
            f"• из упоминаний: {stats['mentions']}\n"
            f"• просканировано сообщений: {stats['scanned']}"
        )

    async def parse_chat_users_background(self, account_id: int, chat_id: str, bot, user_id: int,
                                          progress_callback=None, limit: int = 10000,
                                          history_limit: int = 5000, include_members: bool = True):
        task = asyncio.current_task()
        self.active_parse_tasks[account_id] = task
        try:
            users, msg = await self.parse_chat_users(
                account_id, chat_id, bot, user_id, limit, progress_callback,
                history_limit=history_limit, include_members=include_members
            )
            if users is None:
                try:
                    await bot.send_message(user_id, f"❌ Парсинг завершен с ошибкой: {msg}")
                except:
                    pass
                return
            try:
                from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
                markup = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="📋 Показать список", callback_data=f"parsed_users_page_{account_id}_0")],
                    [InlineKeyboardButton(text="🌐 HTML-таблица", callback_data=f"parsed_html_{account_id}"),
                     InlineKeyboardButton(text="📥 CSV", callback_data=f"download_parsed_{account_id}")],
                    [InlineKeyboardButton(text="◀️ Назад", callback_data=f"manage_acc_{account_id}")]
                ])
                await bot.send_message(user_id, f"✅ Парсинг завершен! {msg}", reply_markup=markup)
            except:
                pass
        except asyncio.CancelledError:
            try:
                await bot.send_message(user_id, "🛑 Парсинг отменен")
            except:
                pass
        finally:
            self.active_parse_tasks.pop(account_id, None)

    def cancel_parse(self, account_id: int):
        task = self.active_parse_tasks.pop(account_id, None)
        if task and not task.done():
            task.cancel()
            return True
        return False

    async def send_account_message(self, account_id: int, chat_id: str, text: str):
        account = db.get_account(account_id)
        if not account:
            return False, "Аккаунт не найден"
        client, err = await self.get_or_start_client(account_id)
        if not client:
            return False, f"Ошибка подключения: {err}"
        try:
            target = int(chat_id) if chat_id.startswith('-') or chat_id.isdigit() else chat_id
            await client.send_message(target, text)
            return True, "OK"
        except Exception as e:
            return False, str(e)

    async def get_last_private_message(self, account_id: int, chat_id: str) -> str:
        account = db.get_account(account_id)
        if not account:
            return ""
        client, err = await self.get_or_start_client(account_id)
        if not client:
            return ""
        try:
            target = int(chat_id) if chat_id.startswith('-') or chat_id.isdigit() else chat_id
            me = await client.get_me()
            async for msg in client.get_chat_history(target, limit=20):
                if (msg.text or msg.caption) and msg.from_user and msg.from_user.id != me.id:
                    return msg.text or msg.caption
            return ""
        except Exception:
            return ""

    async def get_last_private_messages(self, account_id: int, chat_id: str, limit: int = 3) -> list:
        account = db.get_account(account_id)
        if not account:
            print(f"DEBUG: Account {account_id} not found")
            return []
        client, err = await self.get_or_start_client(account_id)
        if not client:
            print(f"DEBUG: Client not started for account {account_id}: {err}")
            return []
        
        print(f"DEBUG: Fetching messages for account {account_id}, chat_id={chat_id}, limit={limit}")
        
        try:
            target = int(chat_id) if chat_id.startswith('-') or chat_id.isdigit() else chat_id
            print(f"DEBUG: Resolved target={target}, type={type(target)}")
            
            try:
                chat = await client.get_chat(target)
                print(f"DEBUG: Chat resolved: {chat.id}, type={chat.type}, title={chat.title}")
            except Exception as chat_err:
                print(f"DEBUG: Failed to resolve chat: {chat_err}")
                return []
            
            messages = []
            count = 0
            me = await client.get_me()
            async for msg in client.get_chat_history(chat.id, limit=50):
                count += 1
                text = msg.text or msg.caption or ''
                if not text:
                    text = '[медиа]'
                messages.append({
                    'text': text,
                    'out': msg.from_user is not None and msg.from_user.id == me.id,
                    'date': msg.date
                })
                print(f"DEBUG: Found message: out={msg.from_user is not None and msg.from_user.id == me.id}, text={text[:50]}")
                if len(messages) >= limit:
                    break
            
            print(f"DEBUG: Total messages scanned: {count}, returned: {len(messages)}")
            return messages[:limit]
        except Exception as e:
            print(f"Error getting last private messages for {chat_id}: {e}")
            import traceback
            traceback.print_exc()
            return []

    async def get_private_chat_users(self, account_id: int, limit: int = 100):
        account = db.get_account(account_id)
        if not account:
            return None, "Аккаунт не найден"
        client, err = await self.get_or_start_client(account_id)
        if not client:
            return None, f"Ошибка подключения: {err}"
        users = []
        seen = set()
        try:
            async for dialog in client.get_dialogs(limit=limit):
                if dialog.chat and dialog.chat.type == enums.ChatType.PRIVATE:
                    if dialog.chat.id in seen:
                        continue
                    seen.add(dialog.chat.id)
                    users.append({
                        'id': dialog.chat.id,
                        'username': dialog.chat.username or '',
                        'first_name': dialog.chat.first_name or 'User',
                        'last_name': dialog.chat.last_name or '',
                        'phone': dialog.chat.phone_number or ''
                    })
        except Exception as e:
            return None, f"Ошибка: {e}"
        return users, f"Найдено {len(users)} пользователей"

    async def invite_users(self, account_id: int, chat_id: str, users: list, bot, user_id: int, auto_join: bool = True):
        logging.info(f"📥 invite_users START | account={account_id} chat={chat_id} users={len(users)} auto_join={auto_join} user_id={user_id}")
        try:
            account = db.get_account(account_id)
            if not account:
                logging.error(f"❌ Account {account_id} not found")
                return
            acc_name = account.get('account_name') or f"Аккаунт #{account_id}"
            notifications_hidden = account.get('notifications_hidden', 0) == 1
            logging.info(f"📥 [{acc_name}] Starting invite flow | chat={chat_id} users={len(users)} notifications_hidden={notifications_hidden}")
            client, err = await self.get_or_start_client(account_id)
            if not client:
                logging.error(f"❌ [{acc_name}] Failed to start client: {err}")
                if bot and not notifications_hidden:
                    await bot.send_message(user_id, f"❌ [{acc_name}] Не удалось подключиться: {err}")
                return
            logging.info(f"✅ [{acc_name}] Client started")
            chat_id_normalized = chat_id.strip()
            if isinstance(chat_id_normalized, str):
                if chat_id_normalized.startswith('@'):
                    chat_id_normalized = chat_id_normalized[1:]
                elif chat_id_normalized.lstrip('-').isdigit():
                    chat_id_normalized = int(chat_id_normalized)
                elif 't.me/' in chat_id_normalized:
                    chat_id_normalized = chat_id_normalized.split('t.me/')[-1].strip('/')
                    if chat_id_normalized.startswith('@'):
                        chat_id_normalized = chat_id_normalized[1:]
                    if chat_id_normalized.lstrip('-').isdigit():
                        chat_id_normalized = int(chat_id_normalized)
            logging.info(f"📥 [{acc_name}] chat_id_normalized={chat_id_normalized} (type={type(chat_id_normalized).__name__})")
            try:
                await self.sync_peer_cache(account_id, [chat_id_normalized])
                logging.info(f"✅ [{acc_name}] Peer cache synced")
            except Exception as e:
                logging.warning(f"⚠️ [{acc_name}] sync_peer_cache failed: {type(e).__name__}: {e}")
            chat_obj = None
            try:
                logging.info(f"🔍 [{acc_name}] Resolving chat: {chat_id_normalized}")
                chat_obj = await asyncio.wait_for(
                    client.get_chat(chat_id_normalized),
                    timeout=5.0
                )
                logging.info(f"✅ [{acc_name}] Chat found: {chat_obj.title if hasattr(chat_obj, 'title') else chat_obj.id}")
            except asyncio.TimeoutError:
                logging.error(f"❌ [{acc_name}] Timeout getting chat {chat_id_normalized}")
                if bot and not notifications_hidden:
                    await bot.send_message(user_id, f"❌ [{acc_name}] Таймаут получения чата {chat_id_normalized}")
                return
            except Exception as e:
                error_str = str(e).lower()
                logging.error(f"❌ [{acc_name}] Error getting chat {chat_id_normalized}: {type(e).__name__}: {e}")
                if any(keyword in error_str for keyword in ['not found', 'invalid', 'forbidden', 'access', 'private']):
                    if bot and not notifications_hidden:
                        await bot.send_message(user_id, f"❌ [{acc_name}] Не удалось открыть чат {chat_id_normalized}: {str(e)[:100]}")
                    return
                if bot and not notifications_hidden:
                    await bot.send_message(user_id, f"⚠️ [{acc_name}] Ошибка доступа к чату: {str(e)[:100]}")
                return
            if not chat_obj:
                logging.error(f"❌ [{acc_name}] Chat object is None")
                if bot and not notifications_hidden:
                    await bot.send_message(user_id, f"❌ [{acc_name}] Чат {chat_id_normalized} не найден")
                return
            if auto_join:
                try:
                    logging.info(f"🔍 [{acc_name}] Checking membership in chat {chat_obj.id}")
                    member = await asyncio.wait_for(
                        client.get_chat_member(chat_obj.id, "me"),
                        timeout=5.0
                    )
                    logging.info(f"📊 [{acc_name}] Membership status: {getattr(member, 'status', 'unknown')}")
                    if getattr(member, 'status', '') in ['left', 'banned', 'restricted']:
                        logging.info(f"🔗 [{acc_name}] Joining chat {chat_obj.id}")
                        try:
                            await asyncio.wait_for(
                                client.join_chat(chat_obj.id),
                                timeout=10.0
                            )
                            await asyncio.sleep(2)
                            logging.info(f"✅ [{acc_name}] Joined chat successfully")
                        except asyncio.TimeoutError:
                            logging.warning(f"⚠️ [{acc_name}] Timeout joining chat")
                            if bot and not notifications_hidden:
                                await bot.send_message(user_id, f"⚠️ [{acc_name}] Таймаут вступления в чат")
                        except Exception as join_err:
                            logging.warning(f"⚠️ [{acc_name}] Failed to join chat: {type(join_err).__name__}: {join_err}")
                            if bot and not notifications_hidden:
                                await bot.send_message(user_id, f"⚠️ [{acc_name}] Не удалось войти в чат: {str(join_err)[:100]}")
                except asyncio.TimeoutError:
                    logging.warning(f"⚠️ [{acc_name}] Timeout checking membership")
                    if bot and not notifications_hidden:
                        await bot.send_message(user_id, f"⚠️ [{acc_name}] Таймаут проверки членства в чате")
                except Exception as chat_err:
                    logging.warning(f"⚠️ [{acc_name}] Failed to check membership: {type(chat_err).__name__}: {chat_err}")
                    if bot and not notifications_hidden:
                        await bot.send_message(user_id, f"⚠️ [{acc_name}] Не удалось проверить членство в чате: {str(chat_err)[:100]}")
            normalized = []
            seen = set()
            for user_entry in users:
                try:
                    peer = None
                    if isinstance(user_entry, str):
                        user_entry = user_entry.strip()
                        if user_entry.startswith('@'):
                            user_entry = user_entry[1:]
                        if user_entry.lstrip('-').isdigit():
                            peer = int(user_entry)
                        else:
                            peer = user_entry
                    elif isinstance(user_entry, int):
                        peer = user_entry
                    if not peer or peer in seen:
                        continue
                    seen.add(peer)
                    normalized.append(peer)
                except Exception:
                    continue
            logging.info(f"📥 [{acc_name}] Normalized {len(normalized)} users from {len(users)} raw entries")
            if not normalized:
                logging.warning(f"⚠️ [{acc_name}] No valid users for invite")
                if bot and not notifications_hidden:
                    await bot.send_message(user_id, f"⚠️ [{acc_name}] Нет валидных пользователей для инвайта")
                return
            if bot and not notifications_hidden:
                await bot.send_message(user_id, f"📥 [{acc_name}] Добавляю {len(normalized)} контактов...")
            contacts = []
            for peer in normalized:
                try:
                    logging.debug(f"📥 [{acc_name}] Resolving peer: {peer}")
                    user = await asyncio.wait_for(
                        client.get_users(peer),
                        timeout=3.0
                    )
                    if hasattr(user, 'id'):
                        user_id_val = user.id
                        first_name = user.first_name or "User"
                        last_name = user.last_name or ""
                    elif isinstance(user, list) and user:
                        user_id_val = user[0].id
                        first_name = user[0].first_name or "User"
                        last_name = user[0].last_name or ""
                    else:
                        logging.warning(f"⚠️ [{acc_name}] Unexpected user format for {peer}: {type(user)}")
                        continue
                    contacts.append((user_id_val, first_name, last_name))
                    logging.debug(f"✅ [{acc_name}] Resolved {peer} -> id={user_id_val} name={first_name} {last_name}")
                except asyncio.TimeoutError:
                    logging.warning(f"⚠️ [{acc_name}] Timeout getting user {peer}")
                    continue
                except Exception as e:
                    logging.warning(f"⚠️ [{acc_name}] Error getting user {peer}: {type(e).__name__}: {e}")
                    continue
            logging.info(f"📥 [{acc_name}] Got {len(contacts)} contacts from {len(normalized)} normalized peers")
            added_contacts = []
            for user_id_val, first_name, last_name in contacts:
                try:
                    logging.debug(f"📥 [{acc_name}] Adding contact: {user_id_val} ({first_name} {last_name})")
                    await asyncio.wait_for(
                        client.add_contact(user_id_val, first_name, last_name),
                        timeout=3.0
                    )
                    added_contacts.append(user_id_val)
                    logging.debug(f"✅ [{acc_name}] Added contact {user_id_val}")
                    await asyncio.sleep(random.randint(1, 3))
                except asyncio.TimeoutError:
                    logging.warning(f"⚠️ [{acc_name}] Timeout adding contact {user_id_val}")
                    continue
                except Exception as e:
                    logging.warning(f"⚠️ [{acc_name}] Error adding contact {user_id_val}: {type(e).__name__}: {e}")
                    continue
            logging.info(f"📥 [{acc_name}] Added {len(added_contacts)} contacts, starting invite")
            if bot and not notifications_hidden:
                await bot.send_message(user_id, f"📥 [{acc_name}] Добавлено контактов: {len(added_contacts)}. Начинаю инвайт...")
            success = 0
            errors = 0
            try:
                logging.debug(f"🔍 [{acc_name}] Pre-invite chat check: {chat_obj.id}")
                chat_check = await asyncio.wait_for(
                    client.get_chat(chat_obj.id),
                    timeout=5.0
                )
                if not chat_check:
                    logging.error(f"❌ [{acc_name}] Chat {chat_id_normalized} unavailable after check")
                    if bot and not notifications_hidden:
                        await bot.send_message(user_id, f"❌ [{acc_name}] Чат {chat_id_normalized} недоступен после проверки")
                    return
            except Exception as e:
                logging.error(f"❌ [{acc_name}] Chat check failed: {type(e).__name__}: {e}")
                if bot and not notifications_hidden:
                    await bot.send_message(user_id, f"❌ [{acc_name}] Чат {chat_id_normalized} недоступен: {str(e)[:100]}")
                return
            logging.info(f"📥 [{acc_name}] Starting invite loop: {len(added_contacts)} contacts")
            for user_id_val in added_contacts:
                try:
                    logging.info(f"📥 [{acc_name}] Inviting user {user_id_val} ({success+1}/{len(added_contacts)})")
                    await self.tg_call(
                        lambda: asyncio.wait_for(
                            client.add_chat_members(chat_id=chat_obj.id, user_ids=[user_id_val]),
                            timeout=5.0
                        ),
                        account_id=account_id, bot=bot, user_id=user_id,
                        description=f"invite {user_id_val}",
                        notify=not notifications_hidden
                    )
                    success += 1
                    logging.info(f"✅ [{acc_name}] Invited user {user_id_val} ({success}/{len(added_contacts)})")
                except AccountBlockedError as e:
                    logging.warning(f"🛑 [{acc_name}] Инвайт остановлен: {e}")
                    break
                except asyncio.TimeoutError:
                    errors += 1
                    logging.warning(f"⚠️ [{acc_name}] Timeout adding {user_id_val}")
                    if bot and not notifications_hidden:
                        try:
                            await bot.send_message(user_id, f"⚠️ [{acc_name}] Таймаут добавления {user_id_val}")
                        except:
                            pass
                except Exception as e:
                    errors += 1
                    error_str = str(e).lower()
                    logging.error(f"❌ [{acc_name}] Error adding {user_id_val}: {type(e).__name__}: {e}")
                    if any(kw in error_str for kw in ['flood', 'too many', 'wait', 'spam', 'restricted', 'banned']):
                        logging.warning(f"🛑 [{acc_name}] Critical flood error, stopping invite")
                        if bot and not notifications_hidden:
                            await bot.send_message(user_id, f"🛑 [{acc_name}] Остановлен инвайт из-за ошибки: {str(e)[:100]}")
                        break
                    if bot and not notifications_hidden:
                        try:
                            await bot.send_message(user_id, f"⚠️ [{acc_name}] Не удалось добавить {user_id_val}: {str(e)[:60]}")
                        except:
                            pass
                await asyncio.sleep(random.randint(5, 10))
            logging.info(f"📥 [{acc_name}] Invite loop complete: success={success} errors={errors}")
            for user_id_val in added_contacts:
                try:
                    logging.debug(f"🗑 [{acc_name}] Deleting contact {user_id_val}")
                    await asyncio.wait_for(
                        client.delete_contacts(user_id_val),
                        timeout=3.0
                    )
                    logging.debug(f"✅ [{acc_name}] Deleted contact {user_id_val}")
                except asyncio.TimeoutError:
                    logging.warning(f"⚠️ [{acc_name}] Timeout deleting contact {user_id_val}")
                except Exception as e:
                    logging.warning(f"⚠️ [{acc_name}] Error deleting contact {user_id_val}: {type(e).__name__}: {e}")
                await asyncio.sleep(random.randint(1, 2))
            msg = f"✅ [{acc_name}] Инвайт завершен: +{success} | ошибок {errors} | контактов удалено {len(added_contacts)}"
            logging.info(msg)
            if bot:
                await bot.send_message(user_id, msg)
            logging.info(f"📥 invite_users END | account={account_id} success={success} errors={errors}")
        except Exception as e:
            logging.error(f"❌ invite_users unhandled exception for account {account_id}: {type(e).__name__}: {e}", exc_info=True)

    async def spam_to_users(self, account_id: int, targets: list, bot, user_id: int, mode: str = 'post', custom_text: str = '', custom_entities: str = None):
        account = db.get_account(account_id)
        if not account:
            return
        
        acc_name = account.get('account_name') or f"Аккаунт #{account_id}"
        notifications_hidden = account.get('notifications_hidden', 0) == 1
        client, err = await self.get_or_start_client(account_id)
        if not client:
            if bot:
                await bot.send_message(user_id, f"❌ [{acc_name}] Не удалось подключиться: {err}")
            return
        
        post_text = account.get('post_text', '') if mode == 'post' else custom_text
        post_photo = account.get('post_photo', '') if mode == 'post' else ''
        
        if not post_text:
            if bot:
                await bot.send_message(user_id, f"❌ [{acc_name}] Текст поста не установлен!")
            return
        
        entities = None
        entities_json = None
        if mode == 'post':
            entities_json = account.get('post_entities')
        else:
            entities_json = custom_entities
        if entities_json:
            try:
                converted = await convert_entities_to_pyrogram(entities_json, client)
                if converted:
                    entities = converted
            except Exception as e:
                logging.error(f"❌ [{acc_name}] Failed to convert entities: {e}")
        
        success = 0
        errors = 0
        
        for target in targets:
            try:
                if isinstance(target, int):
                    peer = target
                elif isinstance(target, str):
                    if target.startswith('@'):
                        peer = target
                    else:
                        peer = f"@{target}"
                else:
                    continue
                
                text_to_send = post_text
                if mode == 'custom' and '{rand}' in post_text:
                    import string
                    def rand_str(length=6):
                        return ''.join(random.choices(string.ascii_letters + string.digits, k=length))
                    text_to_send = post_text.replace('{rand}', rand_str())
                
                if post_photo and os.path.exists(post_photo) and mode == 'post':
                    await client.send_photo(
                        peer, 
                        post_photo, 
                        caption=text_to_send,
                        caption_entities=entities if entities else None,
                        parse_mode=None if entities else None
                    )
                else:
                    await client.send_message(
                        peer, 
                        text_to_send,
                        entities=entities if entities else None,
                        parse_mode=None if entities else None
                    )
                success += 1
                if bot and not notifications_hidden:
                    try:
                        await bot.send_message(user_id, f"✅ [{acc_name}] Отправлено: {peer}")
                    except:
                        pass
            except Exception as e:
                errors += 1
                if bot and not notifications_hidden:
                    try:
                        await bot.send_message(user_id, f"⚠️ [{acc_name}] Ошибка {peer}: {str(e)[:80]}")
                    except:
                        pass
            await asyncio.sleep(random.randint(5, 15))
        
        if bot:
            await bot.send_message(user_id, f"✅ [{acc_name}] Рассылка завершена: {success} отправлено, {errors} ошибок")