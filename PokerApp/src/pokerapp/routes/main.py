from flask import Blueprint, render_template, request, redirect, url_for, abort
from pokerapp.services.auth import login_required, role_required, get_current_user
from pokerapp.db.connection import get_db_connection
from pokerapp.services.game_queries import get_top_players, get_recent_games
from datetime import date
import os
import pandas as pd

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
RAW_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "raw")
)


bp = Blueprint("main", __name__)

# ------------------------------
# מסך ראשי
# ------------------------------
@bp.route("/")
@login_required
def home():
    current_year = str(date.today().year)

    cash_year = request.args.get("cash_year") or current_year
    harbo_year = request.args.get("harbo_year") or current_year

    # חדש: מצב תצוגה לטבלת שחקנים
    cash_players_view = request.args.get("cash_players", "top")  # "top" / "all"
    harbo_players_view = request.args.get("harbo_players", "top")

    cash_limit = 5 if cash_players_view != "all" else 9999
    harbo_limit = 5 if harbo_players_view != "all" else 9999

    cash_top_players = get_top_players("cash", cash_limit, year=cash_year)
    cash_recent_games = get_recent_games("cash", 5, year=cash_year)

    harbo_top_players = get_top_players("harbo", harbo_limit, year=harbo_year)
    harbo_recent_games = get_recent_games("harbo", 5, year=harbo_year)  

    return render_template(
        "home.html",
        cash_year=cash_year,
        harbo_year=harbo_year,
        cash_players_view=cash_players_view,
        harbo_players_view=harbo_players_view,
        cash_top_players=cash_top_players,
        cash_recent_games=cash_recent_games,
        harbo_top_players=harbo_top_players,
        harbo_recent_games=harbo_recent_games,
    )


# ------------------------------
# רשימת משחקים
# ------------------------------
@bp.route("/games")
@login_required
def games_list():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM games ORDER BY date DESC;")
    games = cur.fetchall()
    conn.close()
    return render_template("games.html", games=games)


# ------------------------------
# הוספת משחק חדש
# ------------------------------
@bp.route("/add_game", methods=["GET", "POST"])
@login_required
@role_required("admin", "magician")
def add_game():
    if request.method == "POST":
        date = request.form.get("date")
        location = request.form.get("location")
        game_type = request.form.get("game_type")

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO games (date, location, game_type) VALUES (?, ?, ?)",
            (date, location, game_type),
        )
        conn.commit()
        conn.close()

        return redirect(url_for("main.games_list"))

    return render_template("add_game.html")


# ------------------------------
# מסך שחקנים
# ------------------------------
@bp.route("/players")
@login_required
def players_list():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM players ORDER BY name;")
    players = cur.fetchall()
    conn.close()
    return render_template("players.html", players=players)


# הוספת שחקן חדש
@bp.route("/add_player", methods=["GET", "POST"])
@login_required
@role_required("admin")
def add_player():
    if request.method == "POST":
        name = request.form.get("name")

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("INSERT INTO players (name) VALUES (?);", (name,))
        conn.commit()
        conn.close()

        return redirect(url_for("main.players_list"))

    return render_template("add_player.html")


# ------------------------------
# מסך אדמין לאישור משתמשים
# ------------------------------
@bp.route("/admin/users", methods=["GET", "POST"])
@login_required
@role_required("admin")
def admin_users():
    conn = get_db_connection()
    cur = conn.cursor()

    if request.method == "POST":
        action = request.form.get("action")
        user_id = request.form.get("user_id")
        new_role = request.form.get("new_role", "player")

        if user_id:
            if action == "approve":
                if new_role not in ("admin", "magician", "player"):
                    new_role = "player"
                cur.execute(
                    "UPDATE users SET is_approved = 1, role = ? WHERE id = ?;",
                    (new_role, user_id),
                )
            elif action == "reject":
                cur.execute("DELETE FROM users WHERE id = ?;", (user_id,))
            conn.commit()

    cur.execute("SELECT id, username, role FROM users WHERE is_approved = 0 ORDER BY id DESC;")
    pending = cur.fetchall()

    cur.execute("SELECT id, username, role FROM users WHERE is_approved = 1 ORDER BY username;")
    active = cur.fetchall()

    conn.close()
    return render_template("admin_users.html", pending=pending, active=active)


