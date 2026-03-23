import sqlite3
import config


def get_db():
    conn = sqlite3.connect(config.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
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
        )
    """)

    cursor.execute("""
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
        )
    """)

    cursor.execute("""
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
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    conn.commit()
    conn.close()
