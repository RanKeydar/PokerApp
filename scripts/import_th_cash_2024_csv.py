import os
import sqlite3
from pathlib import Path
import pandas as pd

# paths
BASE_DIR = Path(__file__).resolve().parents[1]   # scripts -> project root
DB_PATH = os.environ.get("DB_PATH", str(BASE_DIR / "instance" / "poker.db"))
CSV_PATH = BASE_DIR / "data" / "raw" / "TH_cash_2024.csv"

LOCATION = "TH"
GAME_TYPE = "cash"
ENCODING = "cp1255"   # עברית Windows


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_player(conn, name: str) -> int:
    name = str(name).strip()
    cur = conn.cursor()
    cur.execute("SELECT id FROM players WHERE name = ?;", (name,))
    row = cur.fetchone()
    if row:
        return int(row["id"])
    cur.execute("INSERT INTO players (name) VALUES (?);", (name,))
    return int(cur.lastrowid)


def get_or_create_game(conn, date_str: str, location: str, game_type: str) -> int:
    cur = conn.cursor()
    cur.execute(
        "SELECT id FROM games WHERE date = ? AND location = ? AND game_type = ?;",
        (date_str, location, game_type),
    )
    row = cur.fetchone()
    if row:
        return int(row["id"])
    cur.execute(
        "INSERT INTO games (date, location, game_type) VALUES (?, ?, ?);",
        (date_str, location, game_type),
    )
    return int(cur.lastrowid)


def replace_game_results(conn, game_id: int, rows: list[dict]):
    cur = conn.cursor()
    cur.execute("DELETE FROM game_results WHERE game_id = ?;", (game_id,))
    for r in rows:
        profit = float(r["profit"])
        buyin = abs(profit) if profit < 0 else 0.0
        cashout = profit if profit > 0 else 0.0
        cur.execute(
            """
            INSERT INTO game_results (game_id, player_id, buyin, cashout, profit)
            VALUES (?, ?, ?, ?, ?);
            """,
            (game_id, int(r["player_id"]), buyin, cashout, profit),
        )


def find_header_row(df_preview: pd.DataFrame) -> int:
    """מחפש שורה שבה העמודה הראשונה היא 'תאריך' / 'date'"""
    for i in range(min(30, len(df_preview))):
        cell = str(df_preview.iloc[i, 0]).strip().lower()
        if cell in ("תאריך", "date"):
            return i
    return 0


def main():
    print("DB:", DB_PATH)
    print("CSV:", CSV_PATH)

    # קריאה ראשונית בלי header
    df0 = pd.read_csv(CSV_PATH, header=None, encoding=ENCODING)

    header_row = find_header_row(df0)
    headers = df0.iloc[header_row].tolist()

    df = df0.iloc[header_row + 1 :].copy()
    df.columns = headers

    # עמודת תאריך
    df = df.rename(columns={df.columns[0]: "date"})
    df["date"] = pd.to_datetime(df["date"], errors="coerce", dayfirst=True)
    df = df[df["date"].notna()].copy()

    # מעבר ל-long format
    value_cols = [c for c in df.columns if c != "date"]
    long_df = df.melt(
        id_vars=["date"],
        value_vars=value_cols,
        var_name="player_name",
        value_name="profit",
    )

    long_df["profit"] = pd.to_numeric(long_df["profit"], errors="coerce")
    long_df = long_df[long_df["profit"].notna()].copy()

    conn = connect()
    try:
        games_imported = 0
        results_imported = 0

        for date_val, grp in long_df.groupby("date"):
            date_str = pd.to_datetime(date_val).strftime("%Y-%m-%d")
            game_id = get_or_create_game(conn, date_str, LOCATION, GAME_TYPE)

            rows = []
            for _, r in grp.iterrows():
                pid = ensure_player(conn, r["player_name"])
                rows.append({"player_id": pid, "profit": float(r["profit"])})

            replace_game_results(conn, game_id, rows)
            games_imported += 1
            results_imported += len(rows)

        conn.commit()
        print(f"✅ Imported {games_imported} games, {results_imported} results")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
