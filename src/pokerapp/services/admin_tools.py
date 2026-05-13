from pathlib import Path
from flask import current_app

from pokerapp.db.connection import log_admin_action
from pokerapp.services.backup_service import backup_database
from pokerapp.services.import_service import discover_import_files


def get_admin_tools_status():
    db_path = Path(current_app.config["DB_PATH"])
    backup_dir = db_path.parent / "backups"

    backup_files = []
    if backup_dir.exists():
        backup_files = sorted(
            [p for p in backup_dir.glob("*.db") if p.is_file()],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

    latest_backup = backup_files[0] if backup_files else None

    raw_import_files = discover_import_files()
    import_files = []

    for item in raw_import_files:
        game_type = item["game_type"]
        year = item["year"]
        label_prefix = "קאש" if game_type == "cash" else "חרבו"

        import_files.append({
            "game_type": game_type,
            "year": year,
            "path": item["path"],
            "filename": item["filename"],
            "label": f"{label_prefix} {year}",
        })

    return {
        "latest_backup": latest_backup,
        "backup_count": len(backup_files),
        "import_files": import_files,
        "import_count": len(import_files),
    }


def run_backup_now():
    db_path = current_app.config["DB_PATH"]

    try:
        backup_path = backup_database(db_path)
        log_admin_action(
            action="backup_now",
            status="success",
            target_type="database",
            target_value=Path(backup_path).name,
            message="Backup created successfully",
        )
        return {
            "ok": True,
            "flash_category": "success",
            "message": f"הגיבוי נוצר בהצלחה: {Path(backup_path).name}",
        }
    except Exception as e:
        log_admin_action(
            action="backup_now",
            status="error",
            target_type="database",
            target_value=str(db_path),
            message=str(e),
        )
        return {
            "ok": False,
            "flash_category": "error",
            "message": f"שגיאה ביצירת גיבוי: {e}",
        }