from pokerapp.app import create_app
from pokerapp.db.connection import get_db_connection
import unicodedata
from collections import defaultdict

app = create_app()

def norm(s: str) -> str:
    s = (s or "")
    s = s.replace("\ufeff", "")  # BOM
    # הסרת תווי כיוון נפוצים
    s = s.replace("\u200e", "").replace("\u200f", "")
    s = s.strip()
    s = unicodedata.normalize("NFKC", s)
    return s

with app.app_context():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT id, name FROM players;")
    rows = cur.fetchall()

    groups = defaultdict(list)
    for r in rows:
        groups[norm(r["name"])].append((r["id"], r["name"]))

    dups = {k: v for k, v in groups.items() if k and len(v) > 1}

    print("DUP GROUPS:", len(dups))
    for k, v in sorted(dups.items(), key=lambda x: len(x[1]), reverse=True)[:50]:
        print("\nNORMALIZED:", repr(k))
        for pid, name in v:
            # כמה רשומות תוצאה לכל id
            cur.execute("SELECT COUNT(*) AS c FROM game_results WHERE player_id = ?;", (pid,))
            c = cur.fetchone()["c"]
            print(f"  id={pid} results={c} name={repr(name)}")

    conn.close()
