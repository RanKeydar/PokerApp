import json
from flask import Blueprint, render_template, request, redirect, url_for, abort, flash, current_app, session as flask_session, jsonify
from pokerapp.services.auth import login_required, role_required, get_current_user
from werkzeug.security import generate_password_hash
from pokerapp.db.connection import get_db_connection
from pokerapp.services.game_queries import (
    get_top_players,
    get_recent_games,
    get_complete_top_players,
    get_complete_recent_games,
)
from datetime import date, datetime
import os
import pandas as pd
import unicodedata
from pathlib import Path
import re

from pokerapp.db.backup import backup_database
from pokerapp.db.connection import log_admin_action, log_activity
from pokerapp.services.admin_tools import get_admin_tools_status, run_backup_now
from pokerapp.services.import_service import run_import_raw_all, run_import_raw_one 

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
RAW_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "raw")
)

bp = Blueprint("main", __name__)

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

from collections import defaultdict
from datetime import datetime

def _parse_dt(s: str) -> datetime:
    s = (s or "").strip()
    try:
        return datetime.fromisoformat(s[:10])
    except Exception:
        return datetime.min

def merge_players_rows(cash_rows, harbo_rows, limit=5):
    agg = defaultdict(lambda: {"player_name": None, "total_profit": 0.0})

    for r in (cash_rows or []):
        rr = dict(r)
        name = (rr.get("player_name") or "").strip()
        if not name:
            continue
        agg[name]["player_name"] = name
        agg[name]["total_profit"] += float(rr.get("total_profit") or 0)

    for r in (harbo_rows or []):
        rr = dict(r)
        name = (rr.get("player_name") or "").strip()
        if not name:
            continue
        agg[name]["player_name"] = name
        agg[name]["total_profit"] += float(rr.get("total_profit") or 0)

    out = list(agg.values())
    out.sort(key=lambda x: x["total_profit"], reverse=True)
    return out[:limit]

def merge_recent_games_rows(cash_games, harbo_games, limit=5):
    merged = []

    for g in (cash_games or []):
        gg = dict(g)
        gg["game_type_label"] = "קאש"
        merged.append(gg)

    for g in (harbo_games or []):
        gg = dict(g)
        gg["game_type_label"] = "חרבו"
        merged.append(gg)

    merged.sort(key=lambda x: _parse_dt(x.get("date")), reverse=True)
    return merged[:limit]

def enrich_recent_games_with_highlights(conn, recent_games):
    enriched = []

    for row in recent_games:
        g = dict(row)
        game_id = g["id"]

        top_winner = conn.execute("""
            SELECT
                p.id AS player_id,
                p.name AS player_name,
                gr.profit AS profit
            FROM game_results gr
            JOIN players p ON p.id = gr.player_id
            WHERE gr.game_id = ?
            ORDER BY gr.profit DESC, p.name ASC
            LIMIT 1
        """, (game_id,)).fetchone()

        top_loser = conn.execute("""
            SELECT
                p.id AS player_id,
                p.name AS player_name,
                gr.profit AS profit
            FROM game_results gr
            JOIN players p ON p.id = gr.player_id
            WHERE gr.game_id = ?
            ORDER BY gr.profit ASC, p.name ASC
            LIMIT 1
        """, (game_id,)).fetchone()

        g["top_winner_name"] = top_winner["player_name"] if top_winner else None
        g["top_winner_id"] = top_winner["player_id"] if top_winner else None
        g["top_winner_amount"] = top_winner["profit"] if top_winner and top_winner["profit"] is not None else 0
        g["top_loser_name"] = top_loser["player_name"] if top_loser else None
        g["top_loser_id"] = top_loser["player_id"] if top_loser else None
        g["top_loser_amount"] = top_loser["profit"] if top_loser and top_loser["profit"] is not None else 0

        enriched.append(g)

    return enriched

