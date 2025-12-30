import sqlite3
from werkzeug.security import generate_password_hash

def seed_admin_if_empty(db_path: str):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM users;")
    count = cur.fetchone()[0]

    if count == 0:
        cur.execute(
            """
            INSERT INTO users (username, password_hash, role, is_approved)
            VALUES (?, ?, ?, ?)
            """,
            (
                "admin",
                generate_password_hash("admin123"),
                "admin",
                1,
            )
        )
        conn.commit()

    conn.close()
