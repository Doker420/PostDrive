"""Регрессия: парсинг сохранял только ОДНОГО пользователя.

В старой схеме было UNIQUE(account_id, user_id), где user_id — владелец бота,
а не спарсенный пользователь. Колонка user_id_val добавлялась позже через
ALTER TABLE и в ограничение не попадала, поэтому INSERT OR IGNORE молча
отбрасывал всех, кроме первого.

Плюс: CSV выгружал user_id (владельца) вместо user_id_val и не имел BOM,
из-за чего Excel показывал кракозябры и один столбец.
"""
import os, sys, sqlite3, tempfile, csv, io
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT = os.path.join(os.path.dirname(__file__), '..')

import sqliter
results = []

# ── 1. Миграция старой схемы без потери данных ────────────────────
p = tempfile.mktemp(suffix='.db')
c = sqlite3.connect(p)
c.execute('''CREATE TABLE parsed_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT, account_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL, username TEXT DEFAULT '', first_name TEXT DEFAULT '',
    last_name TEXT DEFAULT '', phone TEXT DEFAULT '',
    parsed_at INTEGER DEFAULT (strftime('%s','now')), UNIQUE(account_id, user_id))''')
c.execute("ALTER TABLE parsed_users ADD COLUMN user_id_val INTEGER DEFAULT 0")
c.execute("ALTER TABLE parsed_users ADD COLUMN source_chat_id TEXT DEFAULT ''")
c.execute("INSERT INTO parsed_users (account_id,user_id,user_id_val,username) "
          "VALUES (1,777,111,'старый')")
c.commit(); c.close()

db = sqliter.DBConnection(p)
ddl = db.c.execute("SELECT sql FROM sqlite_master WHERE name='parsed_users'").fetchone()[0]
assert 'user_id_val' in ddl.split('UNIQUE')[-1], "UNIQUE не исправлен"
kept = db.c.execute("SELECT username FROM parsed_users").fetchall()
assert len(kept) == 1, f"данные потеряны при миграции: {kept}"
results.append("миграция старой схемы, данные сохранены: OK")

# миграция идемпотентна
sqliter.DBConnection(p)
assert db.c.execute("SELECT COUNT(*) FROM parsed_users").fetchone()[0] == 1
results.append("повторный запуск миграции безопасен: OK")

# ── 2. Сохраняются ВСЕ пользователи, а не один ────────────────────
db2 = sqliter.DBConnection(tempfile.mktemp(suffix='.db'))
db2.conn_ctx.execute("INSERT INTO users (user_id) VALUES (777)")
db2.conn_ctx.execute("INSERT INTO accounts (id,user_id,session_string) VALUES (1,777,'x')")
db2.conn_ctx.commit()

people = [{'id': 1000 + i, 'username': f'user{i}', 'first_name': f'Имя{i}',
           'last_name': f'Фам{i}', 'phone': f'+7900000{i:04d}'} for i in range(50)]
added = db2.save_parsed_users(1, 777, people, source_chat_id='-100999')
total = db2.c.execute("SELECT COUNT(*) FROM parsed_users").fetchone()[0]
assert added == 50 and total == 50, f"added={added} total={total} (был баг: сохранялся 1)"
results.append(f"сохраняются все пользователи: OK ({total} из 50)")

# дубликаты не плодятся
assert db2.save_parsed_users(1, 777, people[:10]) == 0
assert db2.c.execute("SELECT COUNT(*) FROM parsed_users").fetchone()[0] == 50
results.append("повторное сохранение не плодит дубликаты: OK")

# записи без Telegram ID отбрасываются
assert db2.save_parsed_users(1, 777, [{'username': 'no_id'}]) == 0
results.append("записи без Telegram ID отбрасываются: OK")

# ── 3. Пагинация по 20 ────────────────────────────────────────────
page0, tot = db2.get_parsed_users_paginated(1, 777, page=0, per_page=20)
assert len(page0) == 20 and tot == 50
page2, _ = db2.get_parsed_users_paginated(1, 777, page=2, per_page=20)
assert len(page2) == 10, len(page2)
ids0 = {u['user_id_val'] for u in page0}
ids2 = {u['user_id_val'] for u in page2}
assert not (ids0 & ids2), "страницы пересекаются"
results.append("пагинация по 20: 20+20+10, без пересечений: OK")

# выход за диапазон подрезается, а не отдаёт пустоту
oob, _ = db2.get_parsed_users_paginated(1, 777, page=999, per_page=20)
assert len(oob) == 10, f"страница за пределами вернула {len(oob)}"
results.append("страница за пределами подрезается к последней: OK")

# пустой список
empty, z = db2.get_parsed_users_paginated(99, 777, page=0, per_page=20)
assert empty == [] and z == 0
results.append("пустой список не падает: OK")

# ── 4. CSV: правильный ID, BOM, разделитель ───────────────────────
hsrc = open(os.path.join(ROOT, 'handlers.py')).read()
block = hsrc[hsrc.index("async def download_parsed_callback"):]
block = block[:block.index("async def parsed_html_callback")]
assert "u.get('user_id_val')" in block, "CSV снова выгружает ID владельца бота"
assert "u['user_id']" not in block, "остался user_id владельца"
assert "\\ufeff" in block, "нет BOM — Excel покажет кракозябры"
assert "delimiter=';'" in block, "нет разделителя ';' для Excel"
results.append("CSV: user_id_val, BOM, разделитель ';': OK")

# ── 5. HTML-таблица ───────────────────────────────────────────────
start = hsrc.index("def _build_parsed_html")
end = hsrc.index("\nfrom aiogram import Bot")
ns = {}
exec(compile("from html import escape as html_escape\n" + hsrc[start:end], 'g', 'exec'), ns)
build = ns['_build_parsed_html']

rows = [{'user_id_val': 111, 'username': 'ivan', 'first_name': 'Иван',
         'last_name': 'Петров', 'phone': '+79001234567', 'source_chat_id': '-100'},
        {'user_id_val': 222, 'username': '', 'first_name': 'Мария',
         'last_name': '', 'phone': '', 'source_chat_id': ''}]
html = build(rows, 'Тест')
assert html.startswith('<!DOCTYPE html>') and html.rstrip().endswith('</html>')
assert html.count('<tr><td class="num">') == 2
for feature in ('id="q"', 'localeCompare', '<tbody>', 'prefers-color-scheme'):
    assert feature in html, f"нет {feature}"
assert '{{' not in html and '}}' not in html, "артефакты f-string в CSS/JS"
results.append("HTML: валидная структура, поиск, сортировка, тёмная тема: OK")

# XSS
evil = build([{'user_id_val': 1, 'username': '<script>alert(1)</script>',
               'first_name': '<img src=x onerror=alert(2)>', 'last_name': '&',
               'phone': '', 'source_chat_id': ''}], '<b>acc</b>')
assert '<script>alert(1)</script>' not in evil
assert '<img src=x' not in evil
assert '&lt;script&gt;' in evil
results.append("HTML: XSS экранируется: OK")

# баланс тегов
from html.parser import HTMLParser
class P(HTMLParser):
    def __init__(self): super().__init__(); self.d = 0
    def handle_starttag(self, t, a):
        if t not in ('meta', 'input', 'br', 'link', 'img'): self.d += 1
    def handle_endtag(self, t): self.d -= 1
par = P(); par.feed(html)
assert par.d == 0, f"несбалансированные теги: {par.d}"
results.append("HTML: теги сбалансированы: OK")

print("\n".join("  " + r for r in results))
print("\nALL PARSED-USERS TESTS PASSED")
