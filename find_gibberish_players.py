from pokerapp.app import create_app
from pokerapp.db.connection import get_db_connection

app = create_app()

def has_hebrew(s: str) -> bool:
    return any('\u0590' <= ch <= '\u05FF' for ch in s)

with app.app_context():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT id, name FROM players ORDER BY name;")
    rows = cur.fetchall()

    bad = []
    for r in rows:
        name = r["name"]
        if ("�" in name) or (not has_hebrew(name)):
            bad.append((r["id"], name))

    print("SUSPECT PLAYERS:", len(bad))
    for r in bad:
        print(r)

    conn.close()
