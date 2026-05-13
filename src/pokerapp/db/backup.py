import sqlite3
from pathlib import Path
from datetime import datetime

def backup_database(db_path: str, backup_dir: str | None = None) -> str:
    source_path = Path(db_path)
    if backup_dir is None:
        backup_root = source_path.parent / "backups"
    else:
        backup_root = Path(backup_dir)

    backup_root.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = backup_root / f"{source_path.stem}-{timestamp}.db"

    src = sqlite3.connect(db_path, timeout=5)
    dst = sqlite3.connect(str(backup_path))

    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()

    return str(backup_path)