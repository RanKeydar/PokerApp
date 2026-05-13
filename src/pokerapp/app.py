import os
from flask import Flask
from pathlib import Path
from pokerapp.db.init_db import init_db   # ⬅️ הוספה
from flask_wtf.csrf import CSRFProtect
from pokerapp.db.connection import ensure_admin_audit_log_table
from datetime import datetime

csrf = CSRFProtect()

HEBREW_MONTHS = {
    1: "ינואר",
    2: "פברואר",
    3: "מרץ",
    4: "אפריל",
    5: "מאי",
    6: "יוני",
    7: "יולי",
    8: "אוגוסט",
    9: "ספטמבר",
    10: "אוקטובר",
    11: "נובמבר",
    12: "דצמבר",
}

def format_hebrew_date(date_str):
    if not date_str:
        return "—"

    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return f"{dt.day} ב{HEBREW_MONTHS[dt.month]}, {dt.year}"
    except (ValueError, TypeError):
        return date_str

def create_app():
    project_root = Path(__file__).resolve().parents[2]
    instance_path = project_root / "instance"
    instance_path.mkdir(parents=True, exist_ok=True)

    app = Flask(
        __name__,
        instance_path=str(instance_path),
        instance_relative_config=False,
        static_folder=str(project_root / "static"),
        static_url_path="/static"
    )

    @app.template_filter("hedate")
    def hedate_filter(date_value):
        if not date_value:
            return ""

        try:
            s = str(date_value).strip()
            if " " in s:
                s = s.split(" ", 1)[0]

            if "T" in s:
                s = s.split("T", 1)[0]

            year, month, day = s.split("-")
            return f"{day}.{month}.{year[-2:]}"
        except Exception:
            return str(date_value)


    app.config['STATIC_VER'] = 2

    css_path = project_root / "static" / "css" / "style.css"
    app.config["STATIC_VER"] = int(css_path.stat().st_mtime) if css_path.exists() else 1

    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-key")
    app.config["WTF_CSRF_ENABLED"] = True
    csrf.init_app(app)

    db_path = os.environ.get("DB_PATH", str(instance_path / "poker.db"))
    app.config["DB_PATH"] = db_path

    schema_path = Path(__file__).resolve().parent / "db" / "schema.sql"
    init_db(app.config["DB_PATH"], str(schema_path))

    from pokerapp.db.connection import ensure_admin_audit_log_table
    with app.app_context():
        ensure_admin_audit_log_table()

    from pokerapp.db.seed_admin import ensure_admin
    ensure_admin(app.config["DB_PATH"])

    from pokerapp.routes.auth import bp as auth_bp
    from pokerapp.routes.main import bp as main_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)

    return app