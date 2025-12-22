import sqlite3

DB_NAME = "poker.db"

conn = sqlite3.connect(DB_NAME)
cur = conn.cursor()
cur.execute("UPDATE users SET is_approved = 1 WHERE username = 'admin';")
conn.commit()
conn.close()
print("Admin approved.")
