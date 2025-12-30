from flask import Blueprint, render_template, request, redirect, url_for, abort, flash
from pokerapp.services.auth import login_required, role_required, get_current_user
from pokerapp.db.connection import get_db_connection
from pokerapp.services.game_queries import get_top_players, get_recent_games
from datetime import date
import os
import pandas as pd
import unicodedata

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
RAW_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "raw")
)


bp = Blueprint("main", __name__)

def _get_player_stats(conn, game_type: str, year: str, player_id: int) -> tuple[int, int]:
    cur = conn.cursor()

    # נספור רק תאריכים תקינים בפורמט YYYY-MM-DD
    iso_filter = "g.date LIKE '____-__-__'"

    # games_count: אם year == 'all' => בלי פילטר שנה
    if str(year) == "all":
        cur.execute(
            f"""
            SELECT COUNT(DISTINCT g.id) AS games_count
            FROM game_results gr
            JOIN games g ON g.id = gr.game_id
            WHERE gr.player_id = ?
              AND g.game_type = ?
              AND {iso_filter};
            """,
            (player_id, game_type),
        )
    else:
        cur.execute(
            f"""
            SELECT COUNT(DISTINCT g.id) AS games_count
            FROM game_results gr
            JOIN games g ON g.id = gr.game_id
            WHERE gr.player_id = ?
              AND g.game_type = ?
              AND {iso_filter}
              AND substr(g.date, 1, 4) = ?;
            """,
            (player_id, game_type, str(year)),
        )

    games_count = cur.fetchone()["games_count"] or 0

    # years_count: נספור שנים שונות רק מתוך תאריכים תקינים
    cur.execute(
        f"""
        SELECT COUNT(DISTINCT substr(g.date, 1, 4)) AS years_count
        FROM game_results gr
        JOIN games g ON g.id = gr.game_id
        WHERE gr.player_id = ?
          AND g.game_type = ?
          AND {iso_filter};
        """,
        (player_id, game_type),
    )
    years_count = cur.fetchone()["years_count"] or 0

    return int(games_count), int(years_count)


def enrich_players(conn, players, game_type: str, year: str):
    enriched = []
    for p in players:
        # sqlite3.Row -> dict (כדי שיהיה get())
        p = dict(p)

        pid = p.get("player_id") or p.get("id")

        # אם אין id – ננסה לפי שם
        if not pid:
            name = p.get("player_name") or p.get("name")
            if name:
                cur = conn.cursor()
                cur.execute("SELECT id FROM players WHERE name = ? LIMIT 1;", (name,))
                row = cur.fetchone()
                pid = row["id"] if row else None

        total = p.get("total_profit")
        if total is None:
            total = 0

        if pid:
            games_count, years_count = _get_player_stats(conn, game_type, year, int(pid))
        else:
            games_count, years_count = 0, 0

        p["games_count"] = games_count
        p["years_count"] = years_count
        p["avg_per_game"] = int(round(float(total) / games_count)) if games_count else 0
        p["avg_per_year"] = int(round(float(total) / years_count)) if years_count else 0


        enriched.append(p)

    return enriched



