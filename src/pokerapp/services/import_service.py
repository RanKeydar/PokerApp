from pathlib import Path
import os
import re

import pandas as pd

from pokerapp.db.connection import get_db_connection, log_admin_action
from pokerapp.utils.csv_import import _read_csv_hebrew, _norm_name, _parse_date_to_iso

RAW_DIR = os.environ.get("RAW_DIR", str(Path(__file__).resolve().parents[3] / "data" / "raw"))


def discover_import_files():
    raw_path = Path(RAW_DIR)
    found = []

    if not raw_path.exists():
        return found

    pattern = re.compile(r"^TH_(cash|harbo)_(\d{4})\.csv$", re.IGNORECASE)

    for file_path in sorted(raw_path.glob("TH_*.csv")):
        m = pattern.match(file_path.name)
        if not m:
            continue

        game_type = m.group(1).lower()
        year = int(m.group(2))

        found.append({
            "game_type": game_type,
            "year": year,
            "path": str(file_path),
            "filename": file_path.name,
        })

    return found


def import_csv_year_to_db(game_type: str, year: int) -> dict:
    filename = f"TH_{game_type}_{year}.csv"
    path = os.path.join(RAW_DIR, filename)

    if not os.path.exists(path):
        return {
            "game_type": game_type,
            "year": year,
            "status": "missing",
            "imported_games": 0,
            "imported_results": 0,
        }

    df = _read_csv_hebrew(path)
    df = df.loc[:, [c for c in df.columns if c and not str(c).startswith("Unnamed")]]

    if df.shape[1] < 2:
        return {
            "game_type": game_type,
            "year": year,
            "status": "bad_format",
            "imported_games": 0,
            "imported_results": 0,
        }

    date_col = df.columns[0]
    player_cols_raw = list(df.columns[1:])

    conn = get_db_connection()
    cur = conn.cursor()

    imported_games = 0
    imported_results = 0

    cur.execute("SELECT id, name FROM players;")
    players_map = {_norm_name(row["name"]): row["id"] for row in cur.fetchall()}

    for _, row in df.iterrows():
        game_date_raw = str(row.get(date_col, "")).strip()

        if not game_date_raw:
            continue
        if game_date_raw.lower() == "nan":
            continue
        if "סה" in game_date_raw:
            continue

        game_date = _parse_date_to_iso(game_date_raw)
        if not game_date:
            continue

        if len(game_date) >= 4 and game_date[:4] != str(year):
            continue

        cur.execute(
            "SELECT id FROM games WHERE date = ? AND game_type = ? LIMIT 1;",
            (game_date, game_type),
        )
        existing = cur.fetchone()

        if existing:
            game_id = existing["id"]
            cur.execute("DELETE FROM game_results WHERE game_id = ?;", (game_id,))
        else:
            cur.execute(
                "INSERT INTO games (date, location, game_type) VALUES (?, ?, ?);",
                (game_date, None, game_type),
            )
            game_id = cur.lastrowid
            imported_games += 1

        for player_name_raw in player_cols_raw:
            clean_name = _norm_name(str(player_name_raw))
            val = row.get(player_name_raw, None)

            if val is None or (isinstance(val, float) and pd.isna(val)):
                continue

            try:
                profit = float(val)
            except Exception:
                continue

            if abs(profit) < 1e-12:
                continue

            if clean_name not in players_map:
                cur.execute("INSERT INTO players (name) VALUES (?);", (clean_name,))
                players_map[clean_name] = cur.lastrowid

            pid = players_map[clean_name]

            if profit >= 0:
                buyin = 0.0
                cashout = profit
            else:
                buyin = -profit
                cashout = 0.0

            cur.execute(
                """
                INSERT INTO game_results (game_id, player_id, buyin, cashout, profit)
                VALUES (?, ?, ?, ?, ?);
                """,
                (game_id, pid, buyin, cashout, profit),
            )
            imported_results += 1

    conn.commit()
    conn.close()

    return {
        "game_type": game_type,
        "year": year,
        "status": "ok",
        "imported_games": imported_games,
        "imported_results": imported_results,
    }


