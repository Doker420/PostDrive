import os
import sys
import json
import time
import asyncio
import logging
import random
import string
from datetime import datetime
from html import escape as html_escape
from typing import List, Dict, Optional, Any, Tuple


def _build_parsed_html(users, acc_name: str = "") -> str:
    """Самодостаточная HTML-страница с таблицей контактов.

    Без внешних библиотек и CDN: файл должен открываться локально
    двойным кликом, в том числе без интернета.
    """
    from datetime import datetime as _dt

    rows = []
    for i, u in enumerate(users, 1):
        uid = u.get('user_id_val') or ''
        uname = u.get('username') or ''
        fname = html_escape(u.get('first_name') or '')
        lname = html_escape(u.get('last_name') or '')
        phone = html_escape(u.get('phone') or '')
        src = html_escape(str(u.get('source_chat_id') or ''))
        uname_cell = (f'<a href="https://t.me/{html_escape(uname)}" target="_blank">'
                      f'@{html_escape(uname)}</a>') if uname else '<span class="muted">—</span>'
        rows.append(
            f'<tr><td class="num">{i}</td>'
            f'<td class="mono">{uid or "<span class=muted>—</span>"}</td>'
            f'<td>{uname_cell}</td>'
            f'<td>{fname or "<span class=muted>—</span>"}</td>'
            f'<td>{lname or "<span class=muted>—</span>"}</td>'
            f'<td class="mono">{phone or "<span class=muted>—</span>"}</td>'
            f'<td class="mono muted">{src or "—"}</td></tr>'
        )

    with_username = sum(1 for u in users if u.get('username'))
    with_phone = sum(1 for u in users if u.get('phone'))
    generated = _dt.now().strftime('%d.%m.%Y %H:%M')

    return f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Спарсенные пользователи — {html_escape(acc_name)}</title>
<style>
:root {{ color-scheme: light dark; }}
* {{ box-sizing: border-box; }}
body {{ margin:0; padding:24px; background:#f5f6f8; color:#1a1a1a;
  font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif; }}
