from flask import Flask, redirect, url_for, flash, request
from flask_login import current_user, logout_user
from sqlalchemy import text
from flasgger import Swagger
from datetime import datetime
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
    if db.engine.dialect.name != 'sqlite':
        return  # PostgreSQL handles schema via create_all/migrations
    with db.engine.connect() as conn:
        # Attendance table: GPS proof columns + location_type
        result = conn.execute(text("PRAGMA table_info(attendance)"))
        att_cols = {row[1] for row in result}
        for col, col_def in [
            ('gps_lat', 'REAL'),
            ('gps_lng', 'REAL'),
            ('gps_verified', 'INTEGER DEFAULT 0'),
            ('admin_override', 'INTEGER DEFAULT 0'),
            ('location_type', 'VARCHAR(20) DEFAULT \'school\''),
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

        # Schools table: location_type
        result = conn.execute(text("PRAGMA table_info(schools)"))
        school_cols = {row[1] for row in result}
        if 'location_type' not in school_cols:
            conn.execute(text("ALTER TABLE schools ADD COLUMN location_type VARCHAR(30) DEFAULT 'School'"))

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
        print("Employee portal: /portal/login  (phone + password set by admin)")


# Initialize database on startup (works for both local and production)
try:
    init_db()
except Exception as e:
    print(f'DB init warning: {e}')

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