def run_import_raw_all() -> dict:
    files = discover_import_files()
    summaries = []

    try:
        if not files:
            log_admin_action(
                action="import_raw_all",
                status="warning",
                target_type="raw_import",
                target_value="all",
                message="No CSV files found in data/raw",
            )
            return {
                "ok": True,
                "flash_category": "warning",
                "message": "לא נמצאו קבצי CSV לייבוא בתיקיית data/raw.",
            }

        backup_path = None
        if files:
            from pokerapp.services.backup_service import backup_database
            from flask import current_app
            backup_path = backup_database(current_app.config["DB_PATH"])

        for item in files:
            summaries.append(import_csv_year_to_db(item["game_type"], item["year"]))

        ok_count = sum(1 for s in summaries if s["status"] == "ok")

        log_admin_action(
            action="import_raw_all",
            status="success",
            target_type="raw_import",
            target_value="all",
            message=f"Imported {ok_count} files; backup={Path(backup_path).name if backup_path else 'none'}",
        )

        return {
            "ok": True,
            "flash_category": "success",
            "message": (
                f"ייבוא מלא הסתיים. "
                f"גיבוי: {Path(backup_path).name if backup_path else 'none'}. "
                f"עובדו {ok_count} קבצים."
            ),
        }

    except Exception as e:
        log_admin_action(
            action="import_raw_all",
            status="error",
            target_type="raw_import",
            target_value="all",
            message=str(e),
        )
        return {
            "ok": False,
            "flash_category": "error",
            "message": f"שגיאה בייבוא המלא: {e}",
        }


def run_import_raw_one(game_type: str, year: int) -> dict:
    game_type = (game_type or "").strip().lower()
    target_value = f"{game_type}/{year}"

    if game_type not in ("cash", "harbo"):
        log_admin_action(
            action="import_raw_one",
            status="error",
            target_type="raw_import",
            target_value=target_value,
            message="Invalid game_type",
        )
        return {
            "ok": False,
            "flash_category": "error",
            "message": "סוג המשחק חייב להיות cash או harbo",
        }

    try:
        from pokerapp.services.backup_service import backup_database
        from flask import current_app
        backup_path = backup_database(current_app.config["DB_PATH"])
        summary = import_csv_year_to_db(game_type, year)

        if summary["status"] == "missing":
            log_admin_action(
                action="import_raw_one",
                status="warning",
                target_type="raw_import",
                target_value=target_value,
                message=f"File missing, backup={Path(backup_path).name}",
            )
            return {
                "ok": True,
                "flash_category": "warning",
                "message": f"לא נמצא קובץ עבור {game_type} {year}.",
            }

        if summary["status"] == "bad_format":
            log_admin_action(
                action="import_raw_one",
                status="error",
                target_type="raw_import",
                target_value=target_value,
                message=f"Bad format, backup={Path(backup_path).name}",
            )
            return {
                "ok": False,
                "flash_category": "error",
                "message": f"קובץ {game_type} {year} קיים אבל בפורמט לא תקין.",
            }

        log_admin_action(
            action="import_raw_one",
            status="success",
            target_type="raw_import",
            target_value=target_value,
            message=(
                f"backup={Path(backup_path).name}, "
                f"games={summary['imported_games']}, "
                f"results={summary['imported_results']}"
            ),
        )

        return {
            "ok": True,
            "flash_category": "success",
            "message": (
                f"ייבוא {game_type} {year} הסתיים בהצלחה. "
                f"גיבוי: {Path(backup_path).name} | "
                f"משחקים: {summary['imported_games']} | "
                f"תוצאות: {summary['imported_results']}"
            ),
        }

    except Exception as e:
        log_admin_action(
            action="import_raw_one",
            status="error",
            target_type="raw_import",
            target_value=target_value,
            message=str(e),
        )
        return {
            "ok": False,
            "flash_category": "error",
            "message": f"שגיאה בייבוא {game_type} {year}: {e}",
        }