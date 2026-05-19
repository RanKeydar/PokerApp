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

    # ── Phase B: external script (only if present) ─────────────────────
    scripts_dir = Path(__file__).resolve().parent.parent.parent.parent / "scripts"
    phase_b = scripts_dir / "migrate_phase_b.py"
    if phase_b.exists():
        import importlib.util
        spec = importlib.util.spec_from_file_location("migration", phase_b)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.migrate(db_path)

    # ── Phase C inline migrations (idempotent) ──────────────────────────
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS player_notes (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                player_id  INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
                game_id    INTEGER REFERENCES games(id) ON DELETE CASCADE,
                note       TEXT    NOT NULL DEFAULT '',
                updated_at TEXT    NOT NULL DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_player_notes_player
                ON player_notes(player_id);
        """)
        conn.commit()
    finally:
        conn.close()
