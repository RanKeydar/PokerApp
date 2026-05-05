import os
import sqlite3
from werkzeug.security import generate_password_hash

DB_PATH = os.environ.get("DB_PATH", "instance/poker.db")

def init_users():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL CHECK (role IN ('admin', 'magician', 'player'))
    );
    """)

    conn.commit()
    conn.close()
    print("Users table is ready.")

def create_user(username: str, password: str, role: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    pw_hash = generate_password_hash(password)
    cur.execute(
        "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?);",
        (username, pw_hash, role)
    )

    conn.commit()
    conn.close()
    print(f"User created: {username} ({role})")

if __name__ == "__main__":
    init_users()

    # צור משתמש ראשון (תשנה סיסמה!)
    create_user("admin", "admin1234", "admin")
    create_user("magician", "magic1234", "magician")
    create_user("player", "player1234", "player")
