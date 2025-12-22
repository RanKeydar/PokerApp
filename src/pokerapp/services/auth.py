from functools import wraps
from flask import session, redirect, url_for, abort
from pokerapp.db.connection import get_db_connection

def get_current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, username, role FROM users WHERE id = ?;", (uid,))
    user = cur.fetchone()
    conn.close()
    return user

def login_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("auth.login"))
        return view_func(*args, **kwargs)
    return wrapper

def role_required(*allowed_roles):
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(*args, **kwargs):
            user = get_current_user()
            if user is None:
                return redirect(url_for("auth.login"))
            if user["role"] not in allowed_roles:
                abort(403)
            return view_func(*args, **kwargs)
        return wrapper
    return decorator
