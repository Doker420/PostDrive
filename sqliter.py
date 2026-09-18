import sqlite3
import time
import asyncio
import logging
import os
import queue
import threading
import contextlib
import contextvars
import functools
from typing import List, Dict, Optional, Any, Tuple

logger = logging.getLogger(__name__)

# ── Shared singleton accessor ─────────────────────────────────────
_db_instance: Optional['DBConnection'] = None
_db_lock = asyncio.Lock()

async def get_db(db_path: str = 'database.db') -> 'DBConnection':
    """Returns the shared DBConnection singleton. Call this instead of DBConnection()."""
    global _db_instance
    if _db_instance is None:
        async with _db_lock:
            if _db_instance is None:
                _db_instance = DBConnection(db_path)
    return _db_instance

def get_db_sync(db_path: str = 'database.db') -> 'DBConnection':
    """Synchronous fallback for module-level use where async is not available.
    Must be called after the async singleton has been initialised (or in a fresh process)."""
    global _db_instance
    if _db_instance is None:
        _db_instance = DBConnection(db_path)
    return _db_instance

class _AutoCursor:
    """Fallback-курсор для прямого доступа к db.c вне метода класса.

    Захватывает соединение из пула и держит его до сборки мусора. В штатном
    режиме недостижим: все публичные методы DBConnection обёрнуты в
    _with_pooled_connection и уже имеют закреплённое соединение.
    """
    __slots__ = ('_db', '_pooled', '_cm')

    def __init__(self, db):
        self._db = db
        self._cm = db.connection()
        self._pooled = self._cm.__enter__()

    def __getattr__(self, item):
        return getattr(self._pooled.cursor, item)

    def __del__(self):
        try:
            self._cm.__exit__(None, None, None)
        except Exception:
            pass


def _with_pooled_connection(func):
    """Закрепляет за вызовом метода одно соединение из пула.

    Благодаря реентрантности connection() вложенные вызовы методов БД
    переиспользуют то же соединение, поэтому execute() и fetchone() внутри
    одного метода всегда работают на одном курсоре и не могут перемешаться
    с запросами конкурентной задачи.
    """
    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        with self.connection():
            return func(self, *args, **kwargs)
    return wrapper


class _PoolBoundMeta(type):
    """Автоматически оборачивает публичные методы в _with_pooled_connection."""

    _SKIP = {
        'connection', 'transaction', 'close', 'pool_stats', 'c', 'conn_ctx',
        '_cursor', '_new_raw_conn', '_apply_pragmas', '_acquire_raw', '_current',
        '_dict_fetchone', '_dict_fetchall',
    }

    def __new__(mcls, name, bases, ns):
        for attr, value in list(ns.items()):
            if attr.startswith('__') or attr in mcls._SKIP:
                continue
            if isinstance(value, (staticmethod, classmethod, property)):
                continue
            if callable(value) and not asyncio.iscoroutinefunction(value):
                ns[attr] = _with_pooled_connection(value)
        return super().__new__(mcls, name, bases, ns)


class _PooledConnection:
    """Обёртка над sqlite3.Connection, которая возвращает себя в пул при release()."""
    __slots__ = ('raw', 'cursor', 'pool', 'depth')

    def __init__(self, raw, pool):
        self.raw = raw
        self.cursor = raw.cursor()
        self.pool = pool
        self.depth = 0  # счётчик вложенных захватов внутри одной задачи

    # Прозрачное проксирование Connection API (execute/commit/rollback/...)
    def __getattr__(self, item):
        return getattr(self.raw, item)


