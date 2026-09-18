"""Регрессия: Pyrogram 2.0.106 отвергает современные ID каналов.

utils.MIN_CHANNEL_ID = -1002147483647 (32-битный предел), тогда как Telegram
выдаёт ID до -1997852516352 (core.telegram.org/api/bots/ids). Из-за этого
ValueError: Peer id invalid на всех новых каналах (-1002.../-1003.../-1004...),
чаты не резолвились, рассылка и нейрокомментинг их молча пропускали.
"""
import os, sys, asyncio, tempfile, logging
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
logging.disable(logging.WARNING)

import sqliter
db = sqliter.DBConnection(tempfile.mktemp(suffix='.db'))
db.conn_ctx.execute("INSERT INTO users (user_id) VALUES (1)")
db.conn_ctx.execute("INSERT INTO accounts (id,user_id,session_string) VALUES (1,1,'x')")
db.conn_ctx.commit()

import user as U
U.db = db
from pyrogram import utils

results = []

# 1. Границы расширены до официальных
assert utils.MIN_CHANNEL_ID == -1997852516352, utils.MIN_CHANNEL_ID
assert utils.MIN_CHAT_ID == -999999999999, utils.MIN_CHAT_ID
results.append(f"границы исправлены: MIN_CHANNEL_ID={utils.MIN_CHANNEL_ID}")

# 2. Реальные ID из продакшен-логов резолвятся
real = [-1003693073139, -1003580177792, -1003798581031, -1002854304502,
        -1002285086371, -1004300950929, -1002211899496, -1003862135802]
for cid in real:
    assert utils.get_peer_type(cid) == 'channel', f"{cid} не распознан"
results.append(f"ID из логов распознаются как channel: OK ({len(real)} шт)")

# 3. Обратная совместимость
assert utils.get_peer_type(-1001639024398) == 'channel'   # старый канал
assert utils.get_peer_type(-500) == 'chat'                # обычная группа
assert utils.get_peer_type(123456789) == 'user'
results.append("старые channel/chat/user работают: OK")

# 4. Мусор по-прежнему отвергается
# (-1 валиден: диапазон chat по спецификации -999999999999..-1)
for bad in (0, 10**15, -10**15, -2 * 10**12):
    try:
        utils.get_peer_type(bad)
        raise AssertionError(f"{bad} не должен быть валидным")
    except ValueError:
        pass
results.append("невалидные ID отвергаются: OK")

# 5. Патч идемпотентен
U._patch_pyrogram_peer_ranges()
U._patch_pyrogram_peer_ranges()
assert utils.MIN_CHANNEL_ID == -1997852516352
results.append("повторный вызов патча безопасен: OK")

# 6. access_hash сохраняется и не затирается пустым значением
db.sync_account_chats(1, [
    {'id': '-1003693073139', 'title': 'Новый', 'username': 'n',
     'chat_type': 'channel', 'access_hash': '123456789'},
])
row = db.get_account_chats(1, chat_types=('channel',))[0]
assert row.get('access_hash') == '123456789', row
db.sync_account_chats(1, [
    {'id': '-1003693073139', 'title': 'Переименован', 'username': 'n',
     'chat_type': 'channel'},          # без access_hash
])
row = db.get_account_chats(1, chat_types=('channel',))[0]
assert row.get('access_hash') == '123456789', "access_hash затёрт!"
assert row['chat_title'] == 'Переименован'
results.append("access_hash сохраняется, пустым не затирается: OK")

# 7. «Peer id invalid» в tg_call = пропуск цели, а не ERROR/остановка
async def check_skip():
    async def boom():
        raise ValueError("Peer id invalid: -1003693073139")
    mgr = U.AccountSessionManager(1, 'h')
    r = await mgr.tg_call(boom, account_id=1, description='get_chat')
    assert r is None, r
    ok, _ = db.is_account_usable(1)
    assert ok, "неизвестный пир не должен портить здоровье аккаунта"
    # настоящая ValueError по-прежнему пробрасывается
    async def real_err():
        raise ValueError("что-то другое сломалось")
    try:
        await mgr.tg_call(real_err, account_id=1, description='x')
        raise AssertionError("реальная ValueError должна пробрасываться")
    except ValueError as e:
        assert 'другое' in str(e)
asyncio.run(check_skip())
results.append("'Peer id invalid' -> пропуск цели, аккаунт здоров: OK")

# 8. Поиск каналов больше не делает get_chat на каждый канал
src = open(os.path.join(os.path.dirname(__file__), '..', 'user.py')).read()
block = src[src.index('async def list_commentable_channels'):]
block = block[:block.index('# ==================== CHAT LIST')]
assert 'GetChannels' in block, "не используется пакетный GetChannels"
assert 'client.get_chat(' not in block, "остались поштучные get_chat"
results.append("поиск каналов идёт пачками GetChannels, без get_chat: OK")

print("\n".join("  " + r for r in results))
print("\nALL PEER-ID TESTS PASSED")
