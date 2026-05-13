"""
סקריפט לאיפוס סיסמת admin.
הרץ רק כשהשרת כבוי:
  python reset_admin_password.py
"""
import sqlite3
import os
from werkzeug.security import generate_password_hash

DB_PATH = os.path.join(os.path.dirname(__file__), "instance", "poker.db")
NEW_PASSWORD = "admin123"

conn = sqlite3.connect(DB_PATH)
h = generate_password_hash(NEW_PASSWORD, method="pbkdf2:sha256")
conn.execute("UPDATE users SET password_hash=? WHERE username='admin'", (h,))
conn.commit()
conn.close()
print(f"✅ סיסמת admin אופסה ל: {NEW_PASSWORD}")