# ------------------------------
# מסך ראשי
# ------------------------------
@bp.route("/")
@login_required
def home():
    current_year = str(date.today().year)

    cash_year = request.args.get("cash_year") or current_year
    harbo_year = request.args.get("harbo_year") or current_year

    # איזה מסך מציגים: cash / harbo
    view = request.args.get("view", "cash")

    # מצב תצוגה לטבלת שחקנים (טופ/הכל) – נשמור, אבל רק לטבלה שמוצגת בפועל
    cash_players_view = request.args.get("cash_players", "top")  # "top" / "all"
    harbo_players_view = request.args.get("harbo_players", "top")

    cash_limit = 5 if cash_players_view != "all" else 9999
    harbo_limit = 5 if harbo_players_view != "all" else 9999

    # ברירת מחדל ריקה לצד שלא מוצג
    cash_top_players, cash_recent_games = [], []
    harbo_top_players, harbo_recent_games = [], []

    conn = get_db_connection()

    if view == "cash":
        cash_top_players = get_top_players("cash", cash_limit, year=cash_year)
        cash_recent_games = get_recent_games("cash", 5, year=cash_year)
        cash_top_players = enrich_players(conn, cash_top_players, "cash", cash_year)

    else:
        harbo_top_players = get_top_players("harbo", harbo_limit, year=harbo_year)
        harbo_recent_games = get_recent_games("harbo", 5, year=harbo_year)
        harbo_top_players = enrich_players(conn, harbo_top_players, "harbo", harbo_year)

    conn.close()

    return render_template(
        "home.html",
        current_user=get_current_user(),   # <-- להוסיף
        view=view,
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
    view = request.args.get("view", "cash")  # cash / harbo

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(
        "SELECT * FROM games WHERE game_type = ? ORDER BY date DESC;",
        (view,),
    )
    games = cur.fetchall()
    conn.close()

    return render_template(
        "games.html",
        view=view,
        games=games,
        current_user=get_current_user(),
    )


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
@role_required("admin", "magician")
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
@bp.route("/game/<int:game_id>/results", methods=["GET"])
@login_required
def game_results(game_id):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT * FROM games WHERE id = ?;", (game_id,))
    game = cur.fetchone()
    if game is None:
        conn.close()
        return "המשחק לא נמצא", 404

    # מביא רק שחקנים שיש להם שורה ב-game_results (כלומר יש תוצאה),
    # וממיין אלפביתית לפי שם
    cur.execute(
        """
        SELECT
        p.name AS player_name,
        gr.buyin,
        gr.cashout,
        gr.profit
        FROM game_results gr
        JOIN players p ON p.id = gr.player_id
        WHERE gr.game_id = ?
        AND gr.profit IS NOT NULL
        ORDER BY gr.profit DESC, p.name COLLATE NOCASE;
        """,
        (game_id,),
    )
    players = cur.fetchall()



    # סכומים לפי השורות שבאמת מוצגות
    total_buyin = sum(row["buyin"] for row in players) if players else 0
    total_cashout = sum(row["cashout"] for row in players) if players else 0
    diff = total_cashout - total_buyin

    conn.close()

    return render_template(
        "game_results.html",
        game=game,
        players=players,   # שים לב: עכשיו זה "רק מי שיש לו תוצאה"
        total_buyin=total_buyin,
        total_cashout=total_cashout,
        diff=diff,
        mode="view",
        current_user=get_current_user(),   # ← זה החסר
    )


@bp.route("/game/<int:game_id>/results/edit", methods=["GET", "POST"])
@login_required
def game_results_edit(game_id):
    user = get_current_user()
    if user["role"] not in ("admin", "magician"):
        abort(403)

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT * FROM games WHERE id = ?;", (game_id,))
    game = cur.fetchone()
    if game is None:
        conn.close()
        return "המשחק לא נמצא", 404

    if request.method == "POST":
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
        mode="edit", 
        current_user=get_current_user(),
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
    s = (s or "").strip()
    if not s:
        return ""

    # אם כבר ISO
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]

    # ננסה פרסור חכם עם pandas (תומך גם 06.01.2024 / 06-01-2024 / 6/1/2024 וכו')
    try:
        dt = pd.to_datetime(s, dayfirst=True, errors="coerce")
        if pd.isna(dt):
            return ""  # תאריך לא תקין -> נדלג על השורה
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return ""


def _norm_name(s: str) -> str:
    s = (s or "")
    s = s.replace("\ufeff", "")  # BOM
    s = s.strip()
    s = unicodedata.normalize("NFKC", s)
    return s

def import_csv_year_to_db(game_type: str, year: int) -> dict:
    """
    game_type: 'cash' / 'harbo'
    year: int (למשל 2024)
    """
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

        # דילוג על שורות ריקות / NaN / סיכומים (כמו "סה״כ")
        if not game_date_raw:
            continue
        if game_date_raw.lower() == "nan":
            continue
        if "סה" in game_date_raw:  # "סה״כ" / "סהכ" וכו'
            continue

        game_date = _parse_date_to_iso(game_date_raw)
        if not game_date:
            continue

        # סף בטיחות: השנה בקובץ חייבת להתאים לשנה של התאריך
        # (מונע מצב ש-TH_harbo_2024.csv מכיל תאריכי 2025)
        if len(game_date) >= 4 and game_date[:4] != str(year):
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

@bp.route("/admin/reset_harbo")
@login_required
@role_required("admin", "magician")
def admin_reset_harbo():
    conn = get_db_connection()
    cur = conn.cursor()

    # מוחקים תוצאות של משחקי חרבו
    cur.execute("""
    DELETE FROM game_results
    WHERE game_id IN (SELECT id FROM games WHERE game_type='harbo');
    """)

    # מוחקים משחקי חרבו
    cur.execute("DELETE FROM games WHERE game_type='harbo';")

    conn.commit()
    conn.close()

    # מייבאים מחדש
    summaries = []
    for y in HARBO_IMPORT_YEARS:
        summaries.append(import_csv_year_to_db("harbo", y))

    lines = ["<h2>RESET HARBO - סיכום</h2>", "<ul>"]
    for s in summaries:
        lines.append(
            f"<li>{s['game_type']} {s['year']}: {s['status']} | games: {s['imported_games']} | results: {s['imported_results']}</li>"
        )
    lines.append("</ul>")
    lines.append('<p><a href="/">חזרה לדף הבית</a></p>')
    return "\n".join(lines)
