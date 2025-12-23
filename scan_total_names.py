from pokerapp.app import create_app
from pokerapp.db.connection import get_db_connection

app = create_app()

def is_hebrew_letter(ch: str) -> bool:
    return "\u0590" <= ch <= "\u05FF"

def suspicious(name: str) -> bool:
    if name is None:
        return True
    s = str(name)

    # תווים חשודים נפוצים
    if "�" in s:
        return True

    # תווים בלתי נראים / כיווניות
    for ch in s:
        if ch in ("\ufeff", "\u200e", "\u200f", "\u202a", "\u202b", "\u202c"):
            return True

    # אם יש '/' או הרבה ספרות בשם (נראה כמו תאריך)
    if "/" in s:
        return True
    digit_count = sum(c.isdigit() for c in s)
    if digit_count >= 2:
        return True

    # אם יש תווים שאינם עברית/רווח/גרש/מקף/נקודה
    allowed = set(" -'\".")
    for ch in s:
        if is_hebrew_letter(ch) or ch in allowed:
            continue
        # גם סוגריים לפעמים
        if ch in "()":
            continue
        return True

    return False

with app.app_context():
    conn = get_db_connection()
    cur = conn.cursor()

    # הסיכום הכללי בדיוק
    cur.execute("""
        SELECT p.id, p.name, ROUND(SUM(r.profit), 2) AS total_profit, COUNT(*) AS n
        FROM game_results r
        JOIN players p ON p.id = r.player_id
        GROUP BY p.id, p.name
        ORDER BY total_profit DESC;
    """)
    rows = cur.fetchall()

    bad = []
    for r in rows:
        name = r["name"]
        if suspicious(name):
            bad.append(r)

    print("BAD ROWS:", len(bad))
    for r in bad[:50]:
        name = r["name"]
        print("\nID:", r["id"], "TOTAL:", r["total_profit"], "N:", r["n"])
        print("NAME:", name)
        print("REPR:", repr(name))
        print("CODEPOINTS:", [hex(ord(ch)) for ch in str(name)])
    conn.close()