# ------------------------------
# מסך ראשי
# ------------------------------
@bp.route("/")
@login_required
def home():
    current_year = str(date.today().year)

    view = request.args.get("view", "cash")
    selected_year = request.args.get("year") or current_year
    players_view = request.args.get("players", "top")

    players_limit = 5 if players_view != "all" else 9999

    top_players = []
    recent_games = []

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT DISTINCT substr(date, 1, 4) AS year
        FROM games
        WHERE date LIKE '____-__-__'
        ORDER BY year DESC;
    """)
    years = [row["year"] for row in cur.fetchall() if row["year"]]

    if selected_year != "all" and selected_year not in years:
        selected_year = years[0] if years else current_year

    if "all" not in years:
        years.append("all")

    if view == "cash":
        top_players = get_top_players("cash", players_limit, year=selected_year)
        top_players = enrich_players(conn, top_players, "cash", selected_year)
        recent_games = get_recent_games("cash", 5, year=selected_year)
        recent_games = enrich_recent_games_with_highlights(conn, recent_games)

    elif view == "harbo":
        top_players = get_top_players("harbo", players_limit, year=selected_year)
        top_players = enrich_players(conn, top_players, "harbo", selected_year)
        recent_games = get_recent_games("harbo", 5, year=selected_year)
        recent_games = enrich_recent_games_with_highlights(conn, recent_games)

    elif view == "complete":
        top_players = get_complete_top_players(limit=players_limit, year=selected_year)
        recent_games = get_complete_recent_games(limit=5, year=selected_year)
        recent_games = enrich_recent_games_with_highlights(conn, recent_games)

    # ── All-time record: biggest single-game profit ────────────────────
    conn2 = get_db_connection()
    if view == "cash":
        _type_filter = "AND g.game_type = 'cash'"
    elif view == "harbo":
        _type_filter = "AND g.game_type = 'harbo'"
    else:
        _type_filter = ""
    record_game = conn2.execute(f"""
        SELECT p.id AS player_id, p.name AS player_name,
               gr.profit, g.date, g.id AS game_id
        FROM game_results gr
        JOIN players p ON p.id = gr.player_id
        JOIN games g ON g.id = gr.game_id
        WHERE gr.profit IS NOT NULL
          AND g.date LIKE '____-__-__'
          {_type_filter}
        ORDER BY gr.profit DESC
        LIMIT 1
    """).fetchone()
    record_game = dict(record_game) if record_game else None
    conn2.close()
    # ── End record ─────────────────────────────────────────────────────

    conn.close()

    ga_login = flask_session.pop("_ga_login", False)

    return render_template(
        "home.html",
        current_user=get_current_user(),
        view=view,
        selected_year=selected_year,
        years=years,
        players_view=players_view,
        top_players=top_players,
        recent_games=recent_games,
        ga_login=ga_login,
        record_game=record_game,
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
        """
        SELECT
            id,
            date,
            (substr(date,9,2) || '.' || substr(date,6,2) || '.' || substr(date,3,2)) AS date_il,
            location,
            game_type
        FROM games
        WHERE game_type = ?
        ORDER BY date DESC;
        """,
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
    conn = get_db_connection()
    cur = conn.cursor()

    if request.method == "POST":
        game_date  = request.form.get("date", "").strip()
        location   = request.form.get("location", "").strip() or None
        game_type  = request.form.get("game_type", "cash")

        # צור את המשחק
        cur.execute(
            "INSERT INTO games (date, location, game_type) VALUES (?, ?, ?)",
            (game_date, location, game_type),
        )
        conn.commit()
        game_id = cur.lastrowid

        # שמור תוצאות שחקנים (אם הוזנו)
        cur.execute("SELECT * FROM players ORDER BY name COLLATE NOCASE;")
        all_players = cur.fetchall()

        for p in all_players:
            pid = p["id"]
            buyin_str   = request.form.get(f"buyin_{pid}",   "").strip()
            cashout_str = request.form.get(f"cashout_{pid}", "").strip()

            if buyin_str == "" and cashout_str == "":
                continue

            try:
                buyin   = float(buyin_str)   if buyin_str   else 0.0
                cashout = float(cashout_str) if cashout_str else 0.0
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
        conn.close()
        log_activity("add_game", f"משחק {game_id} | {game_date} | {game_type}")
        return redirect(url_for("main.game_results", game_id=game_id))

    # GET — טען שחקנים פעילים (כאלה שמופיעים ב-game_results)
    cur.execute("""
        SELECT DISTINCT p.id, p.name
        FROM players p
        JOIN game_results gr ON gr.player_id = p.id
        ORDER BY p.name COLLATE NOCASE;
    """)
    players = [dict(r) for r in cur.fetchall()]
    conn.close()

    from datetime import date as _date
    today = _date.today().isoformat()
    return render_template("add_game.html", players=players, today=today, current_user=get_current_user())


# ------------------------------
# מסך שחקנים
# ------------------------------
@bp.route("/players")
@login_required
def players():
    current_year = date.today().year
    show = request.args.get("show", "active")
    sort = request.args.get("sort", type=str)
    direction = request.args.get("dir", type=str)

    if not sort:
        sort = "year_profit"
    if not direction:
        direction = "desc"

    sort = sort.strip().lower()
    direction = direction.strip().lower()
    
    allowed_sorts = {
        "name": "p.name COLLATE NOCASE",
        "total_profit": "total_profit",
        "year_profit": "year_profit",
        "year_avg": "year_avg",
        "year_games": "year_games",
        "last_result": "last_result",
        "last_position": "last_position_sort",
        "last_game_date": "last_game_date",
    }

    sort_sql = allowed_sorts.get(sort, "year_profit")
    dir_sql = "ASC" if direction == "asc" else "DESC"

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(
        """
        WITH totals AS (
            SELECT
                player_id,
                ROUND(COALESCE(SUM(profit), 0), 2) AS total_profit,
                COUNT(*) AS total_games
            FROM game_results
            GROUP BY player_id
        ),
        year_stats AS (
            SELECT
                gr.player_id,
                ROUND(COALESCE(SUM(gr.profit), 0), 2) AS year_profit,
                ROUND(COALESCE(AVG(gr.profit), 0), 2) AS year_avg,
                COUNT(*) AS year_games
            FROM game_results gr
            JOIN games g ON g.id = gr.game_id
            WHERE substr(g.date, 1, 4) = ?
            GROUP BY gr.player_id
        ),
        ranked_last AS (
            SELECT
                gr.player_id,
                ROUND(gr.profit, 2) AS last_result,
                g.date AS last_game_date,
                ROW_NUMBER() OVER (
                    PARTITION BY gr.player_id
                    ORDER BY g.date DESC, g.id DESC
                ) AS rn,
                ROW_NUMBER() OVER (
                    PARTITION BY gr.game_id
                    ORDER BY gr.profit DESC, p.name COLLATE NOCASE ASC
                ) AS position_in_game,
                COUNT(*) OVER (
                    PARTITION BY gr.game_id
                ) AS players_in_game
            FROM game_results gr
            JOIN games g ON g.id = gr.game_id
            JOIN players p ON p.id = gr.player_id
        )
        SELECT
            p.id,
            p.name,
            COALESCE(t.total_profit, 0) AS total_profit,
            COALESCE(t.total_games, 0) AS total_games,
            COALESCE(y.year_profit, 0) AS year_profit,
            COALESCE(y.year_avg, 0) AS year_avg,
            COALESCE(y.year_games, 0) AS year_games,
            rl.last_result,
            rl.last_game_date,
            CASE
                WHEN rl.position_in_game IS NOT NULL
                THEN CAST(rl.position_in_game AS TEXT) || ' מתוך ' || CAST(rl.players_in_game AS TEXT)
                ELSE '—'
            END AS last_position,
            CASE
                WHEN rl.position_in_game IS NOT NULL THEN rl.position_in_game
                ELSE 9999
            END AS last_position_sort
        FROM players p
        LEFT JOIN totals t ON t.player_id = p.id
        LEFT JOIN year_stats y ON y.player_id = p.id
        LEFT JOIN ranked_last rl ON rl.player_id = p.id AND rl.rn = 1
        ORDER BY """ + sort_sql + f" {dir_sql}, p.name COLLATE NOCASE ASC"
        ,
        (str(current_year),)
    )
    players = cur.fetchall()
    conn.close()

    if show == "active":
        players = [p for p in players if p["year_games"] > 0]

    return render_template(
        "players.html",
        players=players,
        year=current_year,
        sort=sort,
        direction=direction,
        show=show,
        current_user=get_current_user(),
    )

# ------------------------------
# עמוד סטטיסטיקות כלליות
# ------------------------------
@bp.route("/stats")
@login_required
def stats():
    log_activity("view_stats", "סטטיסטיקות קבוצתיות")
    from itertools import groupby as _groupby

    current_year_int = date.today().year
    current_year     = str(current_year_int)

    # ── URL params ────────────────────────────────────────
    scope       = request.args.get("scope",       "all")   # all | active  → records
    year        = request.args.get("year",        "all")   # all | YYYY    → KPI
    player_year = request.args.get("player_year", "all")   # all | YYYY    → player analysis
    if scope not in ("all", "active"):
        scope = "all"
    player_scope = request.args.get("player_scope", "active")
    if player_scope not in ("all", "active"):
        player_scope = "active"

    conn = get_db_connection()
    cur  = conn.cursor()

    # Available years (descending for display: current year first)
    cur.execute("SELECT DISTINCT substr(date,1,4) AS y FROM games ORDER BY y DESC")
    available_years = [r["y"] for r in cur.fetchall()]
    if year        not in available_years: year        = "all"
    if player_year not in available_years: player_year = "all"

    # ── SQL filter snippets ───────────────────────────────
    kpi_cond        = f"AND substr(g.date,1,4) = '{year}'"         if year        != "all" else ""
    kpi_cond_games  = f"AND substr(date,1,4) = '{year}'"           if year        != "all" else ""
    py_cond         = f"AND substr(g.date,1,4) = '{player_year}'"  if player_year != "all" else ""

    # Active player IDs (played cash this year) — used by scope + lucky_locations
    cur.execute(f"""
        SELECT DISTINCT gr.player_id FROM game_results gr
        JOIN games g ON g.id=gr.game_id
        WHERE g.game_type='cash' AND substr(g.date,1,4)='{current_year}'
    """)
    active_pids = {r["player_id"] for r in cur.fetchall()}

    # scope_cond: filter by PLAYER POOL (פעילים=active this year), not by date
    if scope == "active" and active_pids:
        scope_cond = f"AND gr.player_id IN ({','.join(str(i) for i in active_pids)})"
    else:
        scope_cond = ""


    # ── KPI counts ────────────────────────────────────────
    cur.execute(f"""
        SELECT COUNT(CASE WHEN game_type='cash'  THEN 1 END) AS cash_games,
               COUNT(CASE WHEN game_type='harbo' THEN 1 END) AS harbo_games,
               COUNT(*) AS total_games
        FROM games WHERE 1=1 {kpi_cond_games}
    """)
    kpi = dict(cur.fetchone())

    cur.execute(f"""
        SELECT COUNT(DISTINCT gr.player_id) AS n
        FROM game_results gr JOIN games g ON g.id = gr.game_id
        WHERE 1=1 {kpi_cond}
    """)
    kpi["total_players"] = cur.fetchone()["n"]

    cur.execute(f"""
        SELECT ROUND(AVG(cnt), 1) AS v FROM (
            SELECT COUNT(*) AS cnt FROM game_results gr
            JOIN games g ON g.id = gr.game_id
            WHERE g.game_type='cash' {kpi_cond} GROUP BY gr.game_id)
    """)
    row = cur.fetchone()
    kpi["avg_players_per_game"] = dict(row).get("v") or 0 if row else 0

    cur.execute(f"""
        SELECT ROUND(AVG(pot), 0) AS v FROM (
            SELECT SUM(gr.buyin) AS pot FROM game_results gr
            JOIN games g ON g.id = gr.game_id
            WHERE g.game_type='cash' {kpi_cond} GROUP BY gr.game_id)
    """)
    row = cur.fetchone()
    kpi["avg_pot"] = dict(row).get("v") or 0 if row else 0

    # ── Records (scope filter) ────────────────────────────
    def _fmt_date(d):
        return f"{d[8:10]}.{d[5:7]}.{d[2:4]}" if d else ""

    def _first(q):
        cur.execute(q)
        r = cur.fetchone()
        return dict(r) if r else None

    record_win = _first(f"""
        SELECT p.name AS player_name, p.id AS player_id,
               gr.profit, g.date, g.id AS game_id
        FROM game_results gr JOIN games g ON g.id=gr.game_id
        JOIN players p ON p.id=gr.player_id
        WHERE g.game_type='cash' AND gr.profit > 0 {scope_cond}
        ORDER BY gr.profit DESC LIMIT 1""")
    if record_win: record_win["date_il"] = _fmt_date(record_win.get("date"))

    record_loss = _first(f"""
        SELECT p.name AS player_name, p.id AS player_id,
               gr.profit, g.date, g.id AS game_id
        FROM game_results gr JOIN games g ON g.id=gr.game_id
        JOIN players p ON p.id=gr.player_id
        WHERE g.game_type='cash' AND gr.profit < 0 {scope_cond}
        ORDER BY gr.profit ASC LIMIT 1""")
    if record_loss: record_loss["date_il"] = _fmt_date(record_loss.get("date"))

    most_active = _first(f"""
        SELECT p.name AS player_name, p.id AS player_id, COUNT(*) AS games_count
        FROM game_results gr JOIN games g ON g.id=gr.game_id
        JOIN players p ON p.id=gr.player_id
        WHERE g.game_type='cash' {scope_cond}
        GROUP BY gr.player_id ORDER BY games_count DESC LIMIT 1""")

    best_player = _first(f"""
        SELECT p.name AS player_name, p.id AS player_id,
               ROUND(SUM(gr.profit),0) AS total_profit
        FROM game_results gr JOIN games g ON g.id=gr.game_id
        JOIN players p ON p.id=gr.player_id
        WHERE g.game_type='cash' {scope_cond}
        GROUP BY gr.player_id ORDER BY total_profit DESC LIMIT 1""")

    worst_player = _first(f"""
        SELECT p.name AS player_name, p.id AS player_id,
               ROUND(SUM(gr.profit),0) AS total_profit
        FROM game_results gr JOIN games g ON g.id=gr.game_id
        JOIN players p ON p.id=gr.player_id
        WHERE g.game_type='cash' {scope_cond}
        GROUP BY gr.player_id ORDER BY total_profit ASC LIMIT 1""")

    biggest_pot = _first(f"""
        SELECT g.id AS game_id, g.date, g.location,
               ROUND(SUM(gr.buyin),0) AS total_pot, COUNT(*) AS players_count
        FROM game_results gr JOIN games g ON g.id=gr.game_id
        WHERE g.game_type='cash' {scope_cond}
        GROUP BY gr.game_id ORDER BY total_pot DESC LIMIT 1""")
    if biggest_pot: biggest_pot["date_il"] = _fmt_date(biggest_pot.get("date"))

    # Streak (scope filter)
    cur.execute(f"""
        SELECT gr.player_id, p.name AS player_name, gr.profit, g.date, g.id AS game_id
        FROM game_results gr JOIN games g ON g.id=gr.game_id
        JOIN players p ON p.id=gr.player_id
        WHERE g.game_type='cash' {scope_cond}
        ORDER BY gr.player_id, g.date ASC, g.id ASC
    """)
    all_results = cur.fetchall()

    record_win_streak = record_loss_streak = None
    best_ws = best_ls = 0
    for pid, grp in _groupby(all_results, key=lambda r: r["player_id"]):
        gl = list(grp)
        pname = gl[0]["player_name"]
        cw = cl = mw = ml = 0
        for g in gl:
            if   g["profit"] > 0: cw += 1; cl = 0
            elif g["profit"] < 0: cl += 1; cw = 0
            else:                 cw = cl = 0
            if cw > mw: mw = cw
            if cl > ml: ml = cl
        if mw > best_ws:
            best_ws = mw
            record_win_streak  = {"player_name": pname, "player_id": pid, "streak": mw}
        if ml > best_ls:
            best_ls = ml
            record_loss_streak = {"player_name": pname, "player_id": pid, "streak": ml}

    # ── Player analysis (player_year filter) ──────────────
    cur.execute(f"""
        SELECT p.id AS player_id, p.name AS player_name,
               COUNT(*) AS games,
               ROUND(100.0 * SUM(CASE WHEN gr.profit > 0 THEN 1 ELSE 0 END) / COUNT(*), 1) AS win_rate,
               ROUND(AVG(gr.profit), 1) AS avg_profit,
               ROUND(SQRT(MAX(0, AVG(gr.profit * gr.profit) - AVG(gr.profit) * AVG(gr.profit))), 1) AS volatility
        FROM game_results gr
        JOIN games g ON g.id = gr.game_id
        JOIN players p ON p.id = gr.player_id
        WHERE g.game_type = 'cash' {py_cond}
        GROUP BY gr.player_id
        HAVING games >= 3
        ORDER BY games DESC
    """)
    player_stats = [dict(r) for r in cur.fetchall()]
    if player_scope == "active":
        player_stats = [p for p in player_stats if p["player_id"] in active_pids]

    qualified       = [p for p in player_stats if p["games"] >= 5]
    most_volatile   = max(qualified, key=lambda x: x["volatility"]) if qualified else None
    least_volatile  = min(qualified, key=lambda x: x["volatility"]) if qualified else None
    highest_winrate = max(qualified, key=lambda x: x["win_rate"])   if qualified else None

    # ── Current streaks (active players, cash games) ─────────────────────────────
    scope_pids = active_pids if player_scope == "active" else None
    cur.execute(
        """
        SELECT gr.player_id, p.name AS player_name, gr.profit
        FROM game_results gr
        JOIN games g ON g.id = gr.game_id
        JOIN players p ON p.id = gr.player_id
        WHERE g.game_type = 'cash'
        ORDER BY gr.player_id, g.date DESC, g.id DESC
        """
    )
    streak_rows = cur.fetchall()
    current_streaks = []
    for pid, grp in _groupby(streak_rows, key=lambda r: r["player_id"]):
        if scope_pids is not None and pid not in scope_pids:
            continue
        games_desc = list(grp)
        if not games_desc:
            continue
        pname = games_desc[0]["player_name"]
        streak_val = 0
        streak_sum = 0
        streak_type = None
        for g in games_desc:
            if g["profit"] > 0:
                gt = "win"
            elif g["profit"] < 0:
                gt = "loss"
            else:
                break
            if streak_type is None:
                streak_type = gt
                streak_val = 1
                streak_sum = g["profit"]
            elif gt == streak_type:
                streak_val += 1
                streak_sum += g["profit"]
            else:
                break
        if streak_type and streak_val >= 2:
            current_streaks.append({
                "player_id": pid,
                "player_name": pname,
                "streak": streak_val,
                "streak_sum": int(round(streak_sum)),
                "streak_type": streak_type,
            })

    hot_streak  = max((s for s in current_streaks if s["streak_type"] == "win"),
                      key=lambda x: x["streak"], default=None)
    cold_streak = max((s for s in current_streaks if s["streak_type"] == "loss"),
                      key=lambda x: x["streak"], default=None)

    # ── Most improved (last full year vs year before) ──────────────────────────
    from datetime import date as _date
    _cur_year  = str(_date.today().year)
    _prev_year = str(_date.today().year - 1)

    cur.execute(
        f"""
        SELECT gr.player_id, p.name AS player_name,
               SUM(CASE WHEN substr(g.date,1,4)='{_cur_year}'  THEN 1 ELSE 0 END) AS games_cur,
               SUM(CASE WHEN substr(g.date,1,4)='{_prev_year}' THEN 1 ELSE 0 END) AS games_prev,
               ROUND(AVG(CASE WHEN substr(g.date,1,4)='{_cur_year}'  THEN gr.profit END), 1) AS avg_cur,
               ROUND(AVG(CASE WHEN substr(g.date,1,4)='{_prev_year}' THEN gr.profit END), 1) AS avg_prev
        FROM game_results gr
        JOIN games g ON g.id = gr.game_id
        JOIN players p ON p.id = gr.player_id
        WHERE g.game_type = 'cash'
        GROUP BY gr.player_id
        HAVING games_cur >= 3 AND games_prev >= 3
        """
    )
    improved_rows = [dict(r) for r in cur.fetchall()]
    if scope_pids is not None:
        improved_rows = [r for r in improved_rows if r["player_id"] in scope_pids]
    for r in improved_rows:
        r["delta"] = round((r["avg_cur"] or 0) - (r["avg_prev"] or 0), 1)
    most_improved = max(improved_rows, key=lambda x: x["delta"], default=None)
    most_declined = min(improved_rows, key=lambda x: x["delta"], default=None) if len(improved_rows) > 1 else None
    if most_improved and most_improved["delta"] <= 0:
        most_improved = None
    if most_declined and most_declined["delta"] >= 0:
        most_declined = None

    # ── בית המזל — all active players ────────────────────
    # active_pids already computed above
    # Step 2: best location per active player
    cur.execute("""
        SELECT gr.player_id, p.name AS player_name, g.location,
               ROUND(AVG(gr.profit), 0) AS avg_profit, COUNT(*) AS games
        FROM game_results gr JOIN games g ON g.id=gr.game_id
        JOIN players p ON p.id=gr.player_id
        WHERE g.game_type='cash'
          AND g.location IS NOT NULL
          AND TRIM(g.location) != ''
          AND UPPER(TRIM(g.location)) != 'TH'
        GROUP BY gr.player_id, g.location
        HAVING games >= 1
        ORDER BY gr.player_id, avg_profit DESC
    """)
    seen_loc = set()
    lucky_locations = []
    for r in cur.fetchall():
        pid = r["player_id"]
        if pid in active_pids and pid not in seen_loc:
            seen_loc.add(pid)
            lucky_locations.append(dict(r))
    lucky_locations.sort(key=lambda x: x["avg_profit"], reverse=True)

    # ── בית המנחוס — worst location per active player ────
    cur.execute("""
        SELECT gr.player_id, p.name AS player_name, g.location,
               ROUND(AVG(gr.profit), 0) AS avg_profit, COUNT(*) AS games
        FROM game_results gr JOIN games g ON g.id=gr.game_id
        JOIN players p ON p.id=gr.player_id
        WHERE g.game_type='cash'
          AND g.location IS NOT NULL
          AND TRIM(g.location) != ''
          AND UPPER(TRIM(g.location)) != 'TH'
        GROUP BY gr.player_id, g.location
        HAVING games >= 1
        ORDER BY gr.player_id, avg_profit ASC
    """)
    seen_unlucky = set()
    unlucky_locations = []
    for r in cur.fetchall():
        pid = r["player_id"]
        if pid in active_pids and pid not in seen_unlucky:
            seen_unlucky.add(pid)
            unlucky_locations.append(dict(r))
    unlucky_locations.sort(key=lambda x: x["avg_profit"])

    # ── Charts (always all-time) ──────────────────────────
    cur.execute("""
        SELECT substr(date,1,4) AS year,
               COUNT(CASE WHEN game_type='cash'  THEN 1 END) AS cash_count,
               COUNT(CASE WHEN game_type='harbo' THEN 1 END) AS harbo_count
        FROM games GROUP BY year ORDER BY year ASC
    """)
    yearly_rows = cur.fetchall()
    chart_years = [r["year"]       for r in yearly_rows]
    chart_cash  = [r["cash_count"] for r in yearly_rows]
    chart_harbo = [r["harbo_count"]for r in yearly_rows]

    month_names = ["ינו","פבר","מרץ","אפר","מאי","יונ","יול","אוג","ספט","אוק","נוב","דצמ"]
    cur.execute("""
        SELECT month,
               ROUND(CAST(COUNT(*) AS REAL) / COUNT(DISTINCT year), 1) AS avg_cnt
        FROM (
            SELECT CAST(substr(date,6,2) AS INTEGER) AS month,
                   substr(date,1,4) AS year
            FROM games WHERE game_type='cash'
              AND date LIKE '____-__-__'
        )
        GROUP BY month ORDER BY month ASC
    """)
    month_raw         = {r["month"]: r["avg_cnt"] for r in cur.fetchall()}
    chart_months_data = [month_raw.get(i, 0) for i in range(1, 13)]

    cur.execute("""
        SELECT substr(g.date,1,4) AS year, ROUND(AVG(sub.cnt),1) AS avg_players
        FROM (
            SELECT gr.game_id, COUNT(*) AS cnt
            FROM game_results gr JOIN games g2 ON g2.id=gr.game_id
            WHERE g2.game_type='cash' GROUP BY gr.game_id
        ) sub JOIN games g ON g.id=sub.game_id
        GROUP BY year ORDER BY year ASC
    """)
    trend_rows          = cur.fetchall()
    chart_trend_years   = [r["year"]        for r in trend_rows]
    chart_trend_players = [r["avg_players"] for r in trend_rows]

    # Pot by year table (avg pot per game per year)
    cur.execute("""
        SELECT substr(g.date,1,4) AS year,
               COUNT(DISTINCT sub.game_id) AS games,
               ROUND(AVG(sub.pot), 0) AS avg_pot,
               ROUND(SUM(sub.pot), 0) AS total_pot
        FROM (
            SELECT gr.game_id, SUM(gr.buyin) AS pot
            FROM game_results gr JOIN games g2 ON g2.id=gr.game_id
            WHERE g2.game_type='cash' GROUP BY gr.game_id
        ) sub JOIN games g ON g.id=sub.game_id
        GROUP BY year ORDER BY year DESC
    """)
    pot_by_year = [dict(r) for r in cur.fetchall()]

    # Chart data for pot-by-year
    _pot_asc = list(reversed(pot_by_year))
    chart_pot_years = json.dumps([r["year"]      for r in _pot_asc])
    chart_pot_avg   = json.dumps([r["avg_pot"]   for r in _pot_asc])
    chart_pot_total = json.dumps([r["total_pot"] for r in _pot_asc])

    # Earliest cash game date (for בית המזל note)
    row = cur.execute(
        "SELECT MIN(date) AS d FROM games WHERE game_type='cash' AND date LIKE '____-__-__'"
    ).fetchone()
    earliest_raw = row["d"] if row and row["d"] else None
    earliest_date = (
        f"{earliest_raw[8:10]}.{earliest_raw[5:7]}.{earliest_raw[0:4]}"
        if earliest_raw else None
    )

    conn.close()

    return render_template(
        "stats.html",
        kpi=kpi,
        scope=scope,
        year=year,
        player_year=player_year,
        current_year=current_year,
        available_years=available_years,
        record_win=record_win,
        record_loss=record_loss,
        most_active=most_active,
        best_player=best_player,
        worst_player=worst_player,
        biggest_pot=biggest_pot,
        player_stats=player_stats,
        most_volatile=most_volatile,
        least_volatile=least_volatile,
        highest_winrate=highest_winrate,
        lucky_locations=lucky_locations,
        unlucky_locations=unlucky_locations,
        record_win_streak=record_win_streak,
        record_loss_streak=record_loss_streak,
        hot_streak=hot_streak,
        cold_streak=cold_streak,
        most_improved=most_improved,
        most_declined=most_declined,
        pot_by_year=pot_by_year,
        player_scope=player_scope,
        chart_pot_years=chart_pot_years,
        chart_pot_avg=chart_pot_avg,
        chart_pot_total=chart_pot_total,
        chart_years=json.dumps(chart_years),
        chart_cash=json.dumps(chart_cash),
        chart_harbo=json.dumps(chart_harbo),
        chart_months=json.dumps(month_names),
        chart_months_data=json.dumps(chart_months_data),
        chart_trend_years=json.dumps(chart_trend_years),
        chart_trend_players=json.dumps(chart_trend_players),
        earliest_date=earliest_date,
        current_user=get_current_user(),
    )

# ------------------------------
# מסך אדמין לאישור משתמשים




@bp.route("/admin/users", methods=["GET", "POST"])
@login_required
@role_required("admin")
def admin_users():
    conn = get_db_connection()
    cur = conn.cursor()

    flash_msg = None
    if request.method == "POST":
        action = request.form.get("action")
        user_id = request.form.get("user_id")
        new_role = request.form.get("new_role", "player")
        if new_role not in ("admin", "magician", "player"):
            new_role = "player"

        if action == "create_user":
            new_username = request.form.get("new_username", "").strip()
            new_password = request.form.get("new_password", "").strip()
            if new_username and new_password:
                existing = cur.execute("SELECT id FROM users WHERE username = ?;", (new_username,)).fetchone()
                if existing:
                    flash_msg = f"שם המשתמש '{new_username}' כבר קיים."
                else:
                    pw_hash = generate_password_hash(new_password)
                    cur.execute(
                        "INSERT INTO users (username, password_hash, role, is_approved) VALUES (?, ?, ?, 1);",
                        (new_username, pw_hash, new_role),
                    )
                    conn.commit()
                    flash_msg = f"המשתמש '{new_username}' נוצר בהצלחה."
            else:
                flash_msg = "חובה למלא שם משתמש וסיסמה."

        elif user_id:
            if action == "approve":
                cur.execute(
                    "UPDATE users SET is_approved = 1, role = ? WHERE id = ?;",
                    (new_role, user_id),
                )
            elif action == "reject":
                cur.execute("DELETE FROM users WHERE id = ?;", (user_id,))
            elif action == "change_role":
                cur.execute(
                    "UPDATE users SET role = ? WHERE id = ? AND username != 'admin';",
                    (new_role, user_id),
                )
            elif action == "reset_password":
                new_pw = request.form.get("new_password", "").strip()
                if new_pw:
                    cur.execute(
                        "UPDATE users SET password_hash = ? WHERE id = ? AND username != 'admin';",
                        (generate_password_hash(new_pw), user_id),
                    )
                    flash_msg = "הסיסמה אופסה בהצלחה."
                else:
                    flash_msg = "חובה להזין סיסמה חדשה."
            elif action == "delete_user":
                cur.execute("DELETE FROM users WHERE id = ? AND username != 'admin';", (user_id,))
                flash_msg = "המשתמש נמחק."
            elif action == "link_player":
                player_id = request.form.get("player_id") or None
                if player_id == "":
                    player_id = None
                cur.execute(
                    "UPDATE users SET player_id = ? WHERE id = ?;",
                    (player_id, user_id),
                )
                flash_msg = "השחקן קושר בהצלחה."
            conn.commit()

    cur.execute("SELECT id, username, role FROM users WHERE is_approved = 0 ORDER BY id DESC;")
    pending = cur.fetchall()

    cur.execute("SELECT id, username, role, player_id FROM users WHERE is_approved = 1 ORDER BY username;")
    active = cur.fetchall()

    cur.execute("SELECT id, name FROM players ORDER BY name;")
    players = cur.fetchall()

    conn.close()

    return render_template("admin_users.html", pending=pending, active=active, players=players, flash_msg=flash_msg)

@bp.route("/game/<int:game_id>/results", methods=["GET"])
@login_required
def game_results(game_id):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT *, (substr(date,9,2) || '.' || substr(date,6,2) || '.' || substr(date,3,2)) AS date_il
        FROM games WHERE id = ?;
        """,
        (game_id,),
    )
    game = cur.fetchone()
    if game is None:
        conn.close()
        return "המשחק לא נמצא", 404

    cur.execute(
        """
        SELECT
        p.id AS player_id,
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

    total_buyin  = sum(row["buyin"]   for row in players) if players else 0
    total_cashout= sum(row["cashout"] for row in players) if players else 0
    diff = total_cashout - total_buyin
    conn.close()

    return render_template(
        "game_results.html",
        game=game,
        players=players,
        total_buyin=total_buyin,
        total_cashout=total_cashout,
        diff=diff,
        mode="view",
        current_user=get_current_user(),
    )

@bp.route("/game/<int:game_id>/results/edit", methods=["GET", "POST"])
@login_required
def game_results_edit(game_id):
    user = get_current_user()
    if user["role"] not in ("admin", "magician"):
        abort(403)

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(
        "SELECT *, (substr(date,9,2) || '.' || substr(date,6,2) || '.' || substr(date,3,2)) AS date_il FROM games WHERE id = ?;",
        (game_id,),
    )
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

    cur.execute("SELECT * FROM game_results WHERE game_id = ?;", (game_id,))
    results_rows = cur.fetchall()
    results_rows = [dict(r) for r in results_rows]

    results_by_player = {row["player_id"]: row for row in results_rows}
    players_in_game_ids = set(results_by_player.keys())

    # שחקנים שכבר במשחק — עם הנתונים שלהם
    cur.execute("""
        SELECT p.id, p.name
        FROM players p
        WHERE p.id IN ({})
        ORDER BY p.name COLLATE NOCASE;
    """.format(",".join("?" * len(players_in_game_ids)) if players_in_game_ids else "NULL"),
        list(players_in_game_ids) if players_in_game_ids else []
    )
    players = [dict(r) for r in cur.fetchall()]

    # שחקנים פעילים שעוד לא במשחק — לחיפוש הוספה
    cur.execute("""
        SELECT DISTINCT p.id, p.name
        FROM players p
        JOIN game_results gr ON gr.player_id = p.id
        WHERE p.id NOT IN ({})
        ORDER BY p.name COLLATE NOCASE;
    """.format(",".join("?" * len(players_in_game_ids)) if players_in_game_ids else "SELECT -1"),
        list(players_in_game_ids) if players_in_game_ids else []
    )
    available_players = [dict(r) for r in cur.fetchall()]

    total_buyin = sum(row["buyin"] for row in results_rows) if results_rows else 0
    total_cashout = sum(row["cashout"] for row in results_rows) if results_rows else 0
    diff = total_cashout - total_buyin

    conn.close()

    return render_template(
        "game_results.html",
        game=game,
        players=players,
        results=results_by_player,
        available_players=available_players,
        total_buyin=total_buyin,
        total_cashout=total_cashout,
        diff=diff,
        mode="edit",
        current_user=get_current_user(),
    )


# ------------------------------
# Import RAW cash CSV -> DB (admin/magician)
# ------------------------------

CASH_IMPORT_YEARS = [2022, 2023,2024, 2025, 2026]
HARBO_IMPORT_YEARS = [2022, 2023, 2024, 2025, 2026]

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

@bp.route("/admin/import/raw-all", methods=["POST"])
@login_required
@role_required("admin", "magician")
def admin_import_raw_all():
    result = run_import_raw_all()
    flash(result["message"], result["flash_category"])
    return redirect(url_for("main.admin_tools"))
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
        log_activity("delete_game", f"משחק {game_id}")
        flash("המשחק נמחק בהצלחה", "ok")
        return redirect(url_for("main.games_list"))

    except Exception as e:
        conn.rollback()
        flash(f"שגיאה במחיקה: {e}", "error")
        return redirect(url_for("main.games_list"))
    finally:
        conn.close()

@bp.route("/admin/import/<game_type>/<int:year>", methods=["POST"])
@login_required
@role_required("admin", "magician")
def admin_import_raw_one(game_type, year):
    result = run_import_raw_one(game_type, year)
    flash(result["message"], result["flash_category"])
    return redirect(url_for("main.admin_tools"))
@bp.route("/admin/backup_now", methods=["POST"])
@login_required
@role_required("admin", "magician")
def admin_backup_now():
    result = run_backup_now()
    flash(result["message"], result["flash_category"])
    return redirect(url_for("main.admin_tools"))
    
@bp.route("/admin/activity")
@login_required
@role_required("admin")
def admin_activity():
    conn = get_db_connection()
    filter_user = request.args.get("user", "")
    filter_action = request.args.get("action", "")
    limit = int(request.args.get("limit", 200))

    where = "WHERE 1=1"
    params = []
    if filter_user:
        where += " AND username = ?"
        params.append(filter_user)
    if filter_action:
        where += " AND action = ?"
        params.append(filter_action)

    rows = conn.execute(
        f"SELECT * FROM user_activity_log {where} ORDER BY created_at DESC LIMIT ?",
        params + [limit],
    ).fetchall()
    users = [r["username"] for r in conn.execute(
        "SELECT DISTINCT username FROM user_activity_log ORDER BY username"
    ).fetchall()]
    actions = [r["action"] for r in conn.execute(
        "SELECT DISTINCT action FROM user_activity_log ORDER BY action"
    ).fetchall()]
    conn.close()
    return render_template("admin_activity.html",
        rows=rows, users=users, actions=actions,
        filter_user=filter_user, filter_action=filter_action, limit=limit)


@bp.route("/admin/tools")
@login_required
@role_required("admin")
def admin_tools():
    status = get_admin_tools_status()
    return render_template(
        "admin_tools.html",
        latest_backup=status["latest_backup"],
        backup_count=status["backup_count"],
        import_files=status["import_files"],
        import_count=status["import_count"],
    )


@bp.route("/calculator")
@login_required
def calculator():
    log_activity("view_calculator", "")
    return render_template("calculator.html", current_user=get_current_user())

@bp.route("/players/<int:player_id>")
@login_required
def player_detail(player_id):
    current_year = date.today().year

    sort = request.args.get("sort", "date", type=str).strip().lower()
    direction = request.args.get("dir", "desc", type=str).strip().lower()
    view = request.args.get("view", "complete", type=str).strip().lower()
    if view not in ("cash", "harbo", "complete"):
        view = "complete"

    allowed_sorts = {
        "date": "g.date",
        "location": "g.location",
        "game_type": "g.game_type",
        "buyin": "gr.buyin",
        "cashout": "gr.cashout",
        "profit": "gr.profit",
    }
    sort_sql = allowed_sorts.get(sort, "g.date")
    dir_sql = "ASC" if direction == "asc" else "DESC"

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT id, name
        FROM players
        WHERE id = ?;
        """,
        (player_id,),
    )
    player = cur.fetchone()

    if player is None:
        conn.close()
        return "השחקן לא נמצא", 404

    player = dict(player)
    log_activity("view_player_stats", player["name"])

    cur.execute(
        """
        WITH ranked_results AS (
            SELECT
                gr.player_id,
                gr.game_id,
                gr.profit,
                g.date,
                g.game_type,
                ROW_NUMBER() OVER (
                    PARTITION BY gr.player_id
                    ORDER BY g.date DESC, g.id DESC
                ) AS player_last_game_rn,
                ROW_NUMBER() OVER (
                    PARTITION BY gr.game_id
                    ORDER BY gr.profit DESC, p.name COLLATE NOCASE ASC
                ) AS position_in_game,
                COUNT(*) OVER (
                    PARTITION BY gr.game_id
                ) AS players_in_game
            FROM game_results gr
            JOIN games g ON g.id = gr.game_id
            JOIN players p ON p.id = gr.player_id
        ),
        totals AS (
            SELECT
                player_id,
                ROUND(COALESCE(SUM(profit), 0), 2) AS total_profit,
                COUNT(*) AS total_games
            FROM game_results
            WHERE player_id = ?
            GROUP BY player_id
        ),
        year_stats AS (
            SELECT
                gr.player_id,
                ROUND(COALESCE(SUM(gr.profit), 0), 2) AS year_profit,
                ROUND(COALESCE(AVG(gr.profit), 0), 2) AS year_avg,
                COUNT(*) AS year_games,
                SUM(CASE WHEN g.game_type = 'cash' THEN 1 ELSE 0 END) AS year_cash_games,
                SUM(CASE WHEN g.game_type = 'harbo' THEN 1 ELSE 0 END) AS year_harbo_games
            FROM game_results gr
            JOIN games g ON g.id = gr.game_id
            WHERE gr.player_id = ?
              AND substr(g.date, 1, 4) = ?
            GROUP BY gr.player_id
        ),
        last_game AS (
            SELECT
                rr.player_id,
                ROUND(rr.profit, 2) AS last_result,
                rr.date AS last_game_date,
                rr.position_in_game,
                rr.players_in_game
            FROM ranked_results rr
            WHERE rr.player_id = ?
              AND rr.player_last_game_rn = 1
        ),
        best_game AS (
            SELECT
                gr.player_id,
                ROUND(gr.profit, 2) AS best_profit,
                g.date AS best_profit_date,
                ROW_NUMBER() OVER (
                    PARTITION BY gr.player_id
                    ORDER BY gr.profit DESC, g.date DESC, g.id DESC
                ) AS rn
            FROM game_results gr
            JOIN games g ON g.id = gr.game_id
            WHERE gr.player_id = ?
        ),
        worst_game AS (
            SELECT
                gr.player_id,
                ROUND(gr.profit, 2) AS worst_profit,
                g.date AS worst_profit_date,
                ROW_NUMBER() OVER (
                    PARTITION BY gr.player_id
                    ORDER BY gr.profit ASC, g.date DESC, g.id DESC
                ) AS rn
            FROM game_results gr
            JOIN games g ON g.id = gr.game_id
            WHERE gr.player_id = ?
        )
        SELECT
            p.id,
            p.name,
            COALESCE(t.total_profit, 0) AS total_profit,
            COALESCE(t.total_games, 0) AS total_games,
            COALESCE(y.year_profit, 0) AS year_profit,
            COALESCE(y.year_avg, 0) AS year_avg,
            COALESCE(y.year_games, 0) AS year_games,
            COALESCE(y.year_cash_games, 0) AS year_cash_games,
            COALESCE(y.year_harbo_games, 0) AS year_harbo_games,
            lg.last_result,
            lg.last_game_date,
            bg.best_profit,
            bg.best_profit_date,
            wg.worst_profit,
            wg.worst_profit_date,
            CASE
                WHEN lg.position_in_game IS NOT NULL
                THEN CAST(lg.position_in_game AS TEXT) || ' מתוך ' || CAST(lg.players_in_game AS TEXT)
                ELSE '—'
            END AS last_position
        FROM players p
        LEFT JOIN totals t ON t.player_id = p.id
        LEFT JOIN year_stats y ON y.player_id = p.id
        LEFT JOIN last_game lg ON lg.player_id = p.id
        LEFT JOIN best_game bg ON bg.player_id = p.id AND bg.rn = 1
        LEFT JOIN worst_game wg ON wg.player_id = p.id AND wg.rn = 1
        WHERE p.id = ?;
        """,
        (player_id, player_id, str(current_year), player_id, player_id, player_id, player_id),
    )
    summary = cur.fetchone()
    summary = dict(summary) if summary else {}

    games_sql = f"""
        SELECT
            g.id AS game_id,
            g.date,
            g.location,
            g.game_type,
            gr.buyin,
            gr.cashout,
            gr.profit
        FROM game_results gr
        JOIN games g ON g.id = gr.game_id
        WHERE gr.player_id = ?
        ORDER BY {sort_sql} {dir_sql}, g.id DESC
    """
    cur.execute(games_sql, (player_id,))
    games = [dict(r) for r in cur.fetchall()]

    cash_sql = f"""
    SELECT
        g.id AS game_id,
        g.date,
        g.location,
        g.game_type,
        gr.buyin,
        gr.cashout,
        gr.profit
    FROM game_results gr
    JOIN games g ON g.id = gr.game_id
    WHERE gr.player_id = ?
      AND substr(g.date, 1, 4) = ?
      AND g.game_type = 'cash'
    ORDER BY {sort_sql} {dir_sql}, g.id DESC
    """

    cur.execute(cash_sql, (player_id, str(current_year)))
    games_2026_cash = [dict(r) for r in cur.fetchall()]

    harbo_sql = f"""
    SELECT
        g.id AS game_id,
        g.date,
        g.location,
        g.game_type,
        gr.buyin,
        gr.cashout,
        gr.profit
    FROM game_results gr
    JOIN games g ON g.id = gr.game_id
    WHERE gr.player_id = ?
      AND substr(g.date, 1, 4) = ?
      AND g.game_type = 'harbo'
    ORDER BY {sort_sql} {dir_sql}, g.id DESC
    """

    cur.execute(harbo_sql, (player_id, str(current_year)))
    games_2026_harbo = [dict(r) for r in cur.fetchall()]

    summary["year_cash_games"] = len(games_2026_cash)
    summary["year_harbo_games"] = len(games_2026_harbo)

    # ── Cash-only totals for the summary cards ──────────────────────────
    row = cur.execute(
        """
        SELECT
            ROUND(COALESCE(SUM(gr.profit), 0), 2) AS total_cash_profit
        FROM game_results gr
        JOIN games g ON g.id = gr.game_id
        WHERE gr.player_id = ? AND g.game_type = 'cash'
        """,
        (player_id,)
    ).fetchone()
    summary["total_cash_profit"] = row["total_cash_profit"] if row else 0

    row = cur.execute(
        """
        SELECT
            ROUND(COALESCE(SUM(gr.profit), 0), 2) AS year_cash_profit,
            ROUND(COALESCE(AVG(gr.profit), 0), 2) AS year_cash_avg
        FROM game_results gr
        JOIN games g ON g.id = gr.game_id
        WHERE gr.player_id = ?
          AND g.game_type = 'cash'
          AND substr(g.date, 1, 4) = ?
        """,
        (player_id, str(current_year))
    ).fetchone()
    summary["year_cash_profit"] = row["year_cash_profit"] if row else 0
    summary["year_cash_avg"]    = row["year_cash_avg"]    if row else 0


    best_game = None
    worst_game = None

    best_game = None
    worst_game = None

    if games:
        valid_games = [g for g in games if g["profit"] is not None]
        if valid_games:
            best_game = max(valid_games, key=lambda g: g["profit"])
            worst_game = min(valid_games, key=lambda g: g["profit"])

    summary["best_profit"] = best_game["profit"] if best_game else None
    summary["best_profit_date"] = best_game["date"] if best_game else None
    summary["worst_profit"] = worst_game["profit"] if worst_game else None
    summary["worst_profit_date"] = worst_game["date"] if worst_game else None

    conn.close()

    user = get_current_user()

    # Check if the player's linked user has opted into private stats
    conn2 = get_db_connection()
    linked = conn2.execute(
        "SELECT private_stats FROM users WHERE player_id = ?", (player_id,)
    ).fetchone()
    conn2.close()
    is_private = linked is not None and linked["private_stats"] == 1

    can_see_private = (
        not is_private
        or user is None  # shouldn't happen (login_required), but safe
        or user["role"] in ("admin", "magician")
        or user["player_id"] == player_id
    )

    # Is this user the owner of this player page?
    is_own_page = user is not None and user["player_id"] == player_id

    # ── Load private notes (only for own page) ────────────────────────
    general_note = ""
    game_notes = {}
    if is_own_page:
        conn_n = get_db_connection()
        notes_rows = conn_n.execute(
            "SELECT game_id, note FROM player_notes WHERE player_id = ?",
            (player_id,)
        ).fetchall()
        conn_n.close()
        for row in notes_rows:
            if row["game_id"] is None:
                general_note = row["note"]
            else:
                game_notes[row["game_id"]] = row["note"]

    subtitle = f'{summary["total_games"]} משחקים סה"כ - {summary["year_games"]} משחקים ב-{current_year}'

    # ── Year-grouped games for collapsible table ──────────────────────
    from collections import OrderedDict as _OD

    def _group_by_year(glist):
        by_date = sorted(glist, key=lambda g: (g.get("date", ""), g.get("game_id", 0)), reverse=True)
        od = _OD()
        for g in by_date:
            yr = g["date"][:4] if g.get("date") and len(str(g.get("date", ""))) >= 4 else "?"
            g["year"] = yr
            od.setdefault(yr, []).append(g)
        return list(od.items())

    games_cash_grouped     = _group_by_year([g for g in games if g.get("game_type") == "cash"])
    games_harbo_grouped    = _group_by_year([g for g in games if g.get("game_type") == "harbo"])
    games_complete_grouped = _group_by_year(games)
    # ── End year-grouping ─────────────────────────────────────────────

    # ── Analytics / Charts ─────────────────────────────────────────────
    _valid = [
        g for g in games
        if g.get("date") and len(str(g.get("date", ""))) >= 10
        and g.get("profit") is not None
        and g.get("game_type") == "cash"
    ]
    _sorted_asc = sorted(_valid, key=lambda g: (g.get("date", ""), g.get("game_id", 0)))

    _cumulative = 0.0
    _chart_data = []
    for _g in _sorted_asc:
        _cumulative += float(_g["profit"])
        _chart_data.append({
            "date": _g["date"][:10],
            "profit": round(float(_g["profit"])),
            "cumulative": round(_cumulative),
            "game_type": _g.get("game_type", ""),
        })

    _wins = sum(1 for g in _valid if float(g["profit"]) > 0)
    _total_count = len(_valid)
    win_rate = round(_wins / _total_count * 100) if _total_count > 0 else 0
    wins_count = _wins
    games_analytics_count = _total_count

    # Streak — from the most recent game backwards
    streak_count = 0
    streak_type = None
    for _g in sorted(_valid, key=lambda g: (g.get("date", ""), g.get("game_id", 0)), reverse=True):
        _p = float(_g["profit"])
        _gt = "win" if _p > 0 else ("loss" if _p < 0 else None)
        if _gt is None:
            continue
        if streak_type is None:
            streak_type = _gt
            streak_count = 1
        elif _gt == streak_type:
            streak_count += 1
        else:
            break

    # Monthly aggregation
    _monthly: dict[str, float] = {}
    for _g in _sorted_asc:
        _mk = _g["date"][:7]
        _monthly[_mk] = _monthly.get(_mk, 0.0) + float(_g["profit"])
    _monthly_data = [
        {"month": k, "profit": round(float(v))}
        for k, v in sorted(_monthly.items())
    ]

    chart_data_json = json.dumps(_chart_data, ensure_ascii=False)
    monthly_data_json = json.dumps(_monthly_data, ensure_ascii=False)
    # ── End Analytics ──────────────────────────────────────────────────

    return render_template(
        "player_detail.html",
        player=player,
        summary=summary,
        games=games,
        games_2026_cash=games_2026_cash,
        games_2026_harbo=games_2026_harbo,
        year=current_year,
        subtitle=subtitle,
        view=view,
        sort=sort,
        direction=direction,
        current_user=user,
        can_see_private=can_see_private,
        is_own_page=is_own_page,
        is_private=is_private,
        # year-grouped tables
        games_cash_grouped=games_cash_grouped,
        games_harbo_grouped=games_harbo_grouped,
        games_complete_grouped=games_complete_grouped,
        # analytics
        chart_data_json=chart_data_json,
        monthly_data_json=monthly_data_json,
        win_rate=win_rate,
        wins_count=wins_count,
        games_analytics_count=games_analytics_count,
        streak_count=streak_count,
        streak_type=streak_type,
        general_note=general_note,
        game_notes=game_notes,
    )


