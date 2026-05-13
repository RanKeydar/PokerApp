import sqlite3
from flask import Blueprint, render_template, request, redirect, url_for, session
from werkzeug.security import check_password_hash, generate_password_hash
from pokerapp.db.connection import get_db_connection

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

        if user and check_password_hash(user["password_hash"], password):
            if user["is_approved"] != 1:
                return render_template("login.html", error="המשתמש ממתין לאישור מנהל.")

            session["user_id"] = user["id"]
            session["role"] = user["role"]
            session["username"] = user["username"]
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
