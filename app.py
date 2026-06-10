from flask import Flask, redirect, url_for, flash, request
from flask_login import current_user, logout_user
from sqlalchemy import text
from config import Config
from extensions import db, login_manager, csrf, limiter
from models import User, Employee, Department, AppConfig

app = Flask(__name__)
app.config.from_object(Config)

db.init_app(app)
login_manager.init_app(app)
login_manager.login_view = 'auth.login'
login_manager.login_message = 'Please log in to access this page.'
login_manager.login_message_category = 'warning'

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

    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(portal_bp)
    app.register_blueprint(api_bp)


register_blueprints()


# ─── DB Init ─────────────────────────────────────────────────────────────────

def safe_migrate():
    """Add new columns to existing tables without destroying data."""
    if db.engine.dialect.name != 'sqlite':
        return  # PostgreSQL handles schema via create_all/migrations
    with db.engine.connect() as conn:
        # Attendance table: GPS proof columns
        result = conn.execute(text("PRAGMA table_info(attendance)"))
        att_cols = {row[1] for row in result}
        for col, col_def in [
            ('gps_lat', 'REAL'),
            ('gps_lng', 'REAL'),
            ('gps_verified', 'INTEGER DEFAULT 0'),
            ('admin_override', 'INTEGER DEFAULT 0'),
        ]:
            if col not in att_cols:
                conn.execute(text(f"ALTER TABLE attendance ADD COLUMN {col} {col_def}"))

        # Users table: employee_id for portal access
        result = conn.execute(text("PRAGMA table_info(users)"))
        user_cols = {row[1] for row in result}
        if 'employee_id' not in user_cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN employee_id INTEGER REFERENCES employees(id)"))

        # Employees table: admin approval for self-registration
        result = conn.execute(text("PRAGMA table_info(employees)"))
        emp_cols = {row[1] for row in result}
        if 'is_approved' not in emp_cols:
            conn.execute(text("ALTER TABLE employees ADD COLUMN is_approved INTEGER DEFAULT 0"))

        conn.commit()


def init_db():
    with app.app_context():
        db.create_all()
        safe_migrate()

        if not User.query.filter_by(username='admin').first():
            admin = User(username='admin', is_admin=True)
            admin.set_password('admin123')
            db.session.add(admin)

        for dept_name in ['HR', 'Finance', 'Operations', 'Sales', 'IT']:
            if not Department.query.filter_by(name=dept_name).first():
                db.session.add(Department(name=dept_name))

        db.session.commit()
        print("Database initialized.")
        print("Admin login: admin / admin123")
        print("Employee portal: /portal/login  (phone + password set by admin)")


# Initialize database on startup (works for both local and production)
try:
    init_db()
except Exception as e:
    print(f'DB init warning: {e}')

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
