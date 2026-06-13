from flask import Flask, redirect, url_for, flash, request
from flask_login import current_user, logout_user
from sqlalchemy import text, inspect
from flasgger import Swagger
from datetime import datetime
import secrets
import string
from config import Config
from extensions import db, login_manager, csrf, limiter, jwt
from models import User, Employee, Department, AppConfig

app = Flask(__name__)
app.config.from_object(Config)

# Swagger configuration
app.config['SWAGGER'] = {
    'title': 'Robo Pirate Payroll API',
    'uiversion': 3,
    'specs_route': '/api/docs/',
    'openapi': '3.0.0',
    'info': {
        'title': 'Robo Pirate Payroll API',
        'version': '1.0.0',
        'description': 'JWT-authenticated REST API for employee attendance, leaves, payroll, and holidays.',
        'contact': {
            'name': 'Robo Pirate Support',
            'email': 'support@robopirate.in'
        }
    },
    'securityDefinitions': {
        'Bearer': {
            'type': 'apiKey',
            'name': 'Authorization',
            'in': 'header',
            'description': 'JWT Authorization header using the Bearer scheme. Example: "Bearer {token}"'
        }
    },
    'security': [
        {
            'Bearer': []
        }
    ]
}

db.init_app(app)
login_manager.init_app(app)
jwt.init_app(app)
login_manager.login_view = 'auth.login'
login_manager.login_message = 'Please log in to access this page.'
login_manager.login_message_category = 'warning'


@app.context_processor
def inject_now():
    """Make datetime.now() available as `now` in all templates."""
    return {'now': datetime.now}


@app.template_filter('mask_pii')
def mask_pii(value):
    """Mask sensitive personal identifiers in templates and exports."""
    if not value:
        return ''
    s = str(value).strip().replace(' ', '')
    n = len(s)
    if n == 10 and s.isdigit():
        # Mobile number: 98****3210
        return s[:2] + '****' + s[-4:]
    if n == 10 and s[:2].isalpha() and s[-1].isalpha():
        # PAN: ABCDE1234F -> AB****34F
        return s[:2] + '****' + s[-4:]
    if n == 12 and s.isdigit():
        # Aadhar: 123456789012 -> 1234 **** ****
        return s[:4] + ' **** ****'
    if n > 4:
        # Bank account / generic long number
        return s[:2] + '*' * (n - 4) + s[-2:]
    return '*' * n

csrf.init_app(app)
limiter.init_app(app)

# Load persisted config after app context is available
_persisted_config_loaded = False

@app.before_request
def load_persisted_config():
    global _persisted_config_loaded
    if not _persisted_config_loaded:
        persisted_key = AppConfig.get('FAST2SMS_API_KEY')
        if persisted_key:
            app.config['FAST2SMS_API_KEY'] = persisted_key
        _persisted_config_loaded = True


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


@app.before_request
def restrict_employee_to_portal():
    """Prevent employee portal users from accessing admin routes."""
    if current_user.is_authenticated and not current_user.is_admin:
        allowed = ('/portal', '/employee', '/static', '/api', '/logout')
        if request.path != '/' and not request.path.startswith(allowed):
            return redirect(url_for('portal.portal_dashboard'))


# ─── Helpers (imported from services/; do NOT duplicate here) ───────────────

# NOTE: get_working_days_in_month, count_working_days_between,
# calculate_payroll, and haversine_distance are defined in
# services/attendance_service.py and services/payroll_service.py.
# Keep this file clean — import from there instead.

# ─── Blueprints ──────────────────────────────────────────────────────────────

