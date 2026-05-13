"""
seed_demo.py
------------
Populate a public demo poker table with fictional players and 25+ games.

Safe to run multiple times (idempotent):
  - Skips creation if the demo table already exists.
  - Will not duplicate players or games that are already seeded.

Usage:
    python scripts/seed_demo.py [path/to/poker.db]

Default DB path: poker.db in the project root.
"""

import sqlite3
import random
import sys
from datetime import date, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEMO_TABLE_ID   = 2
DEMO_TABLE_NAME = "Demo Table"
DEMO_TABLE_DESC = "A public demo table with fictional players and results"

DEMO_PLAYERS = [
    "Alex Rivera",
    "Sam Cohen",
    "Jordan Blake",
    "Taylor Kim",
    "Morgan Stone",
    "Casey Levy",
    "Riley Novak",
    "Drew Castillo",
]

# Game dates: weekly sessions going back ~6 months
def _generate_dates(n, end=None):
    if end is None:
        end = date(2026, 5, 1)
    dates = []
    current = end
    for _ in range(n):
        dates.append(current.isoformat())
        current -= timedelta(days=random.randint(5, 10))
    return list(reversed(dates))

LOCATIONS = ["Home", "Club", "Office", "Rooftop", "Cafe"]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DEFAULT_DB = Path(__file__).resolve().parent.parent / "poker.db"

def get_db_path():
    if len(sys.argv) > 1:
        return Path(sys.argv[1])
    return DEFAULT_DB


def generate_cash_results(player_ids):
    """Realistic cash game: buyin 50-200, cashout 0-400."""
    results = []
    for pid in player_ids:
        buyin   = random.choice([50, 100, 100, 150, 200])
        # Most players lose a bit; occasionally someone wins big
        r = random.random()
        if r < 0.45:   # ~45%: small loss
            cashout = round(buyin * random.uniform(0.0, 0.8), 0)
        elif r < 0.80: # ~35%: break-even area
            cashout = round(buyin * random.uniform(0.8, 1.3), 0)
        else:           # ~20%: big win
            cashout = round(buyin * random.uniform(1.5, 3.0), 0)
        profit = cashout - buyin
        results.append((pid, float(buyin), float(cashout), float(profit)))
    # Force zero-sum: distribute the house rake back randomly
    total_profit = sum(r[3] for r in results)
    if abs(total_profit) > 0 and results:
        idx = random.randrange(len(results))
        pid, b, c, p = results[idx]
        c_adj = round(c - total_profit, 0)
        c_adj = max(0.0, c_adj)
        results[idx] = (pid, b, c_adj, c_adj - b)
    return results


def generate_harbo_results(player_ids):
    """Harbo (tournament): fixed buyin 100, winner takes most."""
    buyin  = 100.0
    n      = len(player_ids)
    prize  = buyin * n        # total pot
    random.shuffle(player_ids)
    results = []
    remaining = prize
    for i, pid in enumerate(player_ids):
        if i == 0:            # winner
            cashout = round(prize * 0.55, 0)
        elif i == 1 and n > 3: # runner-up (only if 4+ players)
            cashout = round(prize * 0.30, 0)
        else:
            cashout = 0.0
        remaining -= cashout
        profit = cashout - buyin
        results.append((pid, buyin, cashout, profit))
    return results


# ---------------------------------------------------------------------------
# Seed steps
# ---------------------------------------------------------------------------

def seed_demo_table(conn):
    existing = conn.execute(
        "SELECT id FROM poker_tables WHERE id = ?", (DEMO_TABLE_ID,)
    ).fetchone()
    if not existing:
        conn.execute(
            "INSERT INTO poker_tables (id, name, description, is_public) VALUES (?, ?, ?, 1)",
            (DEMO_TABLE_ID, DEMO_TABLE_NAME, DEMO_TABLE_DESC)
        )
        print("  [+] Created demo table (id=%d)" % DEMO_TABLE_ID)
    else:
        print("  [=] Demo table already exists")


def seed_players(conn):
    """Insert demo players, return list of their IDs."""
    player_ids = []
    for name in DEMO_PLAYERS:
        existing = conn.execute(
            "SELECT id FROM players WHERE name = ?", (name,)
        ).fetchone()
        if existing:
            player_ids.append(existing["id"])
        else:
            cur = conn.execute("INSERT INTO players (name) VALUES (?)", (name,))
            player_ids.append(cur.lastrowid)
            print("  [+] Player: %s" % name)
    return player_ids


def seed_games(conn, player_ids):
    """Insert 25 games with results. Skip if already seeded."""
    existing_count = conn.execute(
        "SELECT COUNT(*) FROM games WHERE table_id = ?", (DEMO_TABLE_ID,)
    ).fetchone()[0]
    if existing_count >= 20:
        print("  [=] Demo games already seeded (%d games)" % existing_count)
        return

    random.seed(42)  # reproducible output
    dates = _generate_dates(25)
    games_added = 0

    for i, game_date in enumerate(dates):
        game_type = "harbo" if i % 4 == 0 else "cash"  # 1 in 4 is harbo
        location  = random.choice(LOCATIONS)

        # Pick 4-7 players per game
        n_players = random.randint(4, min(7, len(player_ids)))
        participants = random.sample(player_ids, n_players)

        cur = conn.execute(
            "INSERT INTO games (date, location, game_type, table_id) VALUES (?, ?, ?, ?)",
            (game_date, location, game_type, DEMO_TABLE_ID)
        )
        game_id = cur.lastrowid

        results = (
            generate_harbo_results(list(participants))
            if game_type == "harbo"
            else generate_cash_results(list(participants))
        )
        for pid, buyin, cashout, profit in results:
            conn.execute(
                "INSERT OR IGNORE INTO game_results (game_id, player_id, buyin, cashout, profit)"
                " VALUES (?, ?, ?, ?, ?)",
                (game_id, pid, buyin, cashout, profit)
            )
        games_added += 1

    print("  [+] Seeded %d demo games" % games_added)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def seed(db_path):
    db_path = Path(db_path)
    if not db_path.exists():
        print("[ERROR] DB not found: %s" % db_path)
        sys.exit(1)

    print("\nSeeding demo table into: %s\n" % db_path)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")

    try:
        seed_demo_table(conn)
        player_ids = seed_players(conn)
        seed_games(conn, player_ids)
        conn.commit()

        # Summary
        total_games   = conn.execute(
            "SELECT COUNT(*) FROM games WHERE table_id=?", (DEMO_TABLE_ID,)
        ).fetchone()[0]
        total_results = conn.execute(
            "SELECT COUNT(*) FROM game_results gr"
            " JOIN games g ON g.id=gr.game_id WHERE g.table_id=?",
            (DEMO_TABLE_ID,)
        ).fetchone()[0]
        print("\n[OK] Demo ready: %d games, %d result rows\n" % (total_games, total_results))

    except Exception as exc:
        conn.rollback()
        print("\n[ERROR] Seeding failed: %s" % exc)
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    seed(get_db_path())
