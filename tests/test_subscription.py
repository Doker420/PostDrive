"""Регрессия: «требуется активная подписка» при активной подписке.

Две причины:
1. add_subscription_days делал только UPDATE. Если пользователя не было в
   таблице users (не нажимал /start, или запись потерялась), запрос не
   задевал ни одной строки, но функция рапортовала об успехе — админ видел
   «Подписка выдана», а бот продолжал её требовать.
2. is_user_subscribed смотрел только users.subscription_until и игнорировал
   user_entitlements.tariff_code, который выставляется при оплате тарифа.
"""
import os, sys, time, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sqliter
results = []

def fresh():
    return sqliter.DBConnection(tempfile.mktemp(suffix='.db'))

# ── 1. Подписка пользователю, которого нет в users ────────────────
db = fresh()
new_sub = db.add_subscription_days(999, 30)
assert db.get_user(999) is not None, "пользователь не создан"
assert db.is_user_subscribed(999, 0), "подписка выдана, но не видна — ЭТО БЫЛ БАГ"
assert new_sub > int(time.time()) + 29 * 86400
results.append("подписка несуществующему пользователю создаёт запись: OK")

# ── 2. Продление активной подписки складывается ───────────────────
before = db.get_user(999)['subscription_until']
after = db.add_subscription_days(999, 10)
assert after >= before + 10 * 86400 - 5, (before, after)
assert db.is_user_subscribed(999, 0)
results.append("продление активной подписки складывается: OK")

# ── 3. Истёкшая подписка отсчитывается от текущего момента ────────
db.c.execute("UPDATE users SET subscription_until = ? WHERE user_id = 999",
             (int(time.time()) - 100_000,))
db.conn_ctx.commit()
assert not db.is_user_subscribed(999, 0)
renewed = db.add_subscription_days(999, 7)
assert renewed > int(time.time()) + 6 * 86400, "истёкшая подписка продлена от старой даты"
assert db.is_user_subscribed(999, 0)
results.append("истёкшая подписка отсчитывается от сегодня: OK")

# ── 4. Оплаченный тариф без subscription_until ────────────────────
db2 = fresh()
db2.get_or_create_user(555, 'u', 'F', 'L')
assert not db2.is_user_subscribed(555, 0)
db2.set_user_tariff(555, 'pro')
assert db2.is_user_subscribed(555, 0), "платный тариф не признан подпиской — ЭТО БЫЛ БАГ"
results.append("платный тариф засчитывается как подписка: OK")

# ── 5. trial не даёт доступа ──────────────────────────────────────
db2.get_or_create_user(222, 'u', 'F', 'L')
db2.set_user_tariff(222, 'trial')
assert not db2.is_user_subscribed(222, 0), "trial не должен считаться платной подпиской"
results.append("trial не считается платной подпиской: OK")

# ── 6. Пользователь без всего — доступа нет ───────────────────────
db2.get_or_create_user(111, 'u', 'F', 'L')
assert not db2.is_user_subscribed(111, 0)
assert not db2.is_user_subscribed(424242, 0)       # вообще неизвестный
results.append("без подписки и тарифа доступа нет: OK")

# ── 7. Админ ──────────────────────────────────────────────────────
assert db2.is_user_subscribed(777, 777), "админ по admin_id"
db2.get_or_create_user(888, 'u', 'F', 'L')
db2.set_user_admin(888, 1)
assert db2.is_user_subscribed(888, 0), "админ по флагу is_admin"
results.append("админ (по admin_id и по флагу) всегда имеет доступ: OK")

# ── 8. Промокод и оплата инвойса дают рабочую подписку ────────────
db3 = fresh()
db3.get_or_create_user(321, 'u', 'F', 'L')
db3.add_subscription_days(321, 3)
assert db3.is_user_subscribed(321, 0)
limits = db3.get_user_limits(321, 0)
assert limits['max_accounts'] >= 1
results.append("после выдачи дней лимиты считаются без ошибок: OK")

# ── 9. Сообщение об отказе объясняет, что делать ──────────────────
h = open(os.path.join(os.path.dirname(__file__), '..', 'handlers.py')).read()
block = h[h.index("async def nc_toggle_callback"):]
block = block[:block.index("nc = db.get_neurocomment_settings")]
assert 'поддержку' in block or 'Подписка' in block, "отказ не объясняет, что делать"
results.append("сообщение об отказе подсказывает проверить статус: OK")

# ── 10. Фоновые задачи проверяют подписку С admin_id ──────────────
# Баг: в user.py стояло is_user_subscribed(user_id) без admin_id. Для
# владельца бота, которого нет в таблице users (или без записи is_admin),
# проверка проваливалась, и работающая задача останавливалась с
# «Подписка истекла», хотя у админа безлимитный доступ.
u = open(os.path.join(os.path.dirname(__file__), '..', 'user.py')).read()
assert 'is_user_subscribed(user_id)' not in u, \
    "в user.py снова проверка подписки без admin_id"
assert u.count('is_user_subscribed(user_id, ADMIN_ID)') >= 2, \
    "фоновые задачи должны проверять подписку с ADMIN_ID"
assert "config.get('BOT', 'ADMIN'" in u, "ADMIN_ID не читается из конфига"
assert 'ADMIN_ID = 0' in u, "нет безопасного значения ADMIN_ID по умолчанию"
results.append("фоновые задачи (спам/нейрокомментинг) учитывают admin_id: OK")

# админ, которого нет в users, считается подписанным
db4 = fresh()
assert db4.is_user_subscribed(77777, 77777), "админ без записи в users должен иметь доступ"
assert not db4.is_user_subscribed(77777, 0), "без admin_id доступа быть не должно — это и был баг"
results.append("админ без записи в users: с admin_id доступ есть, без — нет: OK")

# ── 11. Все проверки подписки в handlers.py передают ADMIN ─────────
h2 = open(os.path.join(os.path.dirname(__file__), '..', 'handlers.py')).read()
import re as _re
bad = _re.findall(r'is_user_subscribed\(\s*user_id\s*\)', h2)
assert not bad, f"в handlers.py есть проверки без ADMIN: {len(bad)}"
results.append("все проверки в handlers.py передают ADMIN: OK")

print("\n".join("  " + r for r in results))
print("\nALL SUBSCRIPTION TESTS PASSED")
