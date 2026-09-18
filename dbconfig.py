"""Выбор СУБД и трансляция SQL-диалекта.

PostDrive исторически написан под SQLite. Этот модуль добавляет возможность
переключиться на PostgreSQL через конфиг, не переписывая ~280 SQL-запросов:
запросы транслируются из диалекта SQLite в диалект PostgreSQL на лету.

Переключение:
    [DATABASE]
    ENGINE = sqlite        ; или postgres
    DSN    = postgresql://user:pass@host:5432/postdrive

Либо переменными окружения: DB_ENGINE, DATABASE_URL (имеют приоритет).
"""
import os
import re
import configparser
import logging

logger = logging.getLogger(__name__)

_config = configparser.ConfigParser()
_config.read(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.ini'))


def _cfg(section: str, key: str, fallback: str = '') -> str:
    try:
        return _config.get(section, key, fallback=fallback).strip()
    except Exception:
        return fallback


DB_ENGINE = (os.environ.get('DB_ENGINE') or _cfg('DATABASE', 'ENGINE', 'sqlite')).lower()
DB_DSN = os.environ.get('DATABASE_URL') or _cfg('DATABASE', 'DSN', '')
DB_PATH = os.environ.get('DB_PATH') or _cfg('DATABASE', 'PATH', 'database.db')
DB_POOL_SIZE = int(os.environ.get('DB_POOL_SIZE') or _cfg('DATABASE', 'POOL_SIZE', '12'))

IS_POSTGRES = DB_ENGINE in ('postgres', 'postgresql', 'pg')

if IS_POSTGRES and not DB_DSN:
    raise RuntimeError(
        "ENGINE=postgres, но DSN не задан. Укажите [DATABASE] DSN в config.ini "
        "или переменную окружения DATABASE_URL."
    )


# ── Трансляция SQLite → PostgreSQL ────────────────────────────────
_RE_AUTOINC = re.compile(
    r'\bINTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b', re.IGNORECASE)
_RE_STRFTIME = re.compile(
    r"strftime\(\s*'%s'\s*,\s*'now'\s*\)", re.IGNORECASE)
_RE_INSERT_IGNORE = re.compile(r'\bINSERT\s+OR\s+IGNORE\s+INTO\b', re.IGNORECASE)
_RE_INSERT_REPLACE = re.compile(r'\bINSERT\s+OR\s+REPLACE\s+INTO\b', re.IGNORECASE)
_RE_PRAGMA = re.compile(r'^\s*PRAGMA\b', re.IGNORECASE)


def translate(sql: str) -> str:
    """Переводит SQLite-запрос в PostgreSQL-совместимый."""
    if not IS_POSTGRES:
        return sql

    out = sql
    out = _RE_AUTOINC.sub('BIGSERIAL PRIMARY KEY', out)
    out = _RE_STRFTIME.sub("EXTRACT(EPOCH FROM NOW())::BIGINT", out)
    out = _RE_INSERT_REPLACE.sub('INSERT INTO', out)

    # INSERT OR IGNORE → INSERT ... ON CONFLICT DO NOTHING
    if _RE_INSERT_IGNORE.search(out):
        out = _RE_INSERT_IGNORE.sub('INSERT INTO', out)
        if 'ON CONFLICT' not in out.upper():
            out = out.rstrip().rstrip(';') + ' ON CONFLICT DO NOTHING'

    # Плейсхолдеры ? → %s (не трогаем знаки внутри строковых литералов)
    parts = re.split(r"('(?:[^']|'')*')", out)
    for i in range(0, len(parts), 2):
        parts[i] = parts[i].replace('?', '%s')
    out = ''.join(parts)

    return out


def is_pragma(sql: str) -> bool:
    return bool(_RE_PRAGMA.match(sql))


def describe() -> str:
    if IS_POSTGRES:
        safe = re.sub(r'://[^@]*@', '://***@', DB_DSN)
        return f"PostgreSQL ({safe}), pool={DB_POOL_SIZE}"
    return f"SQLite ({DB_PATH}), pool={DB_POOL_SIZE}"