# ------------------------------
# תוצאות למשחק מסוים
# ------------------------------
@bp.route("/game/<int:game_id>/results", methods=["GET", "POST"])
@login_required
def game_results(game_id):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT * FROM games WHERE id = ?;", (game_id,))
    game = cur.fetchone()
    if game is None:
        conn.close()
        return "המשחק לא נמצא", 404

    if request.method == "POST":
        user = get_current_user()
        if user["role"] not in ("admin", "magician"):
            abort(403)

        cur.execute("DELETE FROM game_results WHERE game_id = ?;", (game_id,))

        cur.execute("SELECT * FROM players ORDER BY name;")
        players = cur.fetchall()

        for player in players:
            pid = player["id"]
            buyin_str = request.form.get(f"buyin_{pid}", "").strip()
            cashout_str = request.form.get(f"cashout_{pid}", "").strip()

            if buyin_str == "" and cashout_str == "":
                continue

            try:
                buyin = float(buyin_str) if buyin_str != "" else 0.0
                cashout = float(cashout_str) if cashout_str != "" else 0.0
            except ValueError:
                continue

            profit = cashout - buyin

            cur.execute(
                """
                INSERT INTO game_results (game_id, player_id, buyin, cashout, profit)
                VALUES (?, ?, ?, ?, ?);
                """,
                (game_id, pid, buyin, cashout, profit),
            )

        conn.commit()

    cur.execute("SELECT * FROM players ORDER BY name;")
    players = cur.fetchall()

    cur.execute("SELECT * FROM game_results WHERE game_id = ?;", (game_id,))
    results_rows = cur.fetchall()

    results_by_player = {row["player_id"]: row for row in results_rows}

    total_buyin = sum(row["buyin"] for row in results_rows) if results_rows else 0
    total_cashout = sum(row["cashout"] for row in results_rows) if results_rows else 0
    diff = total_cashout - total_buyin

    conn.close()

    return render_template(
        "game_results.html",
        game=game,
        players=players,
        results=results_by_player,
        total_buyin=total_buyin,
        total_cashout=total_cashout,
        diff=diff,
    )

# ------------------------------
# Import RAW cash CSV -> DB (admin/magician)
# ------------------------------

CASH_IMPORT_YEARS = [2022, 2023, 2025]
HARBO_IMPORT_YEARS = [2023, 2024, 2025]

def _read_csv_hebrew(path: str) -> pd.DataFrame:
    # Excel בעברית לרוב = cp1255
    try:
        return pd.read_csv(path, encoding="cp1255")
    except UnicodeDecodeError:
        return pd.read_csv(path, encoding="utf-8")

def _parse_date_to_iso(s: str) -> str:
    """
    הופך '06/01/2022' ל-'2022-01-06' (כמו שמקובל ב-DB).
    אם כבר ISO - מחזיר כמו שהוא.
    """
    s = (s or "").strip()
    if not s:
        return ""
    # כבר ISO?
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]
    # dd/mm/yyyy
    try:
        d, m, y = s.split("/")
        return f"{y.zfill(4)}-{m.zfill(2)}-{d.zfill(2)}"
    except Exception:
        return s  # fallback

def import_csv_year_to_db(game_type: str, year: int) -> dict:
    """
    game_type: 'cash' / 'harbo'
    """
    filename = f"TH_{game_type}_{year}.csv"
    path = os.path.join(RAW_DIR, filename)
    if not os.path.exists(path):
        return {"game_type": game_type, "year": year, "status": "missing", "imported_games": 0, "imported_results": 0}

    df = _read_csv_hebrew(path)
    df = df.loc[:, [c for c in df.columns if c and not str(c).startswith("Unnamed")]]

    if df.shape[1] < 2:
        return {"game_type": game_type, "year": year, "status": "bad_format", "imported_games": 0, "imported_results": 0}

    date_col = df.columns[0]
    player_cols = list(df.columns[1:])

    conn = get_db_connection()
    cur = conn.cursor()

    imported_games = 0
    imported_results = 0

    cur.execute("SELECT id, name FROM players;")
    players_map = {row["name"]: row["id"] for row in cur.fetchall()}

    for _, row in df.iterrows():
        game_date_raw = str(row.get(date_col, "")).strip()
        game_date = _parse_date_to_iso(game_date_raw)
        if not game_date:
            continue

        # משחק קיים? (תאריך + סוג משחק)
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

        for player_name in player_cols:
            val = row.get(player_name, None)
            if val is None or (isinstance(val, float) and pd.isna(val)):
                continue
            try:
                profit = float(val)
            except Exception:
                continue
            if abs(profit) < 1e-12:
                continue

            if player_name not in players_map:
                cur.execute("INSERT INTO players (name) VALUES (?);", (player_name,))
                players_map[player_name] = cur.lastrowid
            pid = players_map[player_name]

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

    return {"game_type": game_type, "year": year, "status": "ok", "imported_games": imported_games, "imported_results": imported_results}



@bp.route("/admin/import_raw_all")
@login_required
@role_required("admin", "magician")
def admin_import_raw_all():
    summaries = []

    for y in CASH_IMPORT_YEARS:
        summaries.append(import_csv_year_to_db("cash", y))

    for y in HARBO_IMPORT_YEARS:
        summaries.append(import_csv_year_to_db("harbo", y))

    lines = ["<h2>Import RAW - סיכום</h2>", "<ul>"]
    for s in summaries:
        lines.append(
            f"<li>{s['game_type']} {s['year']}: {s['status']} | games: {s['imported_games']} | results: {s['imported_results']}</li>"
        )
    lines.append("</ul>")
    lines.append('<p><a href="/">חזרה לדף הבית</a></p>')
    return "\n".join(lines)

