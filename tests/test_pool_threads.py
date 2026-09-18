import threading, tempfile, os, sys, random
import os, sys; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sqliter
p=tempfile.mktemp(suffix='.db')
db=sqliter.DBConnection(p, pool_size=10)
with db.transaction() as pc:
    for uid in range(1,16):
        pc.raw.execute("INSERT INTO users (user_id) VALUES (?)",(uid,))
        pc.raw.execute("INSERT INTO accounts (id,user_id,session_string,account_name) VALUES (?,?,?,?)",(uid,uid,'x',f'acc{uid}'))
for uid in range(1,16):
    db.sync_account_chats(uid,[{'id':f'-100{uid}{i}','title':f'G{uid}_{i}','username':'','chat_type':'group'} for i in range(30)])

errors=[]; maxpool=[0]
def work(uid):
    for _ in range(80):
        try:
            chats=db.get_account_chats(uid, chat_types=db.GROUP_CHAT_TYPES)
            if len(chats)!=30: errors.append(f"acc{uid} len={len(chats)}")
            for ch in chats:
                if not ch['chat_title'].startswith(f'G{uid}_'):
                    errors.append(f"acc{uid} leak {ch['chat_title']}"); break
            a=db.get_account(uid)
            if not a or a['account_name']!=f'acc{uid}': errors.append(f"acc{uid} acct leak")
            db.toggle_chat_spam(uid,f'-100{uid}{random.randint(0,29)}')
            maxpool[0]=max(maxpool[0], db.pool_stats()['in_use'])
        except Exception as e:
            errors.append(f"acc{uid} EXC {type(e).__name__}: {e}")
ts=[threading.Thread(target=work,args=(u,)) for u in range(1,16)]
[t.start() for t in ts]; [t.join() for t in ts]
print("pool stats:",db.pool_stats(),"peak in_use:",maxpool[0])
print("ERRORS:",len(errors))
for e in errors[:5]: print("  ",e)
print("PASS" if not errors else "FAIL")
db.close(); os.remove(p)
