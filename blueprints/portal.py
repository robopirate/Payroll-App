from flask import Blueprint, render_template, redirect, url_for, flash, request, abort, send_file
from flask_login import login_user, current_user
from datetime import date, datetime, timedelta
import calendar
import io

from extensions import db, limiter
from decorators import portal_required
from services.attendance_service import count_working_days_between
from services.login_protection import is_allowed
from flask_limiter.util import get_remote_address
from sqlalchemy import extract
from models import Employee, Attendance, Leave, LeaveBalance, Payroll, Holiday, User
from pdf_service import generate_payslip_pdf
from sms_service import get_month_name

bp = Blueprint('portal', __name__)

@bp.route('/portal/login', methods=['GET', 'POST'])
@limiter.limit("10 per minute")
def portal_login():
    if current_user.is_authenticated:
        return redirect(url_for('auth.index'))
    if request.method == 'POST':
        phone = request.form.get('phone', '').strip()
        password = request.form.get('password', '')
        emp = Employee.query.filter_by(phone=phone, is_active=True, is_approved=True).first()
        if emp:
            portal_user = User.query.filter_by(employee_id=emp.id).first()
            if portal_user and portal_user.check_password(password):
                login_user(portal_user, remember=request.form.get('remember'))
                return redirect(url_for('.portal_dashboard'))

        # Record failed attempt and enforce brute-force protection
        client_ip = get_remote_address()
        if not is_allowed(client_ip, limit=5, window=60):
            flash('Too many login attempts. Please try again in a minute.', 'danger')
        else:
            flash('Invalid phone number or password, or account not yet approved.', 'danger')
    return render_template('portal/login.html')


@bp.route('/register', methods=['GET', 'POST'])
def register():
    """Employee self-registration route."""
    if current_user.is_authenticated:
        return redirect(url_for('auth.index'))

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
            return redirect(url_for('.register'))

        # Phone validation
        if not phone.isdigit() or len(phone) != 10:
            flash('Phone number must be exactly 10 digits.', 'danger')
            return redirect(url_for('.register'))

        if password != confirm_password:
            flash('Passwords do not match.', 'danger')
            return redirect(url_for('.register'))

        if len(password) < 6:
            flash('Password must be at least 6 characters long.', 'danger')
            return redirect(url_for('.register'))

        # Check if phone already registered
        existing_emp = Employee.query.filter_by(phone=phone).first()
        if existing_emp:
            flash('Phone number already registered. Please use a different number or login.', 'danger')
            return redirect(url_for('.register'))

        # Check if user already exists
        existing_user = User.query.filter_by(username=phone).first()
        if existing_user:
            flash('This phone number is already registered in the system.', 'danger')
            return redirect(url_for('.register'))

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
                is_active=True,
                is_approved=False  # Requires admin approval
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

            flash('Registration successful! Awaiting admin approval. You will be notified once approved.', 'success')
            return redirect(url_for('.portal_login'))

        except Exception as e:
            db.session.rollback()
            flash(f'Registration failed: {str(e)}', 'danger')
            return redirect(url_for('.register'))

    return render_template('register.html')


@bp.route('/portal/dashboard')
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


@bp.route('/portal/punch')
@portal_required
def portal_punch():
    emp = Employee.query.get(current_user.employee_id)
    today = date.today()
    today_att = Attendance.query.filter_by(employee_id=emp.id, date=today).first()
    location = emp.schools[0] if emp.schools else None
    return render_template('portal/punch.html', emp=emp, location=location, today_attendance=today_att)


@bp.route('/portal/attendance')
@portal_required
def portal_attendance():
    emp = Employee.query.get(current_user.employee_id)
    month = int(request.args.get('month', date.today().month))
    year = int(request.args.get('year', date.today().year))
    _, days_in_month = calendar.monthrange(year, month)

    atts = {a.date.day: a for a in Attendance.query.filter_by(employee_id=emp.id).filter(
        extract('year', Attendance.date) == year,
        extract('month', Attendance.date) == month
    ).all()}

    present = sum(1 for a in atts.values() if a.status == 'present')
    half = sum(0.5 for a in atts.values() if a.status == 'half_day')
    absent = sum(1 for a in atts.values() if a.status == 'absent')

    return render_template('portal/attendance.html', emp=emp, atts=atts, month=month, year=year,
        days_in_month=days_in_month, present=present + half, absent=absent,
        get_month_name=get_month_name,
        months=list(range(1, 13)), years=list(range(2020, date.today().year + 2)))


@bp.route('/portal/payslips')
@portal_required
def portal_payslips():
    emp = Employee.query.get(current_user.employee_id)
    payrolls = Payroll.query.filter_by(employee_id=emp.id).order_by(
        Payroll.year.desc(), Payroll.month.desc()).all()
    return render_template('portal/payslips.html', emp=emp, payrolls=payrolls, get_month_name=get_month_name)


@bp.route('/portal/payslip/<int:payroll_id>')
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


@bp.route('/portal/leaves')
@portal_required
def portal_leaves():
    emp = Employee.query.get(current_user.employee_id)
    year = date.today().year
    leave_balances = LeaveBalance.query.filter_by(employee_id=emp.id, year=year).all()
    leaves_list = Leave.query.filter_by(employee_id=emp.id).order_by(Leave.applied_on.desc()).all()
    return render_template('portal/leaves.html', emp=emp, leave_balances=leave_balances, leaves=leaves_list, today=date.today())


@bp.route('/portal/leaves/<int:leave_id>/cancel', methods=['POST'])
@portal_required
def portal_cancel_leave(leave_id):
    """Employee can cancel their own pending or future approved leave."""
    emp = Employee.query.get(current_user.employee_id)
    leave = Leave.query.get_or_404(leave_id)
    if leave.employee_id != emp.id:
        flash('You can only cancel your own leave.', 'danger')
        return redirect(url_for('.portal_leaves'))

    today = date.today()
    # Allow cancelling pending leaves, or approved leaves that haven't started yet
    if leave.status not in ('pending', 'approved'):
        flash('This leave cannot be cancelled.', 'warning')
        return redirect(url_for('.portal_leaves'))
    if leave.status == 'approved' and leave.start_date < today:
        flash('Past approved leave cannot be cancelled.', 'warning')
        return redirect(url_for('.portal_leaves'))

    # Restore balance if it was already approved
    if leave.status == 'approved':
        balance = LeaveBalance.query.filter_by(
            employee_id=emp.id, leave_type=leave.leave_type, year=leave.start_date.year
        ).first()
        if balance:
            balance.used_days = max(0, balance.used_days - leave.days)

    db.session.delete(leave)
    db.session.commit()
    flash('Leave cancelled.', 'success')
    return redirect(url_for('.portal_leaves'))


@bp.route('/portal/leaves/apply', methods=['GET', 'POST'])
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
            return redirect(url_for('.portal_leaves'))
    return render_template('portal/apply_leave.html', emp=emp, leave_balances=leave_balances)


