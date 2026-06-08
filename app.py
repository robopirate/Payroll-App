from flask import Flask, redirect, url_for, flash, request
from flask_login import current_user, logout_user
from sqlalchemy import text
from config import Config
from extensions import db, login_manager, csrf, limiter
from decorators import portal_required
from models import User, Employee, Department, AppConfig
from services.attendance_service import get_working_days_in_month, count_working_days_between, haversine_distance
from services.payroll_service import calculate_payroll

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


# ─── Helpers ─────────────────────────────────────────────────────────────────

def get_working_days_in_month(year, month):
    _, days_in_month = calendar.monthrange(year, month)
    first_day = date(year, month, 1)
    last_day = date(year, month, days_in_month)
    holidays = {h.date for h in Holiday.query.filter(
        Holiday.date >= first_day,
        Holiday.date <= last_day,
        Holiday.is_active == True
    ).all()}
    working = 0
    for d in range(1, days_in_month + 1):
        current_date = date(year, month, d)
        if current_date.weekday() < 6 and current_date not in holidays:  # Mon-Sat, excluding holidays
            working += 1
    return working


def count_working_days_between(start_date, end_date):
    """Count working days (Mon-Sat) between two dates, excluding holidays."""
    holidays = {h.date for h in Holiday.query.filter(
        Holiday.date >= start_date,
        Holiday.date <= end_date,
        Holiday.is_active == True
    ).all()}
    days = 0
    current = start_date
    while current <= end_date:
        if current.weekday() < 6 and current not in holidays:
            days += 1
        current += timedelta(days=1)
    return days


def calculate_payroll(employee, month, year):
    working_days = get_working_days_in_month(year, month)
    attendances = Attendance.query.filter_by(employee_id=employee.id).filter(
        db.func.strftime('%Y', Attendance.date) == str(year),
        db.func.strftime('%m', Attendance.date) == f"{month:02d}"
    ).all()

    present_days = 0.0
    overtime_hours = 0.0
    for att in attendances:
        if att.status == 'present':
            present_days += 1.0
        elif att.status == 'half_day':
            present_days += 0.5
        elif att.status == 'overtime':
            present_days += 1.0
        elif att.status == 'leave':
            present_days += 1.0
        overtime_hours += (att.overtime_hours or 0.0)

    # Also count approved leave days that may not have attendance records
    approved_leaves = Leave.query.filter_by(
        employee_id=employee.id, status='approved'
    ).filter(
        db.func.strftime('%Y', Leave.start_date) == str(year),
        db.func.strftime('%m', Leave.start_date) == f"{month:02d}"
    ).all()
    leave_days_in_month = 0.0
    for leave in approved_leaves:
        # Clip leave range to this month
        month_start = date(year, month, 1)
        _, dim = calendar.monthrange(year, month)
        month_end = date(year, month, dim)
        start = max(leave.start_date, month_start)
        end = min(leave.end_date, month_end)
        if start <= end:
            leave_days_in_month += count_working_days_between(start, end)
    present_days += leave_days_in_month

    daily_rate = employee.basic_salary / working_days if working_days > 0 else 0
    earned_basic = daily_rate * present_days
    hourly_rate = employee.basic_salary / app.config['WORKING_DAYS_PER_MONTH'] / app.config['WORKING_HOURS_PER_DAY']
    overtime_pay = hourly_rate * app.config['OVERTIME_RATE_MULTIPLIER'] * overtime_hours
    hra = earned_basic * app.config['HRA_RATE']
    gross = earned_basic + hra + overtime_pay
    pf = earned_basic * app.config['PF_RATE']
    esi = gross * app.config['ESI_RATE'] if gross <= app.config['ESI_THRESHOLD'] else 0

    advances = Advance.query.filter_by(
        employee_id=employee.id, status='approved',
        month_deducted=month, year_deducted=year
    ).all()
    advance_total = sum(a.amount for a in advances)
    total_deductions = pf + esi + advance_total
    net = gross - total_deductions

    return {
        'working_days': working_days, 'present_days': present_days,
        'basic_salary': round(earned_basic, 2), 'overtime_hours': overtime_hours,
        'overtime_pay': round(overtime_pay, 2), 'hra': round(hra, 2),
        'other_allowances': 0.0, 'gross_salary': round(gross, 2),
        'pf_deduction': round(pf, 2), 'esi_deduction': round(esi, 2),
        'advance_deduction': round(advance_total, 2), 'other_deductions': 0.0,
        'total_deductions': round(total_deductions, 2), 'net_salary': round(net, 2),
    }


def haversine_distance(lat1, lng1, lat2, lng2):
    """Return distance in metres between two GPS coordinates."""
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


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
