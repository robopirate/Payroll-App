"""SQLite database backup script for PayrollPro.

Run from the project root:
    python scripts/backup_db.py

Backs up the SQLite DB configured in config.py:Config.DB_PATH to:
    scripts/backups/payroll_backup_YYYYMMDD_HHMMSS.db

Keeps only the latest 10 backups.
"""
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

# Allow running as `python scripts/backup_db.py` from the project root.
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from config import Config


def main():
    db_uri = Config.SQLALCHEMY_DATABASE_URI or ''

    if not db_uri.startswith('sqlite'):
        print('PostgreSQL detected — use pg_dump instead.')
        sys.exit(0)

    source_db = Path(Config.DB_PATH)
    if not source_db.exists():
        print(f'Source database not found: {source_db}')
        sys.exit(1)

    # backups/ folder lives next to this script
    script_dir = Path(__file__).resolve().parent
    backups_dir = script_dir / 'backups'
    backups_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_filename = f'payroll_backup_{timestamp}.db'
    backup_path = backups_dir / backup_filename

    shutil.copy2(str(source_db), str(backup_path))

    # Keep only the last 10 backups (sort newest first by filename timestamp)
    backup_files = sorted(
        [f for f in backups_dir.iterdir() if f.is_file() and f.name.startswith('payroll_backup_') and f.name.endswith('.db')],
        key=lambda f: f.name,
        reverse=True,
    )
    for old_backup in backup_files[10:]:
        old_backup.unlink()
        print(f'Removed old backup: {old_backup.name}')

    print(f'Backup created: {backup_path}')


if __name__ == '__main__':
    main()
