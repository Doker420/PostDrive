"""Проверяем адаптеры PG на фейковом драйвере: трансляция SQL, %s-плейсхолдеры, dict/index-доступ."""
import sys; import os, sys; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import dbconfig, sqliter

executed = []

class FakeCur:
    def __init__(self): self.rows=[]; self.description=None
    def execute(self, sql, params=None):
        executed.append((sql, params))
        self.rows=[{'id':1,'name':'alice'},{'id':2,'name':'bob'}]
    def executemany(self, sql, seq): executed.append((sql, list(seq)))
    def fetchone(self): return self.rows[0] if self.rows else None
    def fetchall(self): return self.rows
    def close(self): pass

cur = sqliter._PgCursorAdapter(FakeCur())

# PRAGMA должен игнорироваться
dbconfig.IS_POSTGRES = True
cur.execute("PRAGMA journal_mode=WAL")
assert not executed, "PRAGMA не должен уходить в PostgreSQL"
print("PRAGMA ignored: OK")

cur.execute("SELECT * FROM users WHERE id = ? AND tag = 'x?y'", (5,))
sql, params = executed[-1]
assert sql == "SELECT * FROM users WHERE id = %s AND tag = 'x?y'", sql
assert params == (5,), params
print("placeholder translation: OK ->", sql)

cur.execute("INSERT OR IGNORE INTO t (a) VALUES (?)", (1,))
assert "ON CONFLICT DO NOTHING" in executed[-1][0]
print("INSERT OR IGNORE: OK ->", executed[-1][0])

# строки: доступ и по имени, и по индексу (код использует оба стиля)
row = cur.fetchone()
assert row['name'] == 'alice' and row[0] == 1, (dict(row), row[0])
assert dict(row) == {'id':1,'name':'alice'}
print("row dict+index access: OK ->", dict(row), "| row[0] =", row[0])

rows = cur.fetchall()
assert [dict(r) for r in rows][1]['name'] == 'bob'
print("fetchall: OK, rows =", len(rows))

dbconfig.IS_POSTGRES = False
print("\nALL PG ADAPTER TESTS PASSED")
