"""
ChannelFlow AI - Database Layer
=================================

SQLite access layer for the whole project. All connections:

    * Enable ``PRAGMA foreign_keys=ON`` (SQLite defaults this OFF per
      connection, so it must be set every time or ON DELETE CASCADE
      silently does nothing).
    * Use WAL journal mode so the bot's request/response cycle and the
      forwarder's background writes don't block each other with
      "database is locked" errors.
    * Use ``sqlite3.Row`` so callers can access columns by name.

Schema
------
users              - one row per Telegram bot user (owner of projects)
projects           - forwarding "pipelines", owned by a user
sources            - chats a project listens to
destinations       - chats a project forwards into
project_settings   - per-project forward/filter/delay configuration
logs               - forward/error/retry log lines per project
stats              - running counters per project
"""

import sqlite3
import os

DB_NAME = os.getenv("DB_NAME", "channelflow.db")


def get_connection():

    conn = sqlite3.connect(DB_NAME, timeout=30)

    conn.row_factory = sqlite3.Row

    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")

    return conn


def _column_exists(cur, table, column):

    cur.execute(f"PRAGMA table_info({table})")
    return any(row["name"] == column for row in cur.fetchall())


def _migrate_existing_schema(cur):
    """
    Adds columns that didn't exist in earlier versions of this project
    to tables that already exist, so upgrading in place on a database
    that already has real data never crashes with
    'no such column'.
    """

    if not _column_exists(cur, "sources", "enabled"):
        cur.execute("ALTER TABLE sources ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1")

    if not _column_exists(cur, "destinations", "enabled"):
        cur.execute("ALTER TABLE destinations ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1")

    if not _column_exists(cur, "users", "is_admin"):
        cur.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")


def init_db():

    conn = get_connection()

    cur = conn.cursor()

    # ==========================
    # USERS
    # ==========================

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users(
        telegram_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        is_admin INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # ==========================
    # PROJECTS
    # ==========================

    cur.execute("""
    CREATE TABLE IF NOT EXISTS projects(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        status INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(telegram_id) ON DELETE CASCADE
    )
    """)

    cur.execute("CREATE INDEX IF NOT EXISTS idx_projects_user ON projects(user_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(status)")

    # ==========================
    # SOURCES
    # ==========================

    cur.execute("""
    CREATE TABLE IF NOT EXISTS sources(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        chat_id TEXT NOT NULL,
        username TEXT,
        title TEXT,
        chat_type TEXT,
        enabled INTEGER NOT NULL DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
    )
    """)

    cur.execute("CREATE INDEX IF NOT EXISTS idx_sources_project ON sources(project_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sources_chat ON sources(chat_id)")

    # ==========================
    # DESTINATIONS
    # ==========================

    cur.execute("""
    CREATE TABLE IF NOT EXISTS destinations(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        chat_id TEXT NOT NULL,
        username TEXT,
        title TEXT,
        chat_type TEXT,
        enabled INTEGER NOT NULL DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
    )
    """)

    cur.execute("CREATE INDEX IF NOT EXISTS idx_destinations_project ON destinations(project_id)")

    _migrate_existing_schema(cur)

    # ==========================
    # PROJECT SETTINGS
    # ==========================

    cur.execute("""
    CREATE TABLE IF NOT EXISTS project_settings(
        project_id INTEGER PRIMARY KEY,
        mode TEXT NOT NULL DEFAULT 'forward',
        silent INTEGER NOT NULL DEFAULT 0,
        protect_content INTEGER NOT NULL DEFAULT 0,
        keep_media_groups INTEGER NOT NULL DEFAULT 1,
        delay_min REAL NOT NULL DEFAULT 0,
        delay_max REAL NOT NULL DEFAULT 0,
        media_filter TEXT NOT NULL DEFAULT 'all',
        keyword_whitelist TEXT NOT NULL DEFAULT '',
        keyword_blacklist TEXT NOT NULL DEFAULT '',
        regex_filter TEXT NOT NULL DEFAULT '',
        FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
    )
    """)

    # ==========================
    # LOGS
    # ==========================

    cur.execute("""
    CREATE TABLE IF NOT EXISTS logs(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        level TEXT NOT NULL,
        message TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
    )
    """)

    cur.execute("CREATE INDEX IF NOT EXISTS idx_logs_project ON logs(project_id, id DESC)")

    # ==========================
    # STATS
    # ==========================

    cur.execute("""
    CREATE TABLE IF NOT EXISTS stats(
        project_id INTEGER PRIMARY KEY,
        forwarded INTEGER NOT NULL DEFAULT 0,
        failed INTEGER NOT NULL DEFAULT 0,
        retried INTEGER NOT NULL DEFAULT 0,
        filtered INTEGER NOT NULL DEFAULT 0,
        last_forward_at TIMESTAMP,
        FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
    )
    """)

    conn.commit()
    conn.close()
