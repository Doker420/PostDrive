"""Регрессии нейрокомментинга.

Симптом: «включил — и ничего не происходит», хотя аккаунт админ в группе.
Найденные причины:
  1. last_seen инициализировался ПОСЛЕДНИМ постом → комментировался только
     следующий новый пост, уже опубликованный игнорировался навсегда.
  2. Копия поста в чате обсуждений искалась перебором 200 сообщений —
     ненадёжно; штатный get_discussion_message не использовался.
  3. Аккаунт, ограниченный за спам, не проходил is_account_usable, но
     enabled оставался = 1: меню показывало 🟢, воркер не работал.
  4. AccountBlockedError гасил задачу молча, без уведомления владельцу.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import sqliter

results = []
root = os.path.join(os.path.dirname(__file__), '..')
U = open(os.path.join(root, 'user.py')).read()
H = open(os.path.join(root, 'handlers.py')).read()

# 1. Последний пост считается новым при старте
assert 'max(msg.id - 1, 0)' in U, "last_seen по-прежнему равен id последнего поста"
results.append("последний пост комментируется после включения: OK")

# 2. Дедупликация через БД
assert 'db.was_post_commented(account_id, channel, msg.id)' in U, "нет проверки дубля поста"
assert 'db.mark_post_commented(account_id, channel, msg.id)' in U, "успешный комментарий не фиксируется"
results.append("дедупликация постов в воркере: OK")

# 3. Штатный API комментариев
assert 'async def _send_post_comment' in U, "нет хелпера отправки комментария"
block = U[U.index('async def _send_post_comment'):U.index('# ==================== NEUROCOMMENT: CHANNEL DISCOVERY')]
assert 'get_discussion_message' in block, "не используется get_discussion_message"
assert 'get_chat_history(discussion_chat_id, limit=200)' in block, "нет запасного поиска форварда"
assert '_send_post_comment(' in U.split('async def _send_post_comment')[0], \
    "хелпер не вызывается из воркера"
results.append("комментарий через get_discussion_message + fallback: OK")

# 4. Блокировка аккаунта сообщается владельцу
tail = U[U.index('except AccountBlockedError as e:\n            # Раньше владелец'):]
assert 'bot.send_message' in tail[:900], "AccountBlockedError гасит воркер молча"
results.append("уведомление об ограничении аккаунта: OK")

# 5. Неудачный старт снимает enabled
assert "db.update_neurocomment_settings(account_id, enabled=0)" in H, "enabled не сбрасывается"
seg = H[H.index('async def nc_toggle_callback'):]
seg = seg[:seg.index('back_to_neurocomment')]
assert 'if not ok:' in seg, "неудачный запуск оставляет статус 🟢"
results.append("неудачный запуск не оставляет статус включённым: OK")

# 6. Отслеживание новых постов
assert 'limit=self.NC_HISTORY_LIMIT' in U, "по-прежнему читается только 1 последний пост"
assert 'fresh.reverse()' in U, "посты обрабатываются не от старого к новому"
assert "if mode == 'post_prompt' and not post_text" in U, \
    "пост без текста пропускается даже в режиме промта по теме"
assert 'post_age < self.NC_POST_GRACE' in U, "свежесть поста всё ещё сравнивается с comment_delay"
assert 'sleep_for = max(5, min(comment_delay, self.NC_CHECK_INTERVAL))' in U, \
    "период опроса всё ещё равен comment_delay"
assert '_nc_last_comment' in U, "нет паузы между комментариями"
assert "getattr(msg, 'service', None)" in U, "сервисные сообщения не отсеиваются"
results.append("опрос каналов чаще, пачка последних постов, пауза между комментариями: OK")

# 7. Параллельные задачи не ломают комментинг
assert 'client, cli_err = await self.get_or_start_client(account_id)' in U, \
    "воркер по-прежнему держит один и тот же объект клиента"
assert U.count('client, cli_err = await self.get_or_start_client(account_id)') >= 2, \
    "рассылка не обновляет клиент в цикле"
assert 'def active_task_names' in U, "нет списка параллельных задач"
assert U.count("active_task_names(account_id, exclude=") >= 3, \
    "нет предупреждений о параллельных задачах"
results.append("клиент берётся заново каждый цикл + предупреждение о параллели: OK")

# 8. Сторож поднимает упавший воркер
assert 'async def _restore_stalled_neurocomment' in U, "нет сторожа воркеров"
assert '_restore_stalled_neurocomment()' in U.split('async def _restore_stalled_neurocomment')[0], \
    "сторож не вызывается из cleanup-цикла"
assert 'disable_on_exit' in U, "падение воркера всё ещё гасит настройку"
seg_fin = U[U.index('Neurocomment worker stopped'):][:600]
assert 'if disable_on_exit or account_id in self._nc_intentional_stop:' in seg_fin, \
    "enabled=0 ставится безусловно"
assert '_nc_intentional_stop.add' in U, "намеренная остановка не помечается"
results.append("сторож перезапускает упавший нейрокомментинг: OK")

# 9. Таблица дедупликации реально работает
path = os.path.join(tempfile.mkdtemp(), 'nc.db')
db = sqliter.DBConnection(path)
assert db.was_post_commented(1, '@chan', 100) is False
db.mark_post_commented(1, '@chan', 100)
assert db.was_post_commented(1, '@chan', 100) is True
db.mark_post_commented(1, '@chan', 100)          # повтор не падает
assert db.was_post_commented(1, '@chan', 101) is False
assert db.was_post_commented(2, '@chan', 100) is False
# сторожу нужен список включённых настроек
db.get_or_create_user(5, 'u', 'a', 'b', 0)
aid = db.add_account(5, 'sess', phone='1', account_name='A')
db.create_neurocomment_settings(aid, 5, comment_delay=60)
assert db.get_enabled_neurocomment_settings() == [], "выключенная настройка попала в список"
db.update_neurocomment_settings(aid, enabled=1)
rows = db.get_enabled_neurocomment_settings()
assert [(r['account_id'], r['user_id']) for r in rows] == [(aid, 5)], rows
db.close()
sqliter.DBConnection(path).close()               # миграция идемпотентна
results.append("nc_commented_posts: запись/дубль/изоляция по аккаунту: OK")

print("\n".join("  " + r for r in results))
print("\nALL NEUROCOMMENT TESTS PASSED")
