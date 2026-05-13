"""
migrate_phase_b.py
------------------
Phase B migration: add multi-table infrastructure to an existing DB.
Safe to run multiple times (idempotent).
"""

import sqlite3
import sys
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parent.parent / "poker.db"


def get_db_path():
    if len(sys.argv) > 1:
        return Path(sys.argv[1])
    return DEFAULT_DB


def column_exists(conn, table, column):
    rows = conn.execute("PRAGMA table_info(%s)" % table).fetchall()
    return any(r["name"] == column for r in rows)


def table_exists(conn, table):
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def step_create_poker_tables(conn):
    if not table_exists(conn, "poker_tables"):
        conn.execute(
            "CREATE TABLE poker_tables ("
            "  id          INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  name        TEXT    NOT NULL,"
            "  description TEXT,"
            "  is_public   INTEGER NOT NULL DEFAULT 0"
            "                CHECK (is_public IN (0, 1)),"
            "  created_at  TEXT    NOT NULL DEFAULT (datetime('now'))"
            ")"
        )
        print("  [+] Created table: poker_tables")
    else:
        print("  [=] poker_tables already exists")


def step_create_user_tables(conn):
    if not table_exists(conn, "user_tables"):
        conn.execute(
            "CREATE TABLE user_tables ("
            "  user_id   INTEGER NOT NULL,"
            "  table_id  INTEGER NOT NULL,"
            "  role      TEXT    NOT NULL DEFAULT 'member'"
            "              CHECK (role IN ('admin', 'member')),"
            "  joined_at TEXT    NOT NULL DEFAULT (datetime('now')),"
            "  PRIMARY KEY (user_id, table_id),"
            "  FOREIGN KEY (user_id)  REFERENCES users(id)        ON DELETE CASCADE,"
            "  FOREIGN KEY (table_id) REFERENCES poker_tables(id) ON DELETE CASCADE"
            ")"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_user_tables_table_id ON user_tables(table_id)"
        )
        print("  [+] Created table: user_tables")
    else:
        print("  [=] user_tables already exists")


def step_insert_home_table(conn):
    existing = conn.execute(
        "SELECT id FROM poker_tables WHERE id = 1"
    ).fetchone()
    if not existing:
        conn.execute(
            "INSERT INTO poker_tables (id, name, description, is_public) VALUES (1, ?, ?, 1)",
            ("sholchan habayit", "The main table")
        )
        print("  [+] Inserted home table (id=1)")
    else:
        print("  [=] Home table (id=1) already exists")


def step_add_table_id_to_games(conn):
    if not column_exists(conn, "games", "table_id"):
        conn.execute(
            "ALTER TABLE games ADD COLUMN table_id INTEGER NOT NULL DEFAULT 1"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_games_table_id ON games(table_id)"
        )
        print("  [+] Added games.table_id (default=1)")
    else:
        print("  [=] games.table_id already exists")


def step_add_player_id_to_users(conn):
    if not column_exists(conn, "users", "player_id"):
        conn.execute(
            "ALTER TABLE users ADD COLUMN player_id INTEGER NULL"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_users_player_id ON users(player_id)"
        )
        print("  [+] Added users.player_id (nullable FK to players)")
    else:
        print("  [=] users.player_id already exists")


def step_assign_users_to_home_table(conn):
    users = conn.execute("SELECT id, role FROM users").fetchall()
    if not users:
        print("  [=] No users found, skipping user_tables assignment")
        return

    assigned = 0
    skipped = 0
    for user in users:
        already = conn.execute(
            "SELECT 1 FROM user_tables WHERE user_id=? AND table_id=1",
            (user["id"],)
        ).fetchone()
        if already:
            skipped += 1
            continue

        table_role = "admin" if user["role"] in ("admin", "magician") else "member"
        conn.execute(
            "INSERT INTO user_tables (user_id, table_id, role) VALUES (?, 1, ?)",
            (user["id"], table_role)
        )
        assigned += 1

    if assigned:
        print("  [+] Assigned %d user(s) to home table" % assigned)
    if skipped:
        print("  [=] %d user(s) already assigned, skipped" % skipped)



def step_add_private_stats_to_users(conn):
    if not column_exists(conn, "users", "private_stats"):
        conn.execute(
            "ALTER TABLE users ADD COLUMN private_stats INTEGER NOT NULL DEFAULT 0"
        )
        print("  [+] Added users.private_stats (default=0 = public)")
    else:
        print("  [=] users.private_stats already exists")

def migrate(db_path):
    db_path = Path(db_path)
    if not db_path.exists():
        print("  [!] DB not found at %s, will be created fresh by init_db" % db_path)
        return

    print("\nRunning Phase B migration on: %s\n" % db_path)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")

    try:
        step_create_poker_tables(conn)
        step_create_user_tables(conn)
        step_insert_home_table(conn)
        step_add_table_id_to_games(conn)
        step_add_player_id_to_users(conn)
        step_assign_users_to_home_table(conn)
        step_add_private_stats_to_users(conn)
        conn.commit()
        print("\n[OK] Phase B migration complete.\n")
    except Exception as exc:
        conn.rollback()
        print("\n[ERROR] Migration failed: %s" % exc)
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    migrate(get_db_path())
