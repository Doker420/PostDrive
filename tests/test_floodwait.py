"""Тесты обработки FloodWait и банов (tg_call)."""
import os, sys, asyncio, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sqliter
db = sqliter.DBConnection(tempfile.mktemp(suffix='.db'))
db.conn_ctx.execute("INSERT INTO users (user_id) VALUES (1)")
db.conn_ctx.execute("INSERT INTO accounts (id,user_id,session_string) VALUES (1,1,'x')")
db.conn_ctx.commit()

import user as U
U.db = db
mgr = U.AccountSessionManager(1, 'hash')

slept = []
_real_sleep = asyncio.sleep
async def fake_sleep(sec):
    slept.append(sec)
    await _real_sleep(0)
U.asyncio.sleep = fake_sleep

def make_flood(seconds):
    e = U.FloodWait.__new__(U.FloodWait)
    Exception.__init__(e, f"FLOOD_WAIT_{seconds}")
    e.value = seconds
    return e

async def main():
    results = []

    # 1. FloodWait -> ждём и повторяем, второй вызов успешен
    slept.clear()
    calls = {'n': 0}
    async def flaky():
        calls['n'] += 1
        if calls['n'] == 1:
            raise make_flood(30)
        return "sent"
    r = await mgr.tg_call(flaky, account_id=1, description='send')
    assert r == "sent", r
    assert calls['n'] == 2
    assert slept and 30 <= slept[0] <= 34, slept
    results.append(f"FloodWait retry: OK (ждал {slept[0]:.0f}s, вернул {r!r})")

    # флуд записан в статистику
    h = db.get_account_health(1)
    assert h['flood_count'] == 1 and h['flood_total_seconds'] == 30, h
    results.append(f"flood stats recorded: OK ({h['flood_count']} шт, {h['flood_total_seconds']}s)")
    db.clear_account_health(1)

    # 2. Слишком длинный FloodWait -> AccountBlockedError, БЕЗ ожидания
    slept.clear()
    async def big_flood():
        raise make_flood(7200)
    try:
        await mgr.tg_call(big_flood, account_id=1, description='send')
        assert False, "должно было бросить AccountBlockedError"
    except U.AccountBlockedError as e:
        assert e.kind == 'restricted'
    assert not slept, f"не должен спать 2 часа: {slept}"
    results.append("long FloodWait -> AccountBlockedError без ожидания: OK")
    db.clear_account_health(1)

    # 3. PeerFlood -> restricted + задачи стоп
    async def peer_flood():
        raise U.PeerFlood.__new__(U.PeerFlood)
    try:
        await mgr.tg_call(peer_flood, account_id=1, description='invite')
        assert False
    except U.AccountBlockedError as e:
        assert e.kind == 'restricted'
    ok, reason = db.is_account_usable(1)
    assert not ok, "аккаунт должен быть недоступен"
    results.append(f"PeerFlood -> restricted: OK ({reason[:50]})")
    db.clear_account_health(1)

    # 4. Мёртвая сессия -> banned
    async def dead():
        raise U.UserDeactivated.__new__(U.UserDeactivated)
    try:
        await mgr.tg_call(dead, account_id=1, description='start')
        assert False
    except U.AccountBlockedError as e:
        assert e.kind == 'banned', e.kind
    assert db.get_account_health(1)['health'] == db.HEALTH_BANNED
    results.append("dead session -> banned: OK")
    db.clear_account_health(1)

    # 5. Проблема чата -> None, задача продолжается
    async def no_write():
        raise U.ChatWriteForbidden.__new__(U.ChatWriteForbidden)
    r = await mgr.tg_call(no_write, account_id=1, description='send')
    assert r is None, r
    ok, _ = db.is_account_usable(1)
    assert ok, "ошибка чата не должна ронять здоровье аккаунта"
    results.append("ChatWriteForbidden -> skip target, аккаунт здоров: OK")

    # 6. Кулдаун истекает сам
    db.record_flood_wait(1, 1)
    ok, reason = db.is_account_usable(1)
    assert not ok, "во время кулдауна аккаунт занят"
    db.c.execute("UPDATE accounts SET restricted_until = ? WHERE id = 1", (int(time.time()) - 5,))
    db.conn_ctx.commit()
    ok, _ = db.is_account_usable(1)
    assert ok, "после истечения кулдауна аккаунт снова доступен"
    results.append("cooldown expiry: OK")

    # 7. Повторные FloodWait подряд -> исчерпание попыток
    slept.clear()
    async def always_flood():
        raise make_flood(5)
    try:
        await mgr.tg_call(always_flood, account_id=1, description='send', max_retries=3)
        assert False, "должен был пробросить ошибку"
    except U.FloodWait:
        pass
    assert len(slept) == 3, slept
    results.append(f"исчерпание попыток: OK (3 ожидания)")

    print("\n".join("  " + r for r in results))
    print("\nALL FLOODWAIT TESTS PASSED")

asyncio.run(main())
