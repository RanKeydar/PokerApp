import os
import sqlite3

DB_PATH = os.environ.get("DB_PATH", "instance/poker.db")

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()
cur.execute("UPDATE users SET is_approved = 1 WHERE username = 'admin';")
conn.commit()
conn.close()
print("Admin approved.")