class DBConnection(metaclass=_PoolBoundMeta):
    """SQLite-доступ с пулом соединений.

    Каждая asyncio-задача (или поток) получает собственное соединение и собственный
    курсор на время работы. Это устраняет гонку, при которой два конкурентных
    обработчика делали execute() и fetchone() на одном общем курсоре и получали
    чужие строки. Записи сериализуются через отдельный write-лок, чтение идёт
    параллельно благодаря WAL.
    """

    # Сколько одновременных соединений держать. Читатели в WAL не блокируют друг друга.
    POOL_SIZE = int(os.environ.get('DB_POOL_SIZE', '12'))

    def __init__(self, db_path: str = 'database.db', pool_size: Optional[int] = None):
        self.db_path = db_path
        self.pool_size = pool_size or self.POOL_SIZE

        self._pool: "queue.LifoQueue[_PooledConnection]" = queue.LifoQueue()
        self._all_conns: List[_PooledConnection] = []
        self._pool_lock = threading.Lock()
        self._created = 0

        # Соединение, закреплённое за текущей задачей/потоком (реентрантность)
        self._local = threading.local()
        self._ctx_conn: contextvars.ContextVar = contextvars.ContextVar(
            f'db_conn_{id(self)}', default=None
        )

        # Служебное соединение для миграций/DDL и для legacy-доступа вне задач
        self.conn = self._new_raw_conn()

        self._write_lock = asyncio.Lock()      # для async-писателей
        self._thread_write_lock = threading.RLock()  # для sync-писателей

        self._apply_pragmas(self.conn)
        self.create_tables()
        self.update_db()
        self.seed_default_tariffs()
        self.cleanup_old_data()

        # Register as shared singleton
        global _db_instance
        _db_instance = self
        logger.info(f"DB pool initialised: size={self.pool_size} path={self.db_path}")

    # ── Connection factory ────────────────────────────────────────
    def _new_raw_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self.db_path,
            check_same_thread=False,
            timeout=30,               # wait up to 30s for locks instead of immediate error
            isolation_level=None,     # autocommit mode; we manage transactions explicitly
        )
        conn.row_factory = sqlite3.Row
        return conn

    def _apply_pragmas(self, conn: sqlite3.Connection, verbose: bool = True):
        """Apply performance and safety pragmas. WAL mode allows concurrent reads while writing."""
        c = conn.cursor()
        c.execute('PRAGMA journal_mode=WAL')
        c.execute('PRAGMA busy_timeout=30000')      # 30s lock timeout
        c.execute('PRAGMA synchronous=NORMAL')      # safe + fast with WAL
        c.execute('PRAGMA foreign_keys=ON')
        c.execute('PRAGMA cache_size=-65536')       # 64MB page cache
        c.execute('PRAGMA temp_store=MEMORY')       # temp tables in RAM
        c.execute('PRAGMA mmap_size=268435456')     # 256MB memory-mapped IO
        c.close()
        if verbose:
            logger.info(f"DB pragmas applied (WAL mode, busy_timeout=30s) for {self.db_path}")

    # ── Pool management ───────────────────────────────────────────
    def _acquire_raw(self, timeout: float = 30.0) -> _PooledConnection:
        """Достаёт соединение из пула, при необходимости создавая новое."""
        try:
            return self._pool.get_nowait()
        except queue.Empty:
            pass
        with self._pool_lock:
            if self._created < self.pool_size:
                pooled = _PooledConnection(self._new_raw_conn(), self)
                self._apply_pragmas(pooled.raw, verbose=False)
                self._created += 1
                self._all_conns.append(pooled)
                return pooled
        # Пул исчерпан — ждём освобождения
        try:
            return self._pool.get(timeout=timeout)
        except queue.Empty:
            raise TimeoutError(f"DB pool exhausted (size={self.pool_size}), no connection in {timeout}s")

    def _current(self) -> Optional[_PooledConnection]:
        """Соединение, закреплённое за текущим контекстом (задачей или потоком)."""
        pooled = self._ctx_conn.get()
        if pooled is not None:
            return pooled
        return getattr(self._local, 'conn', None)

    @contextlib.contextmanager
    def connection(self):
        """Закрепляет соединение из пула за текущим контекстом.

        Реентрантно: вложенные вызовы переиспользуют то же соединение, поэтому
        транзакция внутри метода, который сам вызывает другие методы БД,
        остаётся целостной.
        """
        existing = self._current()
        if existing is not None:
            existing.depth += 1
            try:
                yield existing
            finally:
                existing.depth -= 1
            return

        pooled = self._acquire_raw()
        pooled.depth = 1
        token = self._ctx_conn.set(pooled)
        self._local.conn = pooled
        try:
            yield pooled
        finally:
            pooled.depth = 0
            try:
                self._ctx_conn.reset(token)
            except ValueError:
                self._ctx_conn.set(None)
            self._local.conn = None
            try:
                # Не тащим незакрытую транзакцию в следующего пользователя
                if pooled.raw.in_transaction:
                    pooled.raw.rollback()
            except Exception:
                pass
            self._pool.put(pooled)

    @contextlib.contextmanager
    def transaction(self):
        """Атомарная транзакция на выделенном соединении (write-путь)."""
        with self._thread_write_lock:
            with self.connection() as pooled:
                if pooled.depth > 1:
                    # уже внутри внешней транзакции — не открываем вложенную
                    yield pooled
                    return
                try:
                    pooled.raw.execute('BEGIN IMMEDIATE')
                    yield pooled
                    pooled.raw.commit()
                except Exception:
                    try:
                        pooled.raw.rollback()
                    except Exception:
                        pass
                    raise

    def close(self):
        """Закрывает все соединения пула."""
        with self._pool_lock:
            for pooled in self._all_conns:
                try:
                    pooled.cursor.close()
                    pooled.raw.close()
                except Exception:
                    pass
            self._all_conns.clear()
            self._created = 0
        while True:
            try:
                self._pool.get_nowait()
            except queue.Empty:
                break
        try:
            self.conn.close()
        except Exception:
            pass
        logger.info("DB pool closed")

    def pool_stats(self) -> Dict[str, int]:
        return {
            'size': self.pool_size,
            'created': self._created,
            'idle': self._pool.qsize(),
            'in_use': self._created - self._pool.qsize(),
        }

    # ── Cursor access (backwards compatible) ──────────────────────
    @property
    def c(self):
        """Курсор текущего контекста.

        Если задача уже держит соединение (через connection()/transaction()),
        отдаём его курсор. Иначе — автоматически берём соединение из пула на
        время одного вызова, чтобы старый код `self.c.execute(...)` продолжал
        работать и при этом был изолирован от других задач.
        """
        pooled = self._current()
        if pooled is not None:
            return pooled.cursor
        return _AutoCursor(self)

    @property
    def conn_ctx(self):
        """Соединение текущего контекста (или служебное)."""
        pooled = self._current()
        return pooled.raw if pooled is not None else self.conn

    def _cursor(self):
        pooled = self._current()
        if pooled is not None:
            return pooled.raw.cursor()
        return self.conn_ctx.cursor()

    def _dict_fetchone(self, c=None):
        if c is None:
            c = self.c
        row = c.fetchone()
        if row is None:
            return None
        return dict(row)

    def _dict_fetchall(self, c=None):
        if c is None:
            c = self.c
        rows = c.fetchall()
        return [dict(row) for row in rows]

    def create_tables(self):
        c = self._cursor()
        # Users table with subscription support
        c.execute('''CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            subscription_until INTEGER DEFAULT 0,
            is_admin INTEGER DEFAULT 0,
            created_at INTEGER DEFAULT (strftime('%s', 'now'))
        )''')

        # Tariffs for subscription
        self.c.execute('''CREATE TABLE IF NOT EXISTS tariffs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            duration_days INTEGER NOT NULL,
            price_usd REAL NOT NULL,
            description TEXT,
            is_active INTEGER DEFAULT 1
        )''')

        # CryptoBot Invoices
        self.c.execute('''CREATE TABLE IF NOT EXISTS invoices (
            invoice_id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            tariff_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            asset TEXT DEFAULT 'USDT',
            pay_url TEXT,
            status TEXT DEFAULT 'active',
            created_at INTEGER DEFAULT (strftime('%s', 'now'))
        )''')

        # User Telegram accounts (multi-account)
        self.c.execute('''CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            phone TEXT,
            session_string TEXT NOT NULL,
            account_name TEXT,
            proxy TEXT DEFAULT '',
            status TEXT DEFAULT 'active',
            post_text TEXT DEFAULT '',
            post_photo TEXT DEFAULT '',
            post_entities TEXT DEFAULT NULL,
            parse_mode TEXT DEFAULT 'HTML',
            timeout INTEGER DEFAULT 5,
            spam_status INTEGER DEFAULT 0,
            autoresponder_enabled INTEGER DEFAULT 0,
            autoresponder_text TEXT DEFAULT '',
            notifications_hidden INTEGER DEFAULT 0,
            created_at INTEGER DEFAULT (strftime('%s', 'now')),
            FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
        )''')

        # Chats for each account (selective spamming and settings)
        self.c.execute('''CREATE TABLE IF NOT EXISTS account_chats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            chat_id TEXT NOT NULL,
            chat_title TEXT,
            chat_username TEXT,
            chat_type TEXT DEFAULT 'unknown',
            spam_enabled INTEGER DEFAULT 1,
            additional_text TEXT DEFAULT '',
            custom_text TEXT DEFAULT '',
            timeout INTEGER DEFAULT 5,
            synced_at INTEGER DEFAULT (strftime('%s', 'now')),
            FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE CASCADE,
            UNIQUE(account_id, chat_id)
        )''')

        # Categories for chat packs
        self.c.execute('''CREATE TABLE IF NOT EXISTS chat_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            created_at INTEGER DEFAULT (strftime('%s', 'now'))
        )''')

        # Chat packs within categories
        self.c.execute('''CREATE TABLE IF NOT EXISTS chat_packs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            created_at INTEGER DEFAULT (strftime('%s', 'now')),
            FOREIGN KEY(category_id) REFERENCES chat_categories(id) ON DELETE CASCADE
        )''')

        # Items in chat packs
        self.c.execute('''CREATE TABLE IF NOT EXISTS chat_pack_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pack_id INTEGER NOT NULL,
            chat_url TEXT NOT NULL,
            title TEXT DEFAULT '',
            FOREIGN KEY(pack_id) REFERENCES chat_packs(id) ON DELETE CASCADE
        )''')

        # General key-value settings
        self.c.execute('''CREATE TABLE IF NOT EXISTS bot_kv_settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )''')

        # Partners system
        self.c.execute('''CREATE TABLE IF NOT EXISTS partners (
            user_id INTEGER PRIMARY KEY,
            referral_code TEXT UNIQUE NOT NULL,
            earnings_balance REAL DEFAULT 0.0,
            total_earnings REAL DEFAULT 0.0,
            total_withdrawn REAL DEFAULT 0.0,
            referral_count INTEGER DEFAULT 0,
            created_at INTEGER DEFAULT (strftime('%s', 'now')),
            FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
        )''')

        # Partner referrals tracking
        self.c.execute('''CREATE TABLE IF NOT EXISTS partner_referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            partner_id INTEGER NOT NULL,
            referral_user_id INTEGER NOT NULL,
            created_at INTEGER DEFAULT (strftime('%s', 'now')),
            FOREIGN KEY(partner_id) REFERENCES partners(user_id) ON DELETE CASCADE,
            FOREIGN KEY(referral_user_id) REFERENCES users(user_id) ON DELETE CASCADE,
            UNIQUE(referral_user_id)
        )''')

        # Partner transactions (earnings & withdrawals)
        self.c.execute('''CREATE TABLE IF NOT EXISTS partner_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            partner_id INTEGER NOT NULL,
            type TEXT NOT NULL,
            amount REAL NOT NULL,
            description TEXT DEFAULT '',
            created_at INTEGER DEFAULT (strftime('%s', 'now')),
            FOREIGN KEY(partner_id) REFERENCES partners(user_id) ON DELETE CASCADE
        )''')

        # Bot mirrors for partners
        self.c.execute('''CREATE TABLE IF NOT EXISTS bot_mirrors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            partner_id INTEGER NOT NULL,
            bot_token TEXT NOT NULL,
            bot_username TEXT DEFAULT '',
            webhook_url TEXT DEFAULT '',
            is_active INTEGER DEFAULT 1,
            created_at INTEGER DEFAULT (strftime('%s', 'now')),
            FOREIGN KEY(partner_id) REFERENCES partners(user_id) ON DELETE CASCADE
        )''')

        # Recurring messages for admin
        self.c.execute('''CREATE TABLE IF NOT EXISTS recurring_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            text TEXT NOT NULL,
            media_file_id TEXT DEFAULT '',
            buttons TEXT DEFAULT '[]',
            interval_minutes INTEGER NOT NULL DEFAULT 60,
            target_type TEXT DEFAULT 'all',
            is_active INTEGER DEFAULT 1,
            last_sent_at INTEGER DEFAULT 0,
            created_at INTEGER DEFAULT (strftime('%s', 'now'))
        )''')

        # Promo codes for subscription activation
        self.c.execute('''CREATE TABLE IF NOT EXISTS promo_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL UNIQUE,
            days INTEGER NOT NULL,
            max_uses INTEGER DEFAULT 1,
            used_count INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            created_at INTEGER DEFAULT (strftime('%s', 'now'))
        )''')
        self.c.execute('''CREATE TABLE IF NOT EXISTS promo_code_uses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            promo_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            used_at INTEGER DEFAULT (strftime('%s', 'now')),
            FOREIGN KEY(promo_id) REFERENCES promo_codes(id) ON DELETE CASCADE,
            UNIQUE(promo_id, user_id)
        )''')

        # Account reports for spam statistics
        c.execute('''CREATE TABLE IF NOT EXISTS account_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            post_text TEXT DEFAULT '',
            post_photo TEXT DEFAULT '',
            total_chats INTEGER DEFAULT 0,
            sent_count INTEGER DEFAULT 0,
            error_count INTEGER DEFAULT 0,
            started_at INTEGER DEFAULT 0,
            finished_at INTEGER DEFAULT 0,
            FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE CASCADE
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS report_chats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_id INTEGER NOT NULL,
            chat_id TEXT NOT NULL,
            chat_title TEXT DEFAULT '',
            sent INTEGER DEFAULT 0,
            error TEXT DEFAULT '',
            FOREIGN KEY(report_id) REFERENCES account_reports(id) ON DELETE CASCADE
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS parsed_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            user_id_val INTEGER DEFAULT 0,
            username TEXT DEFAULT '',
            first_name TEXT DEFAULT '',
            last_name TEXT DEFAULT '',
            phone TEXT DEFAULT '',
            source_chat_id TEXT DEFAULT '',
            parsed_at INTEGER DEFAULT (strftime('%s', 'now')),
            FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE CASCADE,
            UNIQUE(account_id, user_id, user_id_val)
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS neurocomment_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            enabled INTEGER DEFAULT 0,
            mode TEXT DEFAULT 'prompt',
            prompt TEXT DEFAULT '',
            custom_comments TEXT DEFAULT '',
            post_prompt TEXT DEFAULT '',
            target_channels TEXT DEFAULT '',
            comment_delay INTEGER DEFAULT 60,
            randomize INTEGER DEFAULT 0,
            created_at INTEGER DEFAULT (strftime('%s', 'now')),
            FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE CASCADE,
            FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE,
            UNIQUE(account_id)
        )''')

        # Legacy tables preserved for backwards compatibility
        c.execute('''CREATE TABLE IF NOT EXISTS CHANNELS (
            CHANNEL TEXT PRIMARY KEY,
            ADDITIONAL TEXT,
            SPAM_ENABLED INTEGER DEFAULT 1,
            TIMEOUT INTEGER DEFAULT 5
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS SETTINGS (
            ID INTEGER PRIMARY KEY,
            PHOTO TEXT DEFAULT '',
            TEXT TEXT DEFAULT '',
            PARSE_MODE TEXT DEFAULT 'HTML',
            ADDITIONAL TEXT DEFAULT '',
            SPAM INTEGER DEFAULT 0,
            TIMEOUT INTEGER DEFAULT 5,
            auto_response_enabled INTEGER DEFAULT 1,
            post_entities TEXT DEFAULT NULL
        )''')

        # ── Task registry for persistence and recovery ─────────────
        c.execute('''CREATE TABLE IF NOT EXISTS running_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            account_id INTEGER,
            task_type TEXT NOT NULL,
            status TEXT DEFAULT 'running',
            progress TEXT DEFAULT '',
            started_at INTEGER DEFAULT (strftime('%s', 'now')),
            finished_at INTEGER DEFAULT 0
        )''')

        # ── Performance indexes ────────────────────────────────────
        c.execute('CREATE INDEX IF NOT EXISTS idx_accounts_user_id ON accounts(user_id)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_account_chats_account_id ON account_chats(account_id)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_account_chats_type ON account_chats(account_id, chat_type)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_account_chats_spam ON account_chats(account_id, spam_enabled)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_invoices_status ON invoices(status)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_parsed_users_account ON parsed_users(account_id, user_id)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_running_tasks_user ON running_tasks(user_id)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_running_tasks_status ON running_tasks(status)')

        self.conn_ctx.commit()
        c.close()

    def update_db(self):
        c = self._cursor()
        try:
            c.execute('ALTER TABLE users ADD COLUMN subscription_until INTEGER DEFAULT 0')
        except sqlite3.OperationalError:
            pass
        try:
            c.execute('ALTER TABLE users ADD COLUMN is_admin INTEGER DEFAULT 0')
        except sqlite3.OperationalError:
            pass
        try:
            c.execute('ALTER TABLE users ADD COLUMN created_at INTEGER DEFAULT 0')
        except sqlite3.OperationalError:
            pass
        try:
            c.execute('ALTER TABLE accounts ADD COLUMN proxy TEXT DEFAULT \'\'')
        except sqlite3.OperationalError:
            pass
        try:
            c.execute('ALTER TABLE accounts ADD COLUMN post_entities TEXT DEFAULT NULL')
        except sqlite3.OperationalError:
            pass
        try:
            c.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_account_chats_acc_chat ON account_chats(account_id, chat_id)')
        except Exception:
            pass
        try:
            c.execute('ALTER TABLE accounts ADD COLUMN autoresponder_enabled INTEGER DEFAULT 0')
        except sqlite3.OperationalError:
            pass
        try:
            c.execute('ALTER TABLE accounts ADD COLUMN autoresponder_text TEXT DEFAULT \'\'')
        except sqlite3.OperationalError:
            pass
        try:
            c.execute('ALTER TABLE accounts ADD COLUMN autoresponder_media_path TEXT DEFAULT \'\'')
        except sqlite3.OperationalError:
            pass
        try:
            c.execute('ALTER TABLE accounts ADD COLUMN autoresponder_media_type TEXT DEFAULT \'\'')
        except sqlite3.OperationalError:
            pass
        try:
            c.execute('ALTER TABLE accounts ADD COLUMN autoresponder_entities TEXT DEFAULT NULL')
        except sqlite3.OperationalError:
            pass
        try:
            c.execute('ALTER TABLE accounts ADD COLUMN autoresponder_parse_mode TEXT DEFAULT "HTML"')
        except sqlite3.OperationalError:
            pass
        try:
            c.execute('ALTER TABLE accounts ADD COLUMN post_parse_mode TEXT DEFAULT "HTML"')
        except sqlite3.OperationalError:
            pass
        try:
            c.execute('ALTER TABLE recurring_messages ADD COLUMN media_file_id TEXT DEFAULT ""')
        except sqlite3.OperationalError:
            pass
        try:
            c.execute('ALTER TABLE recurring_messages ADD COLUMN buttons TEXT DEFAULT "[]"')
        except sqlite3.OperationalError:
            pass
        try:
            c.execute('ALTER TABLE account_chats ADD COLUMN custom_text TEXT DEFAULT ""')
        except sqlite3.OperationalError:
            pass
        try:
            c.execute('ALTER TABLE accounts ADD COLUMN notifications_hidden INTEGER DEFAULT 0')
        except sqlite3.OperationalError:
            pass
        try:
            c.execute('ALTER TABLE account_chats ADD COLUMN chat_type TEXT DEFAULT \'unknown\'')
        except sqlite3.OperationalError:
            pass
        try:
            c.execute('ALTER TABLE account_chats ADD COLUMN synced_at INTEGER DEFAULT 0')
        except sqlite3.OperationalError:
            pass
        try:
            c.execute('ALTER TABLE neurocomment_settings ADD COLUMN comment_delay INTEGER DEFAULT 60')
        except sqlite3.OperationalError:
            pass
        try:
            c.execute('ALTER TABLE parsed_users ADD COLUMN user_id_val INTEGER DEFAULT 0')
        except sqlite3.OperationalError:
            pass
        try:
            c.execute('ALTER TABLE parsed_users ADD COLUMN source_chat_id TEXT DEFAULT \'\'')
        except sqlite3.OperationalError:
            pass
        self.conn_ctx.commit()
        c.close()

    def seed_default_tariffs(self):
        c = self._cursor()
        c.execute('SELECT COUNT(*) FROM tariffs')
        if c.fetchone()[0] == 0:
            default_tariffs = [
                ("3 дня (Тест)", 3, 3.0, "Пробный доступ на 3 дня"),
                ("1 месяц", 30, 15.0, "Полный доступ на 30 дней"),
                ("3 месяца (Скидка)", 90, 35.0, "Полный доступ на 90 дней со скидкой"),
                ("Навсегда", 3650, 99.0, "Безлимитный пожизненный доступ")
            ]
            c.executemany(
                'INSERT INTO tariffs (name, duration_days, price_usd, description) VALUES (?, ?, ?, ?)',
                default_tariffs
            )
            self.conn_ctx.commit()
        c.close()

    # ==================== USERS & SUBSCRIPTION ====================
    def get_or_create_user(self, user_id: int, username: str = "", first_name: str = "", last_name: str = "", admin_id: int = 0) -> Dict[str, Any]:
        c = self._cursor()
        c.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        user = self._dict_fetchone(c)
        is_admin = 1 if user_id == admin_id else (user['is_admin'] if user else 0)
        
        now = int(time.time())
        if not user:
            c.execute(
                'INSERT INTO users (user_id, username, first_name, last_name, subscription_until, is_admin, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)',
                (user_id, username, first_name, last_name, 0, is_admin, now)
            )
            self.conn_ctx.commit()
            c.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
            user = self._dict_fetchone(c)
        else:
            c.execute(
                'UPDATE users SET username = ?, first_name = ?, last_name = ?, is_admin = ? WHERE user_id = ?',
                (username, first_name, last_name, is_admin, user_id)
            )
            self.conn_ctx.commit()
            c.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
            user = self._dict_fetchone(c)
        return user

    def get_user(self, user_id: int) -> Optional[Dict[str, Any]]:
        self.c.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        return self._dict_fetchone()

    def get_all_users(self) -> List[Dict[str, Any]]:
        self.c.execute('SELECT * FROM users ORDER BY created_at DESC')
        return self._dict_fetchall()

    def is_user_subscribed(self, user_id: int, admin_id: int = 0) -> bool:
        if user_id == admin_id:
            return True
        user = self.get_user(user_id)
        if not user:
            return False
        if user.get('is_admin') == 1:
            return True
        sub_until = user.get('subscription_until', 0) or 0
        return sub_until > int(time.time())

    def add_subscription_days(self, user_id: int, days: int):
        user = self.get_user(user_id)
        now = int(time.time())
        current_sub = user.get('subscription_until', 0) if user else 0
        
        if current_sub and current_sub > now:
            new_sub = current_sub + (days * 86400)
        else:
            new_sub = now + (days * 86400)

        self.c.execute('UPDATE users SET subscription_until = ? WHERE user_id = ?', (new_sub, user_id))
        self.conn_ctx.commit()
        return new_sub

    def set_user_admin(self, user_id: int, is_admin: int):
        self.c.execute('UPDATE users SET is_admin = ? WHERE user_id = ?', (is_admin, user_id))
        self.conn_ctx.commit()

    # ==================== TARIFFS & INVOICES ====================
    def get_tariffs(self, active_only: bool = True) -> List[Dict[str, Any]]:
        if active_only:
            self.c.execute('SELECT * FROM tariffs WHERE is_active = 1 ORDER BY price_usd ASC')
        else:
            self.c.execute('SELECT * FROM tariffs ORDER BY price_usd ASC')
        return self._dict_fetchall()

    def get_tariff(self, tariff_id: int) -> Optional[Dict[str, Any]]:
        self.c.execute('SELECT * FROM tariffs WHERE id = ?', (tariff_id,))
        return self._dict_fetchone()

    def add_tariff(self, name: str, duration_days: int, price_usd: float, description: str = "") -> int:
        self.c.execute(
            'INSERT INTO tariffs (name, duration_days, price_usd, description, is_active) VALUES (?, ?, ?, ?, 1)',
            (name, duration_days, price_usd, description)
        )
        self.conn_ctx.commit()
        return self.c.lastrowid

    def delete_tariff(self, tariff_id: int):
        self.c.execute('DELETE FROM tariffs WHERE id = ?', (tariff_id,))
        self.conn_ctx.commit()

    def create_invoice_record(self, invoice_id: int, user_id: int, tariff_id: int, amount: float, asset: str, pay_url: str):
        self.c.execute(
            'INSERT OR REPLACE INTO invoices (invoice_id, user_id, tariff_id, amount, asset, pay_url, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
            (invoice_id, user_id, tariff_id, amount, asset, pay_url, 'active', int(time.time()))
        )
        self.conn_ctx.commit()

    def get_invoice(self, invoice_id: int) -> Optional[Dict[str, Any]]:
        self.c.execute('SELECT * FROM invoices WHERE invoice_id = ?', (invoice_id,))
        return self._dict_fetchone()

    def mark_invoice_paid(self, invoice_id: int) -> bool:
        self.c.execute('SELECT * FROM invoices WHERE invoice_id = ?', (invoice_id,))
        invoice = self._dict_fetchone()
        if not invoice:
            return False
        if invoice['status'] == 'paid':
            return True
        
        self.c.execute('UPDATE invoices SET status = "paid" WHERE invoice_id = ?', (invoice_id,))
        tariff = self.get_tariff(invoice['tariff_id'])
        if tariff:
            self.add_subscription_days(invoice['user_id'], tariff['duration_days'])
        self.conn_ctx.commit()
        return True

    # ==================== ACCOUNTS ====================
    def add_account(self, user_id: int, session_string: str, phone: str = "", account_name: str = "", proxy: str = "") -> int:
        self.c.execute('''
            INSERT INTO accounts (user_id, phone, session_string, account_name, proxy, status, post_text, post_photo, parse_mode, timeout, spam_status, created_at)
            VALUES (?, ?, ?, ?, ?, 'active', '', '', 'HTML', 5, 0, ?)
        ''', (user_id, phone, session_string, account_name, proxy, int(time.time())))
        self.conn_ctx.commit()
        return self.c.lastrowid

    def get_user_accounts(self, user_id: int) -> List[Dict[str, Any]]:
        self.c.execute('SELECT * FROM accounts WHERE user_id = ? ORDER BY id ASC', (user_id,))
        return self._dict_fetchall()

    def get_account(self, account_id: int) -> Optional[Dict[str, Any]]:
        self.c.execute('SELECT * FROM accounts WHERE id = ?', (account_id,))
        return self._dict_fetchone()

    def update_account_status(self, account_id: int, status: str):
        self.c.execute('UPDATE accounts SET status = ? WHERE id = ?', (status, account_id))
        self.conn_ctx.commit()

    def update_account_name(self, account_id: int, name: str):
        self.c.execute('UPDATE accounts SET account_name = ? WHERE id = ?', (name, account_id))
        self.conn_ctx.commit()

    def update_account_proxy(self, account_id: int, proxy: str):
        self.c.execute('UPDATE accounts SET proxy = ? WHERE id = ?', (proxy, account_id))
        self.conn_ctx.commit()

    def update_autoresponder(self, account_id: int, text: str, parse_mode: str = None):
        self.c.execute('UPDATE accounts SET autoresponder_text = ?, autoresponder_parse_mode = ? WHERE id = ?', (text, parse_mode, account_id))
        self.conn_ctx.commit()

    def update_autoresponder_media(self, account_id: int, media_path: str, media_type: str):
        self.c.execute('UPDATE accounts SET autoresponder_media_path = ?, autoresponder_media_type = ? WHERE id = ?', (media_path, media_type, account_id))
        self.conn_ctx.commit()

    def update_autoresponder_entities(self, account_id: int, entities: str = None):
        self.c.execute('UPDATE accounts SET autoresponder_entities = ? WHERE id = ?', (entities, account_id))
        self.conn_ctx.commit()

    def toggle_autoresponder(self, account_id: int, enabled: int):
        self.c.execute('UPDATE accounts SET autoresponder_enabled = ? WHERE id = ?', (enabled, account_id))
        self.conn_ctx.commit()

    def toggle_notifications(self, account_id: int, hidden: int):
        self.c.execute('UPDATE accounts SET notifications_hidden = ? WHERE id = ?', (hidden, account_id))
        self.conn_ctx.commit()

    def update_account_post(self, account_id: int, text: str, photo: str = None, parse_mode: str = 'HTML', entities: str = None):
        if photo is not None:
            self.c.execute(
                'UPDATE accounts SET post_text = ?, post_photo = ?, post_parse_mode = ?, post_entities = ? WHERE id = ?',
                (text, photo, parse_mode, entities, account_id)
            )
        else:
            self.c.execute(
                'UPDATE accounts SET post_text = ?, post_parse_mode = ?, post_entities = ? WHERE id = ?',
                (text, parse_mode, entities, account_id)
            )
        self.conn_ctx.commit()

    def update_account_photo(self, account_id: int, photo: str):
        self.c.execute('UPDATE accounts SET post_photo = ? WHERE id = ?', (photo, account_id))
        self.conn_ctx.commit()

    def update_account_timeout(self, account_id: int, timeout: int):
        self.c.execute('UPDATE accounts SET timeout = ? WHERE id = ?', (int(timeout), account_id))
        self.conn_ctx.commit()

    def set_account_spam_status(self, account_id: int, spam_status: int):
        self.c.execute('UPDATE accounts SET spam_status = ? WHERE id = ?', (int(spam_status), account_id))
        self.conn_ctx.commit()

    def delete_account(self, account_id: int, user_id: int) -> bool:
        self.c.execute('DELETE FROM account_chats WHERE account_id = ?', (account_id,))
        self.c.execute('DELETE FROM accounts WHERE id = ? AND user_id = ?', (account_id, user_id))
        self.conn_ctx.commit()
        return self.c.rowcount > 0

    # ==================== ACCOUNT CHATS (Selective Spam & Settings) ====================
    UPSERT_CHAT_SQL = (
        "INSERT INTO account_chats\n    (account_id, chat_id, chat_title, chat_username, chat_type,\n     spam_enabled, additional_text, timeout, synced_at)\nVALUES (?, ?, ?, ?, ?, 1, '', 5, ?)\nON CONFLICT(account_id, chat_id) DO UPDATE SET\n    chat_title = excluded.chat_title,\n    chat_username = excluded.chat_username,\n    chat_type = excluded.chat_type,\n    synced_at = excluded.synced_at"
    )

    def sync_account_chats(self, account_id: int, chat_list: List[Dict[str, Any]]):
        """Adds or updates chats discovered for an account without resetting custom settings.

        Один batch-upsert в одной транзакции вместо N отдельных SELECT/UPDATE —
        критично при тысячах диалогов на аккаунт.
        """
        if not chat_list:
            return
        now = int(time.time())
        rows = []
        for idx, ch in enumerate(chat_list):
            rows.append((
                account_id,
                str(ch.get('id')),
                ch.get('title', ''),
                ch.get('username', ''),
                ch.get('chat_type', 'unknown'),
                now - idx,
            ))
        try:
            with self.transaction() as pooled:
                pooled.raw.executemany(self.UPSERT_CHAT_SQL, rows)
        except Exception as e:
            logger.error(f"sync_account_chats failed for account {account_id}: {e}")
            raise


    # Типы чатов, пригодные для постинга по чатам (только группы/супергруппы)
    GROUP_CHAT_TYPES = ('group', 'supergroup')

    def get_account_chats(self, account_id: int, spam_only: bool = False,
                          chat_types: Optional[Tuple[str, ...]] = None) -> List[Dict[str, Any]]:
        """Возвращает чаты аккаунта.

        chat_types — кортеж допустимых типов ('group', 'channel', 'private', 'bot').
        Для постинга/парсинга используйте chat_types=DBConnection.GROUP_CHAT_TYPES.
        """
        sql = 'SELECT * FROM account_chats WHERE account_id = ?'
        params: List[Any] = [account_id]
        if spam_only:
            sql += ' AND spam_enabled = 1'
        if chat_types:
            sql += ' AND chat_type IN (%s)' % ','.join('?' * len(chat_types))
            params.extend(chat_types)
        sql += ' ORDER BY chat_title ASC'
        self.c.execute(sql, params)
        return self._dict_fetchall()

    def get_account_chats_paginated(self, account_id: int, page: int = 0, per_page: int = 8,
                                    chat_types: Optional[Tuple[str, ...]] = None,
                                    spam_only: bool = False) -> Tuple[List[Dict[str, Any]], int]:
        """Пагинация на уровне SQL — не тянем тысячи строк в память ради одной страницы."""
        where = 'WHERE account_id = ?'
        params: List[Any] = [account_id]
        if spam_only:
            where += ' AND spam_enabled = 1'
        if chat_types:
            where += ' AND chat_type IN (%s)' % ','.join('?' * len(chat_types))
            params.extend(chat_types)
        self.c.execute(f'SELECT COUNT(*) FROM account_chats {where}', params)
        total = self.c.fetchone()[0]
        offset = max(0, page) * per_page
        self.c.execute(
            f'SELECT * FROM account_chats {where} ORDER BY chat_title ASC LIMIT ? OFFSET ?',
            params + [per_page, offset]
        )
        return self._dict_fetchall(), total

    def count_account_chats(self, account_id: int, chat_types: Optional[Tuple[str, ...]] = None,
                            spam_only: bool = False) -> int:
        sql = 'SELECT COUNT(*) FROM account_chats WHERE account_id = ?'
        params: List[Any] = [account_id]
        if spam_only:
            sql += ' AND spam_enabled = 1'
        if chat_types:
            sql += ' AND chat_type IN (%s)' % ','.join('?' * len(chat_types))
            params.extend(chat_types)
        self.c.execute(sql, params)
        return self.c.fetchone()[0]

    def get_account_chat(self, account_id: int, chat_id: str) -> Optional[Dict[str, Any]]:
        self.c.execute('SELECT * FROM account_chats WHERE account_id = ? AND chat_id = ?', (account_id, str(chat_id)))
        return self._dict_fetchone()

    def get_account_private_chats(self, account_id: int, page: int = 0, per_page: int = 20) -> List[Dict[str, Any]]:
        try:
            self.c.execute('PRAGMA table_info(account_chats)')
            columns = [row[1] for row in self.c.fetchall()]
            if 'synced_at' not in columns:
                self.c.execute('ALTER TABLE account_chats ADD COLUMN synced_at INTEGER DEFAULT 0')
                self.conn_ctx.commit()
        except Exception:
            pass
        
        offset = page * per_page
        self.c.execute(
            'SELECT * FROM account_chats WHERE account_id = ? AND chat_type = ? ORDER BY COALESCE(synced_at, 0) DESC LIMIT ? OFFSET ?',
            (account_id, 'private', per_page, offset)
        )
        return self._dict_fetchall()

    def get_account_private_chats_count(self, account_id: int) -> int:
        self.c.execute('SELECT COUNT(*) FROM account_chats WHERE account_id = ? AND chat_type = ?', (account_id, 'private'))
        return self.c.fetchone()[0]

    def toggle_chat_spam(self, account_id: int, chat_id: str) -> int:
        """Toggles spam_enabled between 1 and 0, returns new state."""
        chat = self.get_account_chat(account_id, chat_id)
        new_state = 0 if chat and chat['spam_enabled'] == 1 else 1
        if chat:
            self.c.execute('UPDATE account_chats SET spam_enabled = ? WHERE account_id = ? AND chat_id = ?', (new_state, account_id, str(chat_id)))
        else:
            self.c.execute('INSERT INTO account_chats (account_id, chat_id, spam_enabled) VALUES (?, ?, ?)', (account_id, str(chat_id), new_state))
        self.conn_ctx.commit()
        return new_state

    def set_all_chats_spam(self, account_id: int, enabled: int,
                           chat_types: Optional[Tuple[str, ...]] = None):
        sql = 'UPDATE account_chats SET spam_enabled = ? WHERE account_id = ?'
        params: List[Any] = [int(enabled), account_id]
        if chat_types:
            sql += ' AND chat_type IN (%s)' % ','.join('?' * len(chat_types))
            params.extend(chat_types)
        self.c.execute(sql, params)
        self.conn_ctx.commit()

    def update_chat_additional_text(self, account_id: int, chat_id: str, text: str):
        self.c.execute('''
            INSERT INTO account_chats (account_id, chat_id, additional_text)
            VALUES (?, ?, ?)
            ON CONFLICT(account_id, chat_id) DO UPDATE SET additional_text = excluded.additional_text
        ''', (account_id, str(chat_id), text))
        self.conn_ctx.commit()

    def update_chat_custom_text(self, account_id: int, chat_id: str, text: str):
        self.c.execute('''
            INSERT INTO account_chats (account_id, chat_id, custom_text)
            VALUES (?, ?, ?)
            ON CONFLICT(account_id, chat_id) DO UPDATE SET custom_text = excluded.custom_text
        ''', (account_id, str(chat_id), text))
        self.conn_ctx.commit()

    def remove_account_chat(self, account_id: int, chat_id: str):
        self.c.execute('DELETE FROM account_chats WHERE account_id = ? AND chat_id = ?', (account_id, str(chat_id)))
        self.conn_ctx.commit()

    # ==================== CHAT PACKS & CATEGORIES (Admin side) ====================
    def get_categories(self) -> List[Dict[str, Any]]:
        self.c.execute('SELECT * FROM chat_categories ORDER BY name ASC')
        return self._dict_fetchall()

    def add_category(self, name: str) -> int:
        self.c.execute('INSERT OR IGNORE INTO chat_categories (name) VALUES (?)', (name,))
        self.conn_ctx.commit()
        return self.c.lastrowid

    def delete_category(self, category_id: int):
        # Delete packs and items in cascade
        packs = self.get_packs_in_category(category_id)
        for p in packs:
            self.delete_pack(p['id'])
        self.c.execute('DELETE FROM chat_categories WHERE id = ?', (category_id,))
        self.conn_ctx.commit()

    def get_packs_in_category(self, category_id: int) -> List[Dict[str, Any]]:
        self.c.execute('''
            SELECT p.*, COUNT(i.id) as chats_count 
            FROM chat_packs p
            LEFT JOIN chat_pack_items i ON p.id = i.pack_id
            WHERE p.category_id = ?
            GROUP BY p.id
            ORDER BY p.name ASC
        ''', (category_id,))
        return self._dict_fetchall()

    def get_pack(self, pack_id: int) -> Optional[Dict[str, Any]]:
        self.c.execute('''
            SELECT p.*, c.name as category_name, COUNT(i.id) as chats_count
            FROM chat_packs p
            LEFT JOIN chat_categories c ON p.category_id = c.id
            LEFT JOIN chat_pack_items i ON p.id = i.pack_id
            WHERE p.id = ?
            GROUP BY p.id
        ''', (pack_id,))
        return self._dict_fetchone()

    def add_pack(self, category_id: int, name: str, description: str = "") -> int:
        self.c.execute(
            'INSERT INTO chat_packs (category_id, name, description) VALUES (?, ?, ?)',
            (category_id, name, description)
        )
        self.conn_ctx.commit()
        return self.c.lastrowid

    def delete_pack(self, pack_id: int):
        self.c.execute('DELETE FROM chat_pack_items WHERE pack_id = ?', (pack_id,))
        self.c.execute('DELETE FROM chat_packs WHERE id = ?', (pack_id,))
        self.conn_ctx.commit()

    def add_chats_to_pack(self, pack_id: int, chat_urls: List[str]):
        records = [(pack_id, u.strip(), '') for u in chat_urls if u.strip()]
        self.c.executemany('INSERT INTO chat_pack_items (pack_id, chat_url, title) VALUES (?, ?, ?)', records)
        self.conn_ctx.commit()

    def get_pack_chats(self, pack_id: int) -> List[Dict[str, Any]]:
        self.c.execute('SELECT * FROM chat_pack_items WHERE pack_id = ?', (pack_id,))
        return self._dict_fetchall()

    def delete_pack_chat(self, item_id: int):
        self.c.execute('DELETE FROM chat_pack_items WHERE id = ?', (item_id,))
        self.conn_ctx.commit()

    def get_admin_stats(self) -> Dict[str, Any]:
        now = int(time.time())
        self.c.execute('SELECT COUNT(*) FROM users')
        total_users = self.c.fetchone()[0]

        self.c.execute('SELECT COUNT(*) FROM users WHERE subscription_until > ?', (now,))
        active_subs = self.c.fetchone()[0]

        self.c.execute('SELECT COUNT(*) FROM accounts')
        total_accounts = self.c.fetchone()[0]

        self.c.execute('SELECT COUNT(*) FROM invoices WHERE status = "paid"')
        paid_invoices = self.c.fetchone()[0]

        self.c.execute('SELECT SUM(amount) FROM invoices WHERE status = "paid"')
        rev_row = self.c.fetchone()
        total_revenue = rev_row[0] if rev_row and rev_row[0] else 0.0

        self.c.execute('SELECT COUNT(*) FROM chat_categories')
        total_categories = self.c.fetchone()[0]

        self.c.execute('SELECT COUNT(*) FROM chat_packs')
        total_packs = self.c.fetchone()[0]

        self.c.execute('SELECT COUNT(*) FROM chat_pack_items')
        total_pack_chats = self.c.fetchone()[0]

        return {
            "total_users": total_users,
            "active_subs": active_subs,
            "expired_subs": max(0, total_users - active_subs),
            "total_accounts": total_accounts,
            "paid_invoices": paid_invoices,
            "total_revenue": total_revenue,
            "total_categories": total_categories,
            "total_packs": total_packs,
            "total_pack_chats": total_pack_chats
        }

    # ==================== BOT KV SETTINGS ====================
    def get_kv(self, key: str, default: str = "") -> str:
        self.c.execute('SELECT value FROM bot_kv_settings WHERE key = ?', (key,))
        row = self.c.fetchone()
        return row[0] if row else default

    def set_kv(self, key: str, value: str):
        self.c.execute('INSERT OR REPLACE INTO bot_kv_settings (key, value) VALUES (?, ?)', (key, str(value)))
        self.conn_ctx.commit()

    # ==================== PARTNERS SYSTEM ====================
    def create_partner(self, user_id: int, referral_code: str) -> Dict[str, Any]:
        self.c.execute(
            'INSERT OR IGNORE INTO partners (user_id, referral_code, created_at) VALUES (?, ?, ?)',
            (user_id, referral_code, int(time.time()))
        )
        self.conn_ctx.commit()
        return self.get_partner(user_id)

    def get_partner(self, user_id: int) -> Optional[Dict[str, Any]]:
        self.c.execute('SELECT * FROM partners WHERE user_id = ?', (user_id,))
        return self._dict_fetchone()

    def get_partner_by_code(self, referral_code: str) -> Optional[Dict[str, Any]]:
        self.c.execute('SELECT * FROM partners WHERE referral_code = ?', (referral_code,))
        return self._dict_fetchone()

    def get_partner_by_referral_user(self, referral_user_id: int) -> Optional[Dict[str, Any]]:
        self.c.execute('SELECT p.* FROM partners p JOIN partner_referrals r ON p.user_id = r.partner_id WHERE r.referral_user_id = ?', (referral_user_id,))
        return self._dict_fetchone()

    def add_referral(self, partner_id: int, referral_user_id: int) -> bool:
        existing = self.get_partner_by_referral_user(referral_user_id)
        if existing:
            return False
        self.c.execute(
            'INSERT OR IGNORE INTO partner_referrals (partner_id, referral_user_id, created_at) VALUES (?, ?, ?)',
            (partner_id, referral_user_id, int(time.time()))
        )
        self.c.execute('UPDATE partners SET referral_count = referral_count + 1 WHERE user_id = ?', (partner_id,))
        self.conn_ctx.commit()
        return True

    def add_partner_earning(self, partner_id: int, amount: float, description: str = "") -> bool:
        self.c.execute(
            'UPDATE partners SET earnings_balance = earnings_balance + ?, total_earnings = total_earnings + ? WHERE user_id = ?',
            (amount, amount, partner_id)
        )
        self.c.execute(
            'INSERT INTO partner_transactions (partner_id, type, amount, description, created_at) VALUES (?, ?, ?, ?, ?)',
            (partner_id, 'earning', amount, description, int(time.time()))
        )
        self.conn_ctx.commit()
        return True

    def withdraw_partner_earnings(self, partner_id: int, amount: float) -> bool:
        partner = self.get_partner(partner_id)
        if not partner or partner['earnings_balance'] < amount:
            return False
        self.c.execute(
            'UPDATE partners SET earnings_balance = earnings_balance - ?, total_withdrawn = total_withdrawn + ? WHERE user_id = ?',
            (amount, amount, partner_id)
        )
        self.c.execute(
            'INSERT INTO partner_transactions (partner_id, type, amount, description, created_at) VALUES (?, ?, ?, ?, ?)',
            (partner_id, 'withdrawal', amount, f'Вывод ${amount:.2f}', int(time.time()))
        )
        self.conn_ctx.commit()
        return True

    def get_partner_referrals(self, partner_id: int) -> List[Dict[str, Any]]:
        self.c.execute('''
            SELECT r.*, u.username, u.first_name, u.last_name
            FROM partner_referrals r
            LEFT JOIN users u ON r.referral_user_id = u.user_id
            WHERE r.partner_id = ?
            ORDER BY r.created_at DESC
        ''', (partner_id,))
        return self._dict_fetchall()

    def get_partner_transactions(self, partner_id: int, limit: int = 20) -> List[Dict[str, Any]]:
        self.c.execute('SELECT * FROM partner_transactions WHERE partner_id = ? ORDER BY created_at DESC LIMIT ?', (partner_id, limit))
        return self._dict_fetchall()

    def get_all_partners(self) -> List[Dict[str, Any]]:
        self.c.execute('SELECT * FROM partners ORDER BY total_earnings DESC')
        return self._dict_fetchall()

    def get_partner_stats(self, partner_id: int) -> Dict[str, Any]:
        partner = self.get_partner(partner_id)
        if not partner:
            return {}
        referrals = self.get_partner_referrals(partner_id)
        active_referrals = 0
        for ref in referrals:
            if self.is_user_subscribed(ref['referral_user_id']):
                active_referrals += 1
        return {
            'balance': partner['earnings_balance'],
            'total_earnings': partner['total_earnings'],
            'total_withdrawn': partner['total_withdrawn'],
            'referral_count': partner['referral_count'],
            'active_referrals': active_referrals
        }

    # ==================== BOT MIRRORS ====================
    def add_bot_mirror(self, partner_id: int, bot_token: str, bot_username: str = "", webhook_url: str = "") -> int:
        self.c.execute(
            'INSERT INTO bot_mirrors (partner_id, bot_token, bot_username, webhook_url, created_at) VALUES (?, ?, ?, ?, ?)',
            (partner_id, bot_token, bot_username, webhook_url, int(time.time()))
        )
        self.conn_ctx.commit()
        return self.c.lastrowid

    def get_partner_mirrors(self, partner_id: int) -> List[Dict[str, Any]]:
        self.c.execute('SELECT * FROM bot_mirrors WHERE partner_id = ? ORDER BY created_at DESC', (partner_id,))
        return self._dict_fetchall()

    def get_mirror(self, mirror_id: int) -> Optional[Dict[str, Any]]:
        self.c.execute('SELECT * FROM bot_mirrors WHERE id = ?', (mirror_id,))
        return self._dict_fetchone()

    def delete_mirror(self, mirror_id: int, partner_id: int) -> bool:
        self.c.execute('DELETE FROM bot_mirrors WHERE id = ? AND partner_id = ?', (mirror_id, partner_id))
        self.conn_ctx.commit()
        return self.c.rowcount > 0

    def get_all_mirrors(self) -> List[Dict[str, Any]]:
        self.c.execute('SELECT * FROM bot_mirrors ORDER BY created_at DESC')
        return self._dict_fetchall()

    def toggle_mirror(self, mirror_id: int, partner_id: int) -> bool:
        self.c.execute('UPDATE bot_mirrors SET is_active = CASE WHEN is_active = 1 THEN 0 ELSE 1 END WHERE id = ? AND partner_id = ?', (mirror_id, partner_id))
        self.conn_ctx.commit()
        return self.c.rowcount > 0

    # ==================== ADMIN SESSION EXPORT & CHECK ====================
    def get_all_accounts(self) -> List[Dict[str, Any]]:
        self.c.execute('SELECT * FROM accounts ORDER BY id ASC')
        return self._dict_fetchall()

    def get_all_accounts_with_user(self) -> List[Dict[str, Any]]:
        self.c.execute('''
            SELECT a.*, u.username as owner_username, u.first_name as owner_name
            FROM accounts a
            LEFT JOIN users u ON a.user_id = u.user_id
            ORDER BY a.id ASC
        ''')
        return self._dict_fetchall()

    def update_account_status_by_id(self, account_id: int, status: str):
        self.c.execute('UPDATE accounts SET status = ? WHERE id = ?', (status, account_id))
        self.conn_ctx.commit()

    def create_recurring_message(self, name: str, text: str, interval_minutes: int, target_type: str = "all", media_file_id: str = "", buttons: str = "[]") -> int:
        self.c.execute(
            '''INSERT INTO recurring_messages (name, text, interval_minutes, target_type, media_file_id, buttons, is_active, created_at)
               VALUES (?, ?, ?, ?, ?, ?, 1, ?)''',
            (name, text, interval_minutes, target_type, media_file_id, buttons, int(time.time()))
        )
        self.conn_ctx.commit()
        return self.c.lastrowid

    def get_recurring_messages(self, active_only: bool = False) -> List[Dict[str, Any]]:
        if active_only:
            self.c.execute('SELECT * FROM recurring_messages WHERE is_active = 1 ORDER BY created_at DESC')
        else:
            self.c.execute('SELECT * FROM recurring_messages ORDER BY created_at DESC')
        return self._dict_fetchall()

    def get_recurring_message(self, msg_id: int) -> Optional[Dict[str, Any]]:
        self.c.execute('SELECT * FROM recurring_messages WHERE id = ?', (msg_id,))
        return self._dict_fetchone()

    def toggle_recurring_message(self, msg_id: int) -> bool:
        self.c.execute('UPDATE recurring_messages SET is_active = CASE WHEN is_active = 1 THEN 0 ELSE 1 END WHERE id = ?', (msg_id,))
        self.conn_ctx.commit()
        return self.c.rowcount > 0

    def delete_recurring_message(self, msg_id: int):
        self.c.execute('DELETE FROM recurring_messages WHERE id = ?', (msg_id,))
        self.conn_ctx.commit()

    def update_recurring_message(self, msg_id: int, name: str = None, text: str = None, interval_minutes: int = None, media_file_id: str = None, buttons: str = None):
        updates = []
        params = []
        if name is not None:
            updates.append('name = ?')
            params.append(name)
        if text is not None:
            updates.append('text = ?')
            params.append(text)
        if interval_minutes is not None:
            updates.append('interval_minutes = ?')
            params.append(interval_minutes)
        if media_file_id is not None:
            updates.append('media_file_id = ?')
            params.append(media_file_id)
        if buttons is not None:
            updates.append('buttons = ?')
            params.append(buttons)
        if updates:
            params.append(msg_id)
            self.c.execute(f'UPDATE recurring_messages SET {", ".join(updates)} WHERE id = ?', params)
            self.conn_ctx.commit()

    def update_recurring_last_sent(self, msg_id: int):
        self.c.execute('UPDATE recurring_messages SET last_sent_at = ? WHERE id = ?', (int(time.time()), msg_id))
        self.conn_ctx.commit()

    # ==================== PROMO CODES ====================
    def create_promo_code(self, code: str, days: int, max_uses: int = 1) -> int:
        self.c.execute(
            'INSERT INTO promo_codes (code, days, max_uses) VALUES (?, ?, ?)',
            (code.upper().strip(), days, max_uses)
        )
        self.conn_ctx.commit()
        return self.c.lastrowid

    def get_promo_code(self, code: str) -> Optional[Dict[str, Any]]:
        self.c.execute('SELECT * FROM promo_codes WHERE code = ?', (code.upper().strip(),))
        return self._dict_fetchone()

    def use_promo_code(self, code: str, user_id: int) -> bool:
        promo = self.get_promo_code(code)
        if not promo:
            return False
        if promo['is_active'] != 1:
            return False
        if promo['used_count'] >= promo['max_uses']:
            return False
        self.c.execute('UPDATE promo_codes SET used_count = used_count + 1 WHERE id = ?', (promo['id'],))
        self.c.execute(
            'INSERT OR IGNORE INTO promo_code_uses (promo_id, user_id, used_at) VALUES (?, ?, ?)',
            (promo['id'], user_id, int(time.time()))
        )
        self.add_subscription_days(user_id, promo['days'])
        self.conn_ctx.commit()
        return True

    def get_all_promo_codes(self) -> List[Dict[str, Any]]:
        self.c.execute('SELECT * FROM promo_codes ORDER BY created_at DESC')
        return self._dict_fetchall()

    def delete_promo_code(self, code_id: int):
        self.c.execute('DELETE FROM promo_codes WHERE id = ?', (code_id,))
        self.conn_ctx.commit()

    def get_promo_code_uses(self, promo_id: int) -> List[Dict[str, Any]]:
        self.c.execute('SELECT * FROM promo_code_uses WHERE promo_id = ? ORDER BY used_at DESC', (promo_id,))
        return self._dict_fetchall()

    # ==================== ACCOUNT REPORTS ====================
    def create_account_report(self, account_id: int, user_id: int, post_text: str = '', post_photo: str = '') -> int:
        self.c.execute(
            'INSERT INTO account_reports (account_id, user_id, post_text, post_photo, started_at) VALUES (?, ?, ?, ?, ?)',
            (account_id, user_id, post_text, post_photo, int(time.time()))
        )
        self.conn_ctx.commit()
        return self.c.lastrowid

    def add_report_chat(self, report_id: int, chat_id: str, chat_title: str = '', sent: int = 0, error: str = ''):
        self.c.execute(
            'INSERT INTO report_chats (report_id, chat_id, chat_title, sent, error) VALUES (?, ?, ?, ?, ?)',
            (report_id, chat_id, chat_title, sent, error)
        )
        self.conn_ctx.commit()

    def get_account_reports(self, account_id: int) -> List[Dict[str, Any]]:
        self.c.execute('SELECT * FROM account_reports WHERE account_id = ? ORDER BY started_at DESC', (account_id,))
        return self._dict_fetchall()

    def get_report_chats(self, report_id: int) -> List[Dict[str, Any]]:
        self.c.execute('SELECT * FROM report_chats WHERE report_id = ?', (report_id,))
        return self._dict_fetchall()

    def update_report_stats(self, report_id: int, sent_delta: int = 0, error_delta: int = 0):
        if sent_delta:
            self.c.execute('UPDATE account_reports SET sent_count = sent_count + ? WHERE id = ?', (sent_delta, report_id))
        if error_delta:
            self.c.execute('UPDATE account_reports SET error_count = error_count + ? WHERE id = ?', (error_delta, report_id))
        self.conn_ctx.commit()

    def finish_report(self, report_id: int):
        self.c.execute('UPDATE account_reports SET finished_at = ? WHERE id = ?', (int(time.time()), report_id))
        self.conn_ctx.commit()

    # ==================== PARSED USERS ====================
    def save_parsed_users(self, account_id: int, user_id: int, users: List[Dict[str, Any]], source_chat_id: str = ''):
        try:
            for u in users:
                self.c.execute(
                    'INSERT OR IGNORE INTO parsed_users (account_id, user_id, user_id_val, username, first_name, last_name, phone, source_chat_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                    (account_id, user_id, u.get('id', 0), u.get('username', ''), u.get('first_name', ''), u.get('last_name', ''), u.get('phone', ''), source_chat_id)
                )
            self.conn_ctx.commit()
        except sqlite3.OperationalError:
            # Fallback for old DB schema without user_id_val
            try:
                for u in users:
                    self.c.execute(
                        'INSERT OR IGNORE INTO parsed_users (account_id, user_id, username, first_name, last_name, phone) VALUES (?, ?, ?, ?, ?, ?)',
                        (account_id, user_id, u.get('username', ''), u.get('first_name', ''), u.get('last_name', ''), u.get('phone', ''))
                    )
                self.conn_ctx.commit()
            except sqlite3.OperationalError:
                pass

    def get_parsed_users(self, account_id: int, user_id: int) -> List[Dict[str, Any]]:
        self.c.execute('SELECT * FROM parsed_users WHERE account_id = ? AND user_id = ? ORDER BY parsed_at DESC', (account_id, user_id))
        return self._dict_fetchall()

    def get_parsed_users_paginated(self, account_id: int, user_id: int, page: int = 0, per_page: int = 20) -> Tuple[List[Dict[str, Any]], int]:
        offset = page * per_page
        self.c.execute('SELECT COUNT(*) FROM parsed_users WHERE account_id = ? AND user_id = ?', (account_id, user_id))
        total = self.c.fetchone()[0]
        self.c.execute('SELECT * FROM parsed_users WHERE account_id = ? AND user_id = ? ORDER BY parsed_at DESC LIMIT ? OFFSET ?', (account_id, user_id, per_page, offset))
        return self._dict_fetchall(), total

    def clear_parsed_users(self, account_id: int, user_id: int):
        self.c.execute('DELETE FROM parsed_users WHERE account_id = ? AND user_id = ?', (account_id, user_id))
        self.conn_ctx.commit()

    # ==================== NEUROCOMMENTING ====================
    def create_neurocomment_settings(self, account_id: int, user_id: int, mode: str = 'prompt', prompt: str = '', custom_comments: str = '', post_prompt: str = '', target_channels: str = '', comment_delay: int = 60, randomize: int = 0) -> int:
        self.c.execute(
            'INSERT OR REPLACE INTO neurocomment_settings (account_id, user_id, mode, prompt, custom_comments, post_prompt, target_channels, comment_delay, randomize, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (account_id, user_id, mode, prompt, custom_comments, post_prompt, target_channels, comment_delay, randomize, int(time.time()))
        )
        self.conn_ctx.commit()
        return self.c.lastrowid

    def get_neurocomment_settings(self, account_id: int) -> Optional[Dict[str, Any]]:
        self.c.execute('SELECT * FROM neurocomment_settings WHERE account_id = ?', (account_id,))
        return self._dict_fetchone()

    def get_user_neurocomment_settings(self, user_id: int) -> List[Dict[str, Any]]:
        self.c.execute('SELECT * FROM neurocomment_settings WHERE user_id = ?', (user_id,))
        return self._dict_fetchall()

    def update_neurocomment_settings(self, account_id: int, **kwargs):
        if not kwargs:
            return
        updates = []
        params = []
        for key, value in kwargs.items():
            updates.append(f'{key} = ?')
            params.append(value)
        params.append(account_id)
        self.c.execute(f'UPDATE neurocomment_settings SET {", ".join(updates)} WHERE account_id = ?', params)
        self.conn_ctx.commit()

    def delete_neurocomment_settings(self, account_id: int):
        self.c.execute('DELETE FROM neurocomment_settings WHERE account_id = ?', (account_id,))
        self.conn_ctx.commit()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    # ==================== TASK REGISTRY (persistence & recovery) ====================
    def register_task(self, user_id: int, account_id: int, task_type: str, progress: str = '') -> int:
        c = self._cursor()
        c.execute(
            'INSERT INTO running_tasks (user_id, account_id, task_type, status, progress, started_at) VALUES (?, ?, ?, ?, ?, ?)',
            (user_id, account_id, task_type, 'running', progress, int(time.time()))
        )
        self.conn_ctx.commit()
        task_id = c.lastrowid
        c.close()
        return task_id

    def update_task_progress(self, task_id: int, progress: str):
        c = self._cursor()
        c.execute('UPDATE running_tasks SET progress = ? WHERE id = ?', (progress, task_id))
        self.conn_ctx.commit()
        c.close()

    def finish_task(self, task_id: int, status: str = 'finished'):
        c = self._cursor()
        c.execute('UPDATE running_tasks SET status = ?, finished_at = ? WHERE id = ?', (status, int(time.time()), task_id))
        self.conn_ctx.commit()
        c.close()

    def cancel_task(self, task_id: int):
        c = self._cursor()
        c.execute('UPDATE running_tasks SET status = ?, finished_at = ? WHERE id = ?', ('cancelled', int(time.time()), task_id))
        self.conn_ctx.commit()
        c.close()

    def get_interrupted_tasks(self) -> List[Dict[str, Any]]:
        c = self._cursor()
        c.execute('SELECT * FROM running_tasks WHERE status = ? ORDER BY started_at ASC', ('running',))
        return self._dict_fetchall(c)

    def mark_all_running_tasks_interrupted(self):
        """Called on startup to mark tasks from a previous process as interrupted."""
        c = self._cursor()
        c.execute('UPDATE running_tasks SET status = ? WHERE status = ?', ('interrupted', 'running'))
        self.conn_ctx.commit()
        c.close()

    def get_user_active_tasks(self, user_id: int) -> List[Dict[str, Any]]:
        c = self._cursor()
        c.execute('SELECT * FROM running_tasks WHERE user_id = ? AND status = ?', (user_id, 'running'))
        return self._dict_fetchall(c)

    def get_active_tasks_count(self, user_id: int = None) -> int:
        c = self._cursor()
        if user_id:
            c.execute('SELECT COUNT(*) FROM running_tasks WHERE user_id = ? AND status = ?', (user_id, 'running'))
        else:
            c.execute('SELECT COUNT(*) FROM running_tasks WHERE status = ?', ('running',))
        count = c.fetchone()[0]
        c.close()
        return count

    def cleanup_old_data(self):
        """Clean up old records to prevent unbounded growth."""
        c = self._cursor()
        now = int(time.time())
        cutoff_30d = now - (30 * 86400)
        cutoff_7d = now - (7 * 86400)
        try:
            # Clean old finished/interrupted/cancelled tasks (older than 30 days)
            c.execute('DELETE FROM running_tasks WHERE status != ? AND finished_at < ?', ('running', cutoff_30d))
            # Clean old invoices (older than 30 days)
            c.execute('DELETE FROM invoices WHERE status != ? AND created_at < ?', ('active', cutoff_30d))
            # Clean old promo code uses (older than 30 days)
            c.execute('DELETE FROM promo_code_uses WHERE used_at < ?', (cutoff_30d,))
            self.conn_ctx.commit()
            logger.info("Old data cleanup completed")
        except Exception as e:
            logger.warning(f"Cleanup warning: {e}")
        c.close()

    async def execute_write(self, query, params=()):
        async with self._write_lock:
            self.c.execute(query, params)
            self.conn_ctx.commit()

    async def execute_many_write(self, query, params_list):
        async with self._write_lock:
            self.c.executemany(query, params_list)
            self.conn_ctx.commit()

    async def execute_read(self, query, params=()):
        self.c.execute(query, params)
        return self._dict_fetchone() if 'SELECT' in query and 'COUNT' not in query and 'LIMIT' not in query else self.c.fetchone()

    async def execute_read_all(self, query, params=()):
        self.c.execute(query, params)
        return self._dict_fetchall()

# Shared singleton — use get_db() / get_db_sync() instead of creating new instances
db = None  # Deprecated; will be lazily set by get_db_sync() on first access