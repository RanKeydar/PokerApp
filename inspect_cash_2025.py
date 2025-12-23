from pokerapp.app import create_app
from pokerapp.db.connection import get_db_connection

app = create_app()

def looks_weird(s: str) -> bool:
    if s is None:
        return False
    s = str(s)
    # חשוד אם יש תווי החלפה, או אם יש תווים לא רגילים (control/latin) בתוך שם
    if "�" in s:
        return True
    for ch in s:
        o = ord(ch)
        # תווי בקרה / לטיני בסיסי
        if o < 32 or (32 <= o <= 126):
            # תתיר רווח ומקף ואפוסטרוף
            if ch not in [" ", "-", "'", '"', "."]:
                return True
    return False

with app.app_context():
    conn = get_db_connection()
    cur = conn.cursor()

    # כל התוצאות של CASH 2025 עם שם שחקן
    cur.execute("""
        SELECT g.date, p.id as player_id, p.name, r.profit
        FROM game_results r
        JOIN games g ON g.id = r.game_id
        JOIN players p ON p.id = r.player_id
        WHERE g.game_type='cash' AND substr(g.date,1,4)='2025'
        ORDER BY g.date, p.name;
    """)

    rows = cur.fetchall()
    weird = []
    for row in rows:
        name = row["name"]
        if looks_weird(name):
            weird.append((row["date"], row["player_id"], name, row["profit"]))

    print("TOTAL ROWS:", len(rows))
    print("WEIRD ROWS:", len(weird))
    for w in weird[:50]:
        print(w)

    conn.close()
