import sqlite3

DB_NAME = "poker.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()

    # טבלת שחקנים
    cur.execute("""
    CREATE TABLE IF NOT EXISTS players (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL
    );
    """)

    # טבלת משחקים
    cur.execute("""
    CREATE TABLE IF NOT EXISTS games (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        location TEXT,
        game_type TEXT NOT NULL CHECK (game_type IN ('cash', 'harbo'))
    );
    """)

    # טבלת תוצאות למשחק
    cur.execute("""
    CREATE TABLE IF NOT EXISTS game_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        game_id INTEGER NOT NULL,
        player_id INTEGER NOT NULL,
        buyin REAL NOT NULL,
        cashout REAL NOT NULL,
        profit REAL NOT NULL,
        FOREIGN KEY (game_id) REFERENCES games(id),
        FOREIGN KEY (player_id) REFERENCES players(id)
    );
    """)

    conn.commit()
    conn.close()
    print("Database initialized: poker.db")

if __name__ == "__main__":
    init_db()
