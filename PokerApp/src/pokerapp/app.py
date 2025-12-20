from flask import Flask
from pathlib import Path

def create_app():
    # project root = .../PokerApp
    project_root = Path(__file__).resolve().parents[2]  # src/pokerapp/app.py -> src -> project root
    instance_path = project_root / "instance"
    instance_path.mkdir(parents=True, exist_ok=True)

    app = Flask(
        __name__,
        instance_path=str(instance_path),
        instance_relative_config=False,
    )

    app.config["SECRET_KEY"] = "Donluka77"
    app.config["DB_PATH"] = str(instance_path / "poker.db")

    from pokerapp.routes.auth import bp as auth_bp
    from pokerapp.routes.main import bp as main_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)

    return app
