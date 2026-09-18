import asyncio, tempfile, os, sys, random
import os, sys; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sqliter

p = tempfile.mktemp(suffix='.db')
db = sqliter.DBConnection(p, pool_size=8)

# seed accounts
with db.transaction() as pc:
    for uid in range(1, 21):
        pc.raw.execute("INSERT INTO users (user_id) VALUES (?)", (uid,))
        pc.raw.execute("INSERT INTO accounts (id,user_id,session_string,account_name) VALUES (?,?,?,?)",
                       (uid, uid, 'x', f'acc{uid}'))

# Each account gets a distinct set of chats; a correct read must never see another account's rows.
for uid in range(1, 21):
    db.sync_account_chats(uid, [
        {'id': f'-100{uid}{i}', 'title': f'G{uid}_{i}', 'username': '', 'chat_type': 'group'}
        for i in range(25)
    ])

errors = []

async def reader(uid):
    for _ in range(60):
        chats = db.get_account_chats(uid, chat_types=db.GROUP_CHAT_TYPES)
        if len(chats) != 25:
            errors.append(f"acc{uid}: expected 25 got {len(chats)}")
        for ch in chats:
            if not ch['chat_title'].startswith(f'G{uid}_'):
                errors.append(f"acc{uid}: leaked row {ch['chat_title']}")
        acc = db.get_account(uid)
        if acc is None or acc['account_name'] != f'acc{uid}':
            errors.append(f"acc{uid}: get_account mismatch -> {acc and acc['account_name']}")
        cnt = db.count_account_chats(uid, chat_types=db.GROUP_CHAT_TYPES)
        if cnt != 25:
            errors.append(f"acc{uid}: count {cnt}")
        await asyncio.sleep(0)

async def writer(uid):
    for i in range(40):
        db.toggle_chat_spam(uid, f'-100{uid}{i % 25}')
        db.update_account_timeout(uid, random.randint(1, 60))
        await asyncio.sleep(0)

async def main():
    tasks = []
    for uid in range(1, 21):
        tasks.append(asyncio.create_task(reader(uid)))
        tasks.append(asyncio.create_task(writer(uid)))
    await asyncio.gather(*tasks)

asyncio.run(main())
print("pool stats:", db.pool_stats())
print("ERRORS:", len(errors))
for e in errors[:5]:
    print("  ", e)
assert not errors, "RACE DETECTED"
print("PASS: no cross-task row leakage under 40 concurrent tasks")
db.close()
os.remove(p)
