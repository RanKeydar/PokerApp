from pokerapp.app import create_app
from pokerapp.db.connection import get_db_connection

app = create_app()

def suspicious(name: str) -> bool:
    name = (name or "").strip()
    # חשוד אם יש / או נקודה עם מספרים (תאריכים), או תו החלפה
    if "�" in name:
        return True
    if "/" in name:
        return True
    # הרבה ספרות/נקודות בשם
    digits = sum(ch.isdigit() for ch in name)
    return digits >= 2 and "." in name

with app.app_context():
    conn = get_db_connection()
    cur = conn.cursor()

    # רווח מצטבר על כל השנים (כמו בטבלת הסיכום)
    cur.execute("""
        SELECT p.id, p.name, ROUND(SUM(r.profit), 2) as total_profit, COUNT(*) as n
        FROM game_results r
        JOIN players p ON p.id = r.player_id
        GROUP BY p.id, p.name
        ORDER BY total_profit DESC;
    """)
    rows = cur.fetchall()

    bad = [ (r["id"], r["name"], r["total_profit"], r["n"]) for r in rows if suspicious(r["name"]) ]

    print("SUSPECT TOTAL PLAYERS:", len(bad))
    for x in bad[:50]:
        print(x)

    conn.close()
