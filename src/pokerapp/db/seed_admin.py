import sqlite3
from werkzeug.security import generate_password_hash

def ensure_admin(db_path: str, username: str = "admin", password: str = "admin123"):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # 1) ודא שיש שורה ל-admin (אם אין — תיצור)
    cur.execute(
        """
        INSERT OR IGNORE INTO users (username, password_hash, role, is_approved)
        VALUES (?, ?, ?, ?)
        """,
        (username, generate_password_hash(password), "admin", 1),
    )

    # 2) בכל מקרה עדכן סיסמה/תפקיד כדי שיהיה דטרמיניסטי
    cur.execute(
        """
        UPDATE users
        SET password_hash = ?, role = ?, is_approved = ?
        WHERE username = ?
        """,
        (generate_password_hash(password), "admin", 1, username),
    )

    conn.commit()

    # לוג קצר שיעזור לנו ב-Render logs
    cur.execute("SELECT id, username, role, is_approved FROM users WHERE username = ?", (username,))
    row = cur.fetchone()
    print("ADMIN_SEED:", row, "DB_PATH=", db_path)

    conn.close()
