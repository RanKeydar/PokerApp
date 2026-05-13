import sqlite3
import sys
from pathlib import Path


def init_db(db_path: str, schema_path: str) -> None:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        with open(schema_path, "r", encoding="utf-8") as f:
            conn.executescript(f.read())
        conn.commit()
    finally:
        conn.close()

    # Run incremental migrations so existing DBs stay up to date
    _run_migrations(Path(db_path))


def _run_migrations(db_path: Path) -> None:
    """Run all phase migrations in order (each is idempotent)."""
    scripts_dir = Path(__file__).resolve().parent.parent.parent.parent / "scripts"
    migration_files = [
        scripts_dir / "migrate_phase_b.py",
    ]
    for mig in migration_files:
        if mig.exists():
            # Import and run without polluting sys.argv
            import importlib.util
            spec = importlib.util.spec_from_file_location("migration", mig)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            mod.migrate(db_path)