def register_blueprints():
    from blueprints.auth import bp as auth_bp
    from blueprints.admin import bp as admin_bp
    from blueprints.portal import bp as portal_bp
    from blueprints.api import bp as api_bp
    from blueprints.jwt_auth import bp as jwt_auth_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(portal_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(jwt_auth_bp)


register_blueprints()

# Initialize Swagger UI for API documentation
swagger = Swagger(app)


# ─── DB Init ─────────────────────────────────────────────────────────────────

def safe_migrate():
    """Add new columns to existing tables without destroying data."""
    with db.engine.connect() as conn:
        inspector = inspect(db.engine)

        # Attendance table: GPS proof columns + location_type
        if db.engine.dialect.name == 'sqlite':
            result = conn.execute(text("PRAGMA table_info(attendance)"))
            att_cols = {row[1] for row in result}
        else:
            att_cols = {c['name'] for c in inspector.get_columns('attendance')}
        for col, col_def in [
            ('gps_lat', 'REAL'),
            ('gps_lng', 'REAL'),
            ('gps_verified', 'INTEGER DEFAULT 0'),
            ('admin_override', 'INTEGER DEFAULT 0'),
            ('location_type', 'VARCHAR(20) DEFAULT \'school\''),
        ]:
            if col not in att_cols:
                conn.execute(text(f"ALTER TABLE attendance ADD COLUMN {col} {col_def}"))

        # Users table: employee_id for portal access + password-change enforcement
        if db.engine.dialect.name == 'sqlite':
            result = conn.execute(text("PRAGMA table_info(users)"))
            user_cols = {row[1] for row in result}
        else:
            user_cols = {c['name'] for c in inspector.get_columns('users')}
        if 'employee_id' not in user_cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN employee_id INTEGER REFERENCES employees(id)"))
        if 'must_change_password' not in user_cols:
            if db.engine.dialect.name == 'sqlite':
                conn.execute(text("ALTER TABLE users ADD COLUMN must_change_password INTEGER DEFAULT 0"))
            else:
                conn.execute(text("ALTER TABLE users ADD COLUMN must_change_password BOOLEAN DEFAULT FALSE"))

        # Employees table: admin approval for self-registration
        if db.engine.dialect.name == 'sqlite':
            result = conn.execute(text("PRAGMA table_info(employees)"))
            emp_cols = {row[1] for row in result}
        else:
            emp_cols = {c['name'] for c in inspector.get_columns('employees')}
        if 'is_approved' not in emp_cols:
            conn.execute(text("ALTER TABLE employees ADD COLUMN is_approved INTEGER DEFAULT 0"))

        # Schools table: location_type, working hours, and shift timings
        if db.engine.dialect.name == 'sqlite':
            result = conn.execute(text("PRAGMA table_info(schools)"))
            school_cols = {row[1] for row in result}
        else:
            school_cols = {c['name'] for c in inspector.get_columns('schools')}
        if 'location_type' not in school_cols:
            conn.execute(text("ALTER TABLE schools ADD COLUMN location_type VARCHAR(30) DEFAULT 'School'"))
        if 'working_hours_per_day' not in school_cols:
            if db.engine.dialect.name == 'sqlite':
                conn.execute(text("ALTER TABLE schools ADD COLUMN working_hours_per_day REAL DEFAULT 8.0"))
            else:
                conn.execute(text("ALTER TABLE schools ADD COLUMN working_hours_per_day FLOAT DEFAULT 8.0"))
        if 'shift_start' not in school_cols:
            conn.execute(text("ALTER TABLE schools ADD COLUMN shift_start VARCHAR(5)"))
        if 'shift_end' not in school_cols:
            conn.execute(text("ALTER TABLE schools ADD COLUMN shift_end VARCHAR(5)"))
        if 'grace_minutes' not in school_cols:
            if db.engine.dialect.name == 'sqlite':
                conn.execute(text("ALTER TABLE schools ADD COLUMN grace_minutes INTEGER DEFAULT 15"))
            else:
                conn.execute(text("ALTER TABLE schools ADD COLUMN grace_minutes INTEGER DEFAULT 15"))
        if 'lunch_minutes' not in school_cols:
            if db.engine.dialect.name == 'sqlite':
                conn.execute(text("ALTER TABLE schools ADD COLUMN lunch_minutes INTEGER DEFAULT 60"))
            else:
                conn.execute(text("ALTER TABLE schools ADD COLUMN lunch_minutes INTEGER DEFAULT 60"))

        # Attendance table: late / early-exit minute tracking
        if db.engine.dialect.name == 'sqlite':
            result = conn.execute(text("PRAGMA table_info(attendance)"))
            att_cols = {row[1] for row in result}
        else:
            att_cols = {c['name'] for c in inspector.get_columns('attendance')}
        for col, col_def in [
            ('late_minutes', 'INTEGER DEFAULT 0'),
            ('early_minutes', 'INTEGER DEFAULT 0'),
        ]:
            if col not in att_cols:
                conn.execute(text(f"ALTER TABLE attendance ADD COLUMN {col} {col_def}"))

        # Payroll table: professional tax deduction
        if db.engine.dialect.name == 'sqlite':
            result = conn.execute(text("PRAGMA table_info(payrolls)"))
            payroll_cols = {row[1] for row in result}
        else:
            payroll_cols = {c['name'] for c in inspector.get_columns('payrolls')}
        if 'pt_deduction' not in payroll_cols:
            if db.engine.dialect.name == 'sqlite':
                conn.execute(text("ALTER TABLE payrolls ADD COLUMN pt_deduction REAL DEFAULT 0.0"))
            else:
                conn.execute(text("ALTER TABLE payrolls ADD COLUMN pt_deduction FLOAT DEFAULT 0.0"))

        conn.commit()


def sync_postgres_sequences():
    """Reset PostgreSQL SERIAL sequences to the current max(id) to avoid duplicate PK errors."""
    if db.engine.dialect.name != 'postgresql':
        return
    tables = [
        'users', 'employees', 'departments', 'schools', 'attendance', 'leaves',
        'leave_balances', 'advances', 'payrolls', 'holidays', 'password_resets',
        'attendance_locks', 'app_config', 'audit_logs', 'school_schedules',
    ]
    with db.engine.connect() as conn:
        for table in tables:
            seq = f'{table}_id_seq'
            try:
                conn.execute(text(
                    f"SELECT setval('{seq}', COALESCE((SELECT MAX(id) FROM {table}), 1), "
                    f"(SELECT COUNT(*) > 0 FROM {table}))"
                ))
            except Exception:
                pass
        conn.commit()


def init_db():
    with app.app_context():
        db.create_all()
        safe_migrate()
        sync_postgres_sequences()

        if not app.config.get('TESTING') and not User.query.filter_by(username='admin').first():
            admin = User(username='admin', is_admin=True, must_change_password=True)
            initial_password = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(12))
            admin.set_password(initial_password)
            db.session.add(admin)
            print(f"\n{'='*60}")
            print("INITIAL ADMIN PASSWORD (save this — shown only once):")
            print(f"  Username: admin")
            print(f"  Password: {initial_password}")
            print(f"{'='*60}\n")

        for dept_name in ['HR', 'Finance', 'Operations', 'Sales', 'IT']:
            if not Department.query.filter_by(name=dept_name).first():
                db.session.add(Department(name=dept_name))

        db.session.commit()
        print("Database initialized.")
        print("Employee portal: /portal/login  (phone + password set by admin)")


# Initialize database on startup (works for both local and production)
try:
    init_db()
except Exception as e:
    print(f'DB init warning: {e}')

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
