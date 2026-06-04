from flask import Flask, render_template, redirect, url_for, flash, request, send_file, jsonify, abort
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from datetime import date, datetime, timedelta
from functools import wraps
import calendar
import io
import os
import math
import secrets

from sqlalchemy import text
from config import Config
from models import db, User, Employee, Department, Attendance, Leave, LeaveBalance, Advance, Payroll, School, Holiday, SchoolSchedule, AuditLog, PasswordReset
from sms_service import send_salary_credited_sms, send_attendance_summary_sms, send_sms, get_month_name
from pdf_service import generate_payslip_pdf

app = Flask(__name__)
app.config.from_object(Config)

db.init_app(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to access this page.'
login_manager.login_message_category = 'warning'


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# ─── Decorators ──────────────────────────────────────────────────────────────

def portal_required(f):
    """Restrict route to authenticated employee (non-admin) users."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('portal_login'))
        if current_user.is_admin:
            return redirect(url_for('dashboard'))
        if not current_user.employee_id:
            logout_user()
            return redirect(url_for('portal_login'))
        return f(*args, **kwargs)
    return decorated


@app.before_request
def restrict_employee_to_portal():
    """Prevent employee portal users from accessing admin routes."""
    if current_user.is_authenticated and not current_user.is_admin:
        allowed = ('/portal', '/employee', '/static', '/api', '/logout')
        if request.path != '/' and not request.path.startswith(allowed):
            return redirect(url_for('portal_dashboard'))


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
        overtime_hours += (att.overtime_hours or 0.0)

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


# ─── Auth ────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    if current_user.is_authenticated:
        if current_user.is_admin:
            return redirect(url_for('dashboard'))
        return redirect(url_for('portal_dashboard'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username, is_admin=True).first()
        if user and user.check_password(password):
            login_user(user, remember=request.form.get('remember'))
            return redirect(request.args.get('next') or url_for('dashboard'))
        flash('Invalid username or password.', 'danger')
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    was_employee = not current_user.is_admin
    logout_user()
    flash('You have been logged out.', 'info')
    if was_employee:
        return redirect(url_for('portal_login'))
    return redirect(url_for('login'))


@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    """Request password reset via phone number."""
    if request.method == 'POST':
        phone = request.form.get('phone', '').strip()
        emp = Employee.query.filter_by(phone=phone).first()
        if not emp:
            flash('Phone number not found.', 'warning')
            return redirect(url_for('forgot_password'))

        user = User.query.filter_by(employee_id=emp.id).first()
        if not user:
            flash('No login account found for this employee.', 'warning')
            return redirect(url_for('forgot_password'))

        # Generate reset token
        token = secrets.token_urlsafe(32)
        reset = PasswordReset(
            user_id=user.id,
            token=token,
            expires_at=datetime.utcnow() + timedelta(hours=1)
        )
        db.session.add(reset)
        db.session.commit()

        # Send SMS with reset token
        message = f"Your password reset token: {token}. Valid for 1 hour. Do not share this token."
        send_sms(emp.phone, message)

        # Log audit trail
        audit = AuditLog(
            action='password_reset_request',
            user=emp.name,
            affected_entity=f'User:{user.id}',
            details=f'Password reset requested via phone'
        )
        db.session.add(audit)
        db.session.commit()

        flash('Reset token sent via SMS. Check your phone.', 'success')
        return redirect(url_for('reset_password'))

    return render_template('forgot_password.html')


@app.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    """Reset password using token sent via SMS."""
    if request.method == 'POST':
        token = request.form.get('token', '').strip()
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')

        reset = PasswordReset.query.filter_by(token=token, is_used=False).first()
        if not reset or reset.expires_at < datetime.utcnow():
            flash('Invalid or expired reset token.', 'danger')
            return redirect(url_for('reset_password'))

        if len(new_password) < 6:
            flash('Password must be at least 6 characters.', 'danger')
            return redirect(url_for('reset_password'))

        if new_password != confirm_password:
            flash('Passwords do not match.', 'danger')
            return redirect(url_for('reset_password'))

        user = reset.user
        user.set_password(new_password)
        reset.is_used = True
        db.session.commit()

        # Log audit trail
        audit = AuditLog(
            action='password_reset_complete',
            user=user.username,
            affected_entity=f'User:{user.id}',
            details=f'Password reset completed'
        )
        db.session.add(audit)
        db.session.commit()

        flash('Password reset successfully. Please login with your new password.', 'success')
        return redirect(url_for('login'))

    return render_template('reset_password.html')


# ─── Dashboard ───────────────────────────────────────────────────────────────

@app.route('/dashboard')
@login_required
def dashboard():
    total_employees = Employee.query.filter_by(is_active=True).count()
    today = date.today()
    present_today = Attendance.query.filter_by(date=today, status='present').count()
    absent_today = Attendance.query.filter_by(date=today, status='absent').count()
    pending_leaves = Leave.query.filter_by(status='pending').count()
    pending_advances = Advance.query.filter_by(status='pending').count()
    recent_payrolls = Payroll.query.order_by(Payroll.generated_on.desc()).limit(5).all()
    schools_count = School.query.filter_by(is_active=True).count()
    return render_template('dashboard.html',
        total_employees=total_employees, present_today=present_today,
        absent_today=absent_today, pending_leaves=pending_leaves,
        pending_advances=pending_advances, recent_payrolls=recent_payrolls,
        today=today, schools_count=schools_count)


# ─── Employees ───────────────────────────────────────────────────────────────

@app.route('/employees')
@login_required
def employees():
    dept_filter = request.args.get('dept', '')
    q = Employee.query.filter_by(is_active=True)
    if dept_filter:
        q = q.join(Department).filter(Department.name == dept_filter)
    emps = q.order_by(Employee.name).all()
    departments = Department.query.order_by(Department.name).all()
    return render_template('employees/list.html', employees=emps, departments=departments, dept_filter=dept_filter)


@app.route('/employees/add', methods=['GET', 'POST'])
@login_required
def add_employee():
    departments = Department.query.order_by(Department.name).all()
    schools = School.query.filter_by(is_active=True).order_by(School.name).all()
    if request.method == 'POST':
        f = request.form
        emp_id = f.get('emp_id', '').strip()
        phone = f.get('phone', '').strip()

        # Phone validation
        if not phone.isdigit() or len(phone) != 10:
            flash('Phone number must be exactly 10 digits.', 'danger')
            return render_template('employees/form.html', departments=departments, schools=schools, form=f)

        # Salary validation
        try:
            basic_salary = float(f.get('basic_salary', 0))
            if basic_salary < 0:
                flash('Basic salary cannot be negative.', 'danger')
                return render_template('employees/form.html', departments=departments, schools=schools, form=f)
        except ValueError:
            flash('Basic salary must be a valid number.', 'danger')
            return render_template('employees/form.html', departments=departments, schools=schools, form=f)

        if Employee.query.filter_by(emp_id=emp_id).first():
            flash('Employee ID already exists.', 'danger')
            return render_template('employees/form.html', departments=departments, schools=schools, form=f)

        emp = Employee(
            emp_id=emp_id,
            name=f.get('name', '').strip(),
            phone=phone,
            email=f.get('email', '').strip(),
            department_id=int(f.get('department_id')) if f.get('department_id') else None,
            designation=f.get('designation', '').strip(),
            basic_salary=basic_salary,
            joining_date=datetime.strptime(f.get('joining_date'), '%Y-%m-%d').date() if f.get('joining_date') else date.today(),
            bank_name=f.get('bank_name', '').strip(),
            account_number=f.get('account_number', '').strip(),
            ifsc_code=f.get('ifsc_code', '').strip(),
            pan_number=f.get('pan_number', '').strip(),
            aadhar_number=f.get('aadhar_number', '').strip(),
        )
        db.session.add(emp)
        db.session.commit()
        flash(f'Employee {emp.name} added. Configure leave balances from Leave Setup.', 'success')
        return redirect(url_for('employees'))
    return render_template('employees/form.html', departments=departments, schools=schools, form={}, edit=False)


@app.route('/employees/<int:emp_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_employee(emp_id):
    emp = Employee.query.get_or_404(emp_id)
    departments = Department.query.order_by(Department.name).all()
    schools = School.query.filter_by(is_active=True).order_by(School.name).all()
    if request.method == 'POST':
        f = request.form
        phone = f.get('phone', emp.phone).strip()

        # Phone validation
        if not phone.isdigit() or len(phone) != 10:
            flash('Phone number must be exactly 10 digits.', 'danger')
            return render_template('employees/form.html', departments=departments, schools=schools, form=emp, edit=True)

        # Salary validation
        try:
            basic_salary = float(f.get('basic_salary', emp.basic_salary))
            if basic_salary < 0:
                flash('Basic salary cannot be negative.', 'danger')
                return render_template('employees/form.html', departments=departments, schools=schools, form=emp, edit=True)
        except ValueError:
            flash('Basic salary must be a valid number.', 'danger')
            return render_template('employees/form.html', departments=departments, schools=schools, form=emp, edit=True)

        emp.name = f.get('name', emp.name).strip()
        emp.phone = phone
        emp.email = f.get('email', emp.email).strip()
        emp.department_id = int(f.get('department_id')) if f.get('department_id') else None
        emp.designation = f.get('designation', '').strip()
        emp.basic_salary = basic_salary
        emp.bank_name = f.get('bank_name', '').strip()
        emp.account_number = f.get('account_number', '').strip()
        emp.ifsc_code = f.get('ifsc_code', '').strip()
        emp.pan_number = f.get('pan_number', '').strip()
        emp.aadhar_number = f.get('aadhar_number', '').strip()
        db.session.commit()
        flash('Employee updated successfully.', 'success')
        return redirect(url_for('employees'))
    return render_template('employees/form.html', departments=departments, schools=schools, form=emp, edit=True)


@app.route('/employees/<int:emp_id>/deactivate', methods=['POST'])
@login_required
def deactivate_employee(emp_id):
    emp = Employee.query.get_or_404(emp_id)
    emp.is_active = False
    db.session.commit()
    flash(f'{emp.name} deactivated.', 'info')
    return redirect(url_for('employees'))


@app.route('/employees/<int:emp_id>')
@login_required
def view_employee(emp_id):
    emp = Employee.query.get_or_404(emp_id)
    today = date.today()
    try:
        month = int(request.args.get('month', today.month))
        year = int(request.args.get('year', today.year))
        if month < 1 or month > 12:
            month = today.month
        if year < 2000 or year > today.year + 5:
            year = today.year
    except ValueError:
        month = today.month
        year = today.year

    recent_att = Attendance.query.filter_by(employee_id=emp_id).order_by(Attendance.date.desc()).limit(10).all()
    payrolls = Payroll.query.filter_by(employee_id=emp_id).order_by(Payroll.year.desc(), Payroll.month.desc()).all()
    leaves = Leave.query.filter_by(employee_id=emp_id).order_by(Leave.applied_on.desc()).limit(10).all()
    portal_user = User.query.filter_by(employee_id=emp.id).first()
    all_schools = School.query.filter_by(is_active=True).order_by(School.name).all()

    # Monthly attendance breakdown
    _, days_in_month = calendar.monthrange(year, month)
    first_day = date(year, month, 1)
    last_day = date(year, month, days_in_month)

    monthly_atts = Attendance.query.filter_by(employee_id=emp_id).filter(
        Attendance.date >= first_day,
        Attendance.date <= last_day
    ).all()

    # Create a dict by day for easy lookup
    att_dict = {a.date.day: a for a in monthly_atts}

    # Calculate monthly summary
    present_days = sum(1 for a in monthly_atts if a.status == 'present')
    half_days = sum(0.5 for a in monthly_atts if a.status == 'half_day')
    absent_days = sum(1 for a in monthly_atts if a.status == 'absent')
    working_days = get_working_days_in_month(year, month)

    return render_template('employees/detail.html', emp=emp, recent_att=recent_att,
                           payrolls=payrolls, leaves=leaves, portal_user=portal_user,
                           all_schools=all_schools, get_month_name=get_month_name,
                           month=month, year=year, days_in_month=days_in_month,
                           att_dict=att_dict, present_days=present_days, half_days=half_days,
                           absent_days=absent_days, working_days=working_days,
                           months=list(range(1, 13)), years=list(range(2020, today.year + 2)))


@app.route('/employees/<int:emp_id>/set_password', methods=['POST'])
@login_required
def set_employee_password(emp_id):
    emp = Employee.query.get_or_404(emp_id)
    new_pass = request.form.get('new_password', '').strip()
    if not new_pass or len(new_pass) < 4:
        flash('Password must be at least 4 characters.', 'danger')
        return redirect(url_for('view_employee', emp_id=emp_id))
    portal_user = User.query.filter_by(employee_id=emp.id).first()
    if not portal_user:
        portal_user = User(username=f'emp_{emp.emp_id}', is_admin=False, employee_id=emp.id)
        db.session.add(portal_user)
    portal_user.set_password(new_pass)
    db.session.commit()
    flash(f'Portal password set for {emp.name}. Login: phone {emp.phone} + new password.', 'success')
    return redirect(url_for('view_employee', emp_id=emp_id))


@app.route('/employees/<int:emp_id>/assign_schools', methods=['POST'])
@login_required
def assign_employee_schools(emp_id):
    emp = Employee.query.get_or_404(emp_id)
    school_ids = request.form.getlist('school_ids')
    emp.schools = []
    for sid in school_ids:
        school = School.query.get(int(sid))
        if school:
            emp.schools.append(school)
    db.session.commit()
    flash('School assignments updated.', 'success')
    return redirect(url_for('view_employee', emp_id=emp_id))


# ─── Departments ─────────────────────────────────────────────────────────────

@app.route('/departments', methods=['GET', 'POST'])
@login_required
def departments():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if name and not Department.query.filter_by(name=name).first():
            db.session.add(Department(name=name))
            db.session.commit()
            flash(f'Department "{name}" added.', 'success')
        else:
            flash('Department name empty or already exists.', 'danger')
    depts = Department.query.order_by(Department.name).all()
    return render_template('departments.html', departments=depts)


# ─── Schools ─────────────────────────────────────────────────────────────────

@app.route('/schools')
@login_required
def schools():
    schools_list = School.query.filter_by(is_active=True).order_by(School.name).all()
    today = date.today()
    school_stats = {}
    for school in schools_list:
        active_emps = [e for e in school.assigned_employees if e.is_active]
        present = 0
        for emp in active_emps:
            att = Attendance.query.filter_by(employee_id=emp.id, date=today).first()
            if att and att.status in ('present', 'overtime'):
                present += 1
        school_stats[school.id] = {
            'employee_count': len(active_emps),
            'present_today': present
        }
    return render_template('schools/list.html', schools=schools_list, school_stats=school_stats, today=today)


@app.route('/schools/add', methods=['GET', 'POST'])
@login_required
def add_school():
    if request.method == 'POST':
        f = request.form
        school = School(
            name=f.get('name', '').strip(),
            address=f.get('address', '').strip(),
            latitude=float(f.get('latitude')) if f.get('latitude') else None,
            longitude=float(f.get('longitude')) if f.get('longitude') else None,
            geofence_radius=float(f.get('geofence_radius') or 150),
        )
        db.session.add(school)
        db.session.commit()
        flash(f'School "{school.name}" added.', 'success')
        return redirect(url_for('schools'))
    return render_template('schools/form.html', school=None, edit=False)


@app.route('/schools/<int:school_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_school(school_id):
    school = School.query.get_or_404(school_id)
    if request.method == 'POST':
        f = request.form
        school.name = f.get('name', school.name).strip()
        school.address = f.get('address', '').strip()
        school.latitude = float(f.get('latitude')) if f.get('latitude') else None
        school.longitude = float(f.get('longitude')) if f.get('longitude') else None
        school.geofence_radius = float(f.get('geofence_radius') or school.geofence_radius)
        db.session.commit()
        flash('School updated.', 'success')
        return redirect(url_for('schools'))
    return render_template('schools/form.html', school=school, edit=True)


@app.route('/schools/<int:school_id>/delete', methods=['POST'])
@login_required
def delete_school(school_id):
    school = School.query.get_or_404(school_id)
    school.is_active = False
    db.session.commit()
    flash(f'School "{school.name}" removed.', 'info')
    return redirect(url_for('schools'))


@app.route('/schools/<int:school_id>')
@login_required
def view_school(school_id):
    school = School.query.get_or_404(school_id)
    today = date.today()
    employees_with_status = []
    for emp in school.assigned_employees:
        if emp.is_active:
            att = Attendance.query.filter_by(employee_id=emp.id, date=today).first()
            employees_with_status.append({'employee': emp, 'attendance': att})
    all_employees = Employee.query.filter_by(is_active=True).order_by(Employee.name).all()
    return render_template('schools/detail.html', school=school,
                           employees_with_status=employees_with_status,
                           all_employees=all_employees, today=today)


@app.route('/schools/<int:school_id>/assign', methods=['POST'])
@login_required
def assign_school_employees(school_id):
    school = School.query.get_or_404(school_id)
    emp_ids = request.form.getlist('employee_ids')
    school.assigned_employees = []
    for eid in emp_ids:
        emp = Employee.query.get(int(eid))
        if emp:
            school.assigned_employees.append(emp)
    db.session.commit()
    flash('Employee assignments updated.', 'success')
    return redirect(url_for('view_school', school_id=school_id))


# ─── Attendance ───────────────────────────────────────────────────────────────

@app.route('/attendance', methods=['GET', 'POST'])
@login_required
def attendance():
    selected_date = request.args.get('date', date.today().isoformat())
    try:
        sel_date = datetime.strptime(selected_date, '%Y-%m-%d').date()
    except ValueError:
        sel_date = date.today()

    emps = Employee.query.filter_by(is_active=True).order_by(Employee.name).all()
    existing = {a.employee_id: a for a in Attendance.query.filter_by(date=sel_date).all()}

    # Auto-populate holiday status if date is a holiday and no record exists
    is_holiday = Holiday.query.filter_by(date=sel_date).first() is not None
    if is_holiday:
        for emp in emps:
            if emp.id not in existing:
                att = Attendance(employee_id=emp.id, date=sel_date, status='holiday', admin_override=False)
                db.session.add(att)
        db.session.commit()
        existing = {a.employee_id: a for a in Attendance.query.filter_by(date=sel_date).all()}

    if request.method == 'POST':
        for emp in emps:
            status = request.form.get(f'status_{emp.id}', 'absent')
            ot_hours = float(request.form.get(f'ot_{emp.id}', 0) or 0)
            check_in = request.form.get(f'checkin_{emp.id}', '').strip()
            check_out = request.form.get(f'checkout_{emp.id}', '').strip()
            notes = request.form.get(f'notes_{emp.id}', '').strip()

            att = existing.get(emp.id)
            if att:
                att.status = status
                att.overtime_hours = ot_hours
                att.check_in = check_in
                att.check_out = check_out
                att.notes = notes
                att.admin_override = True
            else:
                att = Attendance(
                    employee_id=emp.id, date=sel_date,
                    status=status, overtime_hours=ot_hours,
                    check_in=check_in, check_out=check_out,
                    notes=notes, admin_override=True
                )
                db.session.add(att)
        db.session.commit()
        flash(f'Attendance saved for {sel_date.strftime("%d %b %Y")}.', 'success')
        return redirect(url_for('attendance', date=selected_date))

    return render_template('attendance/mark.html', employees=emps, sel_date=sel_date, existing=existing)


@app.route('/attendance/report')
@login_required
def attendance_report():
    month = int(request.args.get('month', date.today().month))
    year = int(request.args.get('year', date.today().year))
    emps = Employee.query.filter_by(is_active=True).order_by(Employee.name).all()
    _, days_in_month = calendar.monthrange(year, month)

    report = []
    for emp in emps:
        atts = {a.date.day: a for a in Attendance.query.filter_by(employee_id=emp.id).filter(
            db.func.strftime('%Y', Attendance.date) == str(year),
            db.func.strftime('%m', Attendance.date) == f"{month:02d}"
        ).all()}
        present = sum(1 for a in atts.values() if a.status == 'present')
        half = sum(0.5 for a in atts.values() if a.status == 'half_day')
        absent = sum(1 for a in atts.values() if a.status == 'absent')
        ot = sum(a.overtime_hours or 0 for a in atts.values())
        report.append({'employee': emp, 'atts': atts, 'present': present + half, 'absent': absent, 'overtime': ot})

    return render_template('attendance/report.html', report=report, month=month, year=year,
        days_in_month=days_in_month, get_month_name=get_month_name,
        months=list(range(1, 13)), years=list(range(2020, date.today().year + 2)))


# ─── Leaves ──────────────────────────────────────────────────────────────────

@app.route('/leaves')
@login_required
def leaves():
    status_filter = request.args.get('status', 'pending')
    q = Leave.query
    if status_filter != 'all':
        q = q.filter_by(status=status_filter)
    leave_list = q.order_by(Leave.applied_on.desc()).all()
    return render_template('leaves/list.html', leaves=leave_list, status_filter=status_filter)


@app.route('/leaves/apply', methods=['GET', 'POST'])
@login_required
def apply_leave():
    emps = Employee.query.filter_by(is_active=True).order_by(Employee.name).all()
    if request.method == 'POST':
        f = request.form
        emp_id = int(f.get('employee_id'))
        emp = Employee.query.get_or_404(emp_id)
        leave_type = f.get('leave_type')
        start_date = datetime.strptime(f.get('start_date'), '%Y-%m-%d').date()
        end_date = datetime.strptime(f.get('end_date'), '%Y-%m-%d').date()
        if f.get('half_day'):
            days = 0.5
        else:
            days = count_working_days_between(start_date, end_date)
        if days <= 0:
            flash('Leave range contains no working days (all weekends/holidays).', 'warning')
            return render_template('leaves/apply.html', employees=emps, form=f)
        current_year = date.today().year
        balance = LeaveBalance.query.filter_by(employee_id=emp_id, leave_type=leave_type, year=current_year).first()
        if balance and balance.remaining_days < days:
            flash(f'Insufficient leave balance. Available: {balance.remaining_days} days.', 'danger')
            return render_template('leaves/apply.html', employees=emps, form=f)
        leave = Leave(employee_id=emp_id, leave_type=leave_type, start_date=start_date,
                      end_date=end_date, days=days, reason=f.get('reason', '').strip())
        db.session.add(leave)
        db.session.commit()
        flash('Leave application submitted.', 'success')
        return redirect(url_for('leaves'))
    return render_template('leaves/apply.html', employees=emps, form={})


@app.route('/leaves/<int:leave_id>/approve', methods=['POST'])
@login_required
def approve_leave(leave_id):
    leave = Leave.query.get_or_404(leave_id)
    leave.status = 'approved'
    leave.approved_by = current_user.username
    leave.approved_on = datetime.utcnow()
    current_year = date.today().year
    balance = LeaveBalance.query.filter_by(employee_id=leave.employee_id,
                                            leave_type=leave.leave_type, year=current_year).first()
    if balance:
        balance.used_days += leave.days
    db.session.commit()

    # Send SMS notification
    emp = leave.employee
    message = f"Your {leave.leave_type} leave for {leave.start_date.strftime('%d %b')} - {leave.end_date.strftime('%d %b')} has been APPROVED. Enjoy!"
    send_sms(emp.phone, message)

    # Log audit trail
    audit = AuditLog(
        action='approve_leave',
        user=current_user.username,
        affected_entity=f'Leave:{leave_id}',
        details=f'Approved {leave.leave_type} leave for {emp.name} ({leave.days} days)'
    )
    db.session.add(audit)
    db.session.commit()

    flash('Leave approved.', 'success')
    return redirect(url_for('leaves'))


@app.route('/leaves/<int:leave_id>/reject', methods=['POST'])
@login_required
def reject_leave(leave_id):
    leave = Leave.query.get_or_404(leave_id)
    leave.status = 'rejected'
    leave.approved_by = current_user.username
    leave.approved_on = datetime.utcnow()
    db.session.commit()

    # Send SMS notification
    emp = leave.employee
    message = f"Your {leave.leave_type} leave for {leave.start_date.strftime('%d %b')} - {leave.end_date.strftime('%d %b')} has been REJECTED. Please contact admin for details."
    send_sms(emp.phone, message)

    # Log audit trail
    audit = AuditLog(
        action='reject_leave',
        user=current_user.username,
        affected_entity=f'Leave:{leave_id}',
        details=f'Rejected {leave.leave_type} leave for {emp.name}'
    )
    db.session.add(audit)
    db.session.commit()

    flash('Leave rejected.', 'info')
    return redirect(url_for('leaves'))


@app.route('/leaves/balances')
@login_required
def leave_balances():
    year = int(request.args.get('year', date.today().year))
    emps = Employee.query.filter_by(is_active=True).order_by(Employee.name).all()
    return render_template('leaves/balances.html', employees=emps, year=year,
                           years=list(range(2020, date.today().year + 2)))


# ─── Advances ────────────────────────────────────────────────────────────────

@app.route('/advances', methods=['GET', 'POST'])
@login_required
def advances():
    emps = Employee.query.filter_by(is_active=True).order_by(Employee.name).all()
    if request.method == 'POST':
        f = request.form
        # Amount validation
        try:
            amount = float(f.get('amount', 0))
            if amount <= 0:
                flash('Advance amount must be greater than zero.', 'danger')
                return render_template('advances.html', advances=Advance.query.order_by(Advance.date.desc()).all(),
                                     employees=emps, today=date.today().isoformat(),
                                     months=list(range(1, 13)), years=list(range(2020, date.today().year + 2)),
                                     get_month_name=get_month_name)
        except ValueError:
            flash('Advance amount must be a valid number.', 'danger')
            return render_template('advances.html', advances=Advance.query.order_by(Advance.date.desc()).all(),
                                 employees=emps, today=date.today().isoformat(),
                                 months=list(range(1, 13)), years=list(range(2020, date.today().year + 2)),
                                 get_month_name=get_month_name)

        adv = Advance(
            employee_id=int(f.get('employee_id')),
            amount=amount,
            date=datetime.strptime(f.get('date'), '%Y-%m-%d').date() if f.get('date') else date.today(),
            reason=f.get('reason', '').strip(),
            month_deducted=int(f.get('month_deducted')) if f.get('month_deducted') else None,
            year_deducted=int(f.get('year_deducted')) if f.get('year_deducted') else None,
        )
        db.session.add(adv)
        db.session.commit()
        flash('Advance recorded.', 'success')
        return redirect(url_for('advances'))
    adv_list = Advance.query.order_by(Advance.date.desc()).all()
    return render_template('advances.html', advances=adv_list, employees=emps,
                           today=date.today().isoformat(),
                           months=list(range(1, 13)), years=list(range(2020, date.today().year + 2)),
                           get_month_name=get_month_name)


@app.route('/advances/<int:adv_id>/approve', methods=['POST'])
@login_required
def approve_advance(adv_id):
    adv = Advance.query.get_or_404(adv_id)
    adv.status = 'approved'
    db.session.commit()
    flash('Advance approved.', 'success')
    return redirect(url_for('advances'))


# ─── Payroll ─────────────────────────────────────────────────────────────────

@app.route('/payroll')
@login_required
def payroll():
    month = int(request.args.get('month', date.today().month))
    year = int(request.args.get('year', date.today().year))
    payrolls = Payroll.query.filter_by(month=month, year=year).all()
    emp_ids_done = {p.employee_id for p in payrolls}
    emps = Employee.query.filter_by(is_active=True).all()
    return render_template('payroll/list.html', payrolls=payrolls, month=month, year=year,
        employees=emps, emp_ids_done=emp_ids_done, get_month_name=get_month_name,
        months=list(range(1, 13)), years=list(range(2020, date.today().year + 2)))


@app.route('/payroll/generate', methods=['POST'])
@login_required
def generate_payroll():
    month = int(request.form.get('month', date.today().month))
    year = int(request.form.get('year', date.today().year))
    emp_ids = request.form.getlist('employee_ids')
    if not emp_ids:
        emps = Employee.query.filter_by(is_active=True).all()
        emp_ids = [str(e.id) for e in emps]
    count = 0
    for emp_id in emp_ids:
        emp = Employee.query.get(int(emp_id))
        if not emp:
            continue
        existing = Payroll.query.filter_by(employee_id=emp.id, month=month, year=year).first()
        data = calculate_payroll(emp, month, year)
        if existing:
            for k, v in data.items():
                setattr(existing, k, v)
            existing.generated_on = datetime.utcnow()
        else:
            p = Payroll(employee_id=emp.id, month=month, year=year, **data)
            db.session.add(p)
        count += 1
    db.session.commit()
    flash(f'Payroll generated for {count} employees for {get_month_name(month)} {year}.', 'success')
    return redirect(url_for('payroll', month=month, year=year))


@app.route('/payroll/<int:payroll_id>/finalize', methods=['POST'])
@login_required
def finalize_payroll(payroll_id):
    p = Payroll.query.get_or_404(payroll_id)
    p.status = 'finalized'
    db.session.commit()
    flash('Payroll finalized.', 'success')
    return redirect(url_for('payroll', month=p.month, year=p.year))


@app.route('/payroll/<int:payroll_id>/mark_paid', methods=['POST'])
@login_required
def mark_paid(payroll_id):
    p = Payroll.query.get_or_404(payroll_id)
    p.status = 'paid'
    p.paid_on = datetime.utcnow()
    db.session.commit()
    flash('Marked as paid.', 'success')
    return redirect(url_for('payroll', month=p.month, year=p.year))


@app.route('/payroll/<int:payroll_id>/payslip')
@login_required
def download_payslip(payroll_id):
    p = Payroll.query.get_or_404(payroll_id)
    emp = Employee.query.get_or_404(p.employee_id)
    pdf_bytes = generate_payslip_pdf(emp, p)
    filename = f"payslip_{emp.emp_id}_{get_month_name(p.month)}_{p.year}.pdf"
    return send_file(io.BytesIO(pdf_bytes), mimetype='application/pdf',
                     as_attachment=True, download_name=filename)


@app.route('/payroll/<int:payroll_id>/send_sms', methods=['POST'])
@login_required
def send_payroll_sms(payroll_id):
    p = Payroll.query.get_or_404(payroll_id)
    emp = Employee.query.get_or_404(p.employee_id)
    success, msg = send_salary_credited_sms(emp, p)
    if success:
        p.sms_sent = True
        db.session.commit()
        flash(f'SMS sent to {emp.name}.', 'success')
    else:
        flash(f'SMS failed: {msg}', 'danger')
    return redirect(url_for('payroll', month=p.month, year=p.year))


@app.route('/payroll/send_bulk_sms', methods=['POST'])
@login_required
def send_bulk_sms():
    month = int(request.form.get('month', date.today().month))
    year = int(request.form.get('year', date.today().year))
    payrolls = Payroll.query.filter_by(month=month, year=year, status='paid').all()
    sent = 0
    for p in payrolls:
        emp = Employee.query.get(p.employee_id)
        if emp:
            success, _ = send_salary_credited_sms(emp, p)
            if success:
                p.sms_sent = True
                sent += 1
    db.session.commit()
    flash(f'SMS sent to {sent} employees.', 'success')
    return redirect(url_for('payroll', month=month, year=year))


# ─── SMS ─────────────────────────────────────────────────────────────────────

@app.route('/sms', methods=['GET', 'POST'])
@login_required
def sms_panel():
    emps = Employee.query.filter_by(is_active=True).order_by(Employee.name).all()
    if request.method == 'POST':
        f = request.form
        emp_ids = f.getlist('employee_ids')
        message = f.get('message', '').strip()
        if not message:
            flash('Message cannot be empty.', 'danger')
        elif not emp_ids:
            flash('Select at least one employee.', 'danger')
        else:
            phones = [Employee.query.get(int(i)).phone for i in emp_ids if Employee.query.get(int(i))]
            success, msg = send_sms(phones, message)
            if success:
                flash(f'SMS sent to {len(phones)} employees.', 'success')
            else:
                flash(f'SMS failed: {msg}', 'danger')
    return render_template('sms.html', employees=emps)


# ─── Settings ────────────────────────────────────────────────────────────────

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if request.method == 'POST':
        new_pass = request.form.get('new_password', '')
        confirm = request.form.get('confirm_password', '')
        api_key = request.form.get('api_key', '').strip()
        if new_pass:
            if new_pass != confirm:
                flash('Passwords do not match.', 'danger')
            else:
                current_user.set_password(new_pass)
                db.session.commit()
                flash('Password updated.', 'success')
        if api_key:
            app.config['FAST2SMS_API_KEY'] = api_key
            flash('API key updated for this session.', 'info')
    return render_template('settings.html')


# ─── Employee Portal ──────────────────────────────────────────────────────────

# ─── Holidays ─────────────────────────────────────────────────────────────────

@app.route('/holidays', methods=['GET', 'POST'])
@login_required
def holidays():
    if request.method == 'POST':
        f = request.form
        date_str = f.get('date')
        name = f.get('name', '').strip()
        description = f.get('description', '').strip()
        year = int(f.get('year', date.today().year))

        if not date_str or not name:
            flash('Date and name are required.', 'danger')
            return redirect(url_for('holidays'))

        try:
            holiday_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            existing = Holiday.query.filter_by(date=holiday_date).first()
            if existing:
                flash('Holiday already exists for this date.', 'warning')
            else:
                holiday = Holiday(date=holiday_date, name=name, description=description, year=year)
                db.session.add(holiday)
                db.session.commit()
                flash(f'Holiday "{name}" added successfully.', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Error: {str(e)}', 'danger')

        return redirect(url_for('holidays'))

    holidays_list = Holiday.query.order_by(Holiday.date).all()
    return render_template('holidays.html', holidays=holidays_list, today=date.today())


@app.route('/holidays/<int:holiday_id>/delete', methods=['POST'])
@login_required
def delete_holiday(holiday_id):
    holiday = Holiday.query.get_or_404(holiday_id)
    name = holiday.name
    db.session.delete(holiday)

    # Log audit trail
    audit = AuditLog(
        action='delete_holiday',
        user=current_user.username,
        affected_entity=f'Holiday:{holiday_id}',
        details=f'Deleted holiday: {name} ({holiday.date})'
    )
    db.session.add(audit)
    db.session.commit()

    flash(f'Holiday "{name}" deleted.', 'success')
    return redirect(url_for('holidays'))


@app.route('/holidays/populate-national', methods=['POST'])
@login_required
def populate_national_holidays():
    year = int(request.form.get('year', date.today().year))

    # National and festival holidays (lunar dates adjusted for 2026)
    national_holidays = []

    if year == 2026:
        national_holidays = [
            ('2026-01-26', 'Republic Day', 'National holiday'),
            ('2026-03-09', 'Maha Shivaratri', 'Hindu festival - Lunar calendar'),
            ('2026-03-29', 'Holi', 'Hindu festival - Lunar calendar'),
            ('2026-04-14', 'Eid ul-Fitr', 'Islamic festival - Lunar calendar'),
            ('2026-04-17', 'Good Friday', 'Christian festival'),
            ('2026-04-21', 'Mahavir Jayanti', 'Jain festival - Lunar calendar'),
            ('2026-05-26', 'Buddha Purnima', 'Buddhist festival - Lunar calendar'),
            ('2026-06-04', 'Eid ul-Adha', 'Islamic festival - Lunar calendar'),
            ('2026-08-15', 'Independence Day', 'National holiday'),
            ('2026-08-27', 'Janmashtami', 'Hindu festival - Lunar calendar'),
            ('2026-09-06', 'Milad un-Nabi', 'Islamic festival - Lunar calendar'),
            ('2026-10-02', 'Gandhi Jayanti', 'National holiday'),
            ('2026-10-20', 'Dussehra', 'Hindu festival - Lunar calendar'),
            ('2026-11-08', 'Diwali', 'Hindu festival - Lunar calendar'),
            ('2026-11-09', 'Diwali (Day 2)', 'Hindu festival'),
            ('2026-11-16', 'Guru Nanak Jayanti', 'Sikh festival - Lunar calendar'),
            ('2026-12-25', 'Christmas', 'National holiday'),
        ]
    else:
        # Default holidays for other years
        national_holidays = [
            (f'{year}-01-26', 'Republic Day', 'National holiday'),
            (f'{year}-03-08', 'Maha Shivaratri', 'Hindu festival'),
            (f'{year}-03-25', 'Holi', 'Hindu festival'),
            (f'{year}-04-11', 'Eid ul-Fitr', 'Islamic festival'),
            (f'{year}-04-17', 'Ram Navami', 'Hindu festival'),
            (f'{year}-04-21', 'Mahavir Jayanti', 'Jain festival'),
            (f'{year}-05-23', 'Buddha Purnima', 'Buddhist festival'),
            (f'{year}-06-17', 'Eid ul-Adha', 'Islamic festival'),
            (f'{year}-08-15', 'Independence Day', 'National holiday'),
            (f'{year}-08-26', 'Janmashtami', 'Hindu festival'),
            (f'{year}-09-16', 'Milad un-Nabi', 'Islamic festival'),
            (f'{year}-10-02', 'Gandhi Jayanti', 'National holiday'),
            (f'{year}-10-12', 'Dussehra', 'Hindu festival'),
            (f'{year}-10-31', 'Diwali', 'Hindu festival'),
            (f'{year}-11-01', 'Diwali (Day 2)', 'Hindu festival'),
            (f'{year}-11-15', 'Guru Nanak Jayanti', 'Sikh festival'),
            (f'{year}-12-25', 'Christmas', 'National holiday'),
        ]

    added = 0
    skipped = 0
    for date_str, name, desc in national_holidays:
        try:
            holiday_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            existing = Holiday.query.filter_by(date=holiday_date).first()
            if existing:
                skipped += 1
            else:
                holiday = Holiday(date=holiday_date, name=name, description=desc, year=year)
                db.session.add(holiday)
                added += 1
        except Exception as e:
            skipped += 1

    db.session.commit()
    flash(f'Added {added} national holidays for {year}. {skipped} already existed.', 'success')
    return redirect(url_for('holidays'))


# ─── School Schedule ──────────────────────────────────────────────────────────

@app.route('/school-schedule', methods=['GET', 'POST'])
@login_required
def school_schedule():
    schedule = SchoolSchedule.query.order_by(SchoolSchedule.year.desc()).first()

    if request.method == 'POST':
        f = request.form
        year = int(f.get('year', date.today().year))
        session_start_str = f.get('session_start')
        session_end_str = f.get('session_end')
        notes = f.get('notes', '').strip()

        if not session_start_str or not session_end_str:
            flash('Session dates are required.', 'danger')
            return redirect(url_for('school_schedule'))

        try:
            session_start = datetime.strptime(session_start_str, '%Y-%m-%d').date()
            session_end = datetime.strptime(session_end_str, '%Y-%m-%d').date()

            if schedule and schedule.year == year:
                schedule.session_start = session_start
                schedule.session_end = session_end
                schedule.semester1_start = datetime.strptime(f.get('semester1_start'), '%Y-%m-%d').date() if f.get('semester1_start') else None
                schedule.semester1_end = datetime.strptime(f.get('semester1_end'), '%Y-%m-%d').date() if f.get('semester1_end') else None
                schedule.semester2_start = datetime.strptime(f.get('semester2_start'), '%Y-%m-%d').date() if f.get('semester2_start') else None
                schedule.semester2_end = datetime.strptime(f.get('semester2_end'), '%Y-%m-%d').date() if f.get('semester2_end') else None
                schedule.notes = notes
                flash('Schedule updated.', 'success')
            else:
                schedule = SchoolSchedule(
                    year=year,
                    session_start=session_start,
                    session_end=session_end,
                    semester1_start=datetime.strptime(f.get('semester1_start'), '%Y-%m-%d').date() if f.get('semester1_start') else None,
                    semester1_end=datetime.strptime(f.get('semester1_end'), '%Y-%m-%d').date() if f.get('semester1_end') else None,
                    semester2_start=datetime.strptime(f.get('semester2_start'), '%Y-%m-%d').date() if f.get('semester2_start') else None,
                    semester2_end=datetime.strptime(f.get('semester2_end'), '%Y-%m-%d').date() if f.get('semester2_end') else None,
                    notes=notes
                )
                db.session.add(schedule)
                flash('Schedule created.', 'success')

            db.session.commit()
        except Exception as e:
            db.session.rollback()
            flash(f'Error: {str(e)}', 'danger')

        return redirect(url_for('school_schedule'))

    return render_template('school_schedule.html', schedule=schedule, today=date.today())


# ─── Leave Balance Setup ───────────────────────────────────────────────────────

@app.route('/leave-setup', methods=['GET', 'POST'])
@login_required
def leave_balance_setup():
    employees = Employee.query.filter_by(is_active=True).order_by(Employee.name).all()
    current_year = date.today().year

    leave_balances = {}
    for emp in employees:
        balances = LeaveBalance.query.filter_by(employee_id=emp.id, year=current_year).all()
        for bal in balances:
            leave_balances[(emp.id, bal.leave_type)] = bal

    return render_template('leave_balance_setup.html', employees=employees, leave_balances=leave_balances, today=date.today())


@app.route('/leave-setup/quick', methods=['POST'])
@login_required
def setup_leave_quick():
    f = request.form
    casual = float(f.get('casual_days', 12))
    sick = float(f.get('sick_days', 5))
    earned = float(f.get('earned_days', 20))
    year = date.today().year

    employees = Employee.query.filter_by(is_active=True).all()
    count = 0

    for emp in employees:
        for leave_type, days in [('casual', casual), ('sick', sick), ('earned', earned)]:
            existing = LeaveBalance.query.filter_by(employee_id=emp.id, leave_type=leave_type, year=year).first()
            if existing:
                existing.total_days = days
            else:
                lb = LeaveBalance(employee_id=emp.id, leave_type=leave_type, total_days=days, year=year)
                db.session.add(lb)
            count += 1

    db.session.commit()
    flash(f'Leave balances assigned to {len(employees)} employees.', 'success')
    return redirect(url_for('leave_balance_setup'))


@app.route('/leave-setup/employee', methods=['POST'])
@login_required
def setup_employee_leaves():
    f = request.form
    emp_id = int(f.get('employee_id'))
    casual = float(f.get('casual_days', 0))
    sick = float(f.get('sick_days', 0))
    earned = float(f.get('earned_days', 0))
    year = int(f.get('year', date.today().year))

    emp = Employee.query.get_or_404(emp_id)

    for leave_type, days in [('casual', casual), ('sick', sick), ('earned', earned)]:
        existing = LeaveBalance.query.filter_by(employee_id=emp_id, leave_type=leave_type, year=year).first()
        if existing:
            existing.total_days = days
        else:
            lb = LeaveBalance(employee_id=emp_id, leave_type=leave_type, total_days=days, year=year)
            db.session.add(lb)

    db.session.commit()
    flash(f'Leave balances updated for {emp.name}.', 'success')
    return redirect(url_for('leave_balance_setup'))


@app.route('/portal/login', methods=['GET', 'POST'])
def portal_login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        phone = request.form.get('phone', '').strip()
        password = request.form.get('password', '')
        emp = Employee.query.filter_by(phone=phone, is_active=True).first()
        if emp:
            portal_user = User.query.filter_by(employee_id=emp.id).first()
            if portal_user and portal_user.check_password(password):
                login_user(portal_user, remember=request.form.get('remember'))
                return redirect(url_for('portal_dashboard'))
        flash('Invalid phone number or password.', 'danger')
    return render_template('portal/login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    """Employee self-registration route."""
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        # Get form data
        name = request.form.get('name', '').strip()
        phone = request.form.get('phone', '').strip()
        email = request.form.get('email', '').strip()
        designation = request.form.get('designation', '').strip()
        department = request.form.get('department', '').strip()
        joining_date_str = request.form.get('joining_date', '')
        pan_number = request.form.get('pan_number', '').strip()
        aadhar_number = request.form.get('aadhar_number', '').strip()
        bank_name = request.form.get('bank_name', '').strip()
        account_number = request.form.get('account_number', '').strip()
        ifsc_code = request.form.get('ifsc_code', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')

        # Validation
        if not all([name, phone, designation, bank_name, account_number, ifsc_code, password]):
            flash('Please fill in all required fields.', 'danger')
            return redirect(url_for('register'))

        # Phone validation
        if not phone.isdigit() or len(phone) != 10:
            flash('Phone number must be exactly 10 digits.', 'danger')
            return redirect(url_for('register'))

        if password != confirm_password:
            flash('Passwords do not match.', 'danger')
            return redirect(url_for('register'))

        if len(password) < 6:
            flash('Password must be at least 6 characters long.', 'danger')
            return redirect(url_for('register'))

        # Check if phone already registered
        existing_emp = Employee.query.filter_by(phone=phone).first()
        if existing_emp:
            flash('Phone number already registered. Please use a different number or login.', 'danger')
            return redirect(url_for('register'))

        # Check if user already exists
        existing_user = User.query.filter_by(username=phone).first()
        if existing_user:
            flash('This phone number is already registered in the system.', 'danger')
            return redirect(url_for('register'))

        try:
            # Generate employee ID
            last_emp = Employee.query.order_by(Employee.id.desc()).first()
            emp_number = (last_emp.id + 1) if last_emp else 1
            emp_id = f"EMP{emp_number:03d}"

            # Parse joining date
            try:
                joining_date = datetime.strptime(joining_date_str, '%Y-%m-%d').date() if joining_date_str else date.today()
            except:
                joining_date = date.today()

            # Create employee record
            employee = Employee(
                emp_id=emp_id,
                name=name,
                phone=phone,
                email=email if email else None,
                designation=designation,
                joining_date=joining_date,
                pan_number=pan_number if pan_number else None,
                aadhar_number=aadhar_number if aadhar_number else None,
                bank_name=bank_name,
                account_number=account_number,
                ifsc_code=ifsc_code,
                is_active=True
            )
            db.session.add(employee)
            db.session.flush()  # Get the employee ID before creating user

            # Create user account for login
            user = User(
                username=phone,
                employee_id=employee.id,
                is_admin=False
            )
            user.set_password(password)
            db.session.add(user)

            db.session.commit()

            flash('Registration successful! Please login with your phone number and password.', 'success')
            return redirect(url_for('portal_login'))

        except Exception as e:
            db.session.rollback()
            flash(f'Registration failed: {str(e)}', 'danger')
            return redirect(url_for('register'))

    return render_template('register.html')


@app.route('/portal/dashboard')
@portal_required
def portal_dashboard():
    emp = Employee.query.get(current_user.employee_id)
    today = date.today()
    today_att = Attendance.query.filter_by(employee_id=emp.id, date=today).first()
    recent_att = Attendance.query.filter_by(employee_id=emp.id).order_by(
        Attendance.date.desc()).limit(7).all()
    leave_balances = LeaveBalance.query.filter_by(employee_id=emp.id, year=today.year).all()
    latest_payroll = Payroll.query.filter_by(employee_id=emp.id).order_by(
        Payroll.year.desc(), Payroll.month.desc()).first()

    # Get upcoming holidays (next 30 days)
    thirty_days_later = today + timedelta(days=30)
    upcoming_holidays = Holiday.query.filter(
        Holiday.date >= today,
        Holiday.date <= thirty_days_later,
        Holiday.is_active == True
    ).order_by(Holiday.date).all()

    return render_template('portal/dashboard.html', emp=emp, today=today,
        today_att=today_att, recent_att=recent_att,
        leave_balances=leave_balances, latest_payroll=latest_payroll,
        upcoming_holidays=upcoming_holidays)


@app.route('/portal/punch')
@portal_required
def portal_punch():
    emp = Employee.query.get(current_user.employee_id)
    today = date.today()
    today_att = Attendance.query.filter_by(employee_id=emp.id, date=today).first()
    school = emp.schools[0] if emp.schools else None
    return render_template('portal/punch.html', emp=emp, school=school, today_attendance=today_att)


@app.route('/api/punch', methods=['POST'])
def api_punch():
    if not current_user.is_authenticated or current_user.is_admin:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401

    data = request.get_json(silent=True) or {}
    lat = data.get('lat')
    lng = data.get('lng')
    action = data.get('action', 'in')

    if lat is None or lng is None:
        return jsonify({'success': False, 'message': 'GPS coordinates not received.'})

    emp = Employee.query.get(current_user.employee_id)
    if not emp:
        return jsonify({'success': False, 'message': 'Employee not found.'})

    # Geofence check
    assigned_schools = [s for s in emp.schools if s.latitude and s.longitude]
    if assigned_schools:
        closest_school = None
        min_distance = float('inf')
        for school in assigned_schools:
            dist = haversine_distance(lat, lng, school.latitude, school.longitude)
            if dist < min_distance:
                min_distance = dist
                closest_school = school

        if closest_school and min_distance > closest_school.geofence_radius:
            return jsonify({
                'success': False,
                'message': (f'You are not at your assigned location. '
                            f'You are {int(min_distance)}m away from {closest_school.name} '
                            f'(allowed radius: {int(closest_school.geofence_radius)}m).')
            })

    today = date.today()
    now_time = datetime.now().strftime('%H:%M')
    att = Attendance.query.filter_by(employee_id=emp.id, date=today).first()

    if action == 'in':
        if att and att.check_in:
            return jsonify({'success': False, 'message': f'Already punched IN at {att.check_in}.'})
        if att:
            att.check_in = now_time
            att.status = 'present'
            att.gps_lat = lat
            att.gps_lng = lng
            att.gps_verified = True
        else:
            att = Attendance(employee_id=emp.id, date=today, status='present',
                             check_in=now_time, gps_lat=lat, gps_lng=lng, gps_verified=True)
            db.session.add(att)
        db.session.commit()
        return jsonify({'success': True, 'message': f'Punched IN at {now_time} ✓'})
    else:
        if not att or not att.check_in:
            return jsonify({'success': False, 'message': 'No punch-in record found for today.'})
        if att.check_out:
            return jsonify({'success': False, 'message': f'Already punched OUT at {att.check_out}.'})
        att.check_out = now_time
        db.session.commit()
        return jsonify({'success': True, 'message': f'Punched OUT at {now_time} ✓'})


@app.route('/portal/attendance')
@portal_required
def portal_attendance():
    emp = Employee.query.get(current_user.employee_id)
    month = int(request.args.get('month', date.today().month))
    year = int(request.args.get('year', date.today().year))
    _, days_in_month = calendar.monthrange(year, month)

    atts = {a.date.day: a for a in Attendance.query.filter_by(employee_id=emp.id).filter(
        db.func.strftime('%Y', Attendance.date) == str(year),
        db.func.strftime('%m', Attendance.date) == f"{month:02d}"
    ).all()}

    present = sum(1 for a in atts.values() if a.status == 'present')
    half = sum(0.5 for a in atts.values() if a.status == 'half_day')
    absent = sum(1 for a in atts.values() if a.status == 'absent')

    return render_template('portal/attendance.html', emp=emp, atts=atts, month=month, year=year,
        days_in_month=days_in_month, present=present + half, absent=absent,
        get_month_name=get_month_name,
        months=list(range(1, 13)), years=list(range(2020, date.today().year + 2)))


@app.route('/portal/payslips')
@portal_required
def portal_payslips():
    emp = Employee.query.get(current_user.employee_id)
    payrolls = Payroll.query.filter_by(employee_id=emp.id).order_by(
        Payroll.year.desc(), Payroll.month.desc()).all()
    return render_template('portal/payslips.html', emp=emp, payrolls=payrolls, get_month_name=get_month_name)


@app.route('/portal/payslip/<int:payroll_id>')
@portal_required
def portal_download_payslip(payroll_id):
    p = Payroll.query.get_or_404(payroll_id)
    if p.employee_id != current_user.employee_id:
        abort(403)
    emp = Employee.query.get_or_404(p.employee_id)
    pdf_bytes = generate_payslip_pdf(emp, p)
    filename = f"payslip_{emp.emp_id}_{get_month_name(p.month)}_{p.year}.pdf"
    return send_file(io.BytesIO(pdf_bytes), mimetype='application/pdf',
                     as_attachment=True, download_name=filename)


@app.route('/portal/leaves')
@portal_required
def portal_leaves():
    emp = Employee.query.get(current_user.employee_id)
    year = date.today().year
    leave_balances = LeaveBalance.query.filter_by(employee_id=emp.id, year=year).all()
    leaves_list = Leave.query.filter_by(employee_id=emp.id).order_by(Leave.applied_on.desc()).all()
    return render_template('portal/leaves.html', emp=emp, leave_balances=leave_balances, leaves=leaves_list)


@app.route('/portal/leaves/apply', methods=['GET', 'POST'])
@portal_required
def portal_apply_leave():
    emp = Employee.query.get(current_user.employee_id)
    year = date.today().year
    leave_balances = LeaveBalance.query.filter_by(employee_id=emp.id, year=year).all()
    if request.method == 'POST':
        f = request.form
        leave_type = f.get('leave_type')
        start_date = datetime.strptime(f.get('start_date'), '%Y-%m-%d').date()
        end_date = datetime.strptime(f.get('end_date'), '%Y-%m-%d').date()
        if f.get('half_day'):
            days = 0.5
        else:
            days = count_working_days_between(start_date, end_date)
        if days <= 0:
            flash('Leave range contains no working days (all weekends/holidays).', 'warning')
            return render_template('portal/apply_leave.html', emp=emp, leave_balances=leave_balances)
        balance = LeaveBalance.query.filter_by(employee_id=emp.id, leave_type=leave_type, year=year).first()
        if balance and balance.remaining_days < days:
            flash(f'Insufficient balance. Available: {balance.remaining_days} days.', 'danger')
        else:
            leave = Leave(employee_id=emp.id, leave_type=leave_type, start_date=start_date,
                          end_date=end_date, days=days, reason=f.get('reason', '').strip())
            db.session.add(leave)
            db.session.commit()
            flash('Leave application submitted. Pending admin approval.', 'success')
            return redirect(url_for('portal_leaves'))
    return render_template('portal/apply_leave.html', emp=emp, leave_balances=leave_balances)


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


if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0', port=5000)
