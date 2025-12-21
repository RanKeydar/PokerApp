import sqlite3

conn = sqlite3.connect("instance/poker.db")
cur = conn.cursor()

total = cur.execute("select count(*) from games").fetchone()[0]
games_2024 = cur.execute(
    "select count(*) from games where date like '2024%'"
).fetchone()[0]
minmax = cur.execute(
    "select min(date), max(date) from games"
).fetchone()

print("games total:", total)
print("games 2024:", games_2024)
print("min/max:", minmax)

conn.close()
    