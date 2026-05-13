"""
gen_users.py
------------
Generate user accounts for all active players in 2026 (home table, table_id=1).

"Active" = played at least one game in 2026 in the home table.

For each such player:
  - If a user already linked to that player exists  -> skip.
  - Otherwise create a new user with role='player', is_approved=1,
    link users.player_id = players.id, add to user_tables (table_id=1, role=member).

Prints a credentials table to stdout (save it somewhere safe).
Also writes credentials to a CSV file next to the DB.

Usage:
    python scripts/gen_users.py [path/to/poker.db]
"""

import csv
import random
import re
import sqlite3
import string
import sys
from pathlib import Path
from werkzeug.security import generate_password_hash

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_DB   = Path(__file__).resolve().parent.parent / "poker.db"
HOME_TABLE   = 1
ACTIVE_YEAR  = "2026"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_db_path():
    return Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DB


def slugify(name):
    """Convert a player name to a safe username.

    Hebrew names are kept as-is (spaces -> dots).
    Latin names are lowercased (spaces -> dots).
    Examples:
        "יוסי כהן"  -> "יוסי.כהן"
        "John Smith" -> "john.smith"
        "ג'ון סמית'" -> "גון.סמית"
    """
    # Remove characters that are not letters, digits, Hebrew, dots, or spaces
    name = re.sub(r"[^\w\s֐-׿]", "", name, flags=re.UNICODE)
    name = name.strip()
    parts = name.split()
    slug  = ".".join(p.lower() for p in parts)
    return slug or "player"


def unique_username(base, existing):
    """Return base if free, otherwise base2, base3, ..."""
    if base not in existing:
        return base
    i = 2
    while ("%s%d" % (base, i)) in existing:
        i += 1
    return "%s%d" % (base, i)


def gen_password(length=10):
    """Generate a readable random password: letters + digits, no ambiguous chars."""
    chars = (
        string.ascii_lowercase.replace("l", "").replace("o", "") +
        string.digits.replace("0", "").replace("1", "")
    )
    return "".join(random.choices(chars, k=length))


# ---------------------------------------------------------------------------
# Main logic
# ---------------------------------------------------------------------------

def find_active_players(conn):
    """Players who played at least once in ACTIVE_YEAR on the home table."""
    rows = conn.execute(
        """
        SELECT DISTINCT p.id, p.name
        FROM players p
        JOIN game_results gr ON gr.player_id = p.id
        JOIN games g         ON g.id = gr.game_id
        WHERE g.table_id = ?
          AND g.date LIKE ?
        ORDER BY p.name
        """,
        (HOME_TABLE, ACTIVE_YEAR + "%")
    ).fetchall()
    return rows


def get_existing_usernames(conn):
    return {r["username"] for r in conn.execute("SELECT username FROM users").fetchall()}


def get_linked_player_ids(conn):
    """player_ids that already have a linked user."""
    rows = conn.execute(
        "SELECT player_id FROM users WHERE player_id IS NOT NULL"
    ).fetchall()
    return {r["player_id"] for r in rows}


def create_user_for_player(conn, player, existing_usernames):
    base     = slugify(player["name"])
    username = unique_username(base, existing_usernames)
    password = gen_password()
    pw_hash  = generate_password_hash(password)

    cur = conn.execute(
        """
        INSERT INTO users (username, password_hash, role, is_approved, player_id)
        VALUES (?, ?, 'player', 1, ?)
        """,
        (username, pw_hash, player["id"])
    )
    user_id = cur.lastrowid

    # Link to home table as member
    conn.execute(
        "INSERT OR IGNORE INTO user_tables (user_id, table_id, role) VALUES (?, ?, 'member')",
        (user_id, HOME_TABLE)
    )

    existing_usernames.add(username)
    return username, password


def run(db_path):
    db_path = Path(db_path)
    if not db_path.exists():
        print("[ERROR] DB not found: %s" % db_path)
        sys.exit(1)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")

    try:
        active_players    = find_active_players(conn)
        existing_usernames = get_existing_usernames(conn)
        linked_player_ids  = get_linked_player_ids(conn)

        print("\nActive players in %s: %d\n" % (ACTIVE_YEAR, len(active_players)))

        created  = []
        skipped  = []

        for player in active_players:
            if player["id"] in linked_player_ids:
                skipped.append(player["name"])
                continue
            username, password = create_user_for_player(conn, player, existing_usernames)
            created.append({
                "player":   player["name"],
                "username": username,
                "password": password,
            })

        conn.commit()

        # ── Print results ────────────────────────────────────────────────────
        if created:
            col_w = [max(len(r[k]) for r in created) for k in ("player", "username", "password")]
            col_w = [max(w, min_w) for w, min_w in zip(col_w, [10, 8, 8])]
            header = "  {:<{}} | {:<{}} | {}".format(
                "Player", col_w[0], "Username", col_w[1], "Password"
            )
            sep = "  " + "-" * (col_w[0] + col_w[1] + 20)
            print(header)
            print(sep)
            for r in created:
                print("  {:<{}} | {:<{}} | {}".format(
                    r["player"], col_w[0], r["username"], col_w[1], r["password"]
                ))
            print()
            print("[OK] Created %d user(s)." % len(created))

            # Write CSV
            csv_path = db_path.parent / ("new_users_%s.csv" % ACTIVE_YEAR)
            with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=["player", "username", "password"])
                writer.writeheader()
                writer.writerows(created)
            print("[OK] Credentials saved to: %s" % csv_path)
        else:
            print("[=] No new users to create.")

        if skipped:
            print("\n[=] Already linked (skipped): %s" % ", ".join(skipped))

    except Exception as exc:
        conn.rollback()
        print("\n[ERROR] %s" % exc)
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    run(get_db_path())
