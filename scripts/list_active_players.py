import sqlite3
from pathlib import Path

db = Path(__file__).resolve().parent.parent / "poker.db"
conn = sqlite3.connect(str(db))
conn.row_factory = sqlite3.Row

rows = conn.execute("""
    SELECT DISTINCT p.id, p.name
    FROM players p
    JOIN game_results gr ON gr.player_id = p.id
    JOIN games g ON g.id = gr.game_id
    WHERE g.date LIKE '2026%'
    ORDER BY p.name
""").fetchall()

print("\nשחקנים פעילים ב-2026:\n")
for r in rows:
    print("  id=%-4d  %s" % (r["id"], r["name"]))
print("\nסה\"כ: %d שחקנים" % len(rows))
conn.close()
