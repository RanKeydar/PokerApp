from flask import Blueprint, render_template, request, redirect, url_for, abort
from pokerapp.services.auth import login_required, role_required, get_current_user
from pokerapp.db.connection import get_db_connection
from pokerapp.services.game_queries import get_top_players, get_recent_games

bp = Blueprint("main", __name__)


# ------------------------------
# מסך ראשי
# ------------------------------
@bp.route("/")
@login_required
def home():
    cash_top_players = get_top_players("cash", 5)
    cash_recent_games = get_recent_games("cash", 5)

    harbo_top_players = get_top_players("harbo", 5)
    harbo_recent_games = get_recent_games("harbo", 5)

    return render_template(
        "home.html",
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
