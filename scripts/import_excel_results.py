import argparse
import os
import sqlite3
from pathlib import Path
import pandas as pd


def project_root() -> Path:
    # scripts/import_excel_results.py -> scripts -> project root
    return Path(__file__).resolve().parents[1]


DB_PATH = os.environ.get("DB_PATH", str(project_root() / "instance" / "poker.db"))


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def load_th_excel(excel_path: Path, sheet_name: str | None = None) -> pd.DataFrame:
    """
    האקסל שלך נראה כך:
    - שורות 0-1 ריקות
    - שורה 2 היא header: תאריך + שמות שחקנים
    - שורות הבאות: ערכי profit נטו
    """
    df_raw = pd.read_excel(excel_path, sheet_name=sheet_name)

    # header הוא השורה השלישית (index=2)
    header_row = 2
    headers = df_raw.iloc[header_row].tolist()

    df = df_raw.iloc[header_row + 1 :].copy()
    df.columns = headers

    # עמודת תאריך
    df = df.rename(columns={df.columns[0]: "date"})
    df["date"] = pd.to_datetime(df["date"], errors="coerce")

    # נשאיר רק שורות עם תאריך
    df = df[df["date"].notna()].copy()

    # ננקה עמודות שאין להן שם
    df = df.loc[:, df.columns.notna()].copy()

    return df


def ensure_player(conn: sqlite3.Connection, name: str) -> int:
    name = str(name).strip()
    cur = conn.cursor()
    cur.execute("SELECT id FROM players WHERE name = ?;", (name,))
    row = cur.fetchone()
    if row:
        return int(row["id"])

    cur.execute("INSERT INTO players (name) VALUES (?);", (name,))
    return int(cur.lastrowid)


def get_or_create_game(conn: sqlite3.Connection, date_str: str, location: str, game_type: str) -> int:
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


def replace_game_results(conn: sqlite3.Connection, game_id: int, rows: list[dict]):
    cur = conn.cursor()
    cur.execute("DELETE FROM game_results WHERE game_id = ?;", (game_id,))

    for r in rows:
        profit = float(r["profit"])
        if profit >= 0:
            buyin = 0.0
            cashout = profit
        else:
            buyin = abs(profit)
            cashout = 0.0

        cur.execute(
            """
            INSERT INTO game_results (game_id, player_id, buyin, cashout, profit)
            VALUES (?, ?, ?, ?, ?);
            """,
            (game_id, int(r["player_id"]), buyin, cashout, profit),
        )


def import_excel(excel_path: Path, location: str, game_type: str, sheet_name: str | None = None):
    df = load_th_excel(excel_path, sheet_name=sheet_name)

    # להפוך ל-long format
    value_cols = [c for c in df.columns if c != "date"]
    long_df = df.melt(id_vars=["date"], value_vars=value_cols, var_name="player_name", value_name="profit")

    # רק ערכים מספריים ולא ריקים
    long_df["profit"] = pd.to_numeric(long_df["profit"], errors="coerce")
    long_df = long_df[long_df["profit"].notna()].copy()

    # אם יש 0 ואתה לא רוצה לשמור, אפשר לסנן כאן:
    # long_df = long_df[long_df["profit"] != 0].copy()

    conn = connect()
    cur = conn.cursor()

    # sanity: לוודא טבלאות בסיס
    cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = {r["name"] for r in cur.fetchall()}
    required = {"players", "games", "game_results"}
    missing = required - tables
    if missing:
        conn.close()
        raise RuntimeError(f"Missing tables in DB: {missing}. Run scripts/init_db.py first.")

    try:
        games_imported = 0
        results_imported = 0

        # קיבוץ לפי תאריך (משחק = תאריך)
        for date_val, grp in long_df.groupby("date"):
            date_str = pd.to_datetime(date_val).strftime("%Y-%m-%d")

            game_id = get_or_create_game(conn, date_str, location, game_type)

            rows = []
            for _, r in grp.iterrows():
                pid = ensure_player(conn, r["player_name"])
                rows.append({"player_id": pid, "profit": float(r["profit"])})

            replace_game_results(conn, game_id, rows)

            games_imported += 1
            results_imported += len(rows)

        conn.commit()
        print(f"✅ Imported {games_imported} games, {results_imported} results from: {excel_path.name}")
        print(f"DB: {DB_PATH}")
        print(f"Location='{location}', game_type='{game_type}'")
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Import poker results from Excel into SQLite DB.")
    parser.add_argument("--file", required=True, help="Path to Excel file, e.g. data/raw/TH_cash_2024.xlsx")
    parser.add_argument("--location", default="TH", help="Location value to store in games table")
    parser.add_argument("--game_type", default="cash", help="Game type to store in games table (cash/harbo)")
    parser.add_argument("--sheet", default=None, help="Excel sheet name (optional)")
    args = parser.parse_args()

    excel_path = Path(args.file).resolve()
    if not excel_path.exists():
        raise FileNotFoundError(f"Excel not found: {excel_path}")

    import_excel(excel_path, location=args.location, game_type=args.game_type, sheet_name=args.sheet)


if __name__ == "__main__":
    main()
