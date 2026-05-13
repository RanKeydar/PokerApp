"""
set_users.py
------------
Create specific user accounts for real players with predefined credentials.
Safe to run multiple times (skips players that already have a linked user).

Special case: "ran" (player_id=1) is linked to the existing admin account.
"""

import sqlite3
import sys
from pathlib import Path
from werkzeug.security import generate_password_hash

DEFAULT_DB = Path(__file__).resolve().parent.parent / "poker.db"

# ---------------------------------------------------------------------------
# player_id -> (username, password)
# player_id=1 (ran) is handled separately below (link to existing admin)
# ---------------------------------------------------------------------------
PLAYERS = [
    (7,  "אלעד",  "אלעד"),
    (4,  "בידר",  "בידר"),
    (2,  "גולן",  "גולן"),
    (3,  "ויקו",  "ויקו"),
    (5,  "אבי",   "אוזן"),    # חמו גיסו
    (8,  "יוסי",  "ראובן"),
    (12, "כפיר",  "כפיר"),
    (17, "עמי",   "אוזן"),
    (6,  "עמית",  "פולי"),
    (13, "יוסיפ", "פרץ"),
    (9,  "שלומי", "שלומי"),
]

RAN_PLAYER_ID  = 1   # player id של רן
ADMIN_USERNAME = "admin"  # שם משתמש ה-admin הקיים של רן


def run(db_path):
    db_path = Path(db_path)
    if not db_path.exists():
        print("[ERROR] DB not found: %s" % db_path)
        sys.exit(1)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")

    try:
        # ── קשר את admin לשחקן רן ──────────────────────────────────────────
        admin = conn.execute(
            "SELECT id, player_id FROM users WHERE username = ?", (ADMIN_USERNAME,)
        ).fetchone()

        if admin is None:
            print("[!] Admin user '%s' not found — skipping ran link" % ADMIN_USERNAME)
        elif admin["player_id"] == RAN_PLAYER_ID:
            print("[=] Admin already linked to player רן (id=%d)" % RAN_PLAYER_ID)
        else:
            conn.execute(
                "UPDATE users SET player_id = ? WHERE username = ?",
                (RAN_PLAYER_ID, ADMIN_USERNAME)
            )
            # ודא שהוא גם ב-user_tables של שולחן הבית
            conn.execute(
                "INSERT OR IGNORE INTO user_tables (user_id, table_id, role) VALUES (?, 1, 'admin')",
                (admin["id"],)
            )
            print("[+] Linked admin '%s' to player רן (id=%d)" % (ADMIN_USERNAME, RAN_PLAYER_ID))

        # ── צור יוזרים לשאר השחקנים ────────────────────────────────────────
        existing_usernames = {
            r["username"] for r in conn.execute("SELECT username FROM users")
        }
        linked_player_ids = {
            r["player_id"] for r in conn.execute(
                "SELECT player_id FROM users WHERE player_id IS NOT NULL"
            )
        }

        created = []
        skipped = []

        for player_id, username, password in PLAYERS:
            if player_id in linked_player_ids:
                skipped.append((player_id, username))
                continue

            # אם username תפוס — הוסף מספר
            final_username = username
            i = 2
            while final_username in existing_usernames:
                final_username = "%s%d" % (username, i)
                i += 1
            if final_username != username:
                print("[!] Username '%s' taken, using '%s'" % (username, final_username))

            cur = conn.execute(
                "INSERT INTO users (username, password_hash, role, is_approved, player_id)"
                " VALUES (?, ?, 'player', 1, ?)",
                (final_username, generate_password_hash(password), player_id)
            )
            user_id = cur.lastrowid
            conn.execute(
                "INSERT OR IGNORE INTO user_tables (user_id, table_id, role) VALUES (?, 1, 'member')",
                (user_id,)
            )
            existing_usernames.add(final_username)
            created.append((player_id, final_username, password))

        conn.commit()

        # ── הדפס תוצאות ─────────────────────────────────────────────────────
        if created:
            print("\n  %-6s  %-12s  %s" % ("id", "יוזר", "סיסמה"))
            print("  " + "-" * 32)
            for pid, uname, pw in created:
                print("  %-6d  %-12s  %s" % (pid, uname, pw))
            print("\n[OK] Created %d user(s)." % len(created))
        else:
            print("[=] No new users created.")

        if skipped:
            print("[=] Already linked (skipped): %s" % ", ".join(u for _, u in skipped))

    except Exception as exc:
        conn.rollback()
        print("[ERROR] %s" % exc)
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    db = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DB
    run(db)