@bp.route("/admin/debug_harbo_2025_dates")
@login_required
@role_required("admin", "magician")
def debug_harbo_2025_dates():
    import os
    import pandas as pd

    path = os.path.join(RAW_DIR, "TH_harbo_2025.csv")
    df = _read_csv_hebrew(path)
    df = df.loc[:, [c for c in df.columns if c and not str(c).startswith("Unnamed")]]

    date_col = df.columns[0]
    dates = []
    for x in df[date_col].head(15).tolist():
        iso = _parse_date_to_iso(str(x))
        dates.append((str(x), iso))

    # סיכום שנים
    years = {}
    for _, iso in dates:
        if iso and len(iso) >= 4:
            years[iso[:4]] = years.get(iso[:4], 0) + 1

    return "<pre>" + "\n".join([f"{a}  ->  {b}" for a,b in dates]) + "\n\nYears in first 15 rows: " + str(years) + "</pre>"
@bp.route("/admin/debug_harbo_2024")
@login_required
@role_required("admin", "magician")
def debug_harbo_2024():
    conn = get_db_connection()
    cur = conn.cursor()

    # 1) משחקי חרבו לפי שנה (תאריכים תקינים בלבד)
    cur.execute("""
    SELECT substr(date,1,4) AS y, COUNT(*) AS games
    FROM games
    WHERE game_type='harbo' AND date LIKE '____-__-__'
    GROUP BY y
    ORDER BY y;
    """)
    games_by_year = [dict(r) for r in cur.fetchall()]

    # 2) כמות שורות תוצאות לפי שנה
    cur.execute("""
    SELECT substr(g.date,1,4) AS y, COUNT(*) AS results_rows
    FROM game_results gr
    JOIN games g ON g.id = gr.game_id
    WHERE g.game_type='harbo' AND g.date LIKE '____-__-__'
    GROUP BY y
    ORDER BY y;
    """)
    results_by_year = [dict(r) for r in cur.fetchall()]

    # 3) דוגמה של 10 משחקים מ-2024
    cur.execute("""
    SELECT id, date, location
    FROM games
    WHERE game_type='harbo'
      AND date LIKE '____-__-__'
      AND substr(date,1,4)='2024'
    ORDER BY date
    LIMIT 10;
    """)
    sample_2024 = [dict(r) for r in cur.fetchall()]

    conn.close()

    html = []
    html.append("<h2>DEBUG HARBO 2024</h2>")
    html.append("<h3>Games by year</h3><pre>" + str(games_by_year) + "</pre>")
    html.append("<h3>Results rows by year</h3><pre>" + str(results_by_year) + "</pre>")
    html.append("<h3>Sample games from 2024</h3><pre>" + str(sample_2024) + "</pre>")
    html.append('<p><a href="/">חזרה לדף הבית</a></p>')
    return "\n".join(html)

@bp.route("/admin/debug_import_harbo/<int:year>")
@login_required
@role_required("admin", "magician")
def debug_import_harbo(year):
    path = os.path.join(RAW_DIR, f"TH_harbo_{year}.csv")
    df = _read_csv_hebrew(path)
    df = df.loc[:, [c for c in df.columns if c and not str(c).startswith("Unnamed")]]

    date_col = df.columns[0]
    bad = []
    mismatch = []

    for raw in df[date_col].tolist():
        iso = _parse_date_to_iso(str(raw))
        if not iso:
            bad.append(str(raw))
            continue
        if iso[:4] != str(year):
            mismatch.append((str(raw), iso))

    html = []
    html.append(f"<h2>DEBUG IMPORT HARBO {year}</h2>")
    html.append(f"<p>Bad dates (unparsed): {len(bad)}</p><pre>" + "\n".join(bad[:30]) + "</pre>")
    html.append(f"<p>Year mismatch: {len(mismatch)}</p><pre>" + "\n".join([f"{a} -> {b}" for a,b in mismatch[:30]]) + "</pre>")
    return "\n".join(html)
@bp.route("/game/<int:game_id>/delete", methods=["POST"])
@login_required
@role_required("admin")
def delete_game(game_id):
    conn = get_db_connection()
    try:
        cur = conn.cursor()

        # ודא שהמשחק קיים
        cur.execute("SELECT id FROM games WHERE id = ?;", (game_id,))
        if cur.fetchone() is None:
            flash("המשחק לא נמצא", "error")
            return redirect(url_for("main.games_list"))

        # מחיקה בטוחה: קודם התוצאות ואז המשחק
        cur.execute("DELETE FROM game_results WHERE game_id = ?;", (game_id,))
        cur.execute("DELETE FROM games WHERE id = ?;", (game_id,))

        conn.commit()
        flash("המשחק נמחק בהצלחה", "ok")
        return redirect(url_for("main.games_list"))

    except Exception as e:
        conn.rollback()
        flash(f"שגיאה במחיקה: {e}", "error")
        return redirect(url_for("main.games_list"))
    finally:
        conn.close()