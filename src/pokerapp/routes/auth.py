import sqlite3
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from werkzeug.security import check_password_hash, generate_password_hash
from pokerapp.db.connection import get_db_connection
from pokerapp.services.auth import login_required

bp = Blueprint("auth", __name__)

@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT id, username, password_hash, role, is_approved FROM users WHERE username = ?;",
            (username,),
        )
        user = cur.fetchone()
        conn.close()

        print(f"DEBUG LOGIN: username={repr(username)} password={repr(password)} user_found={user is not None}")
        if user:
            print(f"DEBUG CHECK: {check_password_hash(user['password_hash'], password)}")
        if user and check_password_hash(user["password_hash"], password):
            if user["is_approved"] != 1:
                return render_template("login.html", error="המשתמש ממתין לאישור מנהל.")

            session["user_id"] = user["id"]
            session["role"] = user["role"]
            session["username"] = user["username"]
            session["_ga_login"] = True
            return redirect(url_for("main.home"))

        return render_template("login.html", error="שם משתמש או סיסמה שגויים")

    return render_template("login.html")


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


@bp.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        requested_role = request.form.get("requested_role", "player")

        if not username or not password:
            return render_template("signup.html", error="חובה למלא שם משתמש וסיסמה.")

        if requested_role not in ("player", "magician"):
            requested_role = "player"

        conn = get_db_connection()
        cur = conn.cursor()

        try:
            pw_hash = generate_password_hash(password)
            cur.execute(
                """
                INSERT INTO users (username, password_hash, role, is_approved)
                VALUES (?, ?, ?, 0);
                """,
                (username, pw_hash, requested_role),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            conn.close()
            return render_template("signup.html", error="שם המשתמש כבר קיים. נסה שם אחר.")

        conn.close()
        return render_template("signup.html", success="נשלחה בקשה! המשתמש יופעל לאחר אישור מנהל.")

    return render_template("signup.html")


@bp.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    error   = None
    success = None

    if request.method == "POST":
        old_pw   = request.form.get("old_password", "")
        new_pw   = request.form.get("new_password", "")
        confirm  = request.form.get("confirm_password", "")

        # ── Validation ───────────────────────────────────────────────────────
        if not old_pw or not new_pw or not confirm:
            error = "יש למלא את כל השדות."
        elif new_pw != confirm:
            error = "הסיסמה החדשה ואימות הסיסמה אינם תואמים."
        elif len(new_pw) < 6:
            error = "הסיסמה החדשה חייבת להכיל לפחות 6 תווים."
        elif old_pw == new_pw:
            error = "הסיסמה החדשה זהה לסיסמה הנוכחית."
        else:
            conn = get_db_connection()
            user = conn.execute(
                "SELECT id, password_hash FROM users WHERE id = ?",
                (session["user_id"],)
            ).fetchone()

            if not user or not check_password_hash(user["password_hash"], old_pw):
                error = "הסיסמה הנוכחית שגויה."
            else:
                conn.execute(
                    "UPDATE users SET password_hash = ? WHERE id = ?",
                    (generate_password_hash(new_pw), session["user_id"])
                )
                conn.commit()
                success = "הסיסמה עודכנה בהצלחה."
            conn.close()

    return render_template("change_password.html", error=error, success=success)