@bp.route("/players/<int:player_id>/note", methods=["POST"])
@login_required
def player_save_note(player_id):
    """Save (upsert) a private note for a player. Only the owner can write."""
    user = get_current_user()
    if user is None or user["player_id"] != player_id:
        abort(403)

    note = request.get_json(silent=True) or {}
    text = str(note.get("note", "")).strip()
    game_id_raw = note.get("game_id")
    game_id = int(game_id_raw) if game_id_raw is not None else None

    conn = get_db_connection()
    existing = conn.execute(
        "SELECT id FROM player_notes WHERE player_id = ? AND game_id IS ?",
        (player_id, game_id)
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE player_notes SET note = ?, updated_at = datetime('now') WHERE id = ?",
            (text, existing["id"])
        )
    else:
        conn.execute(
            "INSERT INTO player_notes (player_id, game_id, note) VALUES (?, ?, ?)",
            (player_id, game_id, text)
        )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@bp.route("/players/<int:player_id>/privacy", methods=["POST"])
@login_required
def player_toggle_privacy(player_id):
    user = get_current_user()
    if user is None or user["player_id"] != player_id:
        abort(403)
    new_val = 1 if request.form.get("private_stats") == "1" else 0
    conn = get_db_connection()
    conn.execute(
        "UPDATE users SET private_stats = ? WHERE player_id = ?",
        (new_val, player_id)
    )
    conn.commit()
    conn.close()
    return redirect(url_for("main.player_detail", player_id=player_id))
