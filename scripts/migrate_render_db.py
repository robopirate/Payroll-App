"""Idempotent database migration script for PayrollPro.

This script adds missing columns to existing tables so that older SQLite or
PostgreSQL databases stay in sync with the current SQLAlchemy models.

It is safe to run multiple times — each column is only added if it does not
already exist.

Usage:

    # Local SQLite / PostgreSQL
    python scripts/migrate_render_db.py

    # Render PostgreSQL (set DATABASE_URL in the environment first)
    # Via Render Dashboard → Shell:
    export DATABASE_URL="postgresql://user:pass@host:port/dbname"
    python scripts/migrate_render_db.py

    # Or as a Render one-off job with the start command:
    #   python scripts/migrate_render_db.py
"""
import sys
from pathlib import Path

# Allow running as `python scripts/migrate_render_db.py` from the project root.
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import create_engine, inspect, text

from config import Config


# Table -> {column_name: (sqlite_definition, postgres_definition)}
# Each definition must include the DEFAULT value.
EXPECTED_COLUMNS = {
    'employees': {
        'is_approved': ("INTEGER DEFAULT 0", "BOOLEAN DEFAULT FALSE"),
        'employee_type': ("VARCHAR(20) DEFAULT 'full_time'", "VARCHAR(20) DEFAULT 'full_time'"),
    },
    'users': {
        'employee_id': ("INTEGER", "INTEGER"),
        'must_change_password': ("INTEGER DEFAULT 0", "BOOLEAN DEFAULT FALSE"),
        'role': ("VARCHAR(20) DEFAULT 'viewer'", "VARCHAR(20) DEFAULT 'viewer'"),
    },
    'schools': {
        'location_type': ("VARCHAR(30) DEFAULT 'School'", "VARCHAR(30) DEFAULT 'School'"),
        'working_hours_per_day': ("REAL DEFAULT 8.0", "FLOAT DEFAULT 8.0"),
        'shift_start': ("VARCHAR(5)", "VARCHAR(5)"),
        'shift_end': ("VARCHAR(5)", "VARCHAR(5)"),
        'grace_minutes': ("INTEGER DEFAULT 15", "INTEGER DEFAULT 15"),
        'lunch_minutes': ("INTEGER DEFAULT 60", "INTEGER DEFAULT 60"),
    },
    'attendance': {
        'gps_lat': ("REAL", "FLOAT"),
        'gps_lng': ("REAL", "FLOAT"),
        'gps_verified': ("INTEGER DEFAULT 0", "BOOLEAN DEFAULT FALSE"),
        'admin_override': ("INTEGER DEFAULT 0", "BOOLEAN DEFAULT FALSE"),
        'location_type': ("VARCHAR(20) DEFAULT 'school'", "VARCHAR(20) DEFAULT 'school'"),
        'late_minutes': ("INTEGER DEFAULT 0", "INTEGER DEFAULT 0"),
        'early_minutes': ("INTEGER DEFAULT 0", "INTEGER DEFAULT 0"),
    },
    'payrolls': {
        'pt_deduction': ("REAL DEFAULT 0.0", "FLOAT DEFAULT 0.0"),
        'lwf_deduction': ("REAL DEFAULT 0.0", "FLOAT DEFAULT 0.0"),
        'tds_deduction': ("REAL DEFAULT 0.0", "FLOAT DEFAULT 0.0"),
        'tax_regime': ("VARCHAR(10) DEFAULT 'new'", "VARCHAR(10) DEFAULT 'new'"),
    },
}


def _get_existing_columns(engine, table_name):
    """Return a set of existing column names for the given table."""
    inspector = inspect(engine)
    if not inspector.has_table(table_name):
        return set()
    return {col['name'] for col in inspector.get_columns(table_name)}


def main():
    database_uri = Config.SQLALCHEMY_DATABASE_URI
    if not database_uri:
        print('No SQLALCHEMY_DATABASE_URI configured.')
        sys.exit(1)

    engine = create_engine(database_uri)
    dialect = engine.dialect.name

    if dialect == 'sqlite':
        type_key = 0
    elif dialect == 'postgresql':
        type_key = 1
    else:
        print(f'Unsupported dialect: {dialect}')
        sys.exit(1)

    checked = 0
    added = 0

    with engine.connect() as conn:
        for table_name, columns in EXPECTED_COLUMNS.items():
            existing = _get_existing_columns(engine, table_name)
            for column_name, definitions in columns.items():
                checked += 1
                if column_name in existing:
                    continue
                col_def = definitions[type_key]
                sql = f'ALTER TABLE {table_name} ADD COLUMN {column_name} {col_def}'
                conn.execute(text(sql))
                added += 1
                print(f'Added: {table_name}.{column_name}')
        conn.commit()

    print(f'Checked {checked} columns, added {added} new columns.')


if __name__ == '__main__':
    main()
