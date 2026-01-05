import os
from flask import Flask
from pathlib import Path
from pokerapp.db.init_db import init_db   # ⬅️ הוספה


def create_app():
    project_root = Path(__file__).resolve().parents[2]
    instance_path = project_root / "instance"
    instance_path.mkdir(parents=True, exist_ok=True)

    app = Flask(
        __name__,
        instance_path=str(instance_path),
        instance_relative_config=False,
        static_folder=str(project_root / "static"),   # ✅ הוספה
        static_url_path="/static"                     # (אופציונלי, אבל נחמד)
    )

    @app.template_filter("int0")
    def int0(v):
        if v is None:
            return 0
        try:
            return int(round(float(v)))
        except Exception:
            return v

    app.config['STATIC_VER'] = 2  

    css_path = project_root / "static" / "css" / "style.css"
    app.config["STATIC_VER"] = int(css_path.stat().st_mtime) if css_path.exists() else 1

    app.config["SECRET_KEY"] = os.environ["SECRET_KEY"]
    app.config["DB_PATH"] = "/data/poker.db"

    schema_path = Path(__file__).resolve().parent / "db" / "schema.sql"
    init_db(app.config["DB_PATH"], str(schema_path))

    from pokerapp.db.seed_admin import ensure_admin
    ensure_admin(app.config["DB_PATH"])


    from pokerapp.routes.auth import bp as auth_bp
    from pokerapp.routes.main import bp as main_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)

    return app
