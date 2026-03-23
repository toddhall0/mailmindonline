"""Database abstraction: uses PostgreSQL when DATABASE_URL is set, SQLite otherwise."""
import os
import re
import sqlite3

import config

DATABASE_URL = os.getenv("DATABASE_URL", "")
USE_POSTGRES = bool(DATABASE_URL)

if USE_POSTGRES:
    import psycopg2
    import psycopg2.extras


class _PgConnectionWrapper:
    """Wraps a psycopg2 connection so callers can use '?' placeholders and
    get dict-like row access — matching the sqlite3 interface used everywhere."""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=None):
        sql = sql.replace("?", "%s")
        cur = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql, params)
        return _PgCursorWrapper(cur)

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()


class _PgCursorWrapper:
    """Wraps a psycopg2 cursor to expose fetchone/fetchall and lastrowid."""

    def __init__(self, cur):
        self._cur = cur
        # If the query has RETURNING, the id is available via fetch
        self.lastrowid = None

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()


def get_db():
    if USE_POSTGRES:
        conn = psycopg2.connect(DATABASE_URL)
        return _PgConnectionWrapper(conn)
    else:
        conn = sqlite3.connect(config.DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn


def _pg_schema():
    return """
    CREATE TABLE IF NOT EXISTS tasks (
        id SERIAL PRIMARY KEY,
        title TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'Open'
            CHECK (status IN ('Open', 'In Progress', 'Done', 'Cancelled')),
        priority TEXT NOT NULL DEFAULT 'Medium'
            CHECK (priority IN ('High', 'Medium', 'Low')),
        due_date TEXT,
        tags TEXT DEFAULT '',
        notes TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        source_email_ids TEXT DEFAULT '[]',
        source_account_type TEXT
            CHECK (source_account_type IN ('microsoft', 'google', NULL)),
        thread_id TEXT
    );

    CREATE TABLE IF NOT EXISTS email_accounts (
        id SERIAL PRIMARY KEY,
        account_type TEXT NOT NULL
            CHECK (account_type IN ('microsoft', 'google')),
        email_address TEXT NOT NULL,
        display_name TEXT,
        access_token TEXT,
        refresh_token TEXT,
        token_expiry DOUBLE PRECISION,
        is_active INTEGER DEFAULT 1,
        folders_to_scan TEXT DEFAULT '["Inbox"]',
        last_scan_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS scanned_emails (
        id SERIAL PRIMARY KEY,
        message_id TEXT UNIQUE NOT NULL,
        account_id INTEGER NOT NULL REFERENCES email_accounts(id),
        subject TEXT,
        sender TEXT,
        received_at TIMESTAMP,
        thread_id TEXT,
        was_processed INTEGER DEFAULT 0,
        task_id_created INTEGER REFERENCES tasks(id),
        scanned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS app_settings (
        key TEXT PRIMARY KEY,
        value TEXT
    );
    """


def _sqlite_schema():
    return """
    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'Open'
            CHECK (status IN ('Open', 'In Progress', 'Done', 'Cancelled')),
        priority TEXT NOT NULL DEFAULT 'Medium'
            CHECK (priority IN ('High', 'Medium', 'Low')),
        due_date TEXT,
        tags TEXT DEFAULT '',
        notes TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        source_email_ids TEXT DEFAULT '[]',
        source_account_type TEXT
            CHECK (source_account_type IN ('microsoft', 'google', NULL)),
        thread_id TEXT
    );

    CREATE TABLE IF NOT EXISTS email_accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_type TEXT NOT NULL
            CHECK (account_type IN ('microsoft', 'google')),
        email_address TEXT NOT NULL,
        display_name TEXT,
        access_token TEXT,
        refresh_token TEXT,
        token_expiry TIMESTAMP,
        is_active INTEGER DEFAULT 1,
        folders_to_scan TEXT DEFAULT '["Inbox"]',
        last_scan_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS scanned_emails (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        message_id TEXT UNIQUE NOT NULL,
        account_id INTEGER NOT NULL,
        subject TEXT,
        sender TEXT,
        received_at TIMESTAMP,
        thread_id TEXT,
        was_processed INTEGER DEFAULT 0,
        task_id_created INTEGER,
        scanned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (account_id) REFERENCES email_accounts(id),
        FOREIGN KEY (task_id_created) REFERENCES tasks(id)
    );

    CREATE TABLE IF NOT EXISTS app_settings (
        key TEXT PRIMARY KEY,
        value TEXT
    );
    """


def init_db():
    if USE_POSTGRES:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute(_pg_schema())
        conn.commit()
        conn.close()
    else:
        conn = sqlite3.connect(config.DATABASE_PATH)
        conn.executescript(_sqlite_schema())
        conn.commit()
        conn.close()
