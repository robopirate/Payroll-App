"""Migrate Payroll data from PythonAnywhere SQLite to Render PostgreSQL.

Run this on PythonAnywhere Bash:

    cd ~/Payroll-App
    source venv/bin/activate
    export DATABASE_URL='postgresql://payroll_db_h2z2_user:c065FrxtmWof42365M3fLU4XFBk7qgSt@dpg-d8lut9r7uimc73eg49ig-a.oregon-postgres.render.com/payroll_db_h2z2'
    python scripts/migrate_pa_to_render.py

It reads the local ~/payroll.db file and copies everything to Render Postgres.
"""
import os
import sys

SQLITE_PATH = os.path.expanduser('~/payroll.db')
DATABASE_URL = os.environ.get('DATABASE_URL')

if not DATABASE_URL:
    print("Error: Set DATABASE_URL environment variable.")
    sys.exit(1)

if not os.path.exists(SQLITE_PATH):
    print(f"Error: SQLite file not found at {SQLITE_PATH}")
    sys.exit(1)

# Convert URL for SQLAlchemy depending on available driver
try:
    import psycopg2
    driver = 'postgresql+psycopg2'
except ImportError:
    driver = 'postgresql+psycopg'

pg_url = DATABASE_URL
if pg_url.startswith('postgres://'):
    pg_url = pg_url.replace('postgres://', f'{driver}://', 1)
elif pg_url.startswith('postgresql://'):
    pg_url = pg_url.replace('postgresql://', f'{driver}://', 1)

from sqlalchemy import create_engine, text, inspect

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import app
from extensions import db

TABLE_ORDER = [
    'departments',
    'schools',
    'employees',
    'users',
    'attendance',
    'leaves',
    'leave_balances',
    'advances',
    'payrolls',
    'holidays',
    'school_schedules',
    'audit_logs',
    'password_resets',
    'attendance_locks',
    'employee_schools',
    'app_config',
]

DEFAULTS = {
    'employees': {'is_approved': True},
    'schools': {'location_type': 'School'},
    'attendance': {'location_type': 'school'},
}


def main():
    sqlite_engine = create_engine(f'sqlite:///{SQLITE_PATH}')
    pg_engine = create_engine(pg_url)

    with app.app_context():
        db.drop_all()
        db.create_all()
        print("Created PostgreSQL tables from current models.")

    pg_conn = pg_engine.connect()
    sqlite_conn = sqlite_engine.connect()

    for table in TABLE_ORDER:
        result = sqlite_conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name=:name"),
            {'name': table}
        )
        if not result.fetchone():
            print(f"Skipping {table}: not in SQLite")
            continue

        if not inspect(pg_engine).has_table(table):
            print(f"Skipping {table}: not in current Postgres schema")
            continue

        rows = sqlite_conn.execute(text(f'PRAGMA table_info({table})')).fetchall()
        source_cols = [row[1] for row in rows]

        target_col_info = {c['name']: c for c in inspect(pg_engine).get_columns(table)}
        target_cols = list(target_col_info.keys())
        boolean_cols = {name for name, info in target_col_info.items() if str(info['type']).lower() == 'boolean'}

        common_cols = [c for c in source_cols if c in target_cols]
        missing_defaults = DEFAULTS.get(table, {})

        data = sqlite_conn.execute(text(f'SELECT {", ".join(common_cols)} FROM {table}')).fetchall()
        if not data:
            print(f"Copied 0 rows into {table}")
            continue

        insert_cols = common_cols + list(missing_defaults.keys())
        placeholders = ', '.join([f':{c}' for c in insert_cols])
        insert_sql = f'INSERT INTO {table} ({", ".join(insert_cols)}) VALUES ({placeholders})'

        count = 0
        for row in data:
            row_dict = dict(zip(common_cols, row))
            for col in boolean_cols:
                if col in row_dict and row_dict[col] is not None:
                    row_dict[col] = bool(row_dict[col])
            for col, val in missing_defaults.items():
                row_dict[col] = val
            pg_conn.execute(text(insert_sql), row_dict)
            count += 1

        pg_conn.commit()
        print(f"Copied {count} rows into {table}")

    sqlite_conn.close()
    pg_conn.close()
    print("Migration complete.")


if __name__ == '__main__':
    main()