.wrap {{ max-width:1100px; margin:0 auto; }}
h1 {{ font-size:22px; margin:0 0 4px; }}
.sub {{ color:#667; font-size:14px; margin-bottom:18px; }}
.cards {{ display:flex; gap:12px; flex-wrap:wrap; margin-bottom:18px; }}
.card {{ background:#fff; border:1px solid #e3e6ea; border-radius:10px;
  padding:12px 18px; min-width:130px; }}
.card b {{ display:block; font-size:22px; }}
.card span {{ color:#667; font-size:13px; }}
#q {{ width:100%; padding:11px 14px; font-size:15px; border:1px solid #d7dbe0;
  border-radius:10px; margin-bottom:14px; background:#fff; }}
#q:focus {{ outline:2px solid #2f81f7; border-color:transparent; }}
table {{ width:100%; border-collapse:collapse; background:#fff;
  border:1px solid #e3e6ea; border-radius:10px; overflow:hidden; }}
th,td {{ padding:9px 12px; text-align:left; border-bottom:1px solid #eef0f3;
  font-size:14px; }}
th {{ background:#fafbfc; font-weight:600; cursor:pointer; user-select:none;
  position:sticky; top:0; white-space:nowrap; }}
th:hover {{ background:#f0f2f5; }}
th::after {{ content:" \\2195"; color:#aab; font-size:11px; }}
tr:last-child td {{ border-bottom:none; }}
tbody tr:hover {{ background:#f7f9fc; }}
.num {{ color:#8a93a0; width:52px; }}
.mono {{ font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; font-size:13px; }}
.muted {{ color:#aab; }}
a {{ color:#2f81f7; text-decoration:none; }}
a:hover {{ text-decoration:underline; }}
.foot {{ margin-top:14px; color:#889; font-size:13px; }}
.hidden {{ display:none; }}
@media (prefers-color-scheme: dark) {{
  body {{ background:#15171a; color:#e6e8eb; }}
  .card,table,#q {{ background:#1d2025; border-color:#2c313a; color:#e6e8eb; }}
  th {{ background:#22262c; }} th:hover {{ background:#282d34; }}
  td {{ border-color:#262b32; }} tbody tr:hover {{ background:#22262c; }}
  .sub,.card span,.muted,.foot {{ color:#8b93a1; }}
}}
@media print {{ #q,.cards {{ display:none; }} body {{ padding:0; background:#fff; }} }}
</style></head><body><div class="wrap">
<h1>👥 Спарсенные пользователи</h1>
<div class="sub">{html_escape(acc_name)} · выгружено {generated}</div>
<div class="cards">
  <div class="card"><b>{len(users)}</b><span>всего контактов</span></div>
  <div class="card"><b>{with_username}</b><span>с username</span></div>
  <div class="card"><b>{with_phone}</b><span>с телефоном</span></div>
</div>
<input id="q" type="search" placeholder="Поиск по имени, username, ID или телефону...">
<table id="t"><thead><tr>
<th>#</th><th>Telegram ID</th><th>Username</th><th>Имя</th>
<th>Фамилия</th><th>Телефон</th><th>Источник</th>
</tr></thead><tbody>
{chr(10).join(rows)}
</tbody></table>
<div class="foot" id="cnt"></div>
</div><script>
var q=document.getElementById('q'),tb=document.querySelector('#t tbody'),
    rows=[].slice.call(tb.rows),cnt=document.getElementById('cnt');
function upd(n){{cnt.textContent='Показано '+n+' из '+rows.length;}}
upd(rows.length);
q.addEventListener('input',function(){{
  var v=q.value.toLowerCase().trim(),n=0;
  rows.forEach(function(r){{
    var m=!v||r.textContent.toLowerCase().indexOf(v)>-1;
    r.classList.toggle('hidden',!m); if(m)n++;
  }});
  upd(n);
}});
var dir={{}};
[].forEach.call(document.querySelectorAll('#t th'),function(th,i){{
  th.addEventListener('click',function(){{
    dir[i]=!dir[i]; var k=dir[i]?1:-1;
    rows.sort(function(a,b){{
      var x=a.cells[i].textContent.trim(),y=b.cells[i].textContent.trim();
      var nx=parseFloat(x.replace(/[^0-9.-]/g,'')),ny=parseFloat(y.replace(/[^0-9.-]/g,''));
      if(!isNaN(nx)&&!isNaN(ny)&&x.replace(/[^0-9.-]/g,'')!==''&&y.replace(/[^0-9.-]/g,''))
        return (nx-ny)*k;
      return x.localeCompare(y,'ru')*k;
    }});
    rows.forEach(function(r){{tb.appendChild(r);}});
  }});
}});
</script></body></html>"""


from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile,
    InputMediaPhoto, BufferedInputFile
)
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter, TelegramNetworkError

from sqliter import DBConnection
from cryptobot import CryptoBotClient
from user import AccountSessionManager, parse_proxy_string

logger = logging.getLogger(__name__)

db = DBConnection()

# ==================== FSM STATES ====================
class AddAccountStates(StatesGroup):
    WAITING_PROXY = State()
    WAITING_METHOD = State()
    WAITING_PHONE = State()
    WAITING_CODE = State()
    WAITING_2FA = State()
    WAITING_QR_2FA = State()
    WAITING_SESSION_STRING = State()
    WAITING_QR_SCAN = State()

class AccountPostStates(StatesGroup):
    WAITING_TEXT = State()
    WAITING_PHOTO = State()
    WAITING_TIMEOUT = State()
    WAITING_PROXY = State()

class ChatManagementStates(StatesGroup):
    WAITING_TXT_FILE = State()
    WAITING_ADDITIONAL_TEXT = State()

class AccountSettingsStates(StatesGroup):
    WAITING_FOR_BIO = State()
    WAITING_FOR_AUTORESPONDER = State()
    WAITING_FOR_PM_REPLY = State()

class AdminStates(StatesGroup):
    WAITING_CATEGORY_NAME = State()
    WAITING_PACK_NAME = State()
    WAITING_PACK_DESC = State()
    WAITING_PACK_CHATS_INPUT = State()
    WAITING_TARIFF_NAME = State()
    WAITING_TARIFF_DAYS = State()
    WAITING_TARIFF_PRICE = State()
    WAITING_USER_ID_SUB = State()
    WAITING_DAYS_SUB = State()
    WAITING_CRYPTOBOT_TOKEN = State()
    WAITING_PROMO_MEDIA = State()
    WAITING_PROMO_CAPTION = State()

class PartnerStates(StatesGroup):
    WAITING_WITHDRAW_AMOUNT = State()

class MirrorStates(StatesGroup):
    WAITING_BOT_TOKEN = State()
    WAITING_CONFIRM = State()

class RecurringStates(StatesGroup):
    WAITING_NAME = State()
    WAITING_TEXT = State()
    WAITING_MEDIA = State()
    WAITING_INTERVAL = State()
    WAITING_TARGET = State()
    EDIT_TEXT = State()
    EDIT_INTERVAL = State()
    WAITING_BUTTON_TEXT = State()
    WAITING_BUTTON_URL = State()
    WAITING_BUTTON_STYLE = State()

class ChatTextStates(StatesGroup):
    WAITING_CHAT_TEXT = State()

class MandatorySubStates(StatesGroup):
    WAITING_CHANNEL = State()

class PromoStates(StatesGroup):
    WAITING_PROMO_CODE = State()

class AdminPromoStates(StatesGroup):
    WAITING_PROMO_CODE = State()
    WAITING_PROMO_DAYS = State()
    WAITING_PROMO_MAX_USES = State()

class MassActionStates(StatesGroup):
    SELECTING_ACCOUNTS = State()
    WAITING_TARGETS = State()
    WAITING_CUSTOM_TEXT = State()

class InviteStates(StatesGroup):
    SELECTING_CHAT = State()
    WAITING_CUSTOM_CHAT = State()
    WAITING_USERS_FILE = State()

class ParseStates(StatesGroup):
    WAITING_HISTORY_LIMIT = State()

class NeuroCommentStates(StatesGroup):
    SELECTING_ACCOUNTS = State()
    SELECTING_MODE = State()
    WAITING_PROMPT = State()
    WAITING_CUSTOM_COMMENTS = State()
    WAITING_POST_PROMPT = State()
    WAITING_TARGET_CHANNELS = State()
    WAITING_COMMENT_DELAY = State()

# ==================== HELPER FUNCTIONS ====================
def main_menu_keyboard(user_id: int, is_admin: bool = False, admin_id: int = None):
    is_sub = db.is_user_subscribed(user_id, admin_id)
    buttons = [
        [KeyboardButton(text='➕ Добавить аккаунт', style='primary')],
        [KeyboardButton(text='🚀 Автопостинг', style='success' if is_sub else 'danger'), KeyboardButton(text='🧠 Нейрокомментинг', style='success' if is_sub else 'danger')],
        [KeyboardButton(text='📨 Рассылка', style='success' if is_sub else 'danger'), KeyboardButton(text='📥 Инвайтинг', style='success' if is_sub else 'danger')],
        [KeyboardButton(text='📁 Каталог папок с чатами', style='success' if is_sub else 'danger'), KeyboardButton(text='💳 Подписка', style='success')],
        [KeyboardButton(text='🎁 Промо', style='primary'), KeyboardButton(text='🤝 Партнеры', style='primary')],
        [KeyboardButton(text='ℹ️ Информация')]]
    if is_admin:
        buttons.append([KeyboardButton(text='👑 Админ-панель')])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def cancel_inline_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_action")]
    ])

def format_date(timestamp: int) -> str:
    if not timestamp or timestamp <= 0:
        return "Отсутствует"
    return datetime.fromtimestamp(timestamp).strftime('%d.%m.%Y %H:%M')

def generate_referral_code(user_id: int) -> str:
    prefix = ''.join(random.choices(string.ascii_uppercase, k=3))
    suffix = ''.join(random.choices(string.digits, k=4))
    return f"{prefix}{user_id}{suffix}"

async def process_referral(user_id: int, referral_code: str, admin_id: int) -> bool:
    partner = db.get_partner_by_code(referral_code)
    if not partner:
        return False
    if partner['user_id'] == user_id:
        return False
    return db.add_referral(partner['user_id'], user_id)

async def check_mandatory_subscription(user_id: int, bot: Bot, ADMIN: int) -> bool:
    enabled = db.get_kv("mandatory_sub_enabled", "0")
    channel = db.get_kv("mandatory_sub_channel", "")
    if enabled != "1" or not channel:
        return True
    if user_id == ADMIN:
        return True
    try:
        member = await bot.get_chat_member(channel, user_id)
        if member.status in ['member', 'administrator', 'creator']:
            return True
        return False
    except Exception as e:
        logging.error(f"Error checking mandatory subscription for user {user_id} in channel {channel}: {e}")
        return False

async def get_mandatory_sub_keyboard():
    channel = db.get_kv("mandatory_sub_channel", "")
    if not channel:
        return None
    if channel.startswith('-100'):
        channel_link = f"https://t.me/c/{channel[4:]}"
    elif channel.startswith('@'):
        channel_link = f"https://t.me/{channel[1:]}"
    else:
        channel_link = f"https://t.me/{channel}"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Подписаться на канал", url=channel_link)],
        [InlineKeyboardButton(text="✅ Проверить подписку", callback_data="check_mandatory_sub")]
    ])

def build_recurring_markup(buttons_data: list, include_style: bool = True) -> Optional[InlineKeyboardMarkup]:
    if not buttons_data:
        return None
    rows = []
    for item in buttons_data:
        if not isinstance(item, dict):
            continue
        btn_text = item.get('text', '')
        if not btn_text:
            continue
        btn_url = item.get('url')
        btn_callback = item.get('callback_data')
        btn_style = item.get('style')

        btn_kwargs = {'text': btn_text}
        if btn_url:
            btn_kwargs['url'] = btn_url
        elif btn_callback:
            btn_kwargs['callback_data'] = btn_callback
        else:
            continue

        if include_style and btn_style in ('primary', 'danger', 'success'):
            btn_kwargs['style'] = btn_style

        try:
            btn = InlineKeyboardButton(**btn_kwargs)
            rows.append([btn])
        except Exception:
            btn_kwargs.pop('style', None)
            try:
                btn = InlineKeyboardButton(**btn_kwargs)
                rows.append([btn])
            except Exception as e:
                logger.warning(f"Could not build button {item}: {e}")

    if not rows:
        return None
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def send_recurring_message_to_users(bot: Bot, db: DBConnection, msg_id: int) -> Tuple[int, int]:
    """Send a recurring message to users according to its target_type."""
    msg = db.get_recurring_message(msg_id)
    if not msg:
        logger.warning(f"Recurring message #{msg_id} not found in DB")
        return (0, 0)

    users = db.get_all_users()
    target_type = msg.get('target_type', 'all')
    now_ts = int(time.time())

    if target_type == 'subscribed':
        recipients = [u['user_id'] for u in users if u.get('subscription_until', 0) > now_ts or u.get('is_admin') == 1]
    elif target_type == 'unsubscribed':
        recipients = [u['user_id'] for u in users if u.get('subscription_until', 0) <= now_ts and u.get('is_admin') != 1]
    else:
        recipients = [u['user_id'] for u in users if u.get('user_id')]

    # Deduplicate while preserving order
    recipients = list(dict.fromkeys(recipients))

    logger.info(f"Starting recurring broadcast #{msg_id} ('{msg.get('name')}') to {len(recipients)} users")
    db.update_recurring_last_sent(msg_id)

    success = 0
    failed = 0
    text = msg.get('text', '')
    media_file_id = msg.get('media_file_id', '')

    buttons_raw = msg.get('buttons', '[]')
    try:
        buttons_data = json.loads(buttons_raw) if buttons_raw else []
    except Exception:
        buttons_data = []

    markup = build_recurring_markup(buttons_data, include_style=True)
    markup_no_style = build_recurring_markup(buttons_data, include_style=False)

    for uid in recipients:
        try:
            if media_file_id:
                try:
                    await bot.send_photo(chat_id=uid, photo=media_file_id, caption=text, parse_mode=ParseMode.HTML, reply_markup=markup)
                except TelegramBadRequest as bre:
                    err_msg = str(bre).lower()
                    if "can't parse entities" in err_msg:
                        await bot.send_photo(chat_id=uid, photo=media_file_id, caption=text, parse_mode=None, reply_markup=markup)
                    elif "button" in err_msg and markup_no_style:
                        await bot.send_photo(chat_id=uid, photo=media_file_id, caption=text, parse_mode=ParseMode.HTML, reply_markup=markup_no_style)
                    elif "file" in err_msg or "wrong file" in err_msg:
                        # Fallback to text if photo file_id expired or invalid
                        await bot.send_message(chat_id=uid, text=text, parse_mode=ParseMode.HTML, reply_markup=markup)
                    else:
                        raise
            else:
                try:
                    await bot.send_message(chat_id=uid, text=text, parse_mode=ParseMode.HTML, reply_markup=markup)
                except TelegramBadRequest as bre:
                    err_msg = str(bre).lower()
                    if "can't parse entities" in err_msg:
                        await bot.send_message(chat_id=uid, text=text, parse_mode=None, reply_markup=markup)
                    elif "button" in err_msg and markup_no_style:
                        await bot.send_message(chat_id=uid, text=text, parse_mode=ParseMode.HTML, reply_markup=markup_no_style)
                    else:
                        raise
            success += 1
        except TelegramRetryAfter as e:
            logger.warning(f"Telegram rate limit hit (RetryAfter {e.retry_after}s) on user {uid}")
            await asyncio.sleep(e.retry_after + 1)
            try:
                if media_file_id:
                    await bot.send_photo(chat_id=uid, photo=media_file_id, caption=text, parse_mode=ParseMode.HTML, reply_markup=markup)
                else:
                    await bot.send_message(chat_id=uid, text=text, parse_mode=ParseMode.HTML, reply_markup=markup)
                success += 1
            except Exception as re_err:
                logger.debug(f"Failed retry for user {uid}: {re_err}")
                failed += 1
        except (TelegramForbiddenError, TelegramBadRequest) as e:
            logger.debug(f"Cannot deliver recurring message to user {uid}: {e}")
            failed += 1
        except TelegramNetworkError as e:
            logger.warning(f"Network error delivering to user {uid}: {e}. Retrying in 2s...")
            await asyncio.sleep(2)
            try:
                if media_file_id:
                    await bot.send_photo(chat_id=uid, photo=media_file_id, caption=text, parse_mode=ParseMode.HTML, reply_markup=markup)
                else:
                    await bot.send_message(chat_id=uid, text=text, parse_mode=ParseMode.HTML, reply_markup=markup)
                success += 1
            except Exception as net_retry_err:
                logger.error(f"Network retry failed for user {uid}: {net_retry_err}")
                failed += 1
        except Exception as e:
            logger.error(f"Unexpected error sending recurring message to user {uid}: {e}")
            failed += 1

        await asyncio.sleep(0.05)

    logger.info(f"Recurring broadcast #{msg_id} finished: {success} sent, {failed} failed")
    return (success, failed)


async def start_recurring_messages_loop(bot: Bot, db: DBConnection, check_interval: int = 30):
    """Background task that periodically checks for active recurring messages and sends them."""
    logger.info("Recurring messages scheduler loop started.")
    await asyncio.sleep(5)
    while True:
        try:
            now = int(time.time())
            active_messages = db.get_recurring_messages(active_only=True)
            for m in active_messages:
                interval_seconds = int(m.get('interval_minutes', 60)) * 60
                last_sent = int(m.get('last_sent_at', 0) or 0)
                if now - last_sent >= interval_seconds:
                    logger.info(f"Triggering scheduled recurring message #{m['id']} '{m.get('name')}'")
                    await send_recurring_message_to_users(bot, db, m['id'])
        except asyncio.CancelledError:
            logger.info("Recurring messages loop cancelled.")
            break
        except Exception as e:
            logger.error(f"Error in recurring messages scheduler loop: {e}", exc_info=True)

        await asyncio.sleep(check_interval)


# ==================== REGISTER ALL HANDLERS ====================
def register_all_handlers(dp: Dispatcher, bot: Bot, config: dict):
    ADMIN = config.get('ADMIN', 0)
    CRYPTO_BOT_TOKEN = config.get('CRYPTO_BOT_TOKEN', '')
    TESTNET = config.get('TESTNET', False)
    account_manager = config.get('account_manager')
    USERNAME = config.get('USERNAME', 'bot')
    STARS_ENABLED = config.get('STARS_ENABLED', True)
    STARS_PER_USD = int(config.get('STARS_PER_USD', 50))
    MINIAPP_ENABLED = config.get('MINIAPP_ENABLED', False)
    MINIAPP_URL = config.get('MINIAPP_URL', '')
    TERMS_URL = config.get('TERMS_URL', '')
    PRIVACY_URL = config.get('PRIVACY_URL', '')
    SUPPORT_CONTACT = config.get('SUPPORT', '@support')

    DOCS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'documents')

    def _load_doc(filename: str, limit: int = 3500) -> str:
        """Читает документ из documents/ и готовит его к отправке в Telegram."""
        path = os.path.join(DOCS_DIR, filename)
        try:
            with open(path, 'r', encoding='utf-8') as fh:
                raw = fh.read()
        except Exception as e:
            logger.error(f"Не удалось прочитать {filename}: {e}")
            return ""
        import re as _re
        text = raw
        text = _re.sub(r'^#{1,6}\s*(.+)$', r'<b>\1</b>', text, flags=_re.MULTILINE)
        text = _re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
        text = _re.sub(r'_(.+?)_', r'<i>\1</i>', text)
        text = _re.sub(r'`(.+?)`', r'<code>\1</code>', text)
        text = _re.sub(r'<(https?://[^>]+)>', r'\1', text)
        text = _re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()

    def _doc_pages(text: str, size: int = 3500) -> list:
        """Разбивает длинный документ на страницы по границам абзацев."""
        if not text:
            return ["Документ недоступен."]
        pages, current = [], ""
        for para in text.split('\n\n'):
            candidate = (current + '\n\n' + para) if current else para
            if len(candidate) > size and current:
                pages.append(current)
                current = para
            else:
                current = candidate
        if current:
            pages.append(current)
        return pages or ["Документ недоступен."]

    CHATS_PER_PAGE = 8
    user_selected_leave_chats: Dict[int, set] = {}

    IMG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'img')

    async def send_photo(message, photo_name, caption, reply_markup=None):
        """Send photo with caption, fallback to text if photo not found."""
        photo_path = os.path.join(IMG_DIR, photo_name)
        if os.path.exists(photo_path):
            photo = FSInputFile(photo_path)
            return await message.answer_photo(photo=photo, caption=caption, reply_markup=reply_markup)
        return await message.answer(caption, reply_markup=reply_markup)

    async def edit_photo(callback, photo_name, caption, reply_markup=None):
        """Edit message to photo with caption, fallback to text edit."""
        photo_path = os.path.join(IMG_DIR, photo_name)
        if os.path.exists(photo_path):
            photo = FSInputFile(photo_path)
            try:
                await callback.message.delete()
            except:
                pass
            return await callback.message.answer_photo(photo=photo, caption=caption, reply_markup=reply_markup)
        await edit_message(callback, caption, reply_markup)

    async def edit_message(target, text, reply_markup=None):
        msg = target.message
        try:
            if msg.photo:
                try:
                    await msg.edit_caption(caption=text, reply_markup=reply_markup)
                except Exception:
                    await msg.delete()
                    await msg.answer(text, reply_markup=reply_markup)
            elif msg.video or msg.document or msg.animation:
                await msg.delete()
                await msg.answer(text, reply_markup=reply_markup)
            else:
                await msg.edit_text(text, reply_markup=reply_markup)
        except Exception:
            try:
                await msg.delete()
            except:
                pass
            await msg.answer(text, reply_markup=reply_markup)

    # ==================== START & INFO ====================
    @dp.message(Command('start'))
    async def process_start_command(message: Message, state: FSMContext):
        await state.clear()
        user_id = message.from_user.id
        referral_code = None

        if message.text and len(message.text) > 7:
            arg = message.text[7:].strip()
            if arg:
                referral_code = arg

        user = db.get_or_create_user(
            user_id=user_id,
            username=message.from_user.username or "",
            first_name=message.from_user.first_name or "",
            last_name=message.from_user.last_name or "",
            admin_id=ADMIN
        )

        if referral_code:
            await process_referral(user_id, referral_code, ADMIN)

        if not await check_mandatory_subscription(user_id, bot, ADMIN):
            keyboard = await get_mandatory_sub_keyboard()
            await message.answer(
                "📢 <b>Для использования бота необходимо подписаться на наш канал!</b>\n\n"
                "Подпишитесь и нажмите «Проверить подписку».",
                reply_markup=keyboard
            )
            return

        is_admin = (user_id == ADMIN) or (user.get('is_admin') == 1)
        is_sub = db.is_user_subscribed(user_id, ADMIN)

        status_sub = "🟢 Активна" if is_sub else "🔴 Не активна"
        sub_until = format_date(user.get('subscription_until', 0)) if not is_admin else "Бессрочно (Админ)"

        text = (
            f"👋 <b>Добро пожаловать в Autoposter Multi-Account!</b>\n\n"
            f"👤 <b>Ваш ID:</b> <code>{user_id}</code>\n"
            f"💳 <b>Статус подписки:</b> {status_sub}\n"
            f"⏳ <b>Действует до:</b> {sub_until}\n\n"
            f"Выберите нужный раздел в меню ниже ⬇️"
        )
        await send_photo(message, 'welcome.jpg', text, main_menu_keyboard(user_id, is_admin, ADMIN))

    @dp.callback_query(F.data == "check_mandatory_sub")
    async def check_mandatory_sub_callback(callback: CallbackQuery, state: FSMContext):
        user_id = callback.from_user.id
        if await check_mandatory_subscription(user_id, bot, ADMIN):
            await state.clear()
            user = db.get_user(user_id)
            is_admin = (user_id == ADMIN) or (user and user.get('is_admin') == 1)
            is_sub = db.is_user_subscribed(user_id, ADMIN)
            status_sub = "🟢 Активна" if is_sub else "🔴 Не активна"
            sub_until = format_date(user.get('subscription_until', 0)) if not is_admin else "Бессрочно (Админ)"
            text = (
                f"👋 <b>Добро пожаловать в Autoposter Multi-Account!</b>\n\n"
                f"👤 <b>Ваш ID:</b> <code>{user_id}</code>\n"
                f"💳 <b>Статус подписки:</b> {status_sub}\n"
                f"⏳ <b>Действует до:</b> {sub_until}\n\n"
                f"Выберите нужный раздел в меню ниже ⬇️"
            )
            await edit_photo(callback, 'welcome.jpg', text, main_menu_keyboard(user_id, is_admin))
        else:
            await callback.answer("❌ Вы не подписаны на канал!", show_alert=True)

    @dp.message(F.text == 'ℹ️ Информация')
    async def info_handler(message: Message, state: FSMContext):
        text = (
            "🤖 <b>Autoposter Multi-Account Platform</b>\n"
            "⚡ <b>Версия:</b> 4.0.0 Multi-Session\n\n"
            "<b>Возможности:</b>\n"
            "• Подключение нескольких аккаунтов с HTTP/SOCKS5 прокси\n"
            "• Оплата подписки через CryptoBot (USDT)\n"
            "• База категорий и папок чатов от администратора\n"
            "• Индивидуальная настройка и запуск рассылки для каждого аккаунта\n"
            "• Выборочный спам (включение/выключение конкретных чатов)\n"
            "• Массовый выход из выбранных чатов\n"
            "• Защита от флуда и поддержка форматирования с медиа"
        )
        text += f"\n\n💬 <b>Поддержка:</b> {SUPPORT_CONTACT}"
        rows = [[InlineKeyboardButton(text="📖 Инструкция", callback_data="instructions_start_0")]]
        if TERMS_URL:
            rows.append([InlineKeyboardButton(text="📄 Пользовательское соглашение", url=TERMS_URL)])
        else:
            rows.append([InlineKeyboardButton(text="📄 Пользовательское соглашение", callback_data="legal_terms_0")])
        rows.append([InlineKeyboardButton(text="📋 Правила использования", callback_data="legal_rules_0")])
        rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_main")])
        markup = InlineKeyboardMarkup(inline_keyboard=rows)
        await send_photo(message, 'info.jpg', text, markup)

    @dp.callback_query(F.data.startswith('legal_'))
    async def legal_doc_callback(callback: CallbackQuery):
        # legal_{terms|rules}_{page}
        parts = callback.data.split('_')
        doc = parts[1]
        page = int(parts[2]) if len(parts) > 2 else 0
        filename = 'TERMS.md' if doc == 'terms' else 'RULES.md'
        title = "📄 Пользовательское соглашение" if doc == 'terms' else "📋 Правила использования"

        pages = _doc_pages(_load_doc(filename))
        page = max(0, min(page, len(pages) - 1))

        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"legal_{doc}_{page-1}"))
        nav.append(InlineKeyboardButton(text=f"{page+1}/{len(pages)}", callback_data="noop"))
        if page < len(pages) - 1:
            nav.append(InlineKeyboardButton(text="➡️", callback_data=f"legal_{doc}_{page+1}"))
        rows = [nav]
        other = 'rules' if doc == 'terms' else 'terms'
        other_label = "📋 Правила использования" if doc == 'terms' else "📄 Пользовательское соглашение"
        rows.append([InlineKeyboardButton(text=other_label, callback_data=f"legal_{other}_0")])
        rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_main")])

        await edit_message(callback, f"{title}\n\n{pages[page]}", InlineKeyboardMarkup(inline_keyboard=rows))

    INSTRUCTIONS = [
        (
            "📖 <b>Инструкция 1/5 — Автопостинг</b>\n\n"
            "1. Нажмите «➕ Добавить аккаунт» и авторизуйтесь.\n"
            "2. Откройте «🚀 Автопостинг».\n"
            "3. Нажмите «✏️ Настроить пост» и отправьте текст/медиа.\n"
            "4. В «🎯 Чаты» выберите чаты для рассылки.\n"
            "5. В «⏱ Интервал» задайте паузу в минутах.\n"
            "6. Нажмите «▶️ Запустить рассылку».\n\n"
            "Совет: используйте прокси и не запускайте слишком много аккаунтов одновременно."
        ),
        (
            "📖 <b>Инструкция 2/5 — Инвайтинг</b>\n\n"
            "1. Перейдите в «📥 Инвайтинг».\n"
            "2. Выберите аккаунт и целевой чат.\n"
            "3. Загрузите файл с пользователями или вставьте список.\n"
            "4. Нажмите «🚀 Запустить инвайт».\n"
            "5. Бот добавит контакты и проведёт инвайт.\n\n"
            "Важно: лимиты Telegram учитывайте, иначе будет flood."
        ),
        (
            "📖 <b>Инструкция 3/5 — Парсинг</b>\n\n"
            "1. Откройте аккаунт и выберите «👥 Парсинг».\n"
            "2. Выберите чат для парсинга.\n"
            "3. Нажмите «▶️ Запустить парсинг».\n"
            "4. По завершении скачайте CSV или просмотрите список.\n\n"
            "Парсинг идёт по истории сообщений, поэтому старая история = больше пользователей."
        ),
        (
            "📖 <b>Инструкция 4/5 — Нейрокомментинг</b>\n\n"
            "1. Откройте «🧠 Нейрокомментинг».\n"
            "2. Выберите режим: по промту, свои комментарии или промт нового поста.\n"
            "3. Укажите каналы и задержку.\n"
            "4. Нажмите «✅ Включить».\n\n"
            "Бот будет комментировать новые посты автоматически."
        ),
        (
            "📖 <b>Инструкция 5/5 — Рассылка</b>\n\n"
            "1. Нажмите «📨 Рассылка».\n"
            "2. Выберите аккаунты.\n"
            "3. Отправьте текст/медиа и цели.\n"
            "4. Нажмите «🚀 Запустить рассылку».\n\n"
            "После запуска вы получите уведомления о прогрессе и результате."
        ),
    ]

    INSTRUCTION_QUIZ = [
        {
            "question": "Где настраивается текст поста для автопостинга?",
            "options": ["В инвайтинге", "В Автопостинге → Настроить пост", "В парсинге", "В админке"],
            "answer": 1,
            "explanation": "Текст поста настраивается в разделе «Автопостинг» → «Настроить пост». Там можно задать шаблон, добавить переменные и медиа."
        },
        {
            "question": "Какой формат загрузки пользователей поддерживается для инвайта?",
            "options": ["Только CSV", "Только TXT", "TXT/перечисление через новую строку", "Только Excel"],
            "answer": 2,
            "explanation": "Для загрузки участников используется TXT-файл, где каждый номер/username записан с новой строки. CSV и Excel не поддерживаются."
        },
        {
            "question": "Зачем нужен proxy в настройках аккаунта?",
            "options": ["Для ускорения бота", "Для обхода блокировок и стабильности", "Для красоты", "Для парсинга"],
            "answer": 1,
            "explanation": "Proxy защищает аккаунт от временных блокировок Telegram, обеспечивает стабильную работу и обходит гео-ограничения."
        },
    ]

    @dp.callback_query(F.data.startswith('instructions_start_'))
    async def instructions_start_callback(callback: CallbackQuery, state: FSMContext):
        page = int(callback.data.split('_')[-1])
        await state.update_data(instruction_page=page)
        await show_instruction_page(callback, state, page)

    async def show_instruction_page(callback: CallbackQuery, state: FSMContext, page: int):
        total = len(INSTRUCTIONS)
        if page < 0:
            page = 0
        if page >= total:
            page = total - 1
        text = INSTRUCTIONS[page]
        buttons = []
        if page > 0:
            buttons.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"instructions_start_{page-1}"))
        if page < total - 1:
            buttons.append(InlineKeyboardButton(text="➡️ Далее", callback_data=f"instructions_start_{page+1}"))
        buttons.append(InlineKeyboardButton(text="✅ Прочитал(а)", callback_data=f"instruction_quiz_start_{page}"))
        buttons.append(InlineKeyboardButton(text="◀️ Выход", callback_data="back_to_main"))
        markup = InlineKeyboardMarkup(inline_keyboard=[buttons])
        await edit_message(callback, text, markup)

    @dp.callback_query(F.data.startswith('instruction_quiz_start_'))
    async def instruction_quiz_start_callback(callback: CallbackQuery, state: FSMContext):
        page = int(callback.data.split('_')[-1])
        await state.update_data(quiz_page=0, quiz_score=0, quiz_correct_answers=[])
        await show_quiz_question(callback, state)

    async def show_quiz_question(callback: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        page = data.get('quiz_page', 0)
        quiz = INSTRUCTION_QUIZ
        if page >= len(quiz):
            score = data.get('quiz_score', 0)
            total = len(quiz)
            correct_answers = data.get('quiz_correct_answers', [])
            text = f"✅ <b>Тест завершён!</b>\n\n"
            text += f"📊 Результат: {score}/{total}\n\n"
            if score == total:
                text += "🎉 Отлично! Вы готовы к работе.\n\n"
            elif score >= total * 0.7:
                text += "👍 Хороший результат! Небольшие пробелы — перечитайте разделы:\n\n"
            else:
                text += "⚠️ Рекомендуем перечитать инструкцию и попробовать снова.\n\n"
            for i, q in enumerate(quiz):
                is_correct = i in correct_answers
                icon = "✅" if is_correct else "❌"
                correct_opt = q['options'][q['answer']]
                text += f"{icon} <b>Вопрос {i+1}:</b> {q['question']}\n"
                text += f"   📝 <i>{q.get('explanation', '')}</i>\n"
                if not is_correct:
                    text += f"   💡 Правильный ответ: <b>{correct_opt}</b>\n\n"
                else:
                    text += "\n"
            markup = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Пройти снова", callback_data="instruction_quiz_start_0")],
                [InlineKeyboardButton(text="◀️ Выход", callback_data="back_to_main")]
            ])
            await edit_message(callback, text, markup)
            return
        q = quiz[page]
        options = "\n".join([f"{i+1}. {opt}" for i, opt in enumerate(q['options'])])
        text = f"❓ <b>Вопрос {page+1}/{len(quiz)}</b>\n\n{q['question']}\n\n{options}"
        buttons = []
        for i, opt in enumerate(q['options']):
            buttons.append([InlineKeyboardButton(text=opt, callback_data=f"instruction_quiz_answer_{page}_{i}")])
        buttons.append([InlineKeyboardButton(text="◀️ Выход", callback_data="back_to_main")])
        markup = InlineKeyboardMarkup(inline_keyboard=buttons)
        await edit_message(callback, text, markup)

    @dp.callback_query(F.data.startswith('instruction_quiz_answer_'))
    async def instruction_quiz_answer_callback(callback: CallbackQuery, state: FSMContext):
        parts = callback.data.split('_')
        page = int(parts[3])
        answer = int(parts[4])
        data = await state.get_data()
        quiz = INSTRUCTION_QUIZ
        q = quiz[page]
        score = data.get('quiz_score', 0)
        correct_answers = data.get('quiz_correct_answers', [])
        if answer == q['answer']:
            score += 1
            if page not in correct_answers:
                correct_answers.append(page)
            await state.update_data(quiz_score=score, quiz_correct_answers=correct_answers)
        else:
            if page in correct_answers:
                correct_answers.remove(page)
            await state.update_data(quiz_correct_answers=correct_answers)
        await state.update_data(quiz_page=page + 1)
        await show_quiz_question(callback, state)

    @dp.message(F.text == '🎁 Промо')
    async def promo_handler(message: Message, state: FSMContext):
        promo_media = db.get_kv('promo_media_type', '')
        promo_file_id = db.get_kv('promo_media_file_id', '')
        promo_caption = db.get_kv('promo_caption', '')
        if not promo_media or not promo_file_id:
            await message.answer("🎁 Промо материалов пока нет.")
            return
        try:
            if promo_media == 'photo':
                await message.answer_photo(photo=promo_file_id, caption=promo_caption)
            elif promo_media == 'animation':
                await message.answer_animation(animation=promo_file_id, caption=promo_caption)
            elif promo_media == 'video':
                await message.answer_video(video=promo_file_id, caption=promo_caption)
            else:
                await message.answer(promo_caption or "🎁 Промо")
        except Exception as e:
            await message.answer(f"⚠️ Не удалось показать промо: {e}")

    async def show_account_selection(message_or_callback, action: str, state: FSMContext):
        user_id = message_or_callback.from_user.id if hasattr(message_or_callback, 'from_user') else message_or_callback.message.from_user.id
        accounts = db.get_user_accounts(user_id)
        if not accounts:
            text = "📱 У вас нет аккаунтов! Добавьте аккаунт в меню «Автопостинг»."
            if isinstance(message_or_callback, Message):
                await message_or_callback.answer(text)
            else:
                await edit_message(message_or_callback, text)
            return
        
        data = await state.get_data()
        selected = data.get('selected_accounts', [])
        
        await state.set_state(MassActionStates.SELECTING_ACCOUNTS)
        await state.update_data(action_type=action, selected_accounts=selected)
        
        buttons = []
        for acc in accounts:
            icon = "☑️" if acc['id'] in selected else "⬜"
            name = acc.get('account_name') or f"Аккаунт #{acc['id']}"
            phone = f"({acc['phone']})" if acc.get('phone') else ""
            buttons.append([InlineKeyboardButton(text=f"{icon} {name} {phone}", callback_data=f"toggle_mass_{action}_{acc['id']}")])
        
        buttons.append([InlineKeyboardButton(text="✅ Далее", callback_data=f"mass_action_next_{action}")])
        buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_action")])
        markup = InlineKeyboardMarkup(inline_keyboard=buttons)
        
        action_name = "📨 Рассылка" if action == "spam" else "📥 Инвайтинг"
        text = f"{action_name}\n\nВыберите аккаунты:"
        photo = 'acc.jpg' if action == 'spam' else 'catalog.jpg'
        
        if isinstance(message_or_callback, Message):
            await send_photo(message_or_callback, photo, text, markup)
        else:
            try:
                await message_or_callback.message.delete()
            except:
                pass
            photo_path = os.path.join(IMG_DIR, photo)
            if os.path.exists(photo_path):
                from aiogram.types import FSInputFile
                await message_or_callback.message.answer_photo(photo=FSInputFile(photo_path), caption=text, reply_markup=markup)
            else:
                await message_or_callback.message.answer(text, reply_markup=markup)

    # Пресеты скорости рассылки. Ориентир Telegram: безопасная норма для
    # сообщений незнакомым людям — примерно 20-30 в час на аккаунт;
    # превышение почти гарантированно даёт PeerFlood («спам-блок»).
    SPAM_SPEED_LABELS = {
        'slow':   ("🐢 Безопасная", "90–180 сек между сообщениями (~25 сообщений/час)"),
        'normal': ("🚶 Средняя", "30–90 сек (~60 сообщений/час) — риск умеренный"),
        'fast':   ("🐇 Быстрая", "10–25 сек (~200 сообщений/час) — высокий риск спам-блока"),
    }

    async def ask_for_spam_targets(message_or_callback, state: FSMContext):
        data = await state.get_data()
        account_ids = data.get('spam_account_ids', [])
        mode = data.get('spam_mode', 'post')
        speed = data.get('spam_speed', 'normal')
        speed_label, speed_hint = SPAM_SPEED_LABELS.get(speed, SPAM_SPEED_LABELS['normal'])

        text = (
            f"📨 <b>Рассылка</b>\n\n"
            f"Выбрано аккаунтов: {len(account_ids)}\n"
            f"Режим: {'📝 Текст из поста' if mode == 'post' else '✏️ Свой текст'}\n"
            f"Скорость: {speed_label} — {speed_hint}\n\n"
            f"Отправьте:\n"
            f"• TXT файл с ID юзеров или username (@username или без)\n"
            f"• Или ссылки формата https://t.me/username\n"
            f"• Или список в сообщении (по одному на строку)\n"
            f"• Или нажмите «📇 По контактам аккаунтов» — цели возьмутся "
            f"из адресной книги выбранных аккаунтов"
        )
        speed_row = []
        for code, (label, _hint) in SPAM_SPEED_LABELS.items():
            mark = "✅ " if code == speed else ""
            speed_row.append(InlineKeyboardButton(text=f"{mark}{label}",
                                                  callback_data=f"spam_speed_{code}"))
        buttons = [
            speed_row,
            [InlineKeyboardButton(text="📇 По контактам аккаунтов", callback_data="spam_targets_contacts")],
            [InlineKeyboardButton(text="🔄 Обновить выбор", callback_data="refresh_mass_spam")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_action")]
        ]
        markup = InlineKeyboardMarkup(inline_keyboard=buttons)
        await state.set_state(MassActionStates.WAITING_TARGETS)
        if isinstance(message_or_callback, Message):
            await message_or_callback.answer(text, reply_markup=markup)
        else:
            await edit_message(message_or_callback, text, markup)

    async def show_invite_chat_selection(callback: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        account_ids = data.get('invite_account_ids', [])
        page = data.get('invite_chat_page', 0)
        per_page = 10
        
        all_chats = []
        for acc_id in account_ids:
            # Инвайтить можно только в группы/супергруппы
            for chat in db.get_account_chats(acc_id, chat_types=db.GROUP_CHAT_TYPES):
                all_chats.append(chat)
        
        total = len(all_chats)
        start = page * per_page
        end = start + per_page
        page_chats = all_chats[start:end]
        
        buttons = []
        for chat in page_chats:
            title = chat.get('chat_title') or chat['chat_id']
            buttons.append([InlineKeyboardButton(text=f"💬 {title[:35]}", callback_data=f"invite_chat_{chat['account_id']}_{chat['chat_id']}")])
        
        total_pages = max(1, (total + per_page - 1) // per_page)
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton(text="⬅️", callback_data=f"invite_chat_page_{page-1}"))
        if page < total_pages - 1:
            nav_buttons.append(InlineKeyboardButton(text="➡️", callback_data=f"invite_chat_page_{page+1}"))
        if nav_buttons:
            buttons.append(nav_buttons)
        
        buttons.append([InlineKeyboardButton(text="🔗 Ввести ID/ссылку чата", callback_data="invite_custom_chat")])
        buttons.append([InlineKeyboardButton(text="🔄 Обновить выбор", callback_data="refresh_mass_invite")])
        buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_action")])
        markup = InlineKeyboardMarkup(inline_keyboard=buttons)
        
        text = f"📥 <b>Инвайтинг</b>\n\nЧаты: {total}\nСтраница: {page+1}/{total_pages}\n\nВыберите чат для инвайта:"
        await edit_message(callback, text, markup)

    @dp.message(F.text == '📨 Рассылка')
    async def spam_menu_handler(message: Message, state: FSMContext):
        await state.clear()
        user_id = message.from_user.id
        if not db.is_user_subscribed(user_id, ADMIN):
            await message.answer("🔒 Для использования рассылки требуется активная подписка.")
            return
        await show_account_selection(message, 'spam', state)

    @dp.message(F.text == '📥 Инвайтинг')
    async def invite_menu_handler(message: Message, state: FSMContext):
        await state.clear()
        user_id = message.from_user.id
        if not db.is_user_subscribed(user_id, ADMIN):
            await message.answer("🔒 Для инвайтинга требуется активная подписка.")
            return
        await show_account_selection(message, 'invite', state)

    @dp.callback_query(F.data.startswith('toggle_mass_spam_'))
    async def toggle_mass_spam_callback(callback: CallbackQuery, state: FSMContext):
        account_id = int(callback.data.split('_')[3])
        data = await state.get_data()
        selected = data.get('selected_accounts', [])
        if account_id in selected:
            selected.remove(account_id)
        else:
            selected.append(account_id)
        await state.update_data(selected_accounts=selected)
        await show_account_selection(callback, 'spam', state)

    @dp.callback_query(F.data.startswith('toggle_mass_invite_'))
    async def toggle_mass_invite_callback(callback: CallbackQuery, state: FSMContext):
        account_id = int(callback.data.split('_')[3])
        data = await state.get_data()
        selected = data.get('selected_accounts', [])
        if account_id in selected:
            selected.remove(account_id)
        else:
            selected.append(account_id)
        await state.update_data(selected_accounts=selected)
        await show_account_selection(callback, 'invite', state)

    @dp.callback_query(F.data.startswith('mass_action_next_'))
    async def mass_action_next_callback(callback: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        action = data.get('action_type')
        selected = data.get('selected_accounts', [])
        if not selected:
            await callback.answer("❌ Выберите хотя бы один аккаунт!", show_alert=True)
            return
        
        if action == 'spam':
            await state.clear()
            text = (
                f"🚀 <b>Рассылка</b>\n\n"
                f"Выбрано аккаунтов: {len(selected)}\n\n"
                f"Выберите режим текста:"
            )
            buttons = [
                [InlineKeyboardButton(text="📝 Текст из поста", callback_data="spam_mode_post")],
                [InlineKeyboardButton(text="✏️ Свой текст", callback_data="spam_mode_custom")],
                [InlineKeyboardButton(text="🔄 Обновить выбор", callback_data="refresh_mass_spam")],
                [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_action")]
            ]
            markup = InlineKeyboardMarkup(inline_keyboard=buttons)
            await state.set_state(MassActionStates.SELECTING_ACCOUNTS)
            await state.update_data(spam_account_ids=selected)
            await edit_message(callback, text, markup)
        elif action == 'invite':
            await state.clear()
            await state.set_state(InviteStates.SELECTING_CHAT)
            await state.update_data(invite_account_ids=selected, invite_chat_page=0)
            await show_invite_chat_selection(callback, state)

    @dp.callback_query(F.data == "refresh_mass_spam")
    async def refresh_mass_spam_callback(callback: CallbackQuery, state: FSMContext):
        await show_account_selection(callback, 'spam', state)

    @dp.callback_query(F.data == "refresh_mass_invite")
    async def refresh_mass_invite_callback(callback: CallbackQuery, state: FSMContext):
        await show_account_selection(callback, 'invite', state)

    @dp.callback_query(F.data == "spam_mode_post")
    async def spam_mode_post_callback(callback: CallbackQuery, state: FSMContext):
        await state.update_data(spam_mode='post')
        await ask_for_spam_targets(callback, state)

    @dp.callback_query(F.data == "spam_mode_custom")
    async def spam_mode_custom_callback(callback: CallbackQuery, state: FSMContext):
        await state.update_data(spam_mode='custom')
        await edit_message(
            callback,
            "✏️ <b>Свой текст рассылки</b>\n\n"
            "Отправьте текст сообщения. Для каждого получателя бот подставит "
            "случайные варианты — так рассылка меньше похожа на спам.\n\n"
            "<b>Синтаксис</b>\n"
            "• <code>{вариант1|вариант2|вариант3}</code> — случайный вариант\n"
            "• <code>{rand}</code> — случайный набор символов\n"
            "• вложенные скобки не поддерживаются\n\n"
            "<b>Пример</b>\n"
            "<code>{Привет|Здравствуйте|Добрый день}! {Есть минутка?|Пишу по делу.}\n"
            "Меня зовут Артём, {помогаю|занимаюсь} продвижением Telegram-каналов.\n"
            "{Если интересно|Если актуально} — напишите, {скину|пришлю} пример. "
            "#{rand}</code>\n\n"
            "<i>Из этого получится, например:</i>\n"
            "<i>«Добрый день! Пишу по делу. Меня зовут Артём, занимаюсь продвижением "
            "Telegram-каналов. Если актуально — напишите, пришлю пример. #a7Kq2p»</i>",
            reply_markup=cancel_inline_keyboard())
        await state.set_state(MassActionStates.WAITING_CUSTOM_TEXT)

    @dp.message(MassActionStates.WAITING_CUSTOM_TEXT)
    async def process_custom_spam_text(message: Message, state: FSMContext):
        text = message.html_text or message.text or message.caption or ""
        text = text.strip()
        entities_json = None
        caption_entities = message.caption_entities if message.caption_entities else (message.entities if message.entities else None)
        if caption_entities:
            entities_json = json.dumps([{
                'type': e.type,
                'offset': e.offset,
                'length': e.length,
                'custom_emoji_id': e.custom_emoji_id if hasattr(e, 'custom_emoji_id') else None,
                'language': e.language if hasattr(e, 'language') else None,
                'url': e.url if hasattr(e, 'url') else None,
            } for e in caption_entities])
        await state.update_data(custom_spam_text=text, custom_spam_entities=entities_json)
        await ask_for_spam_targets(message, state)

    @dp.callback_query(F.data.startswith('invite_chat_page_'))
    async def invite_chat_page_callback(callback: CallbackQuery, state: FSMContext):
        page = int(callback.data.split('_')[3])
        await state.update_data(invite_chat_page=page)
        await show_invite_chat_selection(callback, state)

    @dp.callback_query(F.data == "invite_custom_chat")
    async def invite_custom_chat_callback(callback: CallbackQuery, state: FSMContext):
        await edit_message(callback, "🔗 <b>Введите ID чата или ссылку:</b>\n\nНапример: -100123456789 или https://t.me/username", reply_markup=cancel_inline_keyboard())
        await state.set_state(InviteStates.WAITING_CUSTOM_CHAT)

    @dp.message(InviteStates.WAITING_CUSTOM_CHAT)
    async def process_custom_chat(message: Message, state: FSMContext):
        chat_input = message.text.strip()
        await state.update_data(invite_custom_chat=chat_input)
        await state.set_state(InviteStates.WAITING_USERS_FILE)
        await message.answer(f"✅ Чат сохранен: {chat_input}\n\nОтправьте TXT файл с пользователями (ID/@username, по одному на строку):", reply_markup=cancel_inline_keyboard())

    @dp.callback_query(F.data.startswith('invite_chat_'))
    async def invite_chat_callback(callback: CallbackQuery, state: FSMContext):
        parts = callback.data.split('_')
        account_id = int(parts[2])
        chat_id = '_'.join(parts[3:])
        await state.update_data(invite_account_id=account_id, invite_chat_id=chat_id)
        await state.set_state(InviteStates.WAITING_USERS_FILE)
        chat_title = chat_id
        for c in db.get_account_chats(account_id):
            if c['chat_id'] == chat_id:
                chat_title = c.get('chat_title') or chat_id
                break
        await edit_message(callback, f"📥 <b>Инвайтинг</b>\n\nЧат: {chat_title}\n\nОтправьте TXT файл с пользователями (ID/@username, по одному на строку):", reply_markup=cancel_inline_keyboard())

    @dp.message(InviteStates.WAITING_USERS_FILE)
    async def process_invite_users_file(message: Message, state: FSMContext):
        data = await state.get_data()
        account_ids = data.get('invite_account_ids', [data.get('invite_account_id')])
        chat_id = data.get('invite_chat_id') or data.get('invite_custom_chat')
        user_id = message.from_user.id
        
        if not chat_id or not account_ids:
            await message.answer("❌ Ошибка состояния!")
            await state.clear()
            return
        
        users = []
        if message.document:
            try:
                file = await bot.get_file(message.document.file_id)
                content = await bot.download_file(file.file_path)
                text = content.read().decode('utf-8')
                users = [l.strip() for l in text.split('\n') if l.strip()]
            except Exception as e:
                await message.answer(f"❌ Ошибка чтения файла: {e}")
                return
        elif message.text:
            users = [l.strip() for l in message.text.strip().split('\n') if l.strip()]
        
        if not users:
            await message.answer("❌ Нет пользователей в файле!")
            return
        
        await state.clear()
        
        valid_account_ids = [aid for aid in account_ids if aid]
        if not valid_account_ids:
            await message.answer("❌ Не выбраны аккаунты для инвайта!")
            return
        
        per_account = len(users) // len(valid_account_ids)
        remainder = len(users) % len(valid_account_ids)
        
        start = 0
        for idx, account_id in enumerate(valid_account_ids):
            count = per_account + (1 if idx < remainder else 0)
            chunk = users[start:start + count]
            start += count
            await message.answer(f"🚀 [{idx+1}/{len(valid_account_ids)}] Запускаю инвайт {len(chunk)} пользователей на аккаунт #{account_id}...")
            asyncio.create_task(account_manager.run_limited(account_manager.invite_users(account_id, chat_id, list(chunk), bot, user_id, auto_join=True)))
        
        await state.clear()
        await message.answer(
            "✅ Инвайт запущен в фоне. Вы получите уведомления о прогрессе и результате.",
            reply_markup=main_menu_keyboard(user_id)
        )

    @dp.callback_query(F.data == "cancel_action", StateFilter('*'))
    async def cancel_action_handler(callback: CallbackQuery, state: FSMContext):
        _stop_qr_poller(callback.from_user.id)
        if account_manager:
            account_manager.cancel_phone_auth(callback.from_user.id)
        await state.clear()
        await edit_message(callback, "❌ Действие отменено.")

    @dp.message(MassActionStates.WAITING_TARGETS)
    async def process_spam_targets(message: Message, state: FSMContext):
        data = await state.get_data()
        account_ids = data.get('spam_account_ids', [])
        user_id = message.from_user.id
        
        targets = []
        if message.document:
            try:
                file = await bot.get_file(message.document.file_id)
                content = await bot.download_file(file.file_path)
                text = content.read().decode('utf-8')
                targets = [l.strip() for l in text.split('\n') if l.strip()]
            except Exception as e:
                await message.answer(f"❌ Ошибка чтения файла: {e}")
                return
        elif message.text:
            targets = [l.strip() for l in message.text.strip().split('\n') if l.strip()]
        
        if not targets:
            await message.answer("❌ Нет целей! Отправьте файл или список.")
            return
        
        parsed_targets = []
        for t in targets:
            if t.startswith('https://t.me/'):
                username = t.split('https://t.me/')[-1].strip('/')
                if username:
                    parsed_targets.append(f"@{username}")
            elif t.startswith('@'):
                parsed_targets.append(t)
            elif t.isdigit():
                parsed_targets.append(int(t))
            else:
                parsed_targets.append(f"@{t}")
        
        if not parsed_targets:
            await message.answer("❌ Не удалось распознать цели!")
            return
        
        await _start_spam_distribution(message, state, user_id, parsed_targets, data)

    async def _start_spam_distribution(answer_to, state: FSMContext, user_id: int,
                                       parsed_targets: list, data: dict):
        """Общий запуск рассылки: и для списка целей, и для рассылки по контактам."""
        account_ids = data.get('spam_account_ids', [])
        mode = data.get('spam_mode', 'post')
        custom_text = data.get('custom_spam_text', '')
        custom_entities = data.get('custom_spam_entities', None)
        speed = data.get('spam_speed', 'normal')
        delay_min, delay_max = account_manager.SPAM_SPEEDS.get(
            speed, account_manager.SPAM_SPEEDS['normal'])

        await state.clear()
        unique_targets = list(dict.fromkeys(parsed_targets))
        if len(unique_targets) < len(parsed_targets):
            await answer_to.answer(
                f"ℹ️ Убрано дубликатов: {len(parsed_targets) - len(unique_targets)}. "
                f"Итого уникальных: {len(unique_targets)}")

        account_ids = [a for a in account_ids if a]
        if not account_ids:
            await answer_to.answer("❌ Не выбрано ни одного аккаунта.")
            return

        await answer_to.answer(
            f"🚀 Запускаю рассылку на {len(unique_targets)} уникальных целей "
            f"из {len(account_ids)} аккаунтов.\n"
            f"Пауза между сообщениями: {delay_min}–{delay_max} сек.")

        per_account = len(unique_targets) // len(account_ids)
        remainder = len(unique_targets) % len(account_ids)
        start_idx = 0
        for i, account_id in enumerate(account_ids):
            end_idx = start_idx + per_account + (1 if i < remainder else 0)
            account_targets = unique_targets[start_idx:end_idx]
            start_idx = end_idx
            if account_targets:
                asyncio.create_task(account_manager.run_limited(
                    account_manager.spam_to_users(
                        account_id, account_targets, bot, user_id,
                        mode=mode, custom_text=custom_text,
                        custom_entities=custom_entities,
                        delay_min=delay_min, delay_max=delay_max)))

        await answer_to.answer(
            "✅ Рассылка запущена в фоне. Вы получите уведомления о прогрессе и результате.",
            reply_markup=main_menu_keyboard(user_id))

    @dp.callback_query(F.data.startswith("spam_speed_"), MassActionStates.WAITING_TARGETS)
    async def spam_speed_callback(callback: CallbackQuery, state: FSMContext):
        code = callback.data.rsplit('_', 1)[-1]
        if code not in SPAM_SPEED_LABELS:
            await callback.answer("❌ Неизвестная скорость", show_alert=True)
            return
        await state.update_data(spam_speed=code)
        label, hint = SPAM_SPEED_LABELS[code]
        await callback.answer(f"{label}: {hint}", show_alert=(code == 'fast'))
        await ask_for_spam_targets(callback, state)

    @dp.callback_query(F.data == "spam_targets_contacts", MassActionStates.WAITING_TARGETS)
    async def spam_targets_contacts_callback(callback: CallbackQuery, state: FSMContext):
        """Рассылка по адресной книге выбранных аккаунтов."""
        user_id = callback.from_user.id
        data = await state.get_data()
        account_ids = [a for a in data.get('spam_account_ids', []) if a]
        if not account_ids:
            await callback.answer("❌ Сначала выберите аккаунты.", show_alert=True)
            return
        await callback.answer("📇 Собираю контакты…")
        status = await callback.message.answer("📇 Загружаю контакты аккаунтов…")

        targets, problems, per_acc = [], [], []
        for acc_id in account_ids:
            contacts, err = await account_manager.get_account_contacts(acc_id)
            acc = db.get_account(acc_id) or {}
            name = acc.get('account_name') or f"#{acc_id}"
            if err:
                problems.append(f"• {name}: {err}")
                continue
            per_acc.append(f"• {name}: {len(contacts)}")
            for c in contacts:
                targets.append(int(c['user_id']))

        if not targets:
            msg = "❌ Контакты не найдены."
            if problems:
                msg += "\n\n" + "\n".join(problems)
            await status.edit_text(msg)
            return

        report = "📇 <b>Контакты собраны</b>\n\n" + "\n".join(per_acc)
        if problems:
            report += "\n\n⚠️ Проблемы:\n" + "\n".join(problems)
        await status.edit_text(report)
        await _start_spam_distribution(callback.message, state, user_id, targets, data)

    @dp.callback_query(F.data.startswith('acc_pms_'))
    async def acc_pms_callback(callback: CallbackQuery, state: FSMContext):
        await state.clear()
        account_id = int(callback.data.split('_')[2])
        
        await callback.answer("⏳ Синхронизация...", show_alert=False)
        _, err = await account_manager.fetch_and_sync_chats(account_id)
        if err:
            await callback.answer(f"⚠️ Ошибка синхронизации: {err}", show_alert=True)
        
        per_page = 20
        total = db.get_account_private_chats_count(account_id)
        chats = db.get_account_private_chats(account_id, page=0, per_page=per_page)
        
        if not chats:
            await callback.answer("💬 Нет личных чатов!", show_alert=True)
            return
        
        buttons = []
        for chat in chats:
            title = chat.get('chat_title') or chat['chat_id']
            buttons.append([InlineKeyboardButton(text=f"💬 {title[:35]}", callback_data=f"pm_chat_{account_id}_{chat['chat_id']}")])
        
        total_pages = max(1, (total + per_page - 1) // per_page)
        nav_buttons = []
        if total_pages > 1:
            nav_buttons.append(InlineKeyboardButton(text="➡️", callback_data=f"pm_page_{account_id}_1"))
        if nav_buttons:
            buttons.append(nav_buttons)
        
        buttons.append([InlineKeyboardButton(text="🔄 Обновить", callback_data=f"acc_pms_{account_id}")])
        buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data=f"manage_acc_{account_id}")])
        markup = InlineKeyboardMarkup(inline_keyboard=buttons)
        
        text = f"💬 <b>Личные чаты</b> (стр. 1/{total_pages})\n\nВыберите чат для ответа:"
        await edit_message(callback, text, markup)

    @dp.callback_query(F.data.startswith('pm_page_'))
    async def pm_page_callback(callback: CallbackQuery):
        parts = callback.data.split('_')
        account_id = int(parts[2])
        page = int(parts[3])
        per_page = 20
        total = db.get_account_private_chats_count(account_id)
        chats = db.get_account_private_chats(account_id, page=page, per_page=per_page)
        
        if not chats:
            await callback.answer("📭 Пусто!", show_alert=True)
            return
        
        buttons = []
        for chat in chats:
            title = chat.get('chat_title') or chat['chat_id']
            buttons.append([InlineKeyboardButton(text=f"💬 {title[:35]}", callback_data=f"pm_chat_{account_id}_{chat['chat_id']}")])
        
        total_pages = max(1, (total + per_page - 1) // per_page)
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton(text="⬅️", callback_data=f"pm_page_{account_id}_{page-1}"))
        if page < total_pages - 1:
            nav_buttons.append(InlineKeyboardButton(text="➡️", callback_data=f"pm_page_{account_id}_{page+1}"))
        if nav_buttons:
            buttons.append(nav_buttons)
        
        buttons.append([InlineKeyboardButton(text="🔄 Обновить", callback_data=f"acc_pms_{account_id}")])
        buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data=f"manage_acc_{account_id}")])
        markup = InlineKeyboardMarkup(inline_keyboard=buttons)
        
        text = f"💬 <b>Личные чаты</b> (стр. {page+1}/{total_pages})\n\nВыберите чат для ответа:"
        await edit_message(callback, text, markup)

    @dp.callback_query(F.data.startswith('pm_chat_'))
    async def pm_chat_callback(callback: CallbackQuery, state: FSMContext):
        parts = callback.data.split('_')
        account_id = int(parts[2])
        chat_id = '_'.join(parts[3:])
        await state.update_data(pm_account_id=account_id, pm_chat_id=chat_id)
        await state.set_state(AccountSettingsStates.WAITING_FOR_PM_REPLY)
        
        chat_title = chat_id
        account_chats = db.get_account_chats(account_id)
        for c in account_chats:
            if c['chat_id'] == chat_id:
                chat_title = c.get('chat_title') or chat_id
                break
        
        print(f"DEBUG: Looking for chat_id={chat_id}, found title={chat_title}, total chats={len(account_chats)}")
        
        last_messages = []
        try:
            last_messages = await account_manager.get_last_private_messages(account_id, chat_id, limit=3)
            print(f"DEBUG: Got {len(last_messages)} messages for chat {chat_id}")
        except Exception as e:
            print(f"Error fetching last messages for {chat_id}: {e}")
        
        quote_text = f"💬 <b>Ответ в:</b> {chat_title}\n"
        if last_messages:
            quote_text += "\n<b>💭 Последние сообщения:</b>\n"
            for i, msg in enumerate(last_messages, 1):
                prefix = "👤" if not msg.get('out') else "🫵"
                text = msg.get('text', '') or '[медиа]'
                text = text[:100] + ('...' if len(text) > 100 else '')
                quote_text += f"\n{prefix} {text}\n"
        else:
            quote_text += "\n<i>Нет сообщений в истории</i>\n"
        quote_text += "\n✏️ <b>Отправьте сообщение</b> (текст/фото/стикер/документ/голос):"
        
        try:
            await callback.message.delete()
        except:
            pass
        
        await callback.message.answer(
            quote_text,
            reply_markup=cancel_inline_keyboard()
        )

    @dp.message(AccountSettingsStates.WAITING_FOR_PM_REPLY)
    async def process_pm_reply(message: Message, state: FSMContext):
        data = await state.get_data()
        account_id = data.get('pm_account_id')
        chat_id = data.get('pm_chat_id')
        
        if not account_id or not chat_id:
            await state.clear()
            await message.answer("❌ Ошибка состояния!")
            return
        
        account = db.get_account(account_id)
        if not account:
            await state.clear()
            await message.answer("❌ Аккаунт не найден!")
            return
        
        client, err = await account_manager.get_or_start_client(account_id)
        if not client:
            await state.clear()
            await message.answer(f"❌ Ошибка подключения: {err}")
            return
        
        target = int(chat_id) if chat_id.startswith('-') or chat_id.isdigit() else chat_id
        sent = False
        
        try:
            if message.text:
                await client.send_message(target, message.text)
                sent = True
            elif message.sticker:
                file_id = message.sticker.file_id
                file = await bot.get_file(file_id)
                download_path = os.path.join('downloads', f"{account_id}_{file_id}.tmp")
                os.makedirs('downloads', exist_ok=True)
                await bot.download_file(file.file_path, download_path)
                await client.send_sticker(target, download_path)
                sent = True
                os.remove(download_path)
            elif message.animation:
                file_id = message.animation.file_id
                file = await bot.get_file(file_id)
                download_path = os.path.join('downloads', f"{account_id}_{file_id}.tmp")
                os.makedirs('downloads', exist_ok=True)
                await bot.download_file(file.file_path, download_path)
                await client.send_animation(target, download_path)
                sent = True
                os.remove(download_path)
            elif message.photo:
                file_id = message.photo[-1].file_id
                file = await bot.get_file(file_id)
                download_path = os.path.join('downloads', f"{account_id}_{file_id}.tmp")
                os.makedirs('downloads', exist_ok=True)
                await bot.download_file(file.file_path, download_path)
                caption = message.caption or ''
                await client.send_photo(target, download_path, caption=caption)
                sent = True
                os.remove(download_path)
            elif message.video:
                file_id = message.video.file_id
                file = await bot.get_file(file_id)
                download_path = os.path.join('downloads', f"{account_id}_{file_id}.tmp")
                os.makedirs('downloads', exist_ok=True)
                await bot.download_file(file.file_path, download_path)
                caption = message.caption or ''
                await client.send_video(target, download_path, caption=caption)
                sent = True
                os.remove(download_path)
            elif message.document:
                file_id = message.document.file_id
                file = await bot.get_file(file_id)
                download_path = os.path.join('downloads', f"{account_id}_{file_id}.tmp")
                os.makedirs('downloads', exist_ok=True)
                await bot.download_file(file.file_path, download_path)
                caption = message.caption or ''
                await client.send_document(target, download_path, caption=caption)
                sent = True
                os.remove(download_path)
            elif message.audio:
                file_id = message.audio.file_id
                file = await bot.get_file(file_id)
                download_path = os.path.join('downloads', f"{account_id}_{file_id}.tmp")
                os.makedirs('downloads', exist_ok=True)
                await bot.download_file(file.file_path, download_path)
                caption = message.caption or ''
                await client.send_audio(target, download_path, caption=caption)
                sent = True
                os.remove(download_path)
            elif message.voice:
                file_id = message.voice.file_id
                file = await bot.get_file(file_id)
                download_path = os.path.join('downloads', f"{account_id}_{file_id}.tmp")
                os.makedirs('downloads', exist_ok=True)
                await bot.download_file(file.file_path, download_path)
                await client.send_voice(target, download_path)
                sent = True
                os.remove(download_path)
        except Exception as e:
            await state.clear()
            await message.answer(f"❌ Ошибка отправки: {e}")
            return
        
        await state.clear()
        if sent:
            await message.answer("✅ Сообщение отправлено!")
        else:
            await message.answer("❌ Не удалось отправить!")

    # ==================== SUBSCRIPTION & CRYPTOBOT ====================
    TARIFF_ICONS = {'trial': '🎁', 'starter': '🚀', 'pro': '💼', 'team': '🏢',
                    'enterprise': '🏆', 'starter_y': '🚀', 'pro_y': '💼', 'team_y': '🏢'}

    def _usd_to_stars(amount_usd: float) -> int:
        return max(1, int(round(amount_usd * STARS_PER_USD)))

    async def render_subscription(target, user_id: int):
        user = db.get_user(user_id)
        is_admin = (user_id == ADMIN) or (user and user.get('is_admin') == 1)
        is_sub = db.is_user_subscribed(user_id, ADMIN)
        limits = db.get_user_limits(user_id, ADMIN)
        used_accounts = db.count_user_accounts(user_id)
        ai_used = db.get_ai_usage_today(user_id)

        status_str = "🟢 Активна" if is_sub else "🔴 Не активна"
        sub_until = format_date(user.get('subscription_until', 0)) if (user and not is_admin) else "Бессрочно (Администратор)"

        text = (
            f"💳 <b>Подписка и тарифы</b>\n\n"
            f"• <b>Статус:</b> {status_str}\n"
            f"• <b>Действует до:</b> {sub_until}\n"
            f"• <b>Тариф:</b> {limits['tariff_name']}\n\n"
            f"<b>📊 Ваши лимиты</b>\n"
            f"• Аккаунтов: <b>{used_accounts}/{limits['max_accounts']}</b>\n"
            f"• AI-комментариев сегодня: <b>{ai_used}/{limits['ai_per_day']}</b>\n\n"
            f"<i>Лимиты обновляются ежедневно в 00:00 UTC.</i>"
        )

        rows = []
        if MINIAPP_ENABLED and MINIAPP_URL:
            from aiogram.types import WebAppInfo
            rows.append([InlineKeyboardButton(
                text="🛒 Открыть магазин тарифов",
                web_app=WebAppInfo(url=f"{MINIAPP_URL}?uid={user_id}")
            )])
        rows.append([InlineKeyboardButton(text="📦 Тарифные планы", callback_data="show_tariffs")])
        rows.append([InlineKeyboardButton(text="➕ Докупить слоты / AI", callback_data="show_addons")])
        rows.append([InlineKeyboardButton(text="💡 Как пополнить баланс", callback_data="howto_pay")])
        rows.append([InlineKeyboardButton(text="🎁 Ввести промокод", callback_data="enter_promo")])

        markup = InlineKeyboardMarkup(inline_keyboard=rows)
        if isinstance(target, CallbackQuery):
            await edit_message(target, text, markup)
        else:
            await send_photo(target, 'sub.jpg', text, markup)

    @dp.message(F.text == '💳 Подписка')
    async def subscription_menu(message: Message, state: FSMContext):
        await state.clear()
        await render_subscription(message, message.from_user.id)

    @dp.callback_query(F.data == "back_to_subscription")
    async def back_to_subscription_callback(callback: CallbackQuery, state: FSMContext):
        await state.clear()
        await render_subscription(callback, callback.from_user.id)

    @dp.callback_query(F.data == "show_tariffs")
    async def show_tariffs_callback(callback: CallbackQuery):
        tariffs = db.get_tariffs(active_only=True)
        tariffs = sorted(tariffs, key=lambda t: (t.get('sort_order') or 0, t.get('price_usd') or 0))
        rows, lines = [], []
        for t in tariffs:
            icon = TARIFF_ICONS.get(t.get('code', ''), '📦')
            period = "год" if (t.get('duration_days') or 0) >= 365 else f"{t.get('duration_days')} дн."
            lines.append(
                f"{icon} <b>{t['name']}</b> — ${t['price_usd']:.0f} / {period}\n"
                f"    Аккаунтов: {t.get('max_accounts', 1)} · AI/сутки: {t.get('ai_comments_per_day', 0)}"
            )
            rows.append([InlineKeyboardButton(
                text=f"{icon} {t['name']} — ${t['price_usd']:.0f}",
                callback_data=f"tariff_info_{t['id']}"
            )])
        rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_subscription")])
        await edit_message(
            callback,
            "📦 <b>Тарифные планы</b>\n\n" + "\n\n".join(lines) +
            "\n\n<i>Выберите тариф, чтобы перейти к оплате.</i>",
            InlineKeyboardMarkup(inline_keyboard=rows)
        )

    @dp.callback_query(F.data.startswith('tariff_info_'))
    async def tariff_info_callback(callback: CallbackQuery):
        tariff_id = int(callback.data.split('_')[2])
        t = db.get_tariff(tariff_id)
        if not t:
            await callback.answer("❌ Тариф не найден", show_alert=True)
            return
        price = float(t['price_usd'])
        icon = TARIFF_ICONS.get(t.get('code', ''), '📦')
        period = "1 год" if (t.get('duration_days') or 0) >= 365 else f"{t.get('duration_days')} дней"

        text = (
            f"{icon} <b>{t['name']}</b>\n\n"
            f"{t.get('description') or ''}\n\n"
            f"• <b>Цена:</b> ${price:.2f}\n"
            f"• <b>Период:</b> {period}\n"
            f"• <b>Аккаунтов:</b> {t.get('max_accounts', 1)}\n"
            f"• <b>AI-комментариев в сутки:</b> {t.get('ai_comments_per_day', 0)}\n\n"
            f"<b>Выберите способ оплаты:</b>"
        )
        rows = []
        if price > 0:
            rows.append([InlineKeyboardButton(text=f"💎 CryptoBot — ${price:.2f} USDT",
                                              callback_data=f"buy_tariff_{tariff_id}")])
            if STARS_ENABLED:
                rows.append([InlineKeyboardButton(text=f"⭐ Telegram Stars — {_usd_to_stars(price)} ⭐",
                                                  callback_data=f"buy_stars_{tariff_id}")])
        else:
            rows.append([InlineKeyboardButton(text="🎁 Активировать бесплатно",
                                              callback_data=f"activate_trial_{tariff_id}")])
        rows.append([InlineKeyboardButton(text="💡 Как пополнить", callback_data="howto_pay")])
        rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="show_tariffs")])
        await edit_message(callback, text, InlineKeyboardMarkup(inline_keyboard=rows))

    @dp.callback_query(F.data.startswith('activate_trial_'))
    async def activate_trial_callback(callback: CallbackQuery):
        tariff_id = int(callback.data.split('_')[2])
        user_id = callback.from_user.id
        t = db.get_tariff(tariff_id)
        if not t or float(t['price_usd']) > 0:
            await callback.answer("❌ Недоступно", show_alert=True)
            return
        ent = db.get_user_entitlements(user_id)
        if ent.get('tariff_code'):
            await callback.answer("🎁 Пробный период уже активировался ранее.", show_alert=True)
            return
        db.add_subscription_days(user_id, int(t['duration_days']))
        db.set_user_tariff(user_id, t.get('code') or 'trial')
        await callback.answer("🎉 Пробный доступ активирован!", show_alert=True)
        await render_subscription(callback, user_id)

    @dp.callback_query(F.data == "show_addons")
    async def show_addons_callback(callback: CallbackQuery):
        text = (
            "➕ <b>Дополнительные пакеты</b>\n\n"
            f"🔹 <b>Слот аккаунта</b> — ${db.ADDON_ACCOUNT_SLOT_USD:.0f}/мес\n"
            "   +1 аккаунт сверх лимита тарифа\n\n"
            f"🔹 <b>AI-пакет</b> — ${db.ADDON_AI_PACK_USD:.0f}\n"
            f"   +{db.ADDON_AI_PACK_SIZE} комментариев в сутки на 30 дней\n\n"
            f"🔥 <b>Прогрев аккаунта</b> — ${db.ADDON_WARMUP_USD:.0f} за аккаунт\n"
            "   Автоматический warmup новой сессии: имитация живой активности,\n"
            "   постепенный выход на рабочую нагрузку. Снижает риск блокировки.\n\n"
            "<i>Для покупки выберите пакет — оплата через CryptoBot или Stars.</i>"
        )
        rows = [
            [InlineKeyboardButton(text=f"🔹 +1 слот аккаунта — ${db.ADDON_ACCOUNT_SLOT_USD:.0f}",
                                  callback_data="addon_slot")],
            [InlineKeyboardButton(text=f"🔹 AI-пакет {db.ADDON_AI_PACK_SIZE} — ${db.ADDON_AI_PACK_USD:.0f}",
                                  callback_data="addon_ai")],
            [InlineKeyboardButton(text=f"🔥 Прогрев аккаунта — ${db.ADDON_WARMUP_USD:.0f}",
                                  callback_data="addon_warmup")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_subscription")]
        ]
        await edit_message(callback, text, InlineKeyboardMarkup(inline_keyboard=rows))

    @dp.callback_query(F.data.startswith('addon_'))
    async def addon_callback(callback: CallbackQuery):
        kind = callback.data.split('_', 1)[1]
        if kind == 'warmup':
            await callback.answer(
                "🔥 Прогрев аккаунтов скоро будет доступен. "
                f"Напишите в поддержку {SUPPORT_CONTACT} для ручного подключения.",
                show_alert=True
            )
            return
        await callback.answer(
            f"Для покупки пакета напишите в поддержку {SUPPORT_CONTACT}. "
            "Автооплата пакетов появится в ближайшем обновлении.",
            show_alert=True
        )

    @dp.callback_query(F.data == "howto_pay")
    async def howto_pay_callback(callback: CallbackQuery):
        text = (
            "💡 <b>Как оплатить подписку</b>\n\n"
            "<b>Способ 1. Telegram Stars</b> ⭐ <i>(быстро, прямо в Telegram)</i>\n"
            "1. Выберите тариф и нажмите «⭐ Telegram Stars».\n"
            "2. Подтвердите оплату во всплывающем окне Telegram.\n"
            "3. Подписка активируется <b>мгновенно</b>.\n"
            "Звёзды пополняются в Telegram: <b>Настройки → Мои звёзды → Пополнить</b> "
            "(картой или через Apple/Google Pay).\n\n"
            "<b>Способ 2. Криптовалюта через @CryptoBot</b> 💎\n"
            "1. Откройте @CryptoBot и пополните баланс USDT:\n"
            "   • «Кошелёк» → «Пополнить» → выберите USDT;\n"
            "   • переведите средства с биржи (Binance, Bybit, OKX) или другого кошелька;\n"
            "   • сеть TRC-20 обычно дешевле по комиссии.\n"
            "2. Вернитесь сюда, выберите тариф и нажмите «💎 CryptoBot».\n"
            "3. Оплатите счёт и нажмите «Проверить оплату».\n\n"
            "<b>Способ 3. Промокод</b> 🎁\n"
            "Если у вас есть промокод — нажмите «🎁 Ввести промокод».\n\n"
            f"❓ Возникли сложности? Напишите в поддержку: {SUPPORT_CONTACT}"
        )
        rows = [[InlineKeyboardButton(text="📦 К тарифам", callback_data="show_tariffs")],
                [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_subscription")]]
        await edit_message(callback, text, InlineKeyboardMarkup(inline_keyboard=rows))

    @dp.callback_query(F.data.startswith('buy_stars_'))
    async def buy_stars_callback(callback: CallbackQuery):
        """Оплата через Telegram Stars (XTR) — нативный инвойс Telegram."""
        if not STARS_ENABLED:
            await callback.answer("⭐ Оплата звёздами отключена", show_alert=True)
            return
        tariff_id = int(callback.data.split('_')[2])
        t = db.get_tariff(tariff_id)
        if not t:
            await callback.answer("❌ Тариф не найден", show_alert=True)
            return
        stars = _usd_to_stars(float(t['price_usd']))
        from aiogram.types import LabeledPrice
        try:
            await bot.send_invoice(
                chat_id=callback.from_user.id,
                title=f"Подписка {t['name']}",
                description=(
                    f"{t.get('description') or 'Доступ к PostDrive'}. "
                    f"Аккаунтов: {t.get('max_accounts', 1)}, AI/сутки: {t.get('ai_comments_per_day', 0)}."
                ),
                payload=f"tariff:{tariff_id}",
                currency="XTR",                       # Telegram Stars
                prices=[LabeledPrice(label=t['name'], amount=stars)],
                provider_token="",                    # для XTR токен не нужен
                start_parameter="postdrive-sub"
            )
            await callback.answer("⭐ Счёт отправлен")
        except Exception as e:
            logger.error(f"Stars invoice failed: {e}")
            await callback.answer(f"❌ Не удалось создать счёт: {str(e)[:150]}", show_alert=True)

    @dp.pre_checkout_query()
    async def stars_pre_checkout(pre_checkout_query):
        """Telegram требует ответить на pre_checkout в течение 10 секунд."""
        try:
            await pre_checkout_query.answer(ok=True)
        except Exception as e:
            logger.error(f"pre_checkout failed: {e}")

    @dp.message(F.successful_payment)
    async def stars_successful_payment(message: Message):
        """Звёзды оплачены — начисляем подписку и партнёрскую комиссию."""
        sp = message.successful_payment
        user_id = message.from_user.id
        payload = sp.invoice_payload or ''
        if not payload.startswith('tariff:'):
            return
        try:
            tariff_id = int(payload.split(':')[1])
        except (IndexError, ValueError):
            return
        t = db.get_tariff(tariff_id)
        if not t:
            await message.answer("⚠️ Платёж получен, но тариф не найден. Напишите в поддержку.")
            return

        db.add_subscription_days(user_id, int(t['duration_days']))
        if t.get('code'):
            db.set_user_tariff(user_id, t['code'])

        # Партнёрская комиссия: 30% с первого платежа
        try:
            partner = db.get_partner_by_referral_user(user_id)
            if partner:
                commission = float(t['price_usd']) * 0.30
                db.add_partner_earning(partner['user_id'], commission,
                                       f"Комиссия 30% (Stars) от реферала {user_id}")
                await bot.send_message(
                    partner['user_id'],
                    f"💰 <b>Партнёрское вознаграждение!</b>\n\nНачислено: <b>${commission:.2f}</b>"
                )
        except Exception as e:
            logger.error(f"partner commission (stars) failed: {e}")

        user = db.get_user(user_id)
        await message.answer(
            f"🎉 <b>Оплата прошла успешно!</b>\n\n"
            f"Тариф: <b>{t['name']}</b>\n"
            f"Списано: <b>{sp.total_amount} ⭐</b>\n"
            f"Подписка активна до: <b>{format_date(user.get('subscription_until', 0))}</b>",
            reply_markup=main_menu_keyboard(user_id, admin_id=ADMIN)
        )

    @dp.callback_query(F.data == "enter_promo")
    async def enter_promo_callback(callback: CallbackQuery, state: FSMContext):
        await state.set_state(PromoStates.WAITING_PROMO_CODE)
        await edit_message(callback, "🎁 <b>Введите промокод:</b>", reply_markup=cancel_inline_keyboard())

    @dp.message(PromoStates.WAITING_PROMO_CODE)
    async def process_promo_code(message: Message, state: FSMContext):
        code = message.text.strip().upper()
        promo = db.get_promo_code(code)
        if not promo:
            await message.answer("❌ Промокод не найден!")
            return
        if promo['is_active'] != 1:
            await message.answer("❌ Промокод деактивирован!")
            return
        if promo['used_count'] >= promo['max_uses']:
            await message.answer("❌ Промокод закончился!")
            return
        if db.use_promo_code(code, message.from_user.id):
            await state.clear()
            await message.answer(f"✅ Промокод активирован!\n\n🎁 +{promo['days']} дней подписки")
        else:
            await message.answer("❌ Не удалось активировать промокод!")

    @dp.callback_query(F.data.startswith('buy_tariff_'))
    async def buy_tariff_callback(callback: CallbackQuery):
        tariff_id = int(callback.data.split('_')[2])
        tariff = db.get_tariff(tariff_id)
        if not tariff:
            await callback.answer("❌ Тариф не найден!", show_alert=True)
            return

        user_id = callback.from_user.id
        amount = tariff['price_usd']
        description = f"Подписка '{tariff['name']}' на {tariff['duration_days']} дн. в Autoposter Bot"

        token_to_use = db.get_kv("cryptobot_token", CRYPTO_BOT_TOKEN)
        if not token_to_use:
            await edit_message(callback, "⚠️ Оплата временно недоступна.")
            return

        client = CryptoBotClient(token_to_use, testnet=TESTNET)
        inv = await client.create_invoice(amount=amount, asset="USDT", description=description, payload=f"{user_id}:{tariff_id}")

        if not inv:
            await edit_message(callback, "❌ Ошибка создания счёта на оплату. Попробуйте позже.")
            return

        invoice_id = inv['invoice_id']
        pay_url = inv.get('pay_url') or inv.get('bot_invoice_url')
        db.create_invoice_record(invoice_id, user_id, tariff_id, amount, "USDT", pay_url)

        buttons = [
            [InlineKeyboardButton(text=f"💳 Оплатить ${amount:.2f} USDT", url=pay_url)],
            [InlineKeyboardButton(text="🔄 Проверить оплату", callback_data=f"check_pay_{invoice_id}")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_tariffs")]
        ]
        markup = InlineKeyboardMarkup(inline_keyboard=buttons)
        await edit_message(callback, 
            f"🧾 <b>Счёт на оплату #{invoice_id}</b>\n\n"
            f"• <b>Тариф:</b> {tariff['name']} ({tariff['duration_days']} дн.)\n"
            f"• <b>Сумма к оплате:</b> <code>{amount:.2f} USDT</code>\n\n"
            f"1. Нажмите <b>Оплатить</b> и завершите перевод в @CryptoBot.\n"
            f"2. После оплаты нажмите <b>Проверить оплату</b>.",
            reply_markup=markup
        )

    @dp.callback_query(F.data.startswith('check_pay_'))
    async def check_payment_callback(callback: CallbackQuery):
        invoice_id = int(callback.data.split('_')[2])
        token_to_use = db.get_kv("cryptobot_token", CRYPTO_BOT_TOKEN)
        client = CryptoBotClient(token_to_use, testnet=TESTNET)

        is_paid = await client.check_invoice_paid(invoice_id)
        if is_paid:
            invoice = db.get_invoice(invoice_id)
            was_already_paid = invoice and invoice['status'] == 'paid'

            db.mark_invoice_paid(invoice_id)
            user = db.get_user(callback.from_user.id)
            sub_until = format_date(user.get('subscription_until', 0))

            if not was_already_paid and invoice:
                partner = db.get_partner_by_referral_user(callback.from_user.id)
                if partner:
                    commission = invoice['amount'] * 0.30
                    db.add_partner_earning(partner['user_id'], commission, f"Комиссия 30% от оплаты рефералом {callback.from_user.id}")
                    try:
                        await bot.send_message(partner['user_id'], f"💰 <b>Партнёрское вознаграждение!</b>\n\nВаш реферал оплатил подписку.\nНачислено: <b>${commission:.2f}</b>")
                    except:
                        pass

            await edit_message(callback, f"🎉 <b>Оплата успешно подтверждена!</b>\n\n✅ Ваша подписка активна до: <b>{sub_until}</b>")
        else:
            await callback.answer("⏳ Оплата ещё не поступила.", show_alert=True)

    @dp.callback_query(F.data == "back_to_tariffs")
    async def back_to_tariffs_callback(callback: CallbackQuery):
        tariffs = db.get_tariffs(active_only=True)
        buttons = [[InlineKeyboardButton(text=f"🛒 {t['name']} — ${t['price_usd']:.2f} (USDT)", callback_data=f"buy_tariff_{t['id']}")] for t in tariffs]
        markup = InlineKeyboardMarkup(inline_keyboard=buttons)
        await edit_message(callback, "<b>Доступные тарифные планы:</b>", reply_markup=markup)


    # ==================== ACCOUNTS MANAGEMENT ====================
    @dp.message(F.text == '➕ Добавить аккаунт' or F.text == '📱 Мои аккаунты')
    async def my_accounts_handler(message: Message, state: FSMContext):
        await state.clear()
        user_id = message.from_user.id
        if not db.is_user_subscribed(user_id, ADMIN):
            await message.answer("🔒 Для использования аккаунтов требуется активная подписка.")
            return

        accounts = db.get_user_accounts(user_id)
        buttons = []
        warned = 0
        for acc in accounts:
            spam_icon = "🚀 Спамит" if account_manager and account_manager.is_account_spamming(acc['id']) else "⏹ Стоит"
            status_icon = "🟢" if acc['status'] == 'active' else "🔴"
            health = (acc.get('health') or 'ok')
            if health == 'cooldown':
                status_icon, spam_icon, warned = "⏳", "Пауза (FloodWait)", warned + 1
            elif health == 'restricted':
                status_icon, spam_icon, warned = "⚠️", "Ограничен Telegram", warned + 1
            elif health == 'banned':
                status_icon, spam_icon, warned = "🚫", "Сессия недействительна", warned + 1
            name = acc.get('account_name') or f"Аккаунт #{acc['id']}"
            phone = f"({acc['phone']})" if acc.get('phone') else ""
            buttons.append([InlineKeyboardButton(text=f"{status_icon} {name} {phone} | {spam_icon}", callback_data=f"manage_acc_{acc['id']}")])

        buttons.append([InlineKeyboardButton(text="➕ Добавить аккаунт", style="success", callback_data="add_account_start")])
        markup = InlineKeyboardMarkup(inline_keyboard=buttons)
        _title = f"📱 <b>Ваши аккаунты:</b> ({len(accounts)})"
        if warned:
            _title += f"\n\n⚠️ Требуют внимания: {warned}. Откройте аккаунт, чтобы увидеть причину."
        await send_photo(message, 'acc.jpg', _title, markup)

    @dp.callback_query(F.data == "add_account_start")
    async def add_account_start_callback(callback: CallbackQuery, state: FSMContext):
        user_id = callback.from_user.id
        if not db.is_user_subscribed(user_id, ADMIN):
            await callback.answer("🔒 Требуется активная подписка!", show_alert=True)
            return
        allowed, reason, limits = db.can_add_account(user_id, ADMIN)
        if not allowed:
            await callback.answer(
                f"🚫 {reason}\n\nПовысьте тариф или докупите слот в разделе «💳 Подписка».",
                show_alert=True
            )
            return
        await state.set_state(AddAccountStates.WAITING_PROXY)
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➡️ Пропустить (без прокси)", callback_data="skip_proxy")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_action")]
        ])
        await edit_message(callback, "🌐 <b>Шаг 1: Настройка Прокси</b>\n\nОтправьте данные прокси:\n• <code>ip:port:user:pass</code>\n• <code>socks5://user:pass@ip:port</code>\n• <code>http://user:pass@ip:port</code>\n• <code>ip:port</code>\n\n<i>Или нажмите «Пропустить», если хотите подключить напрямую.</i>", reply_markup=markup)

    @dp.callback_query(F.data == "skip_proxy", AddAccountStates.WAITING_PROXY)
    async def skip_proxy_callback(callback: CallbackQuery, state: FSMContext):
        await state.update_data(proxy="")
        await show_auth_method_selection(callback, state)

    @dp.message(AddAccountStates.WAITING_PROXY)
    async def process_account_proxy(message: Message, state: FSMContext):
        proxy_str = message.text.strip()
        parsed = parse_proxy_string(proxy_str)
        if not parsed:
            await message.answer("❌ Неверный формат прокси!")
            return
        await state.update_data(proxy=proxy_str)
        await show_auth_method_selection(message, state)

    async def show_auth_method_selection(target_msg, state: FSMContext):
        await state.set_state(AddAccountStates.WAITING_METHOD)
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📱 Вход по номеру телефона", callback_data="auth_phone")],
            [InlineKeyboardButton(text="📄 Вход по String Session", callback_data="auth_string_session")],
            [InlineKeyboardButton(text="🔳 Вход по QR-коду", callback_data="auth_qr")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_action")]
        ])
        text = "🔑 <b>Шаг 2: Выберите способ авторизации:</b>"
        if isinstance(target_msg, CallbackQuery):
            await edit_message(target_msg, text, markup)
        else:
            try:
                await target_msg.edit_caption(text, reply_markup=markup)
            except:
                try:
                    await target_msg.edit_text(text, reply_markup=markup)
                except:
                    await target_msg.answer(text, reply_markup=markup)

    @dp.callback_query(F.data == "auth_phone", AddAccountStates.WAITING_METHOD)
    async def auth_phone_callback(callback: CallbackQuery, state: FSMContext):
        await state.set_state(AddAccountStates.WAITING_PHONE)
        await edit_message(callback, "📱 Введите номер телефона:", reply_markup=cancel_inline_keyboard())

    @dp.message(AddAccountStates.WAITING_PHONE)
    async def process_auth_phone(message: Message, state: FSMContext):
        phone = message.text.strip().replace(" ", "").replace("-", "")
        data = await state.get_data()
        proxy_str = data.get('proxy', '')
        status_msg = await message.answer("⏳ Отправка кода...")
        success, phone_code_hash, err = await account_manager.start_phone_auth(message.from_user.id, phone, proxy_str)
        if not success:
            await status_msg.edit_text(f"❌ Ошибка: {err}")
            return
        await state.update_data(phone=phone)
        await state.set_state(AddAccountStates.WAITING_CODE)
        await status_msg.edit_text(f"📩 Код отправлен на {phone}!\nВведите код:", reply_markup=cancel_inline_keyboard())

    @dp.message(AddAccountStates.WAITING_CODE)
    async def process_auth_code(message: Message, state: FSMContext):
        code = message.text.strip().replace(" ", "").replace("-", "")
        user_id = message.from_user.id
        data = await state.get_data()
        proxy_str = data.get('proxy', '')
        phone = data.get('phone', '')
        status_msg = await message.answer("⏳ Проверка кода...")
        success, session_str, info, is_2fa, err = await account_manager.submit_phone_code(user_id, code)
        if is_2fa:
            await state.set_state(AddAccountStates.WAITING_2FA)
            await status_msg.edit_text("🔐 Требуется пароль 2FA:", reply_markup=cancel_inline_keyboard())
            return
        if not success:
            await status_msg.edit_text(f"❌ Ошибка: {err}")
            return
        acc_name = f"{info['first_name']} {info['last_name']}".strip() or info['username'] or phone
        _allowed, _reason, _ = db.can_add_account(user_id, ADMIN)
        if not _allowed:
            await message.answer(f"🚫 {_reason}\n\nПовысьте тариф в «💳 Подписка».")
            await state.clear()
            return
        db.add_account(user_id, session_str, phone=phone, account_name=acc_name, proxy=proxy_str)
        await state.clear()
        await status_msg.edit_text(f"✅ Аккаунт {acc_name} подключен!")

    @dp.message(AddAccountStates.WAITING_2FA)
    async def process_auth_2fa(message: Message, state: FSMContext):
        password = message.text.strip()
        user_id = message.from_user.id
        data = await state.get_data()
        proxy_str = data.get('proxy', '')
        phone = data.get('phone', '')
        status_msg = await message.answer("⏳ Проверка пароля...")
        success, session_str, info, err = await account_manager.submit_2fa_password(user_id, password)
        if not success:
            await status_msg.edit_text(f"❌ Неверный пароль: {err}")
            return
        acc_name = f"{info['first_name']} {info['last_name']}".strip() or info['username'] or phone
        _allowed, _reason, _ = db.can_add_account(user_id, ADMIN)
        if not _allowed:
            await message.answer(f"🚫 {_reason}\n\nПовысьте тариф в «💳 Подписка».")
            await state.clear()
            return
        db.add_account(user_id, session_str, phone=phone, account_name=acc_name, proxy=proxy_str)
        await state.clear()
        await status_msg.edit_text(f"✅ Аккаунт {acc_name} подключен!")

    @dp.callback_query(F.data == "auth_string_session", AddAccountStates.WAITING_METHOD)
    async def auth_string_session_callback(callback: CallbackQuery, state: FSMContext):
        await state.set_state(AddAccountStates.WAITING_SESSION_STRING)
        await edit_message(callback, "📄 Отправьте String Session:", reply_markup=cancel_inline_keyboard())

    @dp.message(AddAccountStates.WAITING_SESSION_STRING)
    async def process_auth_string_session(message: Message, state: FSMContext):
        session_str = message.text.strip()
        data = await state.get_data()
        proxy_str = data.get('proxy', '')
        user_id = message.from_user.id
        status_msg = await message.answer("⏳ Проверка сессии...")
        ok, info, err = await account_manager.test_session_string(session_str, proxy_str)
        if not ok:
            await status_msg.edit_text(f"❌ Недействительная сессия: {err}")
            return
        acc_name = f"{info['first_name']} {info['last_name']}".strip() or info['username'] or "User"
        phone = info.get('phone', '')
        _allowed, _reason, _ = db.can_add_account(user_id, ADMIN)
        if not _allowed:
            await message.answer(f"🚫 {_reason}\n\nПовысьте тариф в «💳 Подписка».")
            await state.clear()
            return
        db.add_account(user_id, session_str, phone=phone, account_name=acc_name, proxy=proxy_str)
        await state.clear()
        await status_msg.edit_text(f"✅ Аккаунт {acc_name} подключен!")

    # Активные опросы QR-входа: user_id -> asyncio.Task.
    # Раньше опрос стартовал ТОЛЬКО по кнопке «Я отсканировал». Пользователь
    # сканировал код, клиент-бот никогда не вызывал ImportLoginToken, и в
    # Telegram сессия оставалась в «незавершённых попытках входа», а бот молчал.
    qr_pollers: Dict[int, asyncio.Task] = {}

    def _stop_qr_poller(user_id: int):
        task = qr_pollers.pop(user_id, None)
        if task and not task.done():
            task.cancel()

    async def _qr_poll(user_id: int, proxy_str: str, state: FSMContext,
                       photo_msg, status_msg):
        """Опрашивает Telegram до подтверждения входа и доводит аккаунт до БД."""
        try:
            async for update_msg, is_final in account_manager.finish_qr_login_stream(
                    user_id, proxy_str, bot):
                if not is_final:
                    # Обновлённый QR (токен живёт ~30 секунд) — перерисовываем картинку
                    try:
                        await photo_msg.edit_media(media=InputMediaPhoto(
                            media=BufferedInputFile(update_msg['qr_bytes'], filename='qr.png'),
                            caption="🔲 Отсканируйте QR-код в Telegram: Настройки → Устройства → Подключить устройство"))
                    except Exception:
                        pass
                    continue

                success, session_str, info, err = update_msg
                if not success:
                    if err and ("2FA" in str(err) or "пароль" in str(err).lower()):
                        await status_msg.edit_text("🔐 Требуется пароль 2FA (Cloud Password). Введите его:")
                        await state.set_state(AddAccountStates.WAITING_QR_2FA)
                        await state.update_data(qr_proxy=proxy_str)
                        return
                    await status_msg.edit_text(f"❌ Ошибка: {err}")
                    await state.clear()
                    return

                acc_name = f"{info.get('first_name', '')} {info.get('last_name', '')}".strip() \
                    or info.get('username') or f"ID:{info.get('id')}"
                _allowed, _reason, _ = db.can_add_account(user_id, ADMIN)
                if not _allowed:
                    await status_msg.edit_text(f"🚫 {_reason}\n\nПовысьте тариф в «💳 Подписка».")
                    await state.clear()
                    return
                db.add_account(user_id, session_str, phone=info.get('phone', ''),
                               account_name=acc_name, proxy=proxy_str)
                await state.clear()
                await status_msg.edit_text(f"✅ Аккаунт {acc_name} подключен через QR!")
                return
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"QR poll error for {user_id}: {type(e).__name__}: {e}")
            try:
                await status_msg.edit_text(f"❌ Ошибка QR-входа: {str(e)[:200]}")
            except Exception:
                pass
        finally:
            qr_pollers.pop(user_id, None)

    @dp.callback_query(F.data == "auth_qr", AddAccountStates.WAITING_METHOD)
    async def auth_qr_callback(callback: CallbackQuery, state: FSMContext):
        user_id = callback.from_user.id
        _stop_qr_poller(user_id)
        account_manager.cancel_phone_auth(user_id)     # закрываем прошлую временную сессию
        await state.set_state(AddAccountStates.WAITING_QR_SCAN)
        await edit_message(callback,
            "🔳 <b>Вход по QR-коду</b>\n\n"
            "1. Откройте Telegram → Настройки → Устройства → «Подключить устройство».\n"
            "2. Отсканируйте QR-код из следующего сообщения.\n"
            "3. Больше ничего нажимать не нужно — бот сам завершит вход.\n\n"
            "<i>Код обновляется автоматически, сканируйте самый свежий.</i>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Проверить вход", callback_data="qr_scanned")],
                [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_action")]
            ])
        )
        data = await state.get_data()
        proxy_str = data.get('proxy', '')
        qr_result = await account_manager.start_qr_login(user_id, proxy_str)
        if not qr_result or qr_result.get('error'):
            err = qr_result.get('error') if isinstance(qr_result, dict) else qr_result
            await callback.message.answer(f"❌ Ошибка запуска QR-входа: {err}")
            return

        photo_msg = None
        if qr_result.get('qr_bytes'):
            try:
                photo_msg = await callback.message.answer_photo(
                    BufferedInputFile(qr_result['qr_bytes'], filename='qr.png'),
                    caption="🔲 Отсканируйте QR-код в Telegram: Настройки → Устройства → Подключить устройство")
            except Exception as e:
                logger.error(f"❌ Ошибка отправки QR-фото: {e}")
        if photo_msg is None:
            if qr_result.get('qr_text'):
                photo_msg = await callback.message.answer(f"🔲 Ссылка для входа: {qr_result['qr_text']}")
            else:
                await callback.message.answer("⚠️ Не удалось отправить QR-код. Попробуйте ещё раз.")
                return

        status_msg = await callback.message.answer(
            "⏳ Жду сканирования QR-кода… Подтвердите вход в приложении Telegram.")
        # ⭐ Опрос стартует сразу: как только код отсканирован, вход завершится сам
        qr_pollers[user_id] = asyncio.create_task(
            _qr_poll(user_id, proxy_str, state, photo_msg, status_msg))

    # Без фильтра по состоянию: если FSM потерялся (перезапуск бота), кнопка
    # раньше просто проваливалась в пустоту — «на этапе бота тишина».
    @dp.callback_query(F.data == "qr_scanned")
    async def qr_scanned_callback(callback: CallbackQuery, state: FSMContext):
        user_id = callback.from_user.id
        task = qr_pollers.get(user_id)
        if task and not task.done():
            await callback.answer("⏳ Уже проверяю вход, подождите — ничего нажимать не нужно.",
                                  show_alert=True)
            return
        if user_id not in account_manager.temp_auth_clients:
            await callback.answer("⌛ QR-сессия истекла. Запустите добавление аккаунта заново.",
                                  show_alert=True)
            return
        data = await state.get_data()
        proxy_str = data.get('proxy', '')
        status_msg = await callback.message.answer("⏳ Проверяю подтверждение входа…")
        await callback.answer()
        qr_pollers[user_id] = asyncio.create_task(
            _qr_poll(user_id, proxy_str, state, callback.message, status_msg))

    @dp.message(AddAccountStates.WAITING_QR_2FA)
    async def process_qr_2fa(message: Message, state: FSMContext):
        password = message.text.strip()
        user_id = message.from_user.id
        data = await state.get_data()
        proxy_str = data.get('qr_proxy', '')
        status_msg = await message.answer("⏳ Проверка пароля 2FA...")
        success, session_str, info, err = await account_manager.submit_qr_2fa_password(user_id, password)
        if not success:
            await status_msg.edit_text(f"❌ Ошибка: {err}")
            return
        acc_name = f"{info.get('first_name', '')} {info.get('last_name', '')}".strip() or info.get('username') or f"ID:{info.get('id')}"
        _allowed, _reason, _ = db.can_add_account(user_id, ADMIN)
        if not _allowed:
            await message.answer(f"🚫 {_reason}\n\nПовысьте тариф в «💳 Подписка».")
            await state.clear()
            return
        db.add_account(user_id, session_str, phone=info.get('phone', ''), account_name=acc_name, proxy=proxy_str)
        await state.clear()
        await status_msg.edit_text(f"✅ Аккаунт {acc_name} подложен через QR!")



    # ==================== ACCOUNTS MANAGEMENT ====================
    @dp.message(F.text == '🚀 Автопостинг')
    async def my_accounts_handler(message: Message, state: FSMContext):
        await state.clear()
        user_id = message.from_user.id
        if not db.is_user_subscribed(user_id, ADMIN):
            await message.answer("🔒 Для использования аккаунтов требуется активная подписка.")
            return

        accounts = db.get_user_accounts(user_id)
        buttons = []
        for acc in accounts:
            spam_icon = "🚀 Спамит" if account_manager and account_manager.is_account_spamming(acc['id']) else "⏹ Стоит"
            status_icon = "🟢" if acc['status'] == 'active' else "🔴"
            name = acc.get('account_name') or f"Аккаунт #{acc['id']}"
            phone = f"({acc['phone']})" if acc.get('phone') else ""
            buttons.append([InlineKeyboardButton(text=f"{status_icon} {name} {phone} | {spam_icon}", callback_data=f"manage_acc_{acc['id']}")])

        buttons.append([InlineKeyboardButton(text="➕ Добавить аккаунт", style="success", callback_data="add_account_start")])
        markup = InlineKeyboardMarkup(inline_keyboard=buttons)
        await send_photo(message, 'acc.jpg', f"📱 <b>Ваши аккаунты:</b> ({len(accounts)})", markup)

    @dp.callback_query(F.data == "add_account_start")
    async def add_account_start_callback(callback: CallbackQuery, state: FSMContext):
        user_id = callback.from_user.id
        if not db.is_user_subscribed(user_id, ADMIN):
            await callback.answer("🔒 Требуется активная подписка!", show_alert=True)
            return
        allowed, reason, limits = db.can_add_account(user_id, ADMIN)
        if not allowed:
            await callback.answer(
                f"🚫 {reason}\n\nПовысьте тариф или докупите слот в разделе «💳 Подписка».",
                show_alert=True
            )
            return
        await state.set_state(AddAccountStates.WAITING_PROXY)
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➡️ Пропустить (без прокси)", callback_data="skip_proxy")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_action")]
        ])
        await edit_message(callback, "🌐 <b>Шаг 1: Настройка Прокси</b>\n\nОтправьте данные прокси:", reply_markup=markup)

    @dp.callback_query(F.data == "skip_proxy", AddAccountStates.WAITING_PROXY)
    async def skip_proxy_callback(callback: CallbackQuery, state: FSMContext):
        await state.update_data(proxy="")
        await show_auth_method_selection(callback, state)

    @dp.message(AddAccountStates.WAITING_PROXY)
    async def process_account_proxy(message: Message, state: FSMContext):
        proxy_str = message.text.strip()
        parsed = parse_proxy_string(proxy_str)
        if not parsed:
            await message.answer("❌ Неверный формат прокси!")
            return
        await state.update_data(proxy=proxy_str)
        await show_auth_method_selection(message, state)

    async def show_auth_method_selection(target_msg, state: FSMContext):
        await state.set_state(AddAccountStates.WAITING_METHOD)
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📱 Вход по номеру телефона", callback_data="auth_phone")],
            [InlineKeyboardButton(text="📄 Вход по String Session", callback_data="auth_string_session")],
            [InlineKeyboardButton(text="🔳 Вход по QR-коду", callback_data="auth_qr")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_action")]
        ])
        text = "🔑 <b>Шаг 2: Выберите способ авторизации:</b>"
        if isinstance(target_msg, CallbackQuery):
            await edit_message(target_msg, text, markup)
        else:
            try:
                await target_msg.edit_caption(text, reply_markup=markup)
            except:
                try:
                    await target_msg.edit_text(text, reply_markup=markup)
                except:
                    await target_msg.answer(text, reply_markup=markup)

    @dp.callback_query(F.data == "auth_phone", AddAccountStates.WAITING_METHOD)
    async def auth_phone_callback(callback: CallbackQuery, state: FSMContext):
        await state.set_state(AddAccountStates.WAITING_PHONE)
        await edit_message(callback, "📱 Введите номер телефона:", reply_markup=cancel_inline_keyboard())

    @dp.message(AddAccountStates.WAITING_PHONE)
    async def process_auth_phone(message: Message, state: FSMContext):
        phone = message.text.strip().replace(" ", "").replace("-", "")
        data = await state.get_data()
        proxy_str = data.get('proxy', '')
        status_msg = await message.answer("⏳ Отправка кода...")
        success, phone_code_hash, err = await account_manager.start_phone_auth(message.from_user.id, phone, proxy_str)
        if not success:
            await status_msg.edit_text(f"❌ Ошибка: {err}")
            return
        await state.update_data(phone=phone)
        await state.set_state(AddAccountStates.WAITING_CODE)
        await status_msg.edit_text(f"📩 Код отправлен на {phone}!\nВведите код:", reply_markup=cancel_inline_keyboard())

    @dp.message(AddAccountStates.WAITING_CODE)
    async def process_auth_code(message: Message, state: FSMContext):
        code = message.text.strip().replace(" ", "").replace("-", "")
        user_id = message.from_user.id
        data = await state.get_data()
        proxy_str = data.get('proxy', '')
        phone = data.get('phone', '')
        status_msg = await message.answer("⏳ Проверка кода...")
        success, session_str, info, is_2fa, err = await account_manager.submit_phone_code(user_id, code)
        if is_2fa:
            await state.set_state(AddAccountStates.WAITING_2FA)
            await status_msg.edit_text("🔐 Требуется пароль 2FA:", reply_markup=cancel_inline_keyboard())
            return
        if not success:
            await status_msg.edit_text(f"❌ Ошибка: {err}")
            return
        acc_name = f"{info['first_name']} {info['last_name']}".strip() or info['username'] or phone
        _allowed, _reason, _ = db.can_add_account(user_id, ADMIN)
        if not _allowed:
            await message.answer(f"🚫 {_reason}\n\nПовысьте тариф в «💳 Подписка».")
            await state.clear()
            return
        db.add_account(user_id, session_str, phone=phone, account_name=acc_name, proxy=proxy_str)
        await state.clear()
        await status_msg.edit_text(f"✅ Аккаунт {acc_name} подключен!")

    @dp.message(AddAccountStates.WAITING_2FA)
    async def process_auth_2fa(message: Message, state: FSMContext):
        password = message.text.strip()
        user_id = message.from_user.id
        data = await state.get_data()
        proxy_str = data.get('proxy', '')
        phone = data.get('phone', '')
        status_msg = await message.answer("⏳ Проверка пароля...")
        success, session_str, info, err = await account_manager.submit_2fa_password(user_id, password)
        if not success:
            await status_msg.edit_text(f"❌ Неверный пароль: {err}")
            return
        acc_name = f"{info['first_name']} {info['last_name']}".strip() or info['username'] or phone
        _allowed, _reason, _ = db.can_add_account(user_id, ADMIN)
        if not _allowed:
            await message.answer(f"🚫 {_reason}\n\nПовысьте тариф в «💳 Подписка».")
            await state.clear()
            return
        db.add_account(user_id, session_str, phone=phone, account_name=acc_name, proxy=proxy_str)
        await state.clear()
        await status_msg.edit_text(f"✅ Аккаунт {acc_name} подключен!")

    @dp.callback_query(F.data == "auth_string_session", AddAccountStates.WAITING_METHOD)
    async def auth_string_session_callback(callback: CallbackQuery, state: FSMContext):
        await state.set_state(AddAccountStates.WAITING_SESSION_STRING)
        await edit_message(callback, "📄 Отправьте String Session:", reply_markup=cancel_inline_keyboard())

    @dp.message(AddAccountStates.WAITING_SESSION_STRING)
    async def process_auth_string_session(message: Message, state: FSMContext):
        session_str = message.text.strip()
        data = await state.get_data()
        proxy_str = data.get('proxy', '')
        user_id = message.from_user.id
        status_msg = await message.answer("⏳ Проверка сессии...")
        ok, info, err = await account_manager.test_session_string(session_str, proxy_str)
        if not ok:
            await status_msg.edit_text(f"❌ Недействительная сессия: {err}")
            return
        acc_name = f"{info['first_name']} {info['last_name']}".strip() or info['username'] or "User"
        phone = info.get('phone', '')
        _allowed, _reason, _ = db.can_add_account(user_id, ADMIN)
        if not _allowed:
            await message.answer(f"🚫 {_reason}\n\nПовысьте тариф в «💳 Подписка».")
            await state.clear()
            return
        db.add_account(user_id, session_str, phone=phone, account_name=acc_name, proxy=proxy_str)
        await state.clear()
        await status_msg.edit_text(f"✅ Аккаунт {acc_name} подключен!")

    # ==================== PER-ACCOUNT CONTROL PANEL ====================
    async def render_account_dashboard(message_or_callback, account_id: int, user_id: int):
        account = db.get_account(account_id)
        if not account or account['user_id'] != user_id:
            if isinstance(message_or_callback, CallbackQuery):
                await message_or_callback.answer("❌ Аккаунт не найден!", show_alert=True)
            else:
                await message_or_callback.answer("❌ Аккаунт не найден!")
            return

        is_spamming = account_manager.is_account_spamming(account_id) if account_manager else False
        spam_btn = (
            InlineKeyboardButton(text="🛑 Остановить спам", callback_data=f"stop_spam_{account_id}")
            if is_spamming else
            InlineKeyboardButton(text="🚀 Запустить спам", callback_data=f"start_spam_{account_id}")
        )

        try:
            _, _parsed_total = db.get_parsed_users_paginated(account_id, user_id, page=0, per_page=1)
        except Exception:
            _parsed_total = 0
        total_groups = db.count_account_chats(account_id, chat_types=db.GROUP_CHAT_TYPES)
        enabled_chats_count = db.count_account_chats(account_id, chat_types=db.GROUP_CHAT_TYPES, spam_only=True)

        notifications_hidden = account.get('notifications_hidden', 0) == 1
        notif_btn = (
            InlineKeyboardButton(text="🔔 Показать уведомления", callback_data=f"toggle_notif_{account_id}")
            if notifications_hidden else
            InlineKeyboardButton(text="🔕 Скрыть уведомления", callback_data=f"toggle_notif_{account_id}")
        )

        buttons = [
            [spam_btn],
            [InlineKeyboardButton(text="📝 Настройки поста", callback_data=f"acc_post_{account_id}"),
             InlineKeyboardButton(text="⏱ Интервал", callback_data=f"acc_timeout_{account_id}")],
            [InlineKeyboardButton(text=f"💬 Выбор групп ({enabled_chats_count}/{total_groups})", callback_data=f"acc_chats_{account_id}_0"),
             InlineKeyboardButton(text="🚪 Массовый выход", callback_data=f"acc_massleave_{account_id}_0")],
            [InlineKeyboardButton(text="📥 Вступить в чаты", callback_data=f"acc_join_{account_id}"),
             InlineKeyboardButton(text="📦 Вступить из пака", callback_data=f"acc_join_pack_{account_id}")],
            [InlineKeyboardButton(text="🌐 Прокси", callback_data=f"acc_proxy_{account_id}")],
            [InlineKeyboardButton(text="🤖 Автоответчик", callback_data=f"acc_autoresponder_{account_id}"),
             InlineKeyboardButton(text="👤 Изменить BIO", callback_data=f"acc_bio_{account_id}")],
            [InlineKeyboardButton(text="💬 Ответить в ЛС", callback_data=f"acc_pms_{account_id}")],
            [InlineKeyboardButton(text="🔄 Синхронизировать чаты", callback_data=f"acc_sync_{account_id}"),
             notif_btn],
            [InlineKeyboardButton(text="👥 Парсинг пользователей", callback_data=f"acc_parse_{account_id}")],
            *([[InlineKeyboardButton(
                text=f"📋 Спарсенные контакты ({_parsed_total})",
                callback_data=f"parsed_users_page_{account_id}_0")]] if _parsed_total else []),
            [InlineKeyboardButton(text="📊 Отчет", callback_data=f"acc_report_{account_id}")],
            [InlineKeyboardButton(text="🗑 Удалить аккаунт", callback_data=f"acc_del_{account_id}")],
            [InlineKeyboardButton(text="◀️ Назад к аккаунтам", callback_data="back_to_accounts")]
        ]
        if (account.get('health') or 'ok') != 'ok':
            buttons.insert(1, [InlineKeyboardButton(
                text="♻️ Сбросить статус ограничения",
                callback_data=f"acc_health_reset_{account_id}")])
        markup = InlineKeyboardMarkup(inline_keyboard=buttons)

        acc_name = account.get('account_name') or f"Аккаунт #{account_id}"
        phone = account.get('phone') or 'Не указан'
        proxy_str = account.get('proxy') or 'Прямое (без прокси)'
        post_text_preview = account.get('post_text', '')[:60] + ("..." if len(account.get('post_text', '')) > 60 else "") if account.get('post_text') else "⚠️ Не настроен"
        has_photo = "Да" if account.get('post_photo') else "Нет"

        text = (
            f"📱 <b>Панель управления: {acc_name}</b>\n\n"
            f"• <b>Статус рассылки:</b> {'🚀 Работает' if is_spamming else '⏹ Остановлена'}\n"
            f"• <b>Телефон:</b> <code>{phone}</code>\n"
            f"• <b>Прокси:</b> <code>{proxy_str}</code>\n"
            f"• <b>Интервал цикла:</b> {account.get('timeout', 5)} мин\n"
            f"• <b>Групп всего:</b> {total_groups} (выбрано для рассылки: {enabled_chats_count})\n"
            f"• <b>Текст поста:</b> {post_text_preview}\n"
            f"• <b>Медиа:</b> {has_photo}"
        )

        # ── Здоровье аккаунта (FloodWait / ограничения) ──
        health = account.get('health') or 'ok'
        if health != 'ok':
            reason = account.get('health_reason') or ''
            until = account.get('restricted_until') or 0
            if health == 'cooldown':
                left = max(0, int(until - time.time()))
                text += (f"\n\n⏳ <b>Пауза из-за FloodWait</b>\n"
                         f"Telegram просит подождать. Осталось: <b>{left // 60} мин {left % 60} сек</b>.\n"
                         f"<i>Рассылка продолжится автоматически.</i>")
            elif health == 'restricted':
                text += (f"\n\n⚠️ <b>Аккаунт ограничен Telegram</b>\n"
                         f"{reason[:200]}\n\n"
                         f"Что делать:\n"
                         f"1. Напишите @SpamBot и запросите снятие ограничения\n"
                         f"2. Дайте аккаунту отдохнуть 24–48 часов\n"
                         f"3. Увеличьте интервал рассылки и уменьшите число чатов")
            elif health == 'banned':
                text += (f"\n\n🚫 <b>Сессия недействительна</b>\n"
                         f"{reason[:200]}\n\n"
                         f"Аккаунт нужно подключить заново (удалите и добавьте снова).")

        fc = account.get('flood_count') or 0
        if fc:
            fs = account.get('flood_total_seconds') or 0
            text += f"\n\n📉 <b>Лимиты Telegram:</b> {fc} раз, суммарно {fs // 60} мин ожидания"

        if isinstance(message_or_callback, CallbackQuery):
            try:
                await edit_message(message_or_callback, text, markup)
            except:
                pass
        else:
            await message_or_callback.answer(text, reply_markup=markup)

    @dp.callback_query(F.data.startswith('acc_health_reset_'))
    async def acc_health_reset_callback(callback: CallbackQuery):
        account_id = int(callback.data.rsplit('_', 1)[1])
        account = db.get_account(account_id)
        if not account or account['user_id'] != callback.from_user.id:
            await callback.answer("❌ Аккаунт не найден!", show_alert=True)
            return
        db.clear_account_health(account_id)
        if account.get('status') == 'banned':
            db.update_account_status(account_id, 'active')
        await callback.answer(
            "♻️ Статус сброшен. Если ограничение ещё действует, Telegram выдаст его снова.",
            show_alert=True
        )
        await render_account_dashboard(callback, account_id, callback.from_user.id)

    @dp.callback_query(F.data.startswith('manage_acc_'))
    async def manage_acc_callback(callback: CallbackQuery, state: FSMContext):
        await state.clear()
        account_id = int(callback.data.split('_')[2])
        await render_account_dashboard(callback, account_id, callback.from_user.id)

    @dp.callback_query(F.data == "back_to_accounts")
    async def back_to_accounts_callback(callback: CallbackQuery, state: FSMContext):
        await state.clear()
        user_id = callback.from_user.id
        accounts = db.get_user_accounts(user_id)
        buttons = []
        for acc in accounts:
            spam_icon = "🚀 Спамит" if account_manager and account_manager.is_account_spamming(acc['id']) else "⏹ Стоит"
            status_icon = "🟢" if acc['status'] == 'active' else "🔴"
            name = acc.get('account_name') or f"Аккаунт #{acc['id']}"
            phone = f"({acc['phone']})" if acc.get('phone') else ""
            buttons.append([InlineKeyboardButton(text=f"{status_icon} {name} {phone} | {spam_icon}", callback_data=f"manage_acc_{acc['id']}")])
        buttons.append([InlineKeyboardButton(text="➕ Добавить аккаунт", style= "success", callback_data="add_account_start")])
        markup = InlineKeyboardMarkup(inline_keyboard=buttons)
        await edit_message(callback, f"📱 <b>Ваши аккаунты:</b> ({len(accounts)})", markup)

    @dp.callback_query(F.data.startswith('start_spam_'))
    async def start_spam_callback(callback: CallbackQuery, state: FSMContext):
        await state.clear()
        account_id = int(callback.data.split('_')[2])
        user_id = callback.from_user.id
        if not db.is_user_subscribed(user_id, ADMIN):
            await callback.answer("🔒 Требуется активная подписка!", show_alert=True)
            return
        account = db.get_account(account_id)
        if not account or not account.get('post_text'):
            await callback.answer("⚠️ Сначала настройте текст поста!", show_alert=True)
            return
        chats = db.get_account_chats(account_id, spam_only=True, chat_types=db.GROUP_CHAT_TYPES)
        if not chats:
            await account_manager.fetch_and_sync_chats(account_id)
            chats = db.get_account_chats(account_id, spam_only=True, chat_types=db.GROUP_CHAT_TYPES)
        if not chats:
            await callback.answer("⚠️ Нет выбранных групп для рассылки!", show_alert=True)
            return
        ok, msg = await account_manager.start_account_spam(account_id, bot, user_id)
        await callback.answer(msg, show_alert=True)
        await render_account_dashboard(callback, account_id, user_id)

    @dp.callback_query(F.data.startswith('stop_spam_'))
    async def stop_spam_callback(callback: CallbackQuery):
        account_id = int(callback.data.split('_')[2])
        await account_manager.stop_account_spam(account_id, callback.from_user.id)
        await callback.answer("🛑 Рассылка остановлена", show_alert=True)
        await render_account_dashboard(callback, account_id, callback.from_user.id)

    @dp.callback_query(F.data.startswith('acc_sync_'))
    async def acc_sync_callback(callback: CallbackQuery):
        account_id = int(callback.data.split('_')[2])
        await callback.answer("⏳ Синхронизация...", show_alert=False)
        chats, err = await account_manager.fetch_and_sync_chats(account_id)
        if err:
            await callback.answer(f"❌ Ошибка: {err}", show_alert=True)
        else:
            await callback.answer(f"✅ Найдено {len(chats)} чатов!", show_alert=True)
        await render_account_dashboard(callback, account_id, callback.from_user.id)

    @dp.callback_query(F.data.startswith('toggle_notif_'))
    async def toggle_notif_callback(callback: CallbackQuery):
        account_id = int(callback.data.split('_')[2])
        account = db.get_account(account_id)
        if not account:
            await callback.answer("❌ Аккаунт не найден!", show_alert=True)
            return
        new_state = 0 if account.get('notifications_hidden', 0) == 1 else 1
        db.toggle_notifications(account_id, new_state)
        if new_state == 1:
            await callback.answer("🔕 Уведомления скрыты (только успешные отправки)", show_alert=True)
        else:
            await callback.answer("🔔 Уведомления показываются", show_alert=True)
        await render_account_dashboard(callback, account_id, callback.from_user.id)

    @dp.callback_query(F.data.startswith('acc_report_'))
    async def acc_report_callback(callback: CallbackQuery):
        account_id = int(callback.data.split('_')[2])
        account = db.get_account(account_id)
        if not account:
            await callback.answer("❌ Аккаунт не найден!", show_alert=True)
            return
        
        reports = db.get_account_reports(account_id)
        if not reports:
            await callback.answer("📊 Нет отчетов. Запустите рассылку.", show_alert=True)
            return
        
        last_report = reports[0]
        report_chats = db.get_report_chats(last_report['id'])
        
        text = f"📊 <b>Отчет: {account.get('account_name', f'#{account_id}')}</b>\n\n"
        text += f"💬 Текст: {last_report.get('post_text', '')[:100]}...\n"
        text += f"✅ Отправлено: {last_report.get('sent_count', 0)}\n"
        text += f"❌ Ошибок: {last_report.get('error_count', 0)}\n"
        text += f"📅 Запущен: {format_date(last_report.get('started_at', 0))}\n"
        if last_report.get('finished_at'):
            text += f"🏁 Завершен: {format_date(last_report.get('finished_at', 0))}\n"
        
        buttons = [
            [InlineKeyboardButton(text="📥 Скачать CSV", callback_data=f"download_report_{last_report['id']}")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data=f"manage_acc_{account_id}")]
        ]
        markup = InlineKeyboardMarkup(inline_keyboard=buttons)
        await edit_message(callback, text, markup)

    @dp.callback_query(F.data.startswith('download_report_'))
    async def download_report_callback(callback: CallbackQuery):
        report_id = int(callback.data.split('_')[2])
        report_chats = db.get_report_chats(report_id)
        if not report_chats:
            await callback.answer("📊 Нет данных!", show_alert=True)
            return
        
        import csv
        import io
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Chat ID', 'Chat Title', 'Sent', 'Error'])
        for chat in report_chats:
            writer.writerow([
                chat['chat_id'],
                chat.get('chat_title', ''),
                chat.get('sent', 0),
                chat.get('error', '')
            ])
        output.seek(0)
        from aiogram.types import BufferedInputFile
        file = BufferedInputFile(output.getvalue().encode('utf-8'), filename=f"report_{report_id}.csv")
        await callback.message.answer_document(file, caption=f"📊 Отчет #{report_id}")

    PARSE_DEPTH_OPTIONS = [500, 1000, 5000, 10000, 50000]

    @dp.callback_query(F.data.startswith('acc_parse_'))
    async def acc_parse_callback(callback: CallbackQuery, state: FSMContext):
        await state.clear()
        parts = callback.data.split('_')
        account_id = int(parts[2])
        page = int(parts[3]) if len(parts) > 3 else 0
        per_page = 10
        # Парсинг участников имеет смысл только для групп
        page_chats, total = db.get_account_chats_paginated(
            account_id, page=page, per_page=per_page, chat_types=db.GROUP_CHAT_TYPES
        )
        if total == 0:
            await callback.answer("💬 Групп не найдено. Синхронизируйте чаты!", show_alert=True)
            return
        total_pages = max(1, (total + per_page - 1) // per_page)
        if page >= total_pages:
            page = total_pages - 1
            page_chats, total = db.get_account_chats_paginated(
                account_id, page=page, per_page=per_page, chat_types=db.GROUP_CHAT_TYPES
            )
        buttons = []
        for chat in page_chats:
            title = chat.get('chat_title') or chat['chat_id']
            buttons.append([InlineKeyboardButton(
                text=f"👥 {title[:35]}",
                callback_data=f"parsecfg_{account_id}_{page}_{chat['chat_id']}"
            )])
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton(text="⬅️", callback_data=f"acc_parse_{account_id}_{page-1}"))
        nav_buttons.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="noop"))
        if page < total_pages - 1:
            nav_buttons.append(InlineKeyboardButton(text="➡️", callback_data=f"acc_parse_{account_id}_{page+1}"))
        buttons.append(nav_buttons)
        buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data=f"manage_acc_{account_id}")])
        markup = InlineKeyboardMarkup(inline_keyboard=buttons)
        await edit_message(
            callback,
            f"👥 <b>Парсинг пользователей</b>\n\nВыберите группу (всего: {total}, стр. {page+1}/{total_pages})",
            markup
        )

    @dp.callback_query(F.data.startswith('parsecfg_'))
    async def parse_config_callback(callback: CallbackQuery, state: FSMContext):
        # parsecfg_{account_id}_{page}_{chat_id}
        parts = callback.data.split('_')
        account_id = int(parts[1])
        page = int(parts[2])
        chat_id = '_'.join(parts[3:])
        await state.update_data(parse_account_id=account_id, parse_chat_id=chat_id, parse_page=page)

        chat = db.get_account_chat(account_id, chat_id)
        chat_title = (chat.get('chat_title') if chat else None) or chat_id

        buttons = []
        row = []
        for depth in PARSE_DEPTH_OPTIONS:
            row.append(InlineKeyboardButton(text=f"{depth}", callback_data=f"parsego_{account_id}_{depth}_{chat_id}"))
            if len(row) == 3:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
        buttons.append([InlineKeyboardButton(text="✍️ Своё число сообщений", callback_data=f"parsecustom_{account_id}_{chat_id}")])
        buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data=f"acc_parse_{account_id}_{page}")])
        markup = InlineKeyboardMarkup(inline_keyboard=buttons)
        await edit_message(
            callback,
            f"👥 <b>Парсинг: {chat_title[:40]}</b>\n\n"
            f"Если список участников группы скрыт, пользователи собираются из истории сообщений.\n\n"
            f"<b>Сколько сообщений истории просканировать?</b>\n"
            f"Чем больше — тем больше пользователей, но тем дольше парсинг.",
            markup
        )

    @dp.callback_query(F.data.startswith('parsecustom_'))
    async def parse_custom_depth_callback(callback: CallbackQuery, state: FSMContext):
        parts = callback.data.split('_')
        account_id = int(parts[1])
        chat_id = '_'.join(parts[2:])
        await state.update_data(parse_account_id=account_id, parse_chat_id=chat_id)
        await state.set_state(ParseStates.WAITING_HISTORY_LIMIT)
        await edit_message(
            callback,
            "✍️ Введите количество сообщений истории для сканирования (от 100 до 200000):",
            reply_markup=cancel_inline_keyboard()
        )

    @dp.message(ParseStates.WAITING_HISTORY_LIMIT)
    async def process_parse_history_limit(message: Message, state: FSMContext):
        data = await state.get_data()
        account_id = data.get('parse_account_id')
        chat_id = data.get('parse_chat_id')
        try:
            history_limit = int(message.text.strip())
        except (TypeError, ValueError):
            await message.answer("❌ Введите число!")
            return
        if not (100 <= history_limit <= 200000):
            await message.answer("❌ Значение должно быть от 100 до 200000!")
            return
        await state.clear()
        await start_parse_task(message, account_id, chat_id, history_limit, message.from_user.id)

    async def start_parse_task(target, account_id: int, chat_id: str, history_limit: int, user_id: int):
        if account_id in account_manager.active_parse_tasks:
            if isinstance(target, CallbackQuery):
                await target.answer("⏳ Парсинг уже выполняется!", show_alert=True)
            else:
                await target.answer("⏳ Парсинг уже выполняется!")
            return

        chat = db.get_account_chat(account_id, chat_id)
        chat_title = (chat.get('chat_title') if chat else None) or chat_id

        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🛑 Отменить парсинг", callback_data=f"cancel_parse_{account_id}")]
        ])
        base_msg = target.message if isinstance(target, CallbackQuery) else target
        progress_msg = await base_msg.answer(
            f"⏳ <b>Парсинг: {chat_title[:40]}</b>\n\n"
            f"Глубина истории: {history_limit} сообщений\n"
            f"Найдено пользователей: 0",
            reply_markup=markup
        )

        last_edit = {'t': 0.0}

        async def update_progress(found, scanned=0):
            # Троттлинг правок, чтобы не ловить flood-limit Telegram
            now = time.time()
            if now - last_edit['t'] < 3:
                return
            last_edit['t'] = now
            try:
                await progress_msg.edit_text(
                    f"⏳ <b>Парсинг: {chat_title[:40]}</b>\n\n"
                    f"Глубина истории: {history_limit} сообщений\n"
                    f"Просканировано: {scanned}\n"
                    f"Найдено пользователей: {found}",
                    reply_markup=markup
                )
            except Exception:
                pass

        asyncio.create_task(account_manager.run_limited(
            account_manager.parse_chat_users_background(
                account_id, chat_id, bot, user_id, update_progress,
                limit=100000, history_limit=history_limit
            )
        ))

    @dp.callback_query(F.data.startswith('parsego_'))
    async def parse_go_callback(callback: CallbackQuery, state: FSMContext):
        # parsego_{account_id}_{depth}_{chat_id}
        parts = callback.data.split('_')
        account_id = int(parts[1])
        history_limit = int(parts[2])
        chat_id = '_'.join(parts[3:])
        await state.clear()
        await callback.answer("🚀 Запускаю парсинг...")
        await start_parse_task(callback, account_id, chat_id, history_limit, callback.from_user.id)

    @dp.callback_query(F.data.startswith('cancel_parse_'))
    async def cancel_parse_callback(callback: CallbackQuery):
        account_id = int(callback.data.split('_')[2])
        if account_manager.cancel_parse(account_id):
            await callback.answer("🛑 Парсинг отменен!", show_alert=True)
        else:
            await callback.answer("❌ Нет активного парсинга", show_alert=True)

    PARSED_PER_PAGE = 20

    def _parsed_display_name(u) -> str:
        name = f"{u.get('first_name') or ''} {u.get('last_name') or ''}".strip()
        return name or (f"@{u['username']}" if u.get('username') else f"ID {u.get('user_id_val') or '—'}")

    async def _render_parsed_users(callback: CallbackQuery, account_id: int,
                                   page: int = 0, notice: str = ""):
        """Карусель спарсенных пользователей, по 20 на страницу."""
        user_id = callback.from_user.id
        per_page = PARSED_PER_PAGE
        users, total = db.get_parsed_users_paginated(account_id, user_id,
                                                     page=page, per_page=per_page)
        if total == 0:
            await callback.answer(
                "📭 Список пуст. Сначала запустите парсинг группы.", show_alert=True)
            return

        total_pages = max(1, (total + per_page - 1) // per_page)
        page = max(0, min(page, total_pages - 1))
        start_no = page * per_page + 1

        lines = [f"👥 <b>Спарсенные пользователи</b>",
                 f"Всего: <b>{total}</b> | Страница {page + 1}/{total_pages}", ""]
        for i, u in enumerate(users, start=start_no):
            name = html_escape(_parsed_display_name(u))[:38]
            uname = f" @{html_escape(u['username'])}" if u.get('username') else ""
            uid = u.get('user_id_val') or 0
            phone = f" 📞{html_escape(u['phone'])}" if u.get('phone') else ""
            lines.append(f"{i}. {name}{uname}{phone}\n     <code>{uid}</code>")
        if notice:
            lines.append(f"\n{notice}")
        text = "\n".join(lines)

        buttons = []
        nav = []
        if total_pages > 1:
            if page > 0:
                nav.append(InlineKeyboardButton(
                    text="⬅️", callback_data=f"parsed_users_page_{account_id}_{page - 1}"))
            nav.append(InlineKeyboardButton(
                text=f"{page + 1}/{total_pages}", callback_data="noop"))
            if page < total_pages - 1:
                nav.append(InlineKeyboardButton(
                    text="➡️", callback_data=f"parsed_users_page_{account_id}_{page + 1}"))
            buttons.append(nav)
            # быстрый прыжок в начало/конец при длинном списке
            if total_pages > 3:
                jump = []
                if page > 1:
                    jump.append(InlineKeyboardButton(
                        text="⏮ В начало", callback_data=f"parsed_users_page_{account_id}_0"))
                if page < total_pages - 2:
                    jump.append(InlineKeyboardButton(
                        text="В конец ⏭",
                        callback_data=f"parsed_users_page_{account_id}_{total_pages - 1}"))
                if jump:
                    buttons.append(jump)

        buttons.append([
            InlineKeyboardButton(text="🌐 HTML-таблица",
                                 callback_data=f"parsed_html_{account_id}"),
            InlineKeyboardButton(text="📥 CSV",
                                 callback_data=f"download_parsed_{account_id}"),
        ])
        buttons.append([InlineKeyboardButton(
            text="🗑 Очистить список", callback_data=f"parsed_clear_{account_id}")])
        buttons.append([InlineKeyboardButton(
            text="◀️ Назад", callback_data=f"manage_acc_{account_id}")])
        await edit_message(callback, text, InlineKeyboardMarkup(inline_keyboard=buttons))

    @dp.callback_query(F.data.startswith('download_parsed_'))
    async def download_parsed_callback(callback: CallbackQuery):
        account_id = int(callback.data.split('_')[2])
        user_id = callback.from_user.id
        users = db.get_parsed_users(account_id, user_id)
        if not users:
            await callback.answer("📊 Нет данных!", show_alert=True)
            return
        import csv, io
        output = io.StringIO()
        # Разделитель ';' — Excel с русской локалью иначе кладёт всё в один столбец
        writer = csv.writer(output, delimiter=';', quoting=csv.QUOTE_MINIMAL,
                            lineterminator='\r\n')
        writer.writerow(['№', 'Telegram ID', 'Username', 'Имя', 'Фамилия', 'Телефон', 'Источник'])
        for i, u in enumerate(users, 1):
            writer.writerow([
                i,
                u.get('user_id_val') or '',        # ID спарсенного, а не владельца бота
                f"@{u['username']}" if u.get('username') else '',
                u.get('first_name') or '',
                u.get('last_name') or '',
                # телефон как текст, иначе Excel съедает "+" и ведущие нули
                f"\t{u['phone']}" if u.get('phone') else '',
                u.get('source_chat_id') or '',
            ])
        # BOM обязателен: без него Excel открывает кириллицу кракозябрами
        data = '\ufeff' + output.getvalue()
        file = BufferedInputFile(data.encode('utf-8'),
                                 filename=f"parsed_users_{account_id}.csv")
        await callback.answer("📥 Готовлю CSV...")
        await callback.message.answer_document(
            file,
            caption=(f"👥 Спарсено: {len(users)}\n\n"
                     "Разделитель — точка с запятой, кодировка UTF-8 с BOM.\n"
                     "Открывается в Excel и Google Таблицах без настройки."))

    @dp.callback_query(F.data.startswith('parsed_html_'))
    async def parsed_html_callback(callback: CallbackQuery):
        account_id = int(callback.data.split('_')[2])
        user_id = callback.from_user.id
        users = db.get_parsed_users(account_id, user_id)
        if not users:
            await callback.answer("📊 Нет данных!", show_alert=True)
            return
        await callback.answer("🌐 Собираю таблицу...")
        acc = db.get_account(account_id)
        acc_name = (acc.get('account_name') if acc else None) or f"Аккаунт #{account_id}"
        html = _build_parsed_html(users, acc_name)
        file = BufferedInputFile(html.encode('utf-8'),
                                 filename=f"parsed_users_{account_id}.html")
        await callback.message.answer_document(
            file,
            caption=(f"🌐 Таблица на {len(users)} пользователей.\n\n"
                     "Откройте файл в браузере: работает поиск по списку "
                     "и сортировка по столбцам."))

    @dp.callback_query(F.data.startswith('parsed_clear_'))
    async def parsed_clear_callback(callback: CallbackQuery):
        account_id = int(callback.data.split('_')[2])
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🗑 Да, очистить",
                                  callback_data=f"parsed_clearok_{account_id}")],
            [InlineKeyboardButton(text="❌ Отмена",
                                  callback_data=f"parsed_users_page_{account_id}_0")],
        ])
        await edit_message(callback,
                           "❓ Удалить все спарсенные контакты этого аккаунта?",
                           markup)

    @dp.callback_query(F.data.startswith('parsed_clearok_'))
    async def parsed_clear_ok_callback(callback: CallbackQuery):
        account_id = int(callback.data.split('_')[2])
        db.clear_parsed_users(account_id, callback.from_user.id)
        await callback.answer("🗑 Список очищен", show_alert=True)
        await render_account_dashboard(callback, account_id, callback.from_user.id)

    @dp.callback_query(F.data.startswith('parsed_users_page_'))
    async def parsed_users_page_callback(callback: CallbackQuery):
        parts = callback.data.split('_')
        account_id = int(parts[3])
        page = int(parts[4])
        await callback.answer()
        await _render_parsed_users(callback, account_id, page)

    @dp.callback_query(F.data.startswith('acc_del_'))
    async def acc_del_callback(callback: CallbackQuery):
        account_id = int(callback.data.split('_')[2])
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🗑 Да, удалить", callback_data=f"confirm_del_acc_{account_id}")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data=f"manage_acc_{account_id}")]
        ])
        await edit_message(callback, "❓ Удалить аккаунт?", reply_markup=markup)

    @dp.callback_query(F.data.startswith('confirm_del_acc_'))
    async def confirm_del_acc_callback(callback: CallbackQuery):
        account_id = int(callback.data.split('_')[3])
        user_id = callback.from_user.id
        await account_manager.stop_account_spam(account_id, user_id)
        await account_manager.stop_client(account_id)
        db.delete_account(account_id, user_id)
        await callback.answer("✅ Аккаунт удалён", show_alert=True)
        await back_to_accounts_callback(callback, None)

    # ==================== NEUROCOMMENTING ====================
    @dp.message(F.text == '🧠 Нейрокомментинг')
    async def neurocomment_menu_handler(message: Message, state: FSMContext, user_id: int = None):
        # ВАЖНО: при вызове из callback сюда передаётся callback.message — его
        # from_user это САМ БОТ, а не пользователь. Без явного user_id проверка
        # подписки выполнялась для id бота и всегда падала с «нет подписки»,
        # из-за чего меню не перерисовывалось и статус визуально не менялся.
        await state.clear()
        if user_id is None:
            user_id = message.from_user.id
        if not db.is_user_subscribed(user_id, ADMIN):
            await message.answer("🔒 Для использования нейрокомментинга требуется активная подписка.")
            return

        accounts = db.get_user_accounts(user_id)
        buttons = []
        for acc in accounts:
            status_icon = "🟢" if acc['status'] == 'active' else "🔴"
            name = acc.get('account_name') or f"Аккаунт #{acc['id']}"
            phone = f"({acc['phone']})" if acc.get('phone') else ""
            nc = db.get_neurocomment_settings(acc['id'])
            nc_icon = "🧠" if nc and nc.get('enabled') else "⬜"
            buttons.append([InlineKeyboardButton(text=f"{status_icon} {name} {phone} {nc_icon}", callback_data=f"nc_acc_{acc['id']}")])
        if not buttons:
            await message.answer("📱 У вас нет аккаунтов!")
            return
        buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_main")])
        markup = InlineKeyboardMarkup(inline_keyboard=buttons)
        await send_photo(message, 'acc.jpg', f"🧠 <b>Нейрокомментинг</b>\n\nВыберите аккаунт:", markup)

    @dp.callback_query(F.data.startswith('nc_acc_'))
    async def nc_account_callback(callback: CallbackQuery, state: FSMContext):
        account_id = int(callback.data.split('_')[2])
        user_id = callback.from_user.id
        account = db.get_account(account_id)
        if not account or account['user_id'] != user_id:
            await callback.answer("❌ Аккаунт не найден!", show_alert=True)
            return
        nc = db.get_neurocomment_settings(account_id)
        status = "🟢 Включен" if nc and nc.get('enabled') else "🔴 Выключен"
        mode = nc.get('mode', 'prompt') if nc else 'prompt'
        mode_name = {'prompt': 'По промту', 'custom': 'Свои комментарии', 'post_prompt': 'Промт нового поста'}.get(mode, 'По промту')
        target_channels = nc.get('target_channels', '') if nc else ''
        channels_preview = ', '.join([c.strip() for c in target_channels.split(',') if c.strip()][:3]) if target_channels else 'Не заданы'
        if len([c.strip() for c in target_channels.split(',') if c.strip()]) > 3:
            channels_preview += '...'

        text = (
            f"🧠 <b>Нейрокомментинг</b>\n\n"
            f"Аккаунт: {account.get('account_name') or f'#{account_id}'}\n"
            f"Статус: {status}\n"
            f"Режим: {mode_name}\n"
            f"Каналы: {channels_preview}"
        )
        delay = nc.get('comment_delay', 60) if nc else 60
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✏️ По промту", callback_data=f"nc_mode_prompt_{account_id}"),
             InlineKeyboardButton(text="📝 Свои комментарии", callback_data=f"nc_mode_custom_{account_id}")],
            [InlineKeyboardButton(text="📰 Промт нового поста", callback_data=f"nc_mode_post_prompt_{account_id}")],
            [InlineKeyboardButton(text="🎯 Каналы", callback_data=f"nc_channels_{account_id}")],
            [InlineKeyboardButton(text=f"⏱ Задержка ({delay} сек)", callback_data=f"nc_delay_{account_id}")],
            [InlineKeyboardButton(text="✅ Включить" if not nc or not nc.get('enabled') else "❌ Выключить", callback_data=f"nc_toggle_{account_id}")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_neurocomment")]
        ])
        await edit_message(callback, text, markup)

    NC_PROMPT_HELP = (
        "Опишите <b>тематику и что должен сделать комментарий</b>. Это не текст комментария, "
        "а указание для нейросети — она учтёт его как требование и напишет живой текст по посту.\n\n"
        "<b>Примеры:</b>\n"
        "• <code>Тематика: крипта. Дополнительно призыв глянуть профиль или био!</code>\n"
        "• <code>Пиши по теме поста, в конце ненавязчиво позови в личку</code>\n"
        "• <code>Коротко согласись с автором и намекни, что подробности у меня в профиле</code>\n"
        "• <code>Задай уточняющий вопрос по теме поста</code>\n\n"
        "💡 Можно добавлять любые свои указания — они попадут в блок требований к нейросети."
    )

    @dp.callback_query(F.data.startswith('nc_mode_prompt_'))
    async def nc_mode_prompt_callback(callback: CallbackQuery, state: FSMContext):
        account_id = int(callback.data.split('_')[3])
        await state.update_data(nc_account_id=account_id)
        await state.set_state(NeuroCommentStates.WAITING_PROMPT)
        nc = db.get_neurocomment_settings(account_id)
        current = nc.get('prompt', '') if nc else ''
        buttons = []
        if current:
            buttons.append([InlineKeyboardButton(text="🧪 Тест генерации", callback_data=f"nctest_{account_id}_prompt")])
        buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data=f"nc_acc_{account_id}")])
        await edit_message(callback,
            f"✏️ <b>Режим: По промту</b>\n\n"
            f"<b>Текущий промт:</b>\n<code>{(current[:300] or 'Не задан')}</code>\n\n"
            f"{NC_PROMPT_HELP}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
        )

    @dp.message(NeuroCommentStates.WAITING_PROMPT)
    async def process_nc_prompt(message: Message, state: FSMContext):
        data = await state.get_data()
        account_id = data.get('nc_account_id')
        prompt = (message.text or '').strip()
        if not prompt:
            await message.answer("❌ Промт не может быть пустым!")
            return
        nc = db.get_neurocomment_settings(account_id)
        if not nc:
            db.create_neurocomment_settings(account_id, message.from_user.id, mode='prompt', prompt=prompt)
        else:
            db.update_neurocomment_settings(account_id, mode='prompt', prompt=prompt)
        await state.clear()
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🧪 Тест генерации", callback_data=f"nctest_{account_id}_prompt")],
            [InlineKeyboardButton(text="◀️ К настройкам", callback_data=f"nc_acc_{account_id}")]
        ])
        await message.answer(
            "✅ Промт сохранён!\n\nНажмите «Тест генерации», чтобы проверить, "
            "как нейросеть выполнит ваши указания.",
            reply_markup=markup
        )

    @dp.callback_query(F.data.startswith('nctest_'))
    async def nc_test_generation_callback(callback: CallbackQuery):
        """Прогоняет промт через AI на демо-посте, чтобы пользователь увидел результат до запуска."""
        parts = callback.data.split('_')
        account_id = int(parts[1])
        which = parts[2] if len(parts) > 2 else 'prompt'
        nc = db.get_neurocomment_settings(account_id)
        if not nc:
            await callback.answer("❌ Сначала задайте промт!", show_alert=True)
            return
        instruction = nc.get('post_prompt' if which == 'post_prompt' else 'prompt', '') or ''
        if not instruction.strip():
            await callback.answer("❌ Промт пуст!", show_alert=True)
            return

        await callback.answer("⏳ Генерирую...")
        demo_post = (
            "Сегодня рынок снова удивил: основные активы прибавили около 5% за сутки. "
            "Аналитики спорят, коррекция это или начало нового тренда."
        )
        try:
            result = await account_manager.generate_ai_comment(instruction, demo_post)
        except Exception as e:
            result = ""
            logger.error(f"nc test generation failed: {e}")

        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Ещё раз", callback_data=f"nctest_{account_id}_{which}")],
            [InlineKeyboardButton(text="◀️ К настройкам", callback_data=f"nc_acc_{account_id}")]
        ])
        if result:
            text = (
                f"🧪 <b>Тест генерации</b>\n\n"
                f"<b>Ваш промт:</b>\n<code>{instruction[:200]}</code>\n\n"
                f"<b>Демо-пост:</b>\n<i>{demo_post[:150]}</i>\n\n"
                f"<b>Результат:</b>\n{result}"
            )
        else:
            text = (
                f"⚠️ <b>Не удалось сгенерировать комментарий</b>\n\n"
                f"Ни один AI-провайдер не ответил. Проверьте:\n"
                f"• указан ли <code>GROQ_API_KEY</code> в config.ini (бесплатно, самый надёжный вариант);\n"
                f"• доступен ли интернет с сервера;\n"
                f"• бесплатный g4f часто лежит — на него нельзя полагаться в проде.\n\n"
                f"Подробности — в <code>bot_debug.log</code>."
            )
        await edit_message(callback, text, markup)

    @dp.callback_query(F.data.startswith('nc_mode_custom_'))
    async def nc_mode_custom_callback(callback: CallbackQuery, state: FSMContext):
        account_id = int(callback.data.split('_')[3])
        await state.update_data(nc_account_id=account_id)
        await state.set_state(NeuroCommentStates.WAITING_CUSTOM_COMMENTS)
        nc = db.get_neurocomment_settings(account_id)
        current = nc.get('custom_comments', '') if nc else ''
        current_list = json.loads(current) if current else []
        preview = '\n'.join([f"{i+1}. {c}" for i, c in enumerate(current_list[:5])]) if current_list else 'Не заданы'
        await edit_message(callback,
            f"📝 <b>Режим: Свои комментарии</b>\n\n"
            f"Текущие комментарии:\n{preview}\n\n"
            f"Введите комментарии (каждый с новой строки):\n\n"
            f"<b>💡 Подсказка:</b> для рандомизации в одном комментарии используйте <code>|</code>:\n"
            f"Например: <code>Круто|Отлично|Супер</code> — бот выберет случайный вариант",
            reply_markup=cancel_inline_keyboard()
        )

    @dp.message(NeuroCommentStates.WAITING_CUSTOM_COMMENTS)
    async def process_nc_custom_comments(message: Message, state: FSMContext):
        data = await state.get_data()
        account_id = data.get('nc_account_id')
        lines = [l.strip() for l in message.text.strip().split('\n') if l.strip()]
        comments_json = json.dumps(lines)
        nc = db.get_neurocomment_settings(account_id)
        if not nc:
            db.create_neurocomment_settings(account_id, message.from_user.id, mode='custom', custom_comments=comments_json)
        else:
            db.update_neurocomment_settings(account_id, mode='custom', custom_comments=comments_json)
        await state.clear()
        await message.answer(f"✅ Сохранено {len(lines)} комментариев!", reply_markup=main_menu_keyboard(message.from_user.id))

    @dp.callback_query(F.data.startswith('nc_mode_post_prompt_'))
    async def nc_mode_post_prompt_callback(callback: CallbackQuery, state: FSMContext):
        account_id = int(callback.data.split('_')[4])
        await state.update_data(nc_account_id=account_id)
        await state.set_state(NeuroCommentStates.WAITING_POST_PROMPT)
        nc = db.get_neurocomment_settings(account_id)
        current = nc.get('post_prompt', '') if nc else ''
        buttons = []
        if current:
            buttons.append([InlineKeyboardButton(text="🧪 Тест генерации", callback_data=f"nctest_{account_id}_post_prompt")])
        buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data=f"nc_acc_{account_id}")])
        await edit_message(callback,
            f"📰 <b>Режим: Промт нового поста</b>\n\n"
            f"<b>Текущий промт:</b>\n<code>{(current[:300] or 'Не задан')}</code>\n\n"
            f"{NC_PROMPT_HELP}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
        )

    @dp.message(NeuroCommentStates.WAITING_POST_PROMPT)
    async def process_nc_post_prompt(message: Message, state: FSMContext):
        data = await state.get_data()
        account_id = data.get('nc_account_id')
        prompt = message.text.strip()
        nc = db.get_neurocomment_settings(account_id)
        if not nc:
            db.create_neurocomment_settings(account_id, message.from_user.id, mode='post_prompt', post_prompt=prompt)
        else:
            db.update_neurocomment_settings(account_id, mode='post_prompt', post_prompt=prompt)
        await state.clear()
        await message.answer("✅ Промт для отслеживания постов сохранён!", reply_markup=main_menu_keyboard(message.from_user.id))

    def _nc_channel_list(account_id: int) -> list:
        nc = db.get_neurocomment_settings(account_id)
        current = nc.get('target_channels', '') if nc else ''
        return [c.strip() for c in (current or '').split(',') if c.strip()]

    def _nc_save_channels(account_id: int, user_id: int, channels: list):
        channels_str = ', '.join(dict.fromkeys(channels))
        if not db.get_neurocomment_settings(account_id):
            db.create_neurocomment_settings(account_id, user_id, target_channels=channels_str)
        else:
            db.update_neurocomment_settings(account_id, target_channels=channels_str)

    @dp.callback_query(F.data.startswith('nc_channels_'))
    async def nc_channels_callback(callback: CallbackQuery, state: FSMContext):
        account_id = int(callback.data.split('_')[2])
        await state.update_data(nc_account_id=account_id)
        current_list = _nc_channel_list(account_id)
        preview = '\n'.join([f"{i+1}. {c}" for i, c in enumerate(current_list[:10])]) if current_list else 'Не заданы'
        if len(current_list) > 10:
            preview += f"\n… и ещё {len(current_list) - 10}"
        buttons = [
            [InlineKeyboardButton(text="📢 Выбрать из моих каналов с комментариями", callback_data=f"nccl_{account_id}_0")],
            [InlineKeyboardButton(text="✍️ Ввести свой список", callback_data=f"ncman_{account_id}")],
            [InlineKeyboardButton(text="🗑 Очистить список", callback_data=f"ncclr_{account_id}")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data=f"nc_acc_{account_id}")]
        ]
        await edit_message(callback,
            f"🎯 <b>Целевые каналы</b>\n\n"
            f"Выбрано: {len(current_list)}\n{preview}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
        )

    @dp.callback_query(F.data.startswith('ncman_'))
    async def nc_manual_channels_callback(callback: CallbackQuery, state: FSMContext):
        account_id = int(callback.data.split('_')[1])
        await state.update_data(nc_account_id=account_id)
        await state.set_state(NeuroCommentStates.WAITING_TARGET_CHANNELS)
        await edit_message(callback,
            "✍️ <b>Свой список каналов</b>\n\n"
            "Введите каналы через запятую или с новой строки:\n"
            "<code>@channel1, @channel2, -100123456789, https://t.me/channel3</code>\n\n"
            "Если аккаунт не состоит в канале — бот попробует вступить в канал "
            "и в его чат комментариев автоматически.",
            reply_markup=cancel_inline_keyboard()
        )

    @dp.callback_query(F.data.startswith('ncclr_'))
    async def nc_clear_channels_callback(callback: CallbackQuery, state: FSMContext):
        account_id = int(callback.data.split('_')[1])
        _nc_save_channels(account_id, callback.from_user.id, [])
        await callback.answer("🗑 Список очищен")
        await nc_channels_callback(callback, state)

    _nc_scanning = set()

    async def _load_nc_channels(callback: CallbackQuery, state: FSMContext,
                                account_id: int, refresh: bool = False):
        """Поиск каналов с комментариями. Предупреждает, что это долго,
        и не даёт запустить два сканирования одновременно."""
        cache_key = f"nc_channels_cache_{account_id}"

        if account_id in _nc_scanning:
            await callback.answer(
                "⏳ Поиск каналов уже идёт.\n\n"
                "Дождитесь окончания — не нажимайте кнопки.",
                show_alert=True
            )
            return None, "busy"

        _nc_scanning.add(account_id)
        try:
            await callback.answer("⏳ Начинаю поиск...")
            total_channels = db.count_account_chats(account_id, chat_types=('channel',))
            # Каналы запрашиваются пачками по 100 (1 запрос на пачку)
            eta = max(5, int((total_channels / 100 + 1) * 3))
            try:
                await edit_message(
                    callback,
                    "🔍 <b>Ищу каналы с открытыми комментариями</b>\n\n"
                    f"Каналов для проверки: <b>{total_channels or '?'}</b>\n"
                    f"Примерное время: <b>~{eta} сек</b>\n\n"
                    "⚠️ <b>Не нажимайте кнопки</b> до появления списка.\n\n"
                    "<i>Список появится автоматически.</i>",
                    reply_markup=None
                )
            except Exception:
                pass

            cached, err = await account_manager.list_commentable_channels(
                account_id, refresh=refresh
            )
            if err:
                try:
                    await edit_message(callback, f"❌ {err}", reply_markup=InlineKeyboardMarkup(
                        inline_keyboard=[[InlineKeyboardButton(
                            text="◀️ Назад", callback_data=f"nc_channels_{account_id}")]]))
                except Exception:
                    await callback.answer(f"❌ {err}", show_alert=True)
                return None, err
            await state.update_data(**{cache_key: cached, 'nc_account_id': account_id})
            return cached, None
        finally:
            _nc_scanning.discard(account_id)

    async def _render_nc_channels(callback: CallbackQuery, state: FSMContext,
                                  account_id: int, page: int = 0,
                                  cached=None, notice: str = ""):
        """Отрисовка списка каналов.

        Параметры передаются явно — CallbackQuery у pydantic v2 заморожен,
        присваивание callback.data роняет обработчик (frozen_instance).
        """
        per_page = 8
        cache_key = f"nc_channels_cache_{account_id}"
        if cached is None:
            data = await state.get_data()
            cached = data.get(cache_key)
        if not cached:
            cached, err = await _load_nc_channels(callback, state, account_id)
            if err:
                return

        if not cached:
            await callback.answer(
                "📢 Каналов с открытыми комментариями не найдено. "
                "Синхронизируйте чаты или добавьте каналы вручную.",
                show_alert=True
            )
            return

        selected = set(_nc_channel_list(account_id))
        total = len(cached)
        total_pages = max(1, (total + per_page - 1) // per_page)
        page = max(0, min(page, total_pages - 1))
        page_items = cached[page * per_page:(page + 1) * per_page]

        buttons = []
        for ch in page_items:
            ref = f"@{ch['username']}" if ch.get('username') else ch['chat_id']
            icon = "☑️" if ref in selected or ch['chat_id'] in selected else "⬜"
            buttons.append([InlineKeyboardButton(
                text=f"{icon} {ch['title'][:32]}",
                callback_data=f"nctg_{account_id}_{page}_{ch['chat_id']}"
            )])
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"nccl_{account_id}_{page-1}"))
        nav.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="noop"))
        if page < total_pages - 1:
            nav.append(InlineKeyboardButton(text="➡️", callback_data=f"nccl_{account_id}_{page+1}"))
        buttons.append(nav)
        buttons.append([InlineKeyboardButton(text="🔄 Обновить список", callback_data=f"ncrf_{account_id}")])
        buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data=f"nc_channels_{account_id}")])
        await edit_message(callback,
            f"📢 <b>Каналы с открытыми комментариями</b>\n\n"
            f"Найдено: {total} | Выбрано: {len(selected)}\n"
            f"Страница {page+1}/{total_pages}" + (f"\n\n{notice}" if notice else ""),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
        )

    @dp.callback_query(F.data.startswith('nccl_'))
    async def nc_channel_list_callback(callback: CallbackQuery, state: FSMContext):
        # nccl_{account_id}_{page}
        parts = callback.data.split('_')
        account_id = int(parts[1])
        page = int(parts[2]) if len(parts) > 2 else 0
        await _render_nc_channels(callback, state, account_id, page)

    @dp.callback_query(F.data.startswith('ncrf_'))
    async def nc_refresh_channels_callback(callback: CallbackQuery, state: FSMContext):
        account_id = int(callback.data.split('_')[1])
        cached, err = await _load_nc_channels(callback, state, account_id, refresh=True)
        if err:
            return
        await _render_nc_channels(callback, state, account_id, 0, cached=cached)

    @dp.callback_query(F.data.startswith('nctg_'))
    async def nc_toggle_channel_callback(callback: CallbackQuery, state: FSMContext):
        # nctg_{account_id}_{page}_{chat_id}
        parts = callback.data.split('_')
        account_id = int(parts[1])
        page = int(parts[2])
        chat_id = '_'.join(parts[3:])

        data = await state.get_data()
        cached = data.get(f"nc_channels_cache_{account_id}", [])
        if not cached:
            # FSM-состояние потеряно (перезапуск бота) — список нужно искать заново
            await callback.answer(
                "⚠️ Список устарел. Нажмите «🔄 Обновить список».", show_alert=True
            )
            return
        entry = next((c for c in cached if c['chat_id'] == chat_id), None)
        ref = f"@{entry['username']}" if entry and entry.get('username') else chat_id

        channels = _nc_channel_list(account_id)
        if ref in channels:
            channels.remove(ref)
        elif chat_id in channels:
            channels.remove(chat_id)
        else:
            channels.append(ref)
        _nc_save_channels(account_id, callback.from_user.id, channels)
        await callback.answer("☑️ Выбран" if ref in channels else "⬜ Снят")
        await _render_nc_channels(callback, state, account_id, page, cached=cached)

    @dp.message(NeuroCommentStates.WAITING_TARGET_CHANNELS)
    async def process_nc_channels(message: Message, state: FSMContext):
        data = await state.get_data()
        account_id = data.get('nc_account_id')
        text = (message.text or '').strip()
        lines = [l.strip() for l in text.replace(',', '\n').split('\n') if l.strip()]
        channels = []
        for line in lines:
            if line.startswith('https://t.me/') or line.startswith('t.me/'):
                slug = line.split('t.me/')[-1].strip('/')
                channels.append(slug if slug.startswith('+') else f"@{slug.lstrip('@')}")
            elif line.startswith('@') or line.lstrip('-').isdigit():
                channels.append(line)
            else:
                channels.append(f"@{line.lstrip('@')}")
        existing = _nc_channel_list(account_id)
        merged = list(dict.fromkeys(existing + channels))
        _nc_save_channels(account_id, message.from_user.id, merged)
        await state.clear()
        await message.answer(
            f"✅ Добавлено {len(channels)} каналов. Всего в списке: {len(merged)}.\n\n"
            f"При запуске бот автоматически вступит в каналы и чаты комментариев, если аккаунт в них не состоит."
        )

    @dp.callback_query(F.data.startswith('nc_delay_'))
    async def nc_delay_callback(callback: CallbackQuery, state: FSMContext):
        account_id = int(callback.data.split('_')[2])
        await state.update_data(nc_account_id=account_id)
        await state.set_state(NeuroCommentStates.WAITING_COMMENT_DELAY)
        nc = db.get_neurocomment_settings(account_id)
        current = nc.get('comment_delay', 60) if nc else 60
        await edit_message(callback,
            f"⏱ <b>Задержка перед комментарием</b>\n\n"
            f"Текущая задержка: <b>{current} сек</b>\n\n"
            f"Введите задержку в секундах (30-120):",
            reply_markup=cancel_inline_keyboard()
        )

    @dp.message(NeuroCommentStates.WAITING_COMMENT_DELAY)
    async def process_nc_delay(message: Message, state: FSMContext):
        data = await state.get_data()
        account_id = data.get('nc_account_id')
        try:
            delay = int(message.text.strip())
            if delay < 30 or delay > 120:
                await message.answer("❌ Введите число от 30 до 120!")
                return
            nc = db.get_neurocomment_settings(account_id)
            if not nc:
                db.create_neurocomment_settings(account_id, message.from_user.id, comment_delay=delay)
            else:
                db.update_neurocomment_settings(account_id, comment_delay=delay)
            await state.clear()
            await message.answer(f"✅ Задержка установлена: {delay} сек")
        except:
            await message.answer("❌ Введите число!")

    @dp.callback_query(F.data.startswith('nc_toggle_'))
    async def nc_toggle_callback(callback: CallbackQuery, state: FSMContext):
        user_id = callback.from_user.id
        account_id = int(callback.data.split('_')[2])
        if not db.is_user_subscribed(user_id, ADMIN):
            await callback.answer(
                "🔒 Подписка не активна.\n\n"
                "Если вы её оплачивали — нажмите «💳 Подписка» и проверьте статус, "
                "либо напишите в поддержку.",
                show_alert=True
            )
            return
        nc = db.get_neurocomment_settings(account_id)
        if not nc:
            await callback.answer("❌ Сначала настройте режим нейрокомментинга!", show_alert=True)
            return
        new_state = 0 if nc.get('enabled') == 1 else 1
        db.update_neurocomment_settings(account_id, enabled=new_state)
        if new_state == 1:
            ok, msg = await account_manager.start_neurocomment(account_id, bot, callback.from_user.id)
            if not ok:
                # Иначе в БД оставался enabled=1: меню показывало 🟢, а воркер не работал
                db.update_neurocomment_settings(account_id, enabled=0)
                if 'ограничен' in msg or 'заблокирован' in msg or 'паузе' in msg:
                    msg += ("\n\nЕсли аккаунт уже разблокирован (проверьте @SpamBot), "
                            "сбросьте статус кнопкой «♻️ Сбросить статус ограничения» в меню аккаунта.")
                msg = "❌ " + msg
            await callback.answer(msg, show_alert=True)
        else:
            await account_manager.stop_neurocomment(account_id, callback.from_user.id)
            await callback.answer("🛑 Нейрокомментинг остановлен", show_alert=True)
        await state.clear()
        await neurocomment_menu_handler(callback.message, state, callback.from_user.id)

    @dp.callback_query(F.data == "back_to_neurocomment")
    async def back_to_neurocomment_callback(callback: CallbackQuery, state: FSMContext):
        await state.clear()
        await neurocomment_menu_handler(callback.message, state, callback.from_user.id)

    # ==================== PARTNERS SYSTEM ====================
    @dp.message(F.text == '🤝 Партнеры')
    async def partners_menu_handler(message: Message, state: FSMContext):
        await state.clear()
        user_id = message.from_user.id
        partner = db.get_partner(user_id)
        if partner:
            await show_partner_profile(message, partner)
        else:
            await show_partner_registration(message)

    async def show_partner_registration(target):
        text = "🤝 <b>Партнёрская программа</b>\n\nЗарабатывайте <b>30%</b> от каждой оплаты подписки ваших рефералов!"
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Стать партнёром", callback_data="become_partner")],
            [InlineKeyboardButton(text="◀️ В главное меню", callback_data="back_to_main")]
        ])
        if isinstance(target, Message):
            await send_photo(target, 'partner.jpg', text, markup)
        else:
            await target.answer(text, reply_markup=markup)

    @dp.callback_query(F.data == "become_partner")
    async def become_partner_callback(callback: CallbackQuery):
        user_id = callback.from_user.id
        partner = db.get_partner(user_id)
        if partner:
            await show_partner_profile(callback, partner)
            return
        referral_code = generate_referral_code(user_id)
        partner = db.create_partner(user_id, referral_code)
        if partner:
            await edit_message(callback, f"🎉 <b>Вы стали партнёром!</b>\n\nКод: <code>{referral_code}</code>")
            await show_partner_profile(callback, partner)
        else:
            await callback.answer("❌ Ошибка!", show_alert=True)

    async def show_partner_profile(source, partner: dict):
        stats = db.get_partner_stats(partner['user_id'])
        referral_link = f"https://t.me/{USERNAME}?start={partner['referral_code']}"
        text = (
            f"🤝 <b>Партнёрский профиль</b>\n\n"
            f"• Баланс: <b>${stats.get('balance', 0):.2f}</b>\n"
            f"• Заработано: <b>${stats.get('total_earnings', 0):.2f}</b>\n"
            f"• Рефералов: <b>{stats.get('referral_count', 0)}</b>\n\n"
            f"🔗 <code>{referral_link}</code>"
        )
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💰 Вывести", callback_data="partner_withdraw")],
            [InlineKeyboardButton(text="📋 Рефералы", callback_data="my_referrals_0")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_main")]
        ])
        if isinstance(source, CallbackQuery):
            await edit_message(source, text, markup)
        else:
            await send_photo(source, 'partner.jpg', text, markup)

    @dp.callback_query(F.data == "back_to_main")
    async def back_to_main_callback(callback: CallbackQuery, state: FSMContext):
        await state.clear()
        user_id = callback.from_user.id
        user = db.get_user(user_id)
        is_admin = (user_id == ADMIN) or (user and user.get('is_admin') == 1)
        await edit_message(callback, "🏠 <b>Главное меню</b>", main_menu_keyboard(user_id, is_admin))

    @dp.callback_query(F.data == "partner_withdraw")
    async def partner_withdraw_callback(callback: CallbackQuery, state: FSMContext):
        user_id = callback.from_user.id
        partner = db.get_partner(user_id)
        if not partner:
            await callback.answer("❌ Вы не партнёр!", show_alert=True)
            return
        balance = partner.get('earnings_balance', 0)
        if balance < 10:
            await callback.answer(f"❌ Мин. сумма $10. Баланс: ${balance:.2f}", show_alert=True)
            return
        await edit_message(callback, f"💰 <b>Вывод средств</b>\n\nБаланс: <b>${balance:.2f}</b>\n\nВведите сумму:", cancel_inline_keyboard())

    @dp.message(PartnerStates.WAITING_WITHDRAW_AMOUNT)
    async def process_withdraw_amount(message: Message, state: FSMContext):
        user_id = message.from_user.id
        partner = db.get_partner(user_id)
        if not partner:
            await state.clear()
            await message.answer("❌ Ошибка!")
            return
        try:
            amount = float(message.text.strip())
            balance = partner.get('earnings_balance', 0)
            if amount < 10 or amount > balance:
                await message.answer("❌ Неверная сумма!")
                return
            db.withdraw_partner_earnings(user_id, amount)
            await state.clear()
            await message.answer(f"✅ Заявка на вывод ${amount:.2f} создана!")
        except:
            await message.answer("❌ Введите число!")

    @dp.callback_query(F.data.startswith('my_referrals_'))
    async def my_referrals_callback(callback: CallbackQuery):
        user_id = callback.from_user.id
        partner = db.get_partner(user_id)
        if not partner:
            await callback.answer("❌ Вы не партнёр!", show_alert=True)
            return
        referrals = db.get_partner_referrals(user_id)
        text = f"👥 <b>Мои рефералы</b> ({len(referrals)})\n\n"
        for ref in referrals[:10]:
            name = ref.get('first_name') or ref.get('username') or f"ID:{ref['referral_user_id']}"
            text += f"• {name}\n"
        await edit_message(callback, text)

    @dp.callback_query(F.data == "partner_history")
    async def partner_history_callback(callback: CallbackQuery):
        user_id = callback.from_user.id
        transactions = db.get_partner_transactions(user_id, limit=10)
        text = "📜 <b>История операций</b>\n\n"
        for t in transactions:
            icon = "🟢" if t['type'] == 'earning' else "🔴"
            text += f"{icon} ${t['amount']:.2f} — {t['description']}\n"
        await edit_message(callback, text)

    # ==================== ADMIN PANEL ====================
    @dp.message(F.text == '👑 Админ-панель')
    async def admin_panel_menu(message: Message, state: FSMContext):
        await state.clear()
        user_id = message.from_user.id
        user = db.get_user(user_id)
        if user_id != ADMIN and (not user or user.get('is_admin') != 1):
            await message.answer("❌ Доступ запрещён.")
            return

        users = db.get_all_users()
        sub_count = sum(1 for u in users if u.get('subscription_until', 0) > int(time.time()))

        buttons = [
            [InlineKeyboardButton(text="📁 Паки и Категории", callback_data="admin_manage_packs")],
            [InlineKeyboardButton(text="💳 Тарифы", callback_data="admin_manage_tariffs"),
             InlineKeyboardButton(text="👤 Выдать подписку", callback_data="admin_give_sub")],
            [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
            [InlineKeyboardButton(text="📥 Выгрузка сессий", callback_data="admin_export_sessions"),
             InlineKeyboardButton(text="✅ Чек сессий", callback_data="admin_check_sessions")],
            [InlineKeyboardButton(text="📢 Обязательная подписка", callback_data="admin_mandatory_sub")],
            [InlineKeyboardButton(text="🔄 Рекуррентные сообщения", callback_data="admin_recurring")],
            [InlineKeyboardButton(text="🪞 Зеркала", callback_data="admin_mirrors")],
            [InlineKeyboardButton(text="🎁 Промокоды", callback_data="admin_manage_promos")],
            [InlineKeyboardButton(text="🎬 Промо медиа", callback_data="admin_promo_media")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_main")]
        ]
        markup = InlineKeyboardMarkup(inline_keyboard=buttons)
        text = (
            f"👑 <b>Админ-панель</b>\n\n"
            f"👤 Пользователей: <b>{len(users)}</b>\n"
            f"🟢 Активных подписок: <b>{sub_count}</b>"
        )
        await message.answer(text, reply_markup=markup)

    @dp.callback_query(F.data == "admin_stats")
    async def admin_stats_callback(callback: CallbackQuery):
        stats = db.get_admin_stats()
        text = (
            f"📊 <b>Статистика бота</b>\n\n"
            f"👤 Пользователей: <b>{stats['total_users']}</b>\n"
            f"🟢 Активных подписок: <b>{stats['active_subs']}</b>\n"
            f"🔴 Истекших подписок: <b>{stats['expired_subs']}</b>\n"
            f"📱 Аккаунтов: <b>{stats['total_accounts']}</b>\n"
            f"💳 Оплаченных счетов: <b>{stats['paid_invoices']}</b>\n"
            f"💰 Общий доход: <b>${stats['total_revenue']:.2f}</b>\n"
            f"📁 Категорий: <b>{stats['total_categories']}</b>\n"
            f"📦 Паков: <b>{stats['total_packs']}</b>\n"
            f"💬 Чатов в паках: <b>{stats['total_pack_chats']}</b>"
        )
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_panel")]
        ])
        await edit_message(callback, text, reply_markup=markup)

    @dp.callback_query(F.data == "admin_promo_media")
    async def admin_promo_media_callback(callback: CallbackQuery, state: FSMContext):
        await state.set_state(AdminStates.WAITING_PROMO_MEDIA)
        await edit_message(callback,
            "🎬 <b>Промо медиа</b>\n\n"
            "Отправьте фото, GIF или видео с подписью.\n"
            "Это медиа будет показываться пользователям при нажатии «🎁 Промо».",
            reply_markup=cancel_inline_keyboard()
        )

    @dp.message(AdminStates.WAITING_PROMO_MEDIA)
    async def process_promo_media(message: Message, state: FSMContext):
        file_id = None
        media_type = None
        if message.photo:
            file_id = message.photo[-1].file_id
            media_type = "photo"
        elif message.animation:
            file_id = message.animation.file_id
            media_type = "animation"
        elif message.video:
            file_id = message.video.file_id
            media_type = "video"
        else:
            await message.answer("❌ Отправьте фото, GIF или видео!")
            return
        caption = message.caption or ""
        db.set_kv('promo_media_type', media_type)
        db.set_kv('promo_media_file_id', file_id)
        db.set_kv('promo_caption', caption)
        await state.clear()
        await message.answer("✅ Промо медиа сохранено!", reply_markup=main_menu_keyboard(message.from_user.id, is_admin=message.from_user.id == ADMIN, admin_id=ADMIN))

    @dp.callback_query(F.data == "admin_give_sub")
    async def admin_give_sub_callback(callback: CallbackQuery, state: FSMContext):
        await state.set_state(AdminStates.WAITING_USER_ID_SUB)
        await edit_message(callback, 
            "👤 <b>Выдача подписки</b>\n\nВведите ID пользователя:",
            reply_markup=cancel_inline_keyboard()
        )

    @dp.message(AdminStates.WAITING_USER_ID_SUB)
    async def process_give_sub_user_id(message: Message, state: FSMContext):
        try:
            target_id = int(message.text.strip())
            await state.update_data(target_user_id=target_id)
            await state.set_state(AdminStates.WAITING_DAYS_SUB)
            await message.answer(f"👤 ID: <code>{target_id}</code>\n\nВведите количество дней подписки:", reply_markup=cancel_inline_keyboard())
        except:
            await message.answer("❌ Введите числовой ID!")

    @dp.message(AdminStates.WAITING_DAYS_SUB)
    async def process_give_sub_days(message: Message, state: FSMContext):
        try:
            days = int(message.text.strip())
            data = await state.get_data()
            target_id = data.get('target_user_id')
            db.add_subscription_days(target_id, days)
            await state.clear()
            await message.answer(f"✅ Подписка выдана пользователю <code>{target_id}</code> на <b>{days} дней</b>!")
        except:
            await message.answer("❌ Введите число дней!")

    @dp.callback_query(F.data == "admin_manage_packs")
    async def admin_manage_packs_callback(callback: CallbackQuery):
        categories = db.get_categories()
        buttons = [[InlineKeyboardButton(text=f"📁 {c['name']}", callback_data=f"admin_category_{c['id']}")] for c in categories]
        buttons.append([InlineKeyboardButton(text="➕ Добавить категорию", callback_data="admin_add_category")])
        buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin_panel")])
        markup = InlineKeyboardMarkup(inline_keyboard=buttons)
        await edit_message(callback, "📁 <b>Управление паками и категориями</b>", reply_markup=markup)

    @dp.callback_query(F.data.startswith('admin_category_'))
    async def admin_category_callback(callback: CallbackQuery):
        category_id = int(callback.data.split('_')[2])
        packs = db.get_packs_in_category(category_id)
        buttons = [[InlineKeyboardButton(text=f"📦 {p['name']} ({p['chats_count']} чатов)", callback_data=f"admin_pack_{p['id']}")] for p in packs]
        buttons.append([InlineKeyboardButton(text="➕ Добавить пак", callback_data=f"admin_add_pack_{category_id}")])
        buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin_manage_packs")])
        markup = InlineKeyboardMarkup(inline_keyboard=buttons)
        await edit_message(callback, f"📦 <b>Паки в категории</b>", reply_markup=markup)

    @dp.callback_query(F.data.startswith('admin_pack_'))
    async def admin_pack_callback(callback: CallbackQuery):
        pack_id = int(callback.data.split('_')[2])
        pack = db.get_pack(pack_id)
        if not pack:
            await callback.answer("❌ Пак не найден!", show_alert=True)
            return
        chats = db.get_pack_chats(pack_id)
        buttons = [[InlineKeyboardButton(text=f"❌ {c['chat_url'][:30]}", callback_data=f"admin_del_pack_chat_{c['id']}")] for c in chats[:20]]
        buttons.append([InlineKeyboardButton(text="➕ Добавить чаты", callback_data=f"admin_add_chats_{pack_id}")])
        buttons.append([InlineKeyboardButton(text="🗑 Удалить пак", callback_data=f"admin_del_pack_{pack_id}")])
        buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data=f"admin_category_{pack['category_id']}")])
        markup = InlineKeyboardMarkup(inline_keyboard=buttons)
        text = f"📦 <b>{pack['name']}</b>\n📝 {pack['description']}\n\n💬 Чатов: {len(chats)}"
        await edit_message(callback, text, reply_markup=markup)

    @dp.callback_query(F.data.startswith('admin_add_pack_'))
    async def admin_add_pack_callback(callback: CallbackQuery, state: FSMContext):
        category_id = int(callback.data.split('_')[3])
        await state.update_data(category_id=category_id)
        await state.set_state(AdminStates.WAITING_PACK_NAME)
        await edit_message(callback, "📦 <b>Создание пака</b>\n\nВведите название:", reply_markup=cancel_inline_keyboard())

    @dp.message(AdminStates.WAITING_PACK_NAME)
    async def process_pack_name(message: Message, state: FSMContext):
        await state.update_data(pack_name=message.text.strip())
        await state.set_state(AdminStates.WAITING_PACK_DESC)
        await message.answer("📝 Введите описание пака:", reply_markup=cancel_inline_keyboard())

    @dp.message(AdminStates.WAITING_PACK_DESC)
    async def process_pack_desc(message: Message, state: FSMContext):
        data = await state.get_data()
        category_id = data.get('category_id')
        pack_name = data.get('pack_name')
        description = message.text.strip()
        pack_id = db.add_pack(category_id, pack_name, description)
        await state.clear()
        await message.answer(f"✅ Пак <b>{pack_name}</b> создан!\n\nID: {pack_id}")

    @dp.callback_query(F.data.startswith('admin_add_chats_'))
    async def admin_add_chats_callback(callback: CallbackQuery, state: FSMContext):
        pack_id = int(callback.data.split('_')[3])
        await state.update_data(pack_id=pack_id)
        await state.set_state(AdminStates.WAITING_PACK_CHATS_INPUT)
        await edit_message(callback, 
            "💬 <b>Добавление чатов в пак</b>\n\n"
            "Отправьте ссылки на чаты (по одной на строку):",
            reply_markup=cancel_inline_keyboard()
        )

    @dp.message(AdminStates.WAITING_PACK_CHATS_INPUT)
    async def process_pack_chats_input(message: Message, state: FSMContext):
        data = await state.get_data()
        pack_id = data.get('pack_id')
        urls = [u.strip() for u in message.text.strip().split('\n') if u.strip()]
        db.add_chats_to_pack(pack_id, urls)
        await state.clear()
        await message.answer(f"✅ Добавлено <b>{len(urls)}</b> чатов в пак!")

    @dp.callback_query(F.data.startswith('admin_del_pack_chat_'))
    async def admin_del_pack_chat_callback(callback: CallbackQuery):
        item_id = int(callback.data.split('_')[4])
        db.delete_pack_chat(item_id)
        await callback.answer("✅ Чат удалён из пака!", show_alert=True)

    @dp.callback_query(F.data.startswith('admin_del_pack_'))
    async def admin_del_pack_callback(callback: CallbackQuery):
        pack_id = int(callback.data.split('_')[3])
        pack = db.get_pack(pack_id)
        db.delete_pack(pack_id)
        await callback.answer("✅ Пак удалён!", show_alert=True)
        if pack:
            await admin_category_callback(callback)

    @dp.callback_query(F.data == "admin_add_category")
    async def admin_add_category_callback(callback: CallbackQuery, state: FSMContext):
        await state.set_state(AdminStates.WAITING_CATEGORY_NAME)
        await edit_message(callback, "📁 <b>Новая категория</b>\n\nВведите название:", reply_markup=cancel_inline_keyboard())

    @dp.message(AdminStates.WAITING_CATEGORY_NAME)
    async def process_category_name(message: Message, state: FSMContext):
        db.add_category(message.text.strip())
        await state.clear()
        await message.answer(f"✅ Категория <b>{message.text.strip()}</b> создана!")

    @dp.callback_query(F.data == "admin_manage_tariffs")
    async def admin_manage_tariffs_callback(callback: CallbackQuery):
        tariffs = db.get_tariffs(active_only=False)
        buttons = [[InlineKeyboardButton(text=f"💳 {t['name']} — ${t['price_usd']:.2f} ({t['duration_days']} дн.)", callback_data=f"admin_tariff_{t['id']}")] for t in tariffs]
        buttons.append([InlineKeyboardButton(text="➕ Добавить тариф", callback_data="admin_add_tariff")])
        buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin_panel")])
        markup = InlineKeyboardMarkup(inline_keyboard=buttons)
        await edit_message(callback, "💳 <b>Управление тарифами</b>", reply_markup=markup)

    @dp.callback_query(F.data.startswith('admin_tariff_'))
    async def admin_tariff_callback(callback: CallbackQuery):
        tariff_id = int(callback.data.split('_')[2])
        tariff = db.get_tariff(tariff_id)
        if not tariff:
            await callback.answer("❌ Тариф не найден!", show_alert=True)
            return
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🗑 Удалить тариф", callback_data=f"admin_del_tariff_{tariff_id}")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_manage_tariffs")]
        ])
        text = f"💳 <b>{tariff['name']}</b>\n💰 ${tariff['price_usd']:.2f}\n📅 {tariff['duration_days']} дн.\n📝 {tariff['description']}"
        await edit_message(callback, text, reply_markup=markup)

    @dp.callback_query(F.data.startswith('admin_del_tariff_'))
    async def admin_del_tariff_callback(callback: CallbackQuery):
        tariff_id = int(callback.data.split('_')[3])
        db.delete_tariff(tariff_id)
        await callback.answer("✅ Тариф удалён!", show_alert=True)
        await admin_manage_tariffs_callback(callback)

    @dp.callback_query(F.data == "admin_add_tariff")
    async def admin_add_tariff_callback(callback: CallbackQuery, state: FSMContext):
        await state.set_state(AdminStates.WAITING_TARIFF_NAME)
        await edit_message(callback, "💳 <b>Новый тариф</b>\n\nВведите название:", reply_markup=cancel_inline_keyboard())

    @dp.message(AdminStates.WAITING_TARIFF_NAME)
    async def process_tariff_name(message: Message, state: FSMContext):
        await state.update_data(tariff_name=message.text.strip())
        await state.set_state(AdminStates.WAITING_TARIFF_DAYS)
        await message.answer("📅 Введите количество дней:", reply_markup=cancel_inline_keyboard())

    @dp.message(AdminStates.WAITING_TARIFF_DAYS)
    async def process_tariff_days(message: Message, state: FSMContext):
        try:
            days = int(message.text.strip())
            await state.update_data(tariff_days=days)
            await state.set_state(AdminStates.WAITING_TARIFF_PRICE)
            await message.answer("💰 Введите цену в USD:", reply_markup=cancel_inline_keyboard())
        except:
            await message.answer("❌ Введите число!")

    @dp.message(AdminStates.WAITING_TARIFF_PRICE)
    async def process_tariff_price(message: Message, state: FSMContext):
        try:
            price = float(message.text.strip())
            data = await state.get_data()
            db.add_tariff(data.get('tariff_name'), data.get('tariff_days'), price)
            await state.clear()
            await message.answer(f"✅ Тариф <b>{data.get('tariff_name')}</b> создан!")
        except:
            await message.answer("❌ Введите число!")

    @dp.callback_query(F.data == "admin_export_sessions")
    async def admin_export_sessions_callback(callback: CallbackQuery):
        accounts = db.get_all_accounts_with_user()
        if not accounts:
            await callback.answer("❌ Нет аккаунтов для выгрузки!", show_alert=True)
            return
        import csv
        import io
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['ID', 'User ID', 'Owner', 'Phone', 'Account Name', 'Status', 'Proxy', 'Created'])
        for acc in accounts:
            writer.writerow([
                acc['id'], acc['user_id'],
                acc.get('owner_username') or acc.get('owner_name') or '',
                acc.get('phone', ''), acc.get('account_name', ''),
                acc.get('status', ''), acc.get('proxy', ''),
                format_date(acc.get('created_at', 0))
            ])
        output.seek(0)
        from aiogram.types import BufferedInputFile
        file = BufferedInputFile(output.getvalue().encode('utf-8'), filename="sessions_export.csv")
        await callback.message.answer_document(file, caption="📥 Выгрузка сессий")

    @dp.callback_query(F.data == "admin_check_sessions")
    async def admin_check_sessions_callback(callback: CallbackQuery):
        await callback.answer("⏳ Проверка сессий...", show_alert=False)
        accounts = db.get_all_accounts()
        checked = 0
        valid = 0
        invalid = 0
        for acc in accounts:
            checked += 1
            ok, _, _ = await account_manager.test_session_string(acc['session_string'], acc.get('proxy', ''))
            if ok:
                valid += 1
                db.update_account_status_by_id(acc['id'], 'active')
            else:
                invalid += 1
                db.update_account_status_by_id(acc['id'], 'error')
        text = f"✅ <b>Проверка завершена!</b>\n\n📱 Проверено: {checked}\n🟢 Валидных: {valid}\n🔴 Невалидных: {invalid}"
        await edit_message(callback, text)

    @dp.callback_query(F.data == "admin_mandatory_sub")
    async def admin_mandatory_sub_callback(callback: CallbackQuery, state: FSMContext):
        enabled = db.get_kv("mandatory_sub_enabled", "0")
        channel = db.get_kv("mandatory_sub_channel", "")
        status = "🟢 Включена" if enabled == "1" else "🔴 Выключена"
        text = f"📢 <b>Обязательная подписка</b>\n\nСтатус: {status}\nКанал: <code>{channel or 'Не задан'}</code>"
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⚙️ Задать канал", callback_data="admin_set_mandatory_channel")],
            [InlineKeyboardButton(text="✅ Включить" if enabled != "1" else "❌ Выключить", callback_data="admin_toggle_mandatory")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_panel")]
        ])
        await edit_message(callback, text, reply_markup=markup)

    @dp.callback_query(F.data == "admin_set_mandatory_channel")
    async def admin_set_mandatory_channel_callback(callback: CallbackQuery, state: FSMContext):
        await state.set_state(MandatorySubStates.WAITING_CHANNEL)
        await edit_message(callback, 
            "📢 <b>Канал для обязательной подписки</b>\n\n"
            "Введите @username или ID канала:",
            reply_markup=cancel_inline_keyboard()
        )

    @dp.message(MandatorySubStates.WAITING_CHANNEL)
    async def process_mandatory_channel(message: Message, state: FSMContext):
        channel = message.text.strip()
        db.set_kv("mandatory_sub_channel", channel)
        await state.clear()
        await message.answer(f"✅ Канал <code>{channel}</code> задан!")

    @dp.callback_query(F.data == "admin_toggle_mandatory")
    async def admin_toggle_mandatory_callback(callback: CallbackQuery):
        enabled = db.get_kv("mandatory_sub_enabled", "0")
        new_val = "0" if enabled == "1" else "1"
        db.set_kv("mandatory_sub_enabled", new_val)
        await callback.answer(f"{'✅ Включена' if new_val == '1' else '❌ Выключена'}!", show_alert=True)
        await admin_mandatory_sub_callback(callback, None)

    @dp.callback_query(F.data == "admin_recurring")
    async def admin_recurring_callback(callback: CallbackQuery):
        messages = db.get_recurring_messages()
        buttons = [[InlineKeyboardButton(text=f"🔄 {m['name']} ({m['interval_minutes']} мин.)", callback_data=f"admin_recurring_{m['id']}")] for m in messages]
        buttons.append([InlineKeyboardButton(text="➕ Добавить", callback_data="admin_add_recurring")])
        buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin_panel")])
        markup = InlineKeyboardMarkup(inline_keyboard=buttons)
        await edit_message(callback, "🔄 <b>Рекуррентные сообщения</b>", reply_markup=markup)

    async def _show_recurring_item(callback: CallbackQuery, msg_id: int):
        msg = db.get_recurring_message(msg_id)
        if not msg:
            await callback.answer("❌ Не найдено!", show_alert=True)
            return
        status = "🟢 Активно" if msg['is_active'] == 1 else "🔴 Остановлено"
        last_sent = msg.get('last_sent_at', 0)
        last_sent_str = format_date(last_sent) if last_sent else "Никогда"
        has_media = "✅ Есть" if msg.get('media_file_id') else "❌ Нет"

        buttons_raw = msg.get('buttons', '[]')
        try:
            buttons_list = json.loads(buttons_raw) if buttons_raw else []
        except Exception:
            buttons_list = []
        btns_count_str = f"{len(buttons_list)} шт." if buttons_list else "❌ Нет"

        text = (
            f"🔄 <b>{msg['name']}</b>\n\n"
            f"📝 <b>Текст:</b>\n{msg['text']}\n\n"
            f"🖼 <b>Медиа:</b> {has_media}\n"
            f"🔘 <b>Кнопки:</b> {btns_count_str}\n"
            f"⏱ <b>Интервал:</b> {msg['interval_minutes']} мин.\n"
            f"📊 <b>Статус:</b> {status}\n"
            f"🕒 <b>Посл. отправка:</b> {last_sent_str}\n"
        )
        if buttons_list:
            text += "\n<b>Список кнопок:</b>\n"
            for idx, b in enumerate(buttons_list, 1):
                s_icon = {"primary": "🔵 primary", "danger": "🔴 danger", "success": "🟢 success"}.get(b.get('style'), "⚪ обычная")
                text += f"{idx}. {b.get('text', '')} [{s_icon}] → <code>{b.get('url') or b.get('callback_data')}</code>\n"

        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📝 Изменить текст", callback_data=f"admin_edit_recurring_text_{msg_id}")],
            [InlineKeyboardButton(text="⏱ Изменить интервал", callback_data=f"admin_edit_recurring_interval_{msg_id}")],
            [InlineKeyboardButton(text="🖼 Изменить фото", callback_data=f"admin_edit_recurring_media_{msg_id}")],
            [InlineKeyboardButton(text=f"🔘 Настроить кнопки ({len(buttons_list)})", callback_data=f"admin_edit_recurring_btns_{msg_id}")],
            [InlineKeyboardButton(text="▶️ Запустить" if msg['is_active'] != 1 else "⏹ Остановить", callback_data=f"admin_toggle_recurring_{msg_id}")],
            [InlineKeyboardButton(text="🚀 Отправить сейчас", callback_data=f"admin_send_recurring_{msg_id}")],
            [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"admin_del_recurring_{msg_id}")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_recurring")]
        ])
        await edit_message(callback, text, reply_markup=markup)

    @dp.callback_query(F.data.startswith('admin_recurring_'))
    async def admin_recurring_item_callback(callback: CallbackQuery):
        msg_id = int(callback.data.split('_')[-1])
        await _show_recurring_item(callback, msg_id)

    @dp.callback_query(F.data == "admin_add_recurring")
    async def admin_add_recurring_callback(callback: CallbackQuery, state: FSMContext):
        await state.set_state(RecurringStates.WAITING_NAME)
        await edit_message(callback, "🔄 <b>Новое рекуррентное сообщение</b>\n\nВведите название:", reply_markup=cancel_inline_keyboard())

    @dp.message(RecurringStates.WAITING_NAME)
    async def process_recurring_name(message: Message, state: FSMContext):
        await state.update_data(recurring_name=message.text.strip() if message.text else "Сообщение")
        await state.set_state(RecurringStates.WAITING_TEXT)
        await message.answer(
            "📝 <b>Введите текст сообщения</b> (или перешлите готовый пост):\n\n"
            "<i>Поддерживается вся разметка Telegram (жирный, курсив, ссылки, спойлеры) и прикрепление фото.</i>",
            reply_markup=cancel_inline_keyboard()
        )

    @dp.message(RecurringStates.WAITING_TEXT)
    async def process_recurring_text(message: Message, state: FSMContext):
        text = message.html_text or message.html_caption or message.text or message.caption or ""
        photo_id = message.photo[-1].file_id if message.photo else ""
        await state.update_data(recurring_text=text, recurring_media=photo_id)
        await state.set_state(RecurringStates.WAITING_INTERVAL)
        await message.answer("⏱ Введите интервал отправки в минутах:", reply_markup=cancel_inline_keyboard())

    @dp.message(RecurringStates.WAITING_INTERVAL)
    async def process_recurring_interval(message: Message, state: FSMContext):
        try:
            interval = int(message.text.strip())
            if interval <= 0:
                await message.answer("❌ Интервал должен быть больше 0 минут! Введите число:")
                return
            data = await state.get_data()
            db.create_recurring_message(
                data.get('recurring_name'),
                data.get('recurring_text'),
                interval,
                media_file_id=data.get('recurring_media', '')
            )
            await state.clear()
            await message.answer("✅ Рекуррентное сообщение создано!")
        except:
            await message.answer("❌ Введите число (минуты):")

    @dp.callback_query(F.data.startswith('admin_edit_recurring_text_'))
    async def admin_edit_recurring_text_callback(callback: CallbackQuery, state: FSMContext):
        msg_id = int(callback.data.split('_')[-1])
        msg = db.get_recurring_message(msg_id)
        await state.update_data(edit_recurring_id=msg_id)
        await state.set_state(RecurringStates.EDIT_TEXT)
        current_text = msg.get('text', '') if msg else ''
        await edit_message(
            callback,
            "📝 <b>Введите новый текст сообщения:</b>\n\n"
            "<i>Поддерживается вся разметка Telegram (жирный, курсив, ссылки, спойлеры, эмодзи) и пересылка постов с медиа.</i>\n\n"
            "👇 <b>Текущий текст отправлен сообщением ниже для удобного копирования:</b>",
            reply_markup=cancel_inline_keyboard()
        )
        if current_text:
            try:
                await callback.message.answer(current_text, parse_mode=ParseMode.HTML)
            except Exception:
                await callback.message.answer(current_text, parse_mode=None)

    @dp.message(RecurringStates.EDIT_TEXT)
    async def process_edit_recurring_text(message: Message, state: FSMContext):
        data = await state.get_data()
        msg_id = data.get('edit_recurring_id')
        new_text = message.html_text or message.html_caption or message.text or message.caption or ""
        if message.photo:
            file_id = message.photo[-1].file_id
            db.update_recurring_message(msg_id, text=new_text, media_file_id=file_id)
        else:
            db.update_recurring_message(msg_id, text=new_text)
        await state.clear()
        await message.answer("✅ Текст сообщения обновлён с сохранением разметки (entities)!")

    @dp.callback_query(F.data.startswith('admin_edit_recurring_interval_'))
    async def admin_edit_recurring_interval_callback(callback: CallbackQuery, state: FSMContext):
        msg_id = int(callback.data.split('_')[-1])
        msg = db.get_recurring_message(msg_id)
        current_interval = msg.get('interval_minutes', 60) if msg else 60
        await state.update_data(edit_recurring_id=msg_id)
        await state.set_state(RecurringStates.EDIT_INTERVAL)
        await edit_message(
            callback,
            f"⏱ <b>Изменение интервала</b>\n\n"
            f"Текущий интервал: <b>{current_interval} мин.</b>\n\n"
            f"Введите новый интервал в минутах (целое число больше 0):",
            reply_markup=cancel_inline_keyboard()
        )

    @dp.message(RecurringStates.EDIT_INTERVAL)
    async def process_edit_recurring_interval(message: Message, state: FSMContext):
        data = await state.get_data()
        msg_id = data.get('edit_recurring_id')
        try:
            interval = int(message.text.strip())
            if interval <= 0:
                await message.answer("❌ Интервал должен быть больше 0 минут! Введите число:")
                return
            db.update_recurring_message(msg_id, interval_minutes=interval)
            await state.clear()
            await message.answer(f"✅ Интервал обновлён: <b>{interval} мин.</b>")
        except:
            await message.answer("❌ Введите число (минуты больше 0):")

    @dp.callback_query(F.data.startswith('admin_edit_recurring_media_'))
    async def admin_edit_recurring_media_callback(callback: CallbackQuery, state: FSMContext):
        msg_id = int(callback.data.split('_')[-1])
        await state.update_data(edit_recurring_id=msg_id)
        await state.set_state(RecurringStates.WAITING_MEDIA)
        await edit_message(callback, "🖼 Отправьте фото для рассылки (или напишите 'удалить', чтобы убрать):", reply_markup=cancel_inline_keyboard())

    @dp.message(RecurringStates.WAITING_MEDIA)
    async def process_recurring_media(message: Message, state: FSMContext):
        data = await state.get_data()
        msg_id = data.get('edit_recurring_id')
        if message.photo:
            file_id = message.photo[-1].file_id
            db.update_recurring_message(msg_id, media_file_id=file_id)
            await state.clear()
            await message.answer("✅ Фото для рассылки обновлено!")
        elif message.text and message.text.strip().lower() in ['удалить', 'нет', 'none', '/delete', 'del']:
            db.update_recurring_message(msg_id, media_file_id="")
            await state.clear()
            await message.answer("✅ Фото удалено!")
        else:
            await message.answer("❌ Отправьте фото или напишите 'удалить'.")

    async def _show_recurring_buttons_menu(callback: CallbackQuery, msg_id: int):
        msg = db.get_recurring_message(msg_id)
        if not msg:
            await callback.answer("❌ Сообщение не найдено!", show_alert=True)
            return
        buttons_raw = msg.get('buttons', '[]')
        try:
            buttons_list = json.loads(buttons_raw) if buttons_raw else []
        except Exception:
            buttons_list = []

        text = f"🔘 <b>Настройка кнопок для сообщения:</b> «{msg['name']}»\n\n"
        if not buttons_list:
            text += "<i>Кнопок пока нет. Вы можете добавить кнопки со стилями primary, danger или success.</i>\n"
        else:
            text += "<b>Текущие кнопки:</b>\n"
            for idx, b in enumerate(buttons_list, 1):
                style_icon = {
                    "primary": "🔵 primary",
                    "danger": "🔴 danger",
                    "success": "🟢 success"
                }.get(b.get('style'), "⚪ обычная")
                target = b.get('url') or b.get('callback_data') or '—'
                text += f"{idx}. <b>{b.get('text', '')}</b> [{style_icon}]\n   🔗 <code>{target}</code>\n"

        menu_buttons = []
        for idx, b in enumerate(buttons_list):
            style_icon = {"primary": "🔵", "danger": "🔴", "success": "🟢"}.get(b.get('style'), "⚪")
            menu_buttons.append([
                InlineKeyboardButton(
                    text=f"🗑 Удалить: {b.get('text', '')[:20]} {style_icon}",
                    callback_data=f"admin_del_rec_btn_{msg_id}_{idx}"
                )
            ])
        menu_buttons.append([
            InlineKeyboardButton(text="➕ Добавить кнопку", callback_data=f"admin_add_rec_btn_{msg_id}")
        ])
        if buttons_list:
            menu_buttons.append([
                InlineKeyboardButton(text="🗑 Очистить все кнопки", callback_data=f"admin_clr_rec_btns_{msg_id}")
            ])
        menu_buttons.append([
            InlineKeyboardButton(text="◀️ Назад к сообщению", callback_data=f"admin_recurring_{msg_id}")
        ])
        await edit_message(callback, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=menu_buttons))

    @dp.callback_query(F.data.startswith('admin_edit_recurring_btns_'))
    async def admin_edit_recurring_btns_callback(callback: CallbackQuery):
        msg_id = int(callback.data.split('_')[-1])
        await _show_recurring_buttons_menu(callback, msg_id)

    @dp.callback_query(F.data.startswith('admin_add_rec_btn_'))
    async def admin_add_rec_btn_callback(callback: CallbackQuery, state: FSMContext):
        msg_id = int(callback.data.split('_')[-1])
        await state.update_data(btn_msg_id=msg_id)
        await state.set_state(RecurringStates.WAITING_BUTTON_TEXT)
        await edit_message(
            callback,
            "🔘 <b>Добавление кнопки (Шаг 1 из 3)</b>\n\n"
            "Введите текст кнопки (например: <code>🔥 Наш канал</code> или <code>💳 Оформить подписку</code>):",
            reply_markup=cancel_inline_keyboard()
        )

    @dp.message(RecurringStates.WAITING_BUTTON_TEXT)
    async def process_recurring_button_text(message: Message, state: FSMContext):
        btn_text = message.text.strip() if message.text else ""
        if not btn_text:
            await message.answer("❌ Введите текст для кнопки:")
            return
        await state.update_data(btn_text=btn_text)
        await state.set_state(RecurringStates.WAITING_BUTTON_URL)
        await message.answer(
            f"🔘 <b>Добавление кнопки (Шаг 2 из 3)</b>\n\n"
            f"Текст кнопки: <b>{btn_text}</b>\n\n"
            f"Введите ссылку (URL) для кнопки (например: <code>https://t.me/username</code>)\n"
            f"<i>Или callback_data (например: <code>sub_menu</code>):</i>",
            reply_markup=cancel_inline_keyboard()
        )

    @dp.message(RecurringStates.WAITING_BUTTON_URL)
    async def process_recurring_button_url(message: Message, state: FSMContext):
        val = message.text.strip() if message.text else ""
        if not val:
            await message.answer("❌ Введите ссылку или callback_data:")
            return

        if val.startswith('t.me/'):
            val = 'https://' + val

        is_url = val.startswith(('http://', 'https://', 'tg://'))
        if is_url:
            await state.update_data(btn_url=val, btn_callback=None)
        else:
            await state.update_data(btn_url=None, btn_callback=val)

        data = await state.get_data()
        msg_id = data.get('btn_msg_id')
        await state.set_state(RecurringStates.WAITING_BUTTON_STYLE)

        style_markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔵 Primary (акцентная/синяя)", callback_data=f"set_btn_style_{msg_id}_primary", style="primary")],
            [InlineKeyboardButton(text="🟢 Success (зелёная)", callback_data=f"set_btn_style_{msg_id}_success", style="success")],
            [InlineKeyboardButton(text="🔴 Danger (красная)", callback_data=f"set_btn_style_{msg_id}_danger", style="danger")],
            [InlineKeyboardButton(text="⚪ Обычная (без стиля)", callback_data=f"set_btn_style_{msg_id}_default")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_action")]
        ])
        await message.answer(
            f"🔘 <b>Добавление кнопки (Шаг 3 из 3)</b>\n\n"
            f"Текст: <b>{data.get('btn_text')}</b>\n"
            f"{'Ссылка' if is_url else 'Действие'}: <code>{val}</code>\n\n"
            f"<b>Выберите стиль кнопки (primary, success, danger):</b>",
            reply_markup=style_markup
        )

    @dp.callback_query(F.data.startswith('set_btn_style_'))
    async def set_btn_style_callback(callback: CallbackQuery, state: FSMContext):
        parts = callback.data.split('_')
        msg_id = int(parts[3])
        style = parts[4]

        data = await state.get_data()
        btn_text = data.get('btn_text')
        btn_url = data.get('btn_url')
        btn_callback = data.get('btn_callback')

        msg = db.get_recurring_message(msg_id)
        if not msg:
            await callback.answer("❌ Сообщение не найдено!", show_alert=True)
            await state.clear()
            return

        buttons_raw = msg.get('buttons', '[]')
        try:
            buttons_list = json.loads(buttons_raw) if buttons_raw else []
        except Exception:
            buttons_list = []

        new_button = {
            "text": btn_text,
            "style": style if style in ('primary', 'danger', 'success') else None
        }
        if btn_url:
            new_button["url"] = btn_url
        if btn_callback:
            new_button["callback_data"] = btn_callback

        buttons_list.append(new_button)
        db.update_recurring_message(msg_id, buttons=json.dumps(buttons_list, ensure_ascii=False))
        await state.clear()
        await callback.answer("✅ Кнопка добавлена!", show_alert=True)
        await _show_recurring_buttons_menu(callback, msg_id)

    @dp.callback_query(F.data.startswith('admin_del_rec_btn_'))
    async def admin_del_rec_btn_callback(callback: CallbackQuery):
        parts = callback.data.split('_')
        msg_id = int(parts[4])
        idx = int(parts[5])

        msg = db.get_recurring_message(msg_id)
        if msg:
            buttons_raw = msg.get('buttons', '[]')
            try:
                buttons_list = json.loads(buttons_raw) if buttons_raw else []
            except Exception:
                buttons_list = []
            if 0 <= idx < len(buttons_list):
                buttons_list.pop(idx)
                db.update_recurring_message(msg_id, buttons=json.dumps(buttons_list, ensure_ascii=False))
                await callback.answer("✅ Кнопка удалена!")
        await _show_recurring_buttons_menu(callback, msg_id)

    @dp.callback_query(F.data.startswith('admin_clr_rec_btns_'))
    async def admin_clr_rec_btns_callback(callback: CallbackQuery):
        msg_id = int(callback.data.split('_')[-1])
        db.update_recurring_message(msg_id, buttons="[]")
        await callback.answer("✅ Все кнопки удалены!")
        await _show_recurring_buttons_menu(callback, msg_id)

    @dp.callback_query(F.data.startswith('admin_toggle_recurring_'))
    async def admin_toggle_recurring_callback(callback: CallbackQuery):
        msg_id = int(callback.data.split('_')[-1])
        db.toggle_recurring_message(msg_id)
        await callback.answer("✅ Статус изменён!", show_alert=True)
        await _show_recurring_item(callback, msg_id)

    @dp.callback_query(F.data.startswith('admin_send_recurring_'))
    async def admin_send_recurring_callback(callback: CallbackQuery):
        msg_id = int(callback.data.split('_')[-1])
        msg = db.get_recurring_message(msg_id)
        if not msg:
            await callback.answer("❌ Не найдено!", show_alert=True)
            return
        await callback.answer("🚀 Запуск рассылки...")
        status_msg = await callback.message.answer("⏳ Рассылка выполняется...")
        success, failed = await send_recurring_message_to_users(bot, db, msg_id)
        await status_msg.edit_text(
            f"✅ <b>Рассылка завершена!</b>\n\n"
            f"📬 Доставлено: <b>{success}</b>\n"
            f"❌ Ошибок / заблокировано: <b>{failed}</b>"
        )
        await _show_recurring_item(callback, msg_id)

    @dp.callback_query(F.data.startswith('admin_del_recurring_'))
    async def admin_del_recurring_callback(callback: CallbackQuery):
        msg_id = int(callback.data.split('_')[-1])
        db.delete_recurring_message(msg_id)
        await callback.answer("✅ Удалено!", show_alert=True)
        await admin_recurring_callback(callback)

    @dp.callback_query(F.data == "admin_mirrors")
    async def admin_mirrors_callback(callback: CallbackQuery):
        mirrors = db.get_all_mirrors()
        buttons = [[InlineKeyboardButton(text=f"🪞 @{m['bot_username'] or 'unknown'} {'✅' if m['is_active'] == 1 else '❌'}", callback_data=f"admin_mirror_{m['id']}")] for m in mirrors]
        buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin_panel")])
        markup = InlineKeyboardMarkup(inline_keyboard=buttons)
        await edit_message(callback, "🪞 <b>Управление зеркалами</b>", reply_markup=markup)

    async def _show_admin_mirror_item(callback: CallbackQuery, mirror_id: int):
        mirror = db.get_mirror(mirror_id)
        if not mirror:
            await callback.answer("❌ Зеркало не найдено!", show_alert=True)
            return
        status = "🟢 Активно" if mirror['is_active'] == 1 else "🔴 Остановлено"
        text = f"🪞 <b>Зеркало #{mirror_id}</b>\n\n@{mirror.get('bot_username', 'unknown')}\nСтатус: {status}"
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Переключить", callback_data=f"admin_toggle_mirror_{mirror_id}")],
            [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"admin_del_mirror_{mirror_id}")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_mirrors")]
        ])
        await edit_message(callback, text, reply_markup=markup)

    @dp.callback_query(F.data.startswith('admin_mirror_'))
    async def admin_mirror_item_callback(callback: CallbackQuery):
        mirror_id = int(callback.data.split('_')[-1])
        await _show_admin_mirror_item(callback, mirror_id)

    @dp.callback_query(F.data.startswith('admin_toggle_mirror_'))
    async def admin_toggle_mirror_callback(callback: CallbackQuery):
        mirror_id = int(callback.data.split('_')[-1])
        db.toggle_mirror(mirror_id, ADMIN)
        await callback.answer("✅ Статус изменён!", show_alert=True)
        await _show_admin_mirror_item(callback, mirror_id)

    @dp.callback_query(F.data.startswith('admin_del_mirror_'))
    async def admin_del_mirror_callback(callback: CallbackQuery):
        mirror_id = int(callback.data.split('_')[-1])
        db.delete_mirror(mirror_id, ADMIN)
        await callback.answer("✅ Зеркало удалено!", show_alert=True)
        await admin_mirrors_callback(callback)

    @dp.callback_query(F.data == "admin_panel")
    async def admin_panel_back(callback: CallbackQuery, state: FSMContext):
        await state.clear()
        user_id = callback.from_user.id
        user = db.get_user(user_id)
        if user_id != ADMIN and (not user or user.get('is_admin') != 1):
            await callback.answer("❌ Доступ запрещён!", show_alert=True)
            return
        users = db.get_all_users()
        sub_count = sum(1 for u in users if u.get('subscription_until', 0) > int(time.time()))
        buttons = [
            [InlineKeyboardButton(text="📁 Паки и Категории", callback_data="admin_manage_packs")],
            [InlineKeyboardButton(text="💳 Тарифы", callback_data="admin_manage_tariffs"),
             InlineKeyboardButton(text="👤 Выдать подписку", callback_data="admin_give_sub")],
            [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
            [InlineKeyboardButton(text="📥 Выгрузка сессий", callback_data="admin_export_sessions"),
             InlineKeyboardButton(text="✅ Чек сессий", callback_data="admin_check_sessions")],
            [InlineKeyboardButton(text="📢 Обязательная подписка", callback_data="admin_mandatory_sub")],
            [InlineKeyboardButton(text="🔄 Рекуррентные сообщения", callback_data="admin_recurring")],
            [InlineKeyboardButton(text="🪞 Зеркала", callback_data="admin_mirrors")],
            [InlineKeyboardButton(text="🎁 Промокоды", callback_data="admin_manage_promos")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_main")]
        ]
        markup = InlineKeyboardMarkup(inline_keyboard=buttons)
        text = f"👑 <b>Админ-панель</b>\n\n👤 Пользователей: <b>{len(users)}</b>\n🟢 Активных подписок: <b>{sub_count}</b>"
        await edit_message(callback, text, reply_markup=markup)

    @dp.callback_query(F.data == "admin_manage_promos")
    async def admin_manage_promos_callback(callback: CallbackQuery):
        promos = db.get_all_promo_codes()
        buttons = []
        for p in promos:
            status = "🟢" if p['is_active'] == 1 else "🔴"
            buttons.append([InlineKeyboardButton(
                text=f"{status} {p['code']} ({p['days']} дн.)",
                callback_data=f"admin_promo_{p['id']}"
            )])
        buttons.append([InlineKeyboardButton(text="➕ Создать промокод", callback_data="admin_add_promo")])
        buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin_panel")])
        markup = InlineKeyboardMarkup(inline_keyboard=buttons)
        await edit_message(callback, "🎁 <b>Управление промокодами</b>", markup)

    async def _show_admin_promo_item(callback: CallbackQuery, promo_id: int):
        promo = None
        for p in db.get_all_promo_codes():
            if p['id'] == promo_id:
                promo = p
                break
        if not promo:
            await callback.answer("❌ Не найдено!", show_alert=True)
            return
        uses = db.get_promo_code_uses(promo_id)
        status = "🟢 Активен" if promo['is_active'] == 1 else "🔴 Деактивирован"
        text = (
            f"🎁 <b>Промокод</b>\n\n"
            f"Код: <code>{promo['code']}</code>\n"
            f"Дней: <b>{promo['days']}</b>\n"
            f"Использований: <b>{promo['used_count']}/{promo['max_uses']}</b>\n"
            f"Статус: {status}"
        )
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Переключить", callback_data=f"admin_toggle_promo_{promo_id}")],
            [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"admin_del_promo_{promo_id}")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_manage_promos")]
        ])
        await edit_message(callback, text, markup)

    @dp.callback_query(F.data.startswith('admin_promo_'))
    async def admin_promo_item_callback(callback: CallbackQuery):
        promo_id = int(callback.data.split('_')[-1])
        await _show_admin_promo_item(callback, promo_id)

    @dp.callback_query(F.data == "admin_add_promo")
    async def admin_add_promo_callback(callback: CallbackQuery, state: FSMContext):
        await state.set_state(AdminPromoStates.WAITING_PROMO_CODE)
        await edit_message(callback, "🎁 <b>Новый промокод</b>\n\nВведите код:", reply_markup=cancel_inline_keyboard())

    @dp.message(AdminPromoStates.WAITING_PROMO_CODE)
    async def process_promo_code_name(message: Message, state: FSMContext):
        await state.update_data(promo_code=message.text.strip().upper())
        await state.set_state(AdminPromoStates.WAITING_PROMO_DAYS)
        await message.answer("📅 Введите количество дней подписки:", reply_markup=cancel_inline_keyboard())

    @dp.message(AdminPromoStates.WAITING_PROMO_DAYS)
    async def process_promo_days(message: Message, state: FSMContext):
        try:
            days = int(message.text.strip())
            await state.update_data(promo_days=days)
            await state.set_state(AdminPromoStates.WAITING_PROMO_MAX_USES)
            await message.answer("🔢 Введите макс. количество использований:", reply_markup=cancel_inline_keyboard())
        except:
            await message.answer("❌ Введите число!")

    @dp.message(AdminPromoStates.WAITING_PROMO_MAX_USES)
    async def process_promo_max_uses(message: Message, state: FSMContext):
        try:
            max_uses = int(message.text.strip())
            data = await state.get_data()
            db.create_promo_code(data.get('promo_code'), data.get('promo_days'), max_uses)
            await state.clear()
            await message.answer(f"✅ Промокод <code>{data.get('promo_code')}</code> создан!")
        except:
            await message.answer("❌ Введите число!")

    @dp.callback_query(F.data.startswith('admin_toggle_promo_'))
    async def admin_toggle_promo_callback(callback: CallbackQuery):
        promo_id = int(callback.data.split('_')[-1])
        promo = None
        for p in db.get_all_promo_codes():
            if p['id'] == promo_id:
                promo = p
                break
        if promo:
            db.c.execute('UPDATE promo_codes SET is_active = CASE WHEN is_active = 1 THEN 0 ELSE 1 END WHERE id = ?', (promo_id,))
            db.conn.commit()
        await callback.answer("✅ Статус изменён!", show_alert=True)
        await _show_admin_promo_item(callback, promo_id)

    @dp.callback_query(F.data.startswith('admin_del_promo_'))
    async def admin_del_promo_callback(callback: CallbackQuery):
        promo_id = int(callback.data.split('_')[-1])
        db.delete_promo_code(promo_id)
        await callback.answer("✅ Удалено!", show_alert=True)
        await admin_manage_promos_callback(callback)

    # ==================== CHAT PACKS CATALOG (User View) ====================
    @dp.message(F.text == '📁 Каталог папок с чатами')
    async def chat_catalog_handler(message: Message, state: FSMContext):
        await state.clear()
        user_id = message.from_user.id
        if not db.is_user_subscribed(user_id, ADMIN):
            await message.answer("🔒 Для доступа к каталогу требуется активная подписка.")
            return
        categories = db.get_categories()
        if not categories:
            await message.answer("📭 Каталог пуст.")
            return
        buttons = [[InlineKeyboardButton(text=f"📁 {c['name']}", callback_data=f"user_category_{c['id']}")] for c in categories]
        markup = InlineKeyboardMarkup(inline_keyboard=buttons)
        await send_photo(message, 'catalog.jpg', "📁 <b>Каталог папок с чатами</b>", markup)

    @dp.callback_query(F.data.startswith('user_category_'))
    async def user_category_callback(callback: CallbackQuery):
        category_id = int(callback.data.split('_')[2])
        packs = db.get_packs_in_category(category_id)
        if not packs:
            await callback.answer("📭 В этой категории нет паков!", show_alert=True)
            return
        buttons = [[InlineKeyboardButton(text=f"📦 {p['name']} ({p['chats_count']} чатов)", callback_data=f"user_pack_{p['id']}")] for p in packs]
        buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_catalog")])
        markup = InlineKeyboardMarkup(inline_keyboard=buttons)
        await edit_message(callback, "📦 <b>Паки в категории</b>", reply_markup=markup)

    @dp.callback_query(F.data.startswith('user_pack_'))
    async def user_pack_callback(callback: CallbackQuery):
        pack_id = int(callback.data.split('_')[2])
        pack = db.get_pack(pack_id)
        if not pack:
            await callback.answer("❌ Пак не найден!", show_alert=True)
            return
        chats = db.get_pack_chats(pack_id)
        text = f"📦 <b>{pack['name']}</b>\n\n{pack['description']}\n\n"
        for c in chats:
            text += f"• {c['chat_url']}\n"
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📥 Вступить в чаты", callback_data=f"join_pack_{pack_id}")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data=f"user_category_{pack['category_id']}")]
        ])
        await edit_message(callback, text, reply_markup=markup)

    @dp.callback_query(lambda c: c.data and c.data.startswith('join_pack_') and c.data.split('_')[2].isdigit())
    async def join_pack_callback(callback: CallbackQuery, state: FSMContext):
        await state.clear()
        pack_id = int(callback.data.split('_')[2])
        pack = db.get_pack(pack_id)
        if not pack:
            await callback.answer("❌ Пак не найден!", show_alert=True)
            return
        chats = db.get_pack_chats(pack_id)
        if not chats:
            await callback.answer("📭 В паке нет чатов!", show_alert=True)
            return
        user_id = callback.from_user.id
        accounts = db.get_user_accounts(user_id)
        if not accounts:
            await callback.answer("📱 У вас нет аккаунтов!", show_alert=True)
            return
        if len(accounts) == 1:
            account_id = accounts[0]['id']
            chat_urls = [c['chat_url'] for c in chats]
            asyncio.create_task(account_manager.run_limited(account_manager.join_chats_batch(account_id, chat_urls, bot, user_id)))
            await callback.answer(f"🚀 Вступление запущено на аккаунте {accounts[0].get('account_name', f'#{account_id}')}", show_alert=True)
        else:
            buttons = []
            for acc in accounts:
                name = acc.get('account_name') or f"Аккаунт #{acc['id']}"
                buttons.append([InlineKeyboardButton(text=f"📱 {name}", callback_data=f"join_pack_acc_{pack_id}_{acc['id']}")])
            buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data=f"user_pack_{pack_id}")])
            markup = InlineKeyboardMarkup(inline_keyboard=buttons)
            await edit_message(callback, "📱 <b>Выберите аккаунт для вступления:</b>", markup)

    @dp.callback_query(F.data.startswith('join_pack_acc_'))
    async def join_pack_acc_callback(callback: CallbackQuery, state: FSMContext):
        await state.clear()
        parts = callback.data.split('_')
        pack_id = int(parts[3])
        account_id = int(parts[4])
        pack = db.get_pack(pack_id)
        account = db.get_account(account_id)
        if not pack or not account:
            await callback.answer("❌ Ошибка!", show_alert=True)
            return
        chats = db.get_pack_chats(pack_id)
        chat_urls = [c['chat_url'] for c in chats]
        user_id = callback.from_user.id
        asyncio.create_task(account_manager.run_limited(account_manager.join_chats_batch(account_id, chat_urls, bot, user_id)))
        acc_name = account.get('account_name') or f"#{account_id}"
        await callback.answer(f"🚀 Вступление запущено на {acc_name}!", show_alert=True)

    @dp.callback_query(F.data == "back_to_catalog")
    async def back_to_catalog_callback(callback: CallbackQuery):
        categories = db.get_categories()
        buttons = [[InlineKeyboardButton(text=f"📁 {c['name']}", callback_data=f"user_category_{c['id']}")] for c in categories]
        markup = InlineKeyboardMarkup(inline_keyboard=buttons)
        await edit_message(callback, "📁 <b>Каталог папок с чатами</b>", reply_markup=markup)

    # ==================== POST SETTINGS ====================
    @dp.callback_query(F.data.startswith('acc_post_'))
    async def acc_post_callback(callback: CallbackQuery, state: FSMContext):
        account_id = int(callback.data.split('_')[2])
        await state.clear()
        account = db.get_account(account_id)
        if not account:
            await callback.answer("❌ Аккаунт не найден!", show_alert=True)
            return
        text = (
            f"📝 <b>Настройки поста</b> для {account.get('account_name', f'#{account_id}')}\n\n"
            f"Текущий текст: {account.get('post_text', 'Не задан')[:100]}\n"
            f"Медиа: {'Да' if account.get('post_photo') else 'Нет'}"
        )
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Изменить текст", callback_data=f"set_post_text_{account_id}")],
            [InlineKeyboardButton(text="🖼 Добавить фото", callback_data=f"set_post_photo_{account_id}")],
            [InlineKeyboardButton(text="🗑 Удалить фото", callback_data=f"del_post_photo_{account_id}")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data=f"manage_acc_{account_id}")]
        ])
        await edit_message(callback, text, reply_markup=markup)

    @dp.callback_query(F.data.startswith('set_post_text_'))
    async def set_post_text_callback(callback: CallbackQuery, state: FSMContext):
        account_id = int(callback.data.split('_')[3])
        await state.update_data(edit_post_account_id=account_id)
        await state.set_state(AccountPostStates.WAITING_TEXT)
        await edit_message(callback, "📝 Введите текст поста:", reply_markup=cancel_inline_keyboard())

    @dp.message(AccountPostStates.WAITING_TEXT)
    async def process_post_text(message: Message, state: FSMContext):
        data = await state.get_data()
        account_id = data.get('edit_post_account_id')
        text = message.text or ''
        entities_json = None
        if message.entities:
            entities_json = json.dumps([{
                'type': e.type,
                'offset': e.offset,
                'length': e.length,
                'url': e.url if hasattr(e, 'url') else None,
                'user': e.user.id if hasattr(e, 'user') and e.user else None,
                'custom_emoji_id': e.custom_emoji_id if hasattr(e, 'custom_emoji_id') else None,
                'language': e.language if hasattr(e, 'language') else None
            } for e in message.entities])
        parse_mode = 'HTML' if any(tag in text for tag in ['<b>', '<i>', '<u>', '<s>', '<spoiler>', '<code>']) else 'Markdown' if any(tag in text for tag in ['*', '_', '`']) else 'HTML'
        # ⭐ НЕ сохраняем parse_mode - используем только entities
        db.update_account_post(account_id, text, parse_mode=None, entities=entities_json)
        await state.clear()
        await message.answer(f"✅ Текст поста обновлён!\n📋 Режим разметки: {parse_mode}")

    @dp.callback_query(F.data.startswith('set_post_photo_'))
    async def set_post_photo_callback(callback: CallbackQuery, state: FSMContext):
        account_id = int(callback.data.split('_')[3])
        await state.update_data(edit_post_account_id=account_id)
        await state.set_state(AccountPostStates.WAITING_PHOTO)
        await edit_message(callback, "🖼 Отправите фото для поста:", reply_markup=cancel_inline_keyboard())

    @dp.message(AccountPostStates.WAITING_PHOTO)
    async def process_post_photo(message: Message, state: FSMContext):
        data = await state.get_data()
        account_id = data.get('edit_post_account_id')
        if message.photo:
            photo = message.photo[-1]
            db.update_account_photo(account_id, photo.file_id)
            if message.caption:
                entities_json = None
                if message.caption_entities:
                    entities_json = json.dumps([{
                        'type': e.type,
                        'offset': e.offset,
                        'length': e.length,
                        'url': e.url if hasattr(e, 'url') else None,
                        'user': e.user.id if hasattr(e, 'user') and e.user else None,
                        'custom_emoji_id': e.custom_emoji_id if hasattr(e, 'custom_emoji_id') else None,
                        'language': e.language if hasattr(e, 'language') else None
                    } for e in message.caption_entities])
                db.update_account_post(account_id, message.caption or '', parse_mode='ENTITIES' if entities_json else 'HTML', entities=entities_json)
            await state.clear()
            await message.answer("✅ Фото добавлено к посту!")
        else:
            await message.answer("❌ Отправите фото!")

    @dp.callback_query(F.data.startswith('del_post_photo_'))
    async def del_post_photo_callback(callback: CallbackQuery):
        account_id = int(callback.data.split('_')[3])
        db.update_account_photo(account_id, '')
        await callback.answer("✅ Фото удалено!", show_alert=True)
        await render_account_dashboard(callback, account_id, callback.from_user.id)

    @dp.callback_query(F.data.startswith('acc_timeout_'))
    async def acc_timeout_callback(callback: CallbackQuery, state: FSMContext):
        account_id = int(callback.data.split('_')[2])
        await state.update_data(edit_timeout_account_id=account_id)
        await state.set_state(AccountPostStates.WAITING_TIMEOUT)
        await edit_message(callback, "⏱ Введите интервал между циклами (в минутах):", reply_markup=cancel_inline_keyboard())

    @dp.message(AccountPostStates.WAITING_TIMEOUT)
    async def process_timeout(message: Message, state: FSMContext):
        data = await state.get_data()
        account_id = data.get('edit_timeout_account_id')
        try:
            timeout = int(message.text.strip())
            db.update_account_timeout(account_id, timeout)
            await state.clear()
            await message.answer(f"✅ Интервал установлен: {timeout} мин.")
        except:
            await message.answer("❌ Введите число!")

    # ==================== CHAT MANAGEMENT (Selective & Mass Leave) ====================
    GROUP_TYPES = db.GROUP_CHAT_TYPES

    async def render_acc_chats(callback: CallbackQuery, account_id: int, page: int = 0):
        # Для постинга по чатам нужны ТОЛЬКО группы/супергруппы — каналы, боты и ЛС исключены
        page_chats, total = db.get_account_chats_paginated(
            account_id, page=page, per_page=CHATS_PER_PAGE, chat_types=GROUP_TYPES
        )
        if total == 0:
            total_any = db.count_account_chats(account_id)
            if total_any:
                await callback.answer(
                    "💬 Групп не найдено. Нажмите «Синхронизировать чаты» — старые записи без типа нужно обновить.",
                    show_alert=True
                )
            else:
                await callback.answer("💬 Нет чатов. Сначала синхронизируйте!", show_alert=True)
            return

        total_pages = max(1, (total + CHATS_PER_PAGE - 1) // CHATS_PER_PAGE)
        if page >= total_pages:
            page = total_pages - 1
            page_chats, total = db.get_account_chats_paginated(
                account_id, page=page, per_page=CHATS_PER_PAGE, chat_types=GROUP_TYPES
            )

        enabled_count = db.count_account_chats(account_id, chat_types=GROUP_TYPES, spam_only=True)

        buttons = []
        for chat in page_chats:
            icon = "✅" if chat.get('spam_enabled') == 1 else "❌"
            title = chat.get('chat_title') or chat['chat_id']
            # page передаём в callback, чтобы после переключения остаться на той же странице
            buttons.append([InlineKeyboardButton(
                text=f"{icon} {title[:30]}",
                callback_data=f"toggle_chat_{account_id}_{page}_{chat['chat_id']}"
            )])
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton(text="⬅️", callback_data=f"acc_chats_{account_id}_{page-1}"))
        nav_buttons.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="noop"))
        if page < total_pages - 1:
            nav_buttons.append(InlineKeyboardButton(text="➡️", callback_data=f"acc_chats_{account_id}_{page+1}"))
        buttons.append(nav_buttons)
        buttons.append([
            InlineKeyboardButton(text="✅ Включить все", callback_data=f"enable_all_chats_{account_id}_{page}"),
            InlineKeyboardButton(text="❌ Отключить все", callback_data=f"disable_all_chats_{account_id}_{page}")
        ])
        buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data=f"manage_acc_{account_id}")])
        markup = InlineKeyboardMarkup(inline_keyboard=buttons)
        await edit_message(
            callback,
            f"💬 <b>Выбор групп для постинга</b>\n\n"
            f"Групп всего: {total} | Выбрано: {enabled_count}\n"
            f"Страница {page+1}/{total_pages}",
            reply_markup=markup
        )

    @dp.callback_query(F.data == "noop")
    async def noop_callback(callback: CallbackQuery):
        await callback.answer()

    @dp.callback_query(F.data.startswith('acc_chats_'))
    async def acc_chats_callback(callback: CallbackQuery):
        parts = callback.data.split('_')
        account_id = int(parts[2])
        page = int(parts[3]) if len(parts) > 3 else 0
        await render_acc_chats(callback, account_id, page)

    @dp.callback_query(F.data.startswith('toggle_chat_'))
    async def toggle_chat_callback(callback: CallbackQuery):
        # toggle_chat_{account_id}_{page}_{chat_id}
        parts = callback.data.split('_')
        account_id = int(parts[2])
        try:
            page = int(parts[3])
            chat_id = '_'.join(parts[4:])
        except (ValueError, IndexError):
            page = 0
            chat_id = '_'.join(parts[3:])
        new_state = db.toggle_chat_spam(account_id, chat_id)
        await callback.answer(f"{'✅ Включен' if new_state == 1 else '❌ Отключен'}!", show_alert=False)
        # Остаёмся на текущей странице
        await render_acc_chats(callback, account_id, page)

    @dp.callback_query(F.data.startswith('enable_all_chats_'))
    async def enable_all_chats_callback(callback: CallbackQuery):
        parts = callback.data.split('_')
        account_id = int(parts[3])
        page = int(parts[4]) if len(parts) > 4 else 0
        db.set_all_chats_spam(account_id, 1, chat_types=GROUP_TYPES)
        await callback.answer("✅ Все группы включены!", show_alert=False)
        await render_acc_chats(callback, account_id, page)

    @dp.callback_query(F.data.startswith('disable_all_chats_'))
    async def disable_all_chats_callback(callback: CallbackQuery):
        parts = callback.data.split('_')
        account_id = int(parts[3])
        page = int(parts[4]) if len(parts) > 4 else 0
        db.set_all_chats_spam(account_id, 0, chat_types=GROUP_TYPES)
        await callback.answer("❌ Все группы отключены!", show_alert=False)
        await render_acc_chats(callback, account_id, page)

    async def render_massleave(callback: CallbackQuery, account_id: int, page: int = 0):
        page_chats, total = db.get_account_chats_paginated(account_id, page=page, per_page=CHATS_PER_PAGE)
        if total == 0:
            await callback.answer("💬 Нет чатов для выхода!", show_alert=True)
            return
        total_pages = max(1, (total + CHATS_PER_PAGE - 1) // CHATS_PER_PAGE)
        if page >= total_pages:
            page = total_pages - 1
            page_chats, total = db.get_account_chats_paginated(account_id, page=page, per_page=CHATS_PER_PAGE)
        user_id = callback.from_user.id
        selected = user_selected_leave_chats.setdefault(user_id, set())
        buttons = []
        for chat in page_chats:
            icon = "☑️" if chat['chat_id'] in selected else "⬜"
            title = chat.get('chat_title') or chat['chat_id']
            type_icon = {'group': '👥', 'channel': '📢', 'private': '👤', 'bot': '🤖'}.get(chat.get('chat_type'), '💬')
            buttons.append([InlineKeyboardButton(
                text=f"{icon} {type_icon} {title[:28]}",
                callback_data=f"select_leave_{account_id}_{page}_{chat['chat_id']}"
            )])
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton(text="⬅️", callback_data=f"acc_massleave_{account_id}_{page-1}"))
        nav_buttons.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="noop"))
        if page < total_pages - 1:
            nav_buttons.append(InlineKeyboardButton(text="➡️", callback_data=f"acc_massleave_{account_id}_{page+1}"))
        buttons.append(nav_buttons)
        buttons.append([InlineKeyboardButton(text=f"🚪 Выйти из выбранных ({len(selected)})", callback_data=f"confirm_leave_{account_id}")])
        buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data=f"manage_acc_{account_id}")])
        markup = InlineKeyboardMarkup(inline_keyboard=buttons)
        await edit_message(callback, f"🚪 <b>Массовый выход из чатов</b>\n\nВсего: {total} | Страница {page+1}/{total_pages}", reply_markup=markup)

    @dp.callback_query(F.data.startswith('acc_massleave_'))
    async def acc_massleave_callback(callback: CallbackQuery):
        parts = callback.data.split('_')
        account_id = int(parts[2])
        page = int(parts[3]) if len(parts) > 3 else 0
        await render_massleave(callback, account_id, page)

    @dp.callback_query(F.data.startswith('select_leave_'))
    async def select_leave_callback(callback: CallbackQuery):
        parts = callback.data.split('_')
        account_id = int(parts[2])
        try:
            page = int(parts[3])
            chat_id = '_'.join(parts[4:])
        except (ValueError, IndexError):
            page = 0
            chat_id = '_'.join(parts[3:])
        user_id = callback.from_user.id
        selected = user_selected_leave_chats.setdefault(user_id, set())
        if chat_id in selected:
            selected.discard(chat_id)
        else:
            selected.add(chat_id)
        await callback.answer()
        await render_massleave(callback, account_id, page)

    @dp.callback_query(F.data.startswith('confirm_leave_'))
    async def confirm_leave_callback(callback: CallbackQuery):
        account_id = int(callback.data.split('_')[2])
        user_id = callback.from_user.id
        selected = user_selected_leave_chats.get(user_id, set())
        if not selected:
            await callback.answer("❌ Выберите чаты!", show_alert=True)
            return
        chats_list = list(selected)
        asyncio.create_task(account_manager.run_limited(account_manager.leave_chats_batch(account_id, chats_list, bot, user_id)))
        user_selected_leave_chats[user_id] = set()
        await callback.answer("🚪 Выход запущен!", show_alert=True)
        await render_account_dashboard(callback, account_id, user_id)

    # ==================== JOIN CHATS ====================
    @dp.callback_query(F.data.startswith('acc_join_pack_'))
    async def acc_join_pack_callback(callback: CallbackQuery):
        account_id = int(callback.data.split('_')[3])
        categories = db.get_categories()
        if not categories:
            await callback.answer("📭 Каталог пуст!", show_alert=True)
            return
        buttons = [[InlineKeyboardButton(text=f"📁 {c['name']}", callback_data=f"join_pack_cat_{account_id}_{c['id']}")] for c in categories]
        buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data=f"manage_acc_{account_id}")])
        markup = InlineKeyboardMarkup(inline_keyboard=buttons)
        await edit_message(callback, "📦 <b>Выберите категорию:</b>", markup)

    @dp.callback_query(F.data.startswith('acc_join_'))
    async def acc_join_callback(callback: CallbackQuery, state: FSMContext):
        account_id = int(callback.data.split('_')[2])
        await state.update_data(join_account_id=account_id)
        await state.set_state(ChatManagementStates.WAITING_TXT_FILE)
        await edit_message(callback, 
            "📥 <b>Вступить в чаты</b>\n\n"
            "Отправьте текст со ссылками на чаты (по одной на строку)\n"
            "Или файл .txt со ссылками\n"
            "Или ссылку на папку чатов (addlist):",
            reply_markup=cancel_inline_keyboard()
        )

    @dp.callback_query(F.data.startswith('join_pack_cat_'))
    async def join_pack_cat_callback(callback: CallbackQuery):
        parts = callback.data.split('_')
        account_id = int(parts[3])
        category_id = int(parts[4])
        packs = db.get_packs_in_category(category_id)
        if not packs:
            await callback.answer("📭 В категории нет паков!", show_alert=True)
            return
        buttons = [[InlineKeyboardButton(text=f"📦 {p['name']} ({p['chats_count']} чатов)", callback_data=f"join_pack_acc_{p['id']}_{account_id}")] for p in packs]
        buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data=f"acc_join_pack_{account_id}")])
        markup = InlineKeyboardMarkup(inline_keyboard=buttons)
        await edit_message(callback, "📦 <b>Выберите пак:</b>", markup)

    @dp.message(ChatManagementStates.WAITING_TXT_FILE)
    async def process_join_chats(message: Message, state: FSMContext):
        data = await state.get_data()
        account_ids = data.get('join_account_ids') or [data.get('join_account_id')]
        user_id = message.from_user.id
        links = []
        if message.text:
            links = [l.strip() for l in message.text.strip().split('\n') if l.strip()]
        elif message.document:
            try:
                file = await bot.get_file(message.document.file_id)
                content = await bot.download_file(file.file_path)
                text = content.read().decode('utf-8')
                links = [l.strip() for l in text.split('\n') if l.strip()]
            except Exception as e:
                await message.answer(f"❌ Ошибка чтения файла: {e}")
                return
        if not links:
            await message.answer("❌ Нет ссылок!")
            return
        
        for account_id in account_ids:
            if account_id:
                asyncio.create_task(account_manager.run_limited(account_manager.join_chats_batch(account_id, links, bot, user_id)))
        
        await state.clear()
        await message.answer(f"🚀 Вступление запущено на {len(account_ids)} аккаунтах! Обрабатываю {len(links)} ссылок...")

    # ==================== PROXY MANAGEMENT ====================
    @dp.callback_query(F.data.startswith('acc_proxy_'))
    async def acc_proxy_callback(callback: CallbackQuery, state: FSMContext):
        account_id = int(callback.data.split('_')[2])
        await state.update_data(proxy_account_id=account_id)
        account = db.get_account(account_id)
        current_proxy = account.get('proxy', '') if account else 'Не задан'
        await state.set_state(AddAccountStates.WAITING_PROXY)
        await edit_message(callback, 
            f"🌐 <b>Прокси</b>\n\nТекущее: <code>{current_proxy}</code>\n\n"
            "Введите новое прокси или «удалить» для очистки:",
            reply_markup=cancel_inline_keyboard()
        )

    @dp.message(AddAccountStates.WAITING_PROXY)
    async def process_new_proxy(message: Message, state: FSMContext):
        data = await state.get_data()
        account_id = data.get('proxy_account_id')
        proxy_str = message.text.strip()
        if proxy_str.lower() in ('удалить', 'delete', 'убрать'):
            db.update_account_proxy(account_id, '')
            await state.clear()
            await message.answer("✅ Прокси удалён!")
            return
        parsed = parse_proxy_string(proxy_str)
        if not parsed:
            await message.answer("❌ Неверный формат прокси!")
            return
        db.update_account_proxy(account_id, proxy_str)
        await state.clear()
        await message.answer("✅ Прокси обновлён!")

    # ==================== BIO & AUTORESPONDER ====================
    @dp.callback_query(F.data.startswith('acc_bio_'))
    async def acc_bio_callback(callback: CallbackQuery, state: FSMContext):
        account_id = int(callback.data.split('_')[2])
        await state.update_data(bio_account_id=account_id)
        await state.set_state(AccountSettingsStates.WAITING_FOR_BIO)
        await edit_message(callback, "👤 Введите новый BIO:", reply_markup=cancel_inline_keyboard())

    @dp.message(AccountSettingsStates.WAITING_FOR_BIO)
    async def process_new_bio(message: Message, state: FSMContext):
        data = await state.get_data()
        account_id = data.get('bio_account_id')
        ok, err = await account_manager.change_account_bio(account_id, message.text.strip())
        await state.clear()
        if ok:
            await message.answer("✅ BIO изменено!")
        else:
            await message.answer(f"❌ Ошибка: {err}")

    @dp.callback_query(F.data.startswith('acc_autoresponder_'))
    async def acc_autoresponder_callback(callback: CallbackQuery, state: FSMContext):
        account_id = int(callback.data.split('_')[2])
        account = db.get_account(account_id)
        if not account:
            await callback.answer("❌ Аккаунт не найден!", show_alert=True)
            return
        enabled = account.get('autoresponder_enabled', 0)
        text = account.get('autoresponder_text', '')
        status = "🟢 Включен" if enabled == 1 else "🔴 Выключен"
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Изменить текст", callback_data=f"set_autoresponder_text_{account_id}")],
            [InlineKeyboardButton(text="✅ Включить" if enabled != 1 else "❌ Выключить", callback_data=f"toggle_autoresponder_{account_id}")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data=f"manage_acc_{account_id}")]
        ])
        await edit_message(callback, 
            f"🤖 <b>Автоответчик</b>\n\nСтатус: {status}\nТекст: {text[:100] or 'Не задан'}",
            reply_markup=markup
        )

    @dp.callback_query(F.data.startswith('set_autoresponder_text_'))
    async def set_autoresponder_text_callback(callback: CallbackQuery, state: FSMContext):
        account_id = int(callback.data.split('_')[3])
        await state.update_data(autoresponder_account_id=account_id)
        await state.set_state(AccountSettingsStates.WAITING_FOR_AUTORESPONDER)
        await edit_message(callback, "🤖 Введите текст автоответчика:", reply_markup=cancel_inline_keyboard())

    @dp.message(AccountSettingsStates.WAITING_FOR_AUTORESPONDER)
    async def process_autoresponder_text(message: Message, state: FSMContext):
        data = await state.get_data()
        account_id = data.get('autoresponder_account_id')
        
        media_path = ""
        media_type = ""
        # ⭐ ЧИСТЫЙ ТЕКСТ без тегов + ENTITIES отдельно
        text = message.text or message.caption or ""
        text = text.strip()
        
        # ⭐ КОПИРУЕМ ENTITIES из входящего сообщения
        entities_json = None
        caption_entities = message.caption_entities if message.caption_entities else (message.entities if message.entities else None)
        if caption_entities:
            entities_json = json.dumps([{
                'type': e.type,
                'offset': e.offset,
                'length': e.length,
                'custom_emoji_id': e.custom_emoji_id if hasattr(e, 'custom_emoji_id') else None,
                'language': e.language if hasattr(e, 'language') else None,
                'url': e.url if hasattr(e, 'url') else None,
                'user_id': e.user.id if hasattr(e, 'user') and e.user else None,
            } for e in caption_entities])
        
        import os
        os.makedirs('img', exist_ok=True)
        
        if message.photo:
            file_id = message.photo[-1].file_id
            media_path = f"img/ar_{account_id}_{file_id}.jpg"
            await message.bot.download(message.photo[-1], destination=media_path)
            media_type = "photo"
        elif message.video:
            file_id = message.video.file_id
            media_path = f"img/ar_{account_id}_{file_id}.mp4"
            await message.bot.download(message.video, destination=media_path)
            media_type = "video"
        elif message.document:
            file_id = message.document.file_id
            ext = os.path.splitext(message.document.file_name)[1] if message.document.file_name else ""
            media_path = f"img/ar_{account_id}_{file_id}{ext}"
            await message.bot.download(message.document, destination=media_path)
            media_type = "document"
        elif message.voice:
            file_id = message.voice.file_id
            media_path = f"img/ar_{account_id}_{file_id}.ogg"
            await message.bot.download(message.voice, destination=media_path)
            media_type = "voice"
        elif message.sticker:
            file_id = message.sticker.file_id
            media_path = f"img/ar_{account_id}_{file_id}.webp"
            await message.bot.download(message.sticker, destination=media_path)
            media_type = "sticker"
            
        db.update_autoresponder(account_id, text, None)
        db.update_autoresponder_media(account_id, media_path, media_type)
        db.update_autoresponder_entities(account_id, entities_json)
        await state.clear()
        await message.answer("✅ Автоответчик обновлён (с копированием разметки)!")

    @dp.callback_query(F.data.startswith('toggle_autoresponder_'))
    async def toggle_autoresponder_callback(callback: CallbackQuery):
        account_id = int(callback.data.split('_')[2])
        account = db.get_account(account_id)
        if not account:
            await callback.answer("❌ Аккаунт не найден!", show_alert=True)
            return
        new_state = 0 if account.get('autoresponder_enabled', 0) == 1 else 1
        db.toggle_autoresponder(account_id, new_state)
        await callback.answer(f"{'✅ Включен' if new_state == 1 else '❌ Выключен'}!", show_alert=True)
        await acc_autoresponder_callback(callback, None)

    # ==================== MIRROR MANAGEMENT (User-facing for Partners) ====================
    @dp.callback_query(F.data == "manage_mirrors")
    async def manage_mirrors_callback(callback: CallbackQuery):
        user_id = callback.from_user.id
        mirrors = db.get_partner_mirrors(user_id)
        buttons = []
        for m in mirrors:
            status = "✅" if m['is_active'] == 1 else "❌"
            buttons.append([InlineKeyboardButton(text=f"🪞 @{m['bot_username'] or 'unknown'} {status}", callback_data=f"partner_mirror_{m['id']}")])
        buttons.append([InlineKeyboardButton(text="➕ Добавить зеркало", callback_data="add_mirror")])
        buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_main")])
        markup = InlineKeyboardMarkup(inline_keyboard=buttons)
        await edit_message(callback, "🪞 <b>Мои зеркала</b>", reply_markup=markup)

    @dp.callback_query(F.data == "add_mirror")
    async def add_mirror_callback(callback: CallbackQuery, state: FSMContext):
        await state.set_state(MirrorStates.WAITING_BOT_TOKEN)
        await edit_message(callback, 
            "🪞 <b>Добавление зеркала</b>\n\n"
            "Введите токен бота от @BotFather:",
            reply_markup=cancel_inline_keyboard()
        )

    @dp.message(MirrorStates.WAITING_BOT_TOKEN)
    async def process_mirror_token(message: Message, state: FSMContext):
        token = message.text.strip()
        try:
            test_bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
            me = await test_bot.get_me()
            await test_bot.session.close()
            await state.update_data(mirror_token=token, mirror_username=me.username)
            await state.set_state(MirrorStates.WAITING_CONFIRM)
            await message.answer(
                f"🪞 Бот: @{me.username}\n\nДобавить зеркало?",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="✅ Да", callback_data="confirm_add_mirror")],
                    [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_action")]
                ])
            )
        except Exception as e:
            await message.answer(f"❌ Невалидный токен: {e}")

    @dp.callback_query(F.data == "confirm_add_mirror")
    async def confirm_add_mirror_callback(callback: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        token = data.get('mirror_token')
        username = data.get('mirror_username')
        db.add_bot_mirror(callback.from_user.id, token, username)
        await state.clear()
        await edit_message(callback, f"✅ Зеркало @{username} добавлено!")

    async def _show_partner_mirror_item(callback: CallbackQuery, mirror_id: int):
        mirror = db.get_mirror(mirror_id)
        if not mirror:
            await callback.answer("❌ Зеркало не найдено!", show_alert=True)
            return
        status = "🟢 Активно" if mirror['is_active'] == 1 else "🔴 Остановлено"
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Переключить", callback_data=f"partner_toggle_mirror_{mirror_id}")],
            [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"partner_del_mirror_{mirror_id}")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="manage_mirrors")]
        ])
        await edit_message(callback, 
            f"🪞 <b>Зеркало #{mirror_id}</b>\n\n@{mirror.get('bot_username', 'unknown')}\nСтатус: {status}",
            reply_markup=markup
        )

    @dp.callback_query(F.data.startswith('partner_mirror_'))
    async def partner_mirror_callback(callback: CallbackQuery):
        mirror_id = int(callback.data.split('_')[-1])
        await _show_partner_mirror_item(callback, mirror_id)

    @dp.callback_query(F.data.startswith('partner_toggle_mirror_'))
    async def partner_toggle_mirror_callback(callback: CallbackQuery):
        mirror_id = int(callback.data.split('_')[-1])
        db.toggle_mirror(mirror_id, callback.from_user.id)
        await callback.answer("✅ Статус изменён!", show_alert=True)
        await _show_partner_mirror_item(callback, mirror_id)

    @dp.callback_query(F.data.startswith('partner_del_mirror_'))
    async def partner_del_mirror_callback(callback: CallbackQuery):
        mirror_id = int(callback.data.split('_')[-1])
        db.delete_mirror(mirror_id, callback.from_user.id)
        await callback.answer("✅ Зеркало удалено!", show_alert=True)
        await manage_mirrors_callback(callback)
