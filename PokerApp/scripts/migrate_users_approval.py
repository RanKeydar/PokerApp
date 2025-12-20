import sqlite3

DB_NAME = "poker.db"

def main():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()

    # בדיקה שהטבלה קיימת
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users';")
    if cur.fetchone() is None:
        conn.close()
        print("users table not found. Run init_users.py first.")
        return

    # האם העמודה כבר קיימת?
    cur.execute("PRAGMA table_info(users);")
    cols = [row[1] for row in cur.fetchall()]
    if "is_approved" not in cols:
        cur.execute("ALTER TABLE users ADD COLUMN is_approved INTEGER NOT NULL DEFAULT 0;")
        conn.commit()
        print("Added is_approved column.")
    else:
        print("is_approved already exists.")

    conn.close()

if __name__ == "__main__":
    main()
