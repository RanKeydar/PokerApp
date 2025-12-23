from pokerapp.app import create_app
from pokerapp.db.connection import get_db_connection

BAD_IDS = [25, 29]

app = create_app()

with app.app_context():
    conn = get_db_connection()
    cur = conn.cursor()

    # מציג לפני מחיקה
    cur.execute("SELECT id, name FROM players WHERE id IN (?, ?);", BAD_IDS)
    rows = cur.fetchall()
    print("BEFORE:", [(r["id"], r["name"]) for r in rows])

    # מחיקת תוצאות שלהם
    cur.execute("DELETE FROM game_results WHERE player_id IN (?, ?);", BAD_IDS)

    # מחיקת השחקנים עצמם
    cur.execute("DELETE FROM players WHERE id IN (?, ?);", BAD_IDS)

    conn.commit()

    # מציג אחרי מחיקה
    cur.execute("SELECT id, name FROM players WHERE id IN (?, ?);", BAD_IDS)
    rows2 = cur.fetchall()
    print("AFTER:", [(r["id"], r["name"]) for r in rows2])

    conn.close()

print("DONE")
