import sqlite3
from datetime import datetime, UTC
from flask import current_app, session


def get_db_connection():
    db_path = current_app.config["DB_PATH"]

    conn = sqlite3.connect(db_path, timeout=5)
    conn.row_factory = sqlite3.Row

    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA busy_timeout = 5000;")

    return conn


def ensure_admin_audit_log_table():
    conn = get_db_connection()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS admin_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            actor_username TEXT NOT NULL,
            actor_role TEXT,
            action TEXT NOT NULL,
            target_type TEXT,
            target_value TEXT,
            status TEXT NOT NULL,
            message TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_admin_audit_log_created_at
        ON admin_audit_log (created_at DESC)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_admin_audit_log_action
        ON admin_audit_log (action)
        """
    )
    conn.commit()
    conn.close()


def ensure_activity_log_table():
    conn = get_db_connection()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_activity_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at  TEXT NOT NULL,
            username    TEXT NOT NULL,
            role        TEXT,
            action      TEXT NOT NULL,
            details     TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_activity_log_created_at
        ON user_activity_log (created_at DESC)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_activity_log_username
        ON user_activity_log (username)
        """
    )
    conn.commit()
    conn.close()


def log_activity(action, details=None):
    """רישום פעולת משתמש ללוג הפנימי."""
    try:
        conn = get_db_connection()
        conn.execute(
            """
            INSERT INTO user_activity_log (created_at, username, role, action, details)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                datetime.now(UTC).isoformat(),
                session.get("username", "anonymous"),
                session.get("role"),
                action,
                details,
            ),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass  # לא להפיל את הבקשה בגלל כשל בלוג


def log_admin_action(action, status, target_type=None, target_value=None, message=None):
    conn = get_db_connection()
    conn.execute(
        """
        INSERT INTO admin_audit_log (
            created_at,
            actor_username,
            actor_role,
            action,
            target_type,
            target_value,
            status,
            message
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            datetime.now(UTC).isoformat(),
            session.get("username", "unknown"),
            session.get("role"),
            action,
            target_type,
            target_value,
            status,
            message,
        ),
    )
    conn.commit()
    conn.close()
