from flask_login import UserMixin
from datetime import datetime, date
from werkzeug.security import generate_password_hash, check_password_hash
from extensions import db

# Many-to-many: Employee <-> School
employee_schools = db.Table('employee_schools',
    db.Column('employee_id', db.Integer, db.ForeignKey('employees.id'), primary_key=True),
    db.Column('school_id', db.Integer, db.ForeignKey('schools.id'), primary_key=True)
)


class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    is_admin = db.Column(db.Boolean, default=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=True)
    must_change_password = db.Column(db.Boolean, default=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Department(db.Model):
    __tablename__ = 'departments'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    employees = db.relationship('Employee', backref='dept', lazy=True)


class School(db.Model):
    __tablename__ = 'schools'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    address = db.Column(db.String(300))
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    geofence_radius = db.Column(db.Float, default=150.0)
    working_hours_per_day = db.Column(db.Float, default=8.0)
    # Shift timings (HH:MM). Grace period applies to check-in; lunch is unpaid break.
    shift_start = db.Column(db.String(5))
    shift_end = db.Column(db.String(5))
    grace_minutes = db.Column(db.Integer, default=15)
    lunch_minutes = db.Column(db.Integer, default=60)
    is_active = db.Column(db.Boolean, default=True)
    location_type = db.Column(db.String(30), default='School')


class Employee(db.Model):
    __tablename__ = 'employees'
    id = db.Column(db.Integer, primary_key=True)
    emp_id = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(15), unique=True, nullable=False)
    email = db.Column(db.String(120))
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'))
    designation = db.Column(db.String(100))
    basic_salary = db.Column(db.Float, default=0.0)
    joining_date = db.Column(db.Date, default=date.today)
    is_active = db.Column(db.Boolean, default=True)
    is_approved = db.Column(db.Boolean, default=False)  # Admin approval required for self-registered
    # Bank details
    bank_name = db.Column(db.String(100))
    account_number = db.Column(db.String(30))
    ifsc_code = db.Column(db.String(20))
    pan_number = db.Column(db.String(20))
    aadhar_number = db.Column(db.String(20))
    # Relationships
    attendances = db.relationship('Attendance', backref='employee', lazy=True)
    leaves = db.relationship('Leave', backref='employee', lazy=True)
    payrolls = db.relationship('Payroll', backref='employee', lazy=True)
    advances = db.relationship('Advance', backref='employee', lazy=True)
    schools = db.relationship('School', secondary=employee_schools, lazy=True,
                              backref=db.backref('assigned_employees', lazy=True))

    @property
    def leave_balance(self):
        return {lb.leave_type: lb for lb in self.leave_balances}


class Attendance(db.Model):
    __tablename__ = 'attendance'
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False)
    date = db.Column(db.Date, nullable=False, default=date.today)
    status = db.Column(db.String(20), nullable=False)  # present, absent, half_day, holiday, leave, overtime
    overtime_hours = db.Column(db.Float, default=0.0)
    check_in = db.Column(db.String(10))
    check_out = db.Column(db.String(10))
    notes = db.Column(db.String(200))
    # GPS proof fields
    gps_lat = db.Column(db.Float)
    gps_lng = db.Column(db.Float)
    gps_verified = db.Column(db.Boolean, default=False)
    admin_override = db.Column(db.Boolean, default=False)
    # Late / early-exit tracking based on the employee's location shift timings
    late_minutes = db.Column(db.Integer, default=0)
    early_minutes = db.Column(db.Integer, default=0)
    # Location type: 'school' = within geofence, 'field' = outside all geofences
    location_type = db.Column(db.String(20), default='school')
    __table_args__ = (db.UniqueConstraint('employee_id', 'date', name='uq_emp_date'),)


class Leave(db.Model):
    __tablename__ = 'leaves'
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False)
    leave_type = db.Column(db.String(30), nullable=False)  # casual, sick, earned
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    days = db.Column(db.Float, default=1.0)
    reason = db.Column(db.String(300))
    status = db.Column(db.String(20), default='pending')  # pending, approved, rejected
    applied_on = db.Column(db.DateTime, default=datetime.utcnow)
    approved_by = db.Column(db.String(80))
    approved_on = db.Column(db.DateTime)


class LeaveBalance(db.Model):
    __tablename__ = 'leave_balances'
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False)
    leave_type = db.Column(db.String(30), nullable=False)
    total_days = db.Column(db.Float, default=0.0)
    used_days = db.Column(db.Float, default=0.0)
    year = db.Column(db.Integer, default=lambda: datetime.now().year)
    employee = db.relationship('Employee', backref='leave_balances')
    __table_args__ = (db.UniqueConstraint('employee_id', 'leave_type', 'year', name='uq_emp_leave_year'),)

    @property
    def remaining_days(self):
        return self.total_days - self.used_days


class Advance(db.Model):
    __tablename__ = 'advances'
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    date = db.Column(db.Date, default=date.today)
    reason = db.Column(db.String(200))
    status = db.Column(db.String(20), default='pending')  # pending, approved, deducted
    month_deducted = db.Column(db.Integer)
    year_deducted = db.Column(db.Integer)


class Payroll(db.Model):
    __tablename__ = 'payrolls'
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False)
    month = db.Column(db.Integer, nullable=False)
    year = db.Column(db.Integer, nullable=False)
    working_days = db.Column(db.Integer, default=26)
    present_days = db.Column(db.Float, default=0.0)
    basic_salary = db.Column(db.Float, default=0.0)
    overtime_hours = db.Column(db.Float, default=0.0)
    overtime_pay = db.Column(db.Float, default=0.0)
    hra = db.Column(db.Float, default=0.0)
    other_allowances = db.Column(db.Float, default=0.0)
    gross_salary = db.Column(db.Float, default=0.0)
    pf_deduction = db.Column(db.Float, default=0.0)
    esi_deduction = db.Column(db.Float, default=0.0)
    advance_deduction = db.Column(db.Float, default=0.0)
    other_deductions = db.Column(db.Float, default=0.0)
    total_deductions = db.Column(db.Float, default=0.0)
    net_salary = db.Column(db.Float, default=0.0)
    status = db.Column(db.String(20), default='draft')  # draft, finalized, paid
    generated_on = db.Column(db.DateTime, default=datetime.utcnow)
    paid_on = db.Column(db.DateTime)
    sms_sent = db.Column(db.Boolean, default=False)
    __table_args__ = (db.UniqueConstraint('employee_id', 'month', 'year', name='uq_emp_month_year'),)


class Holiday(db.Model):
    __tablename__ = 'holidays'
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, unique=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(300))
    year = db.Column(db.Integer)
    is_active = db.Column(db.Boolean, default=True)


class SchoolSchedule(db.Model):
    __tablename__ = 'school_schedules'
    id = db.Column(db.Integer, primary_key=True)
    year = db.Column(db.Integer, nullable=False, unique=True)
    session_start = db.Column(db.Date, nullable=False)
    session_end = db.Column(db.Date, nullable=False)
    semester1_start = db.Column(db.Date)
    semester1_end = db.Column(db.Date)
    semester2_start = db.Column(db.Date)
    semester2_end = db.Column(db.Date)
    notes = db.Column(db.String(500))
    created_on = db.Column(db.DateTime, default=datetime.utcnow)


class AuditLog(db.Model):
    __tablename__ = 'audit_logs'
    id = db.Column(db.Integer, primary_key=True)
    action = db.Column(db.String(100), nullable=False)  # e.g., 'delete_holiday', 'approve_leave', 'password_reset'
    user = db.Column(db.String(80), nullable=False)  # username who performed action
    affected_entity = db.Column(db.String(200))  # e.g., 'Holiday:123', 'Leave:456'
    details = db.Column(db.String(500))  # extra details about the action
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class PasswordReset(db.Model):
    __tablename__ = 'password_resets'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    token = db.Column(db.String(100), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    is_used = db.Column(db.Boolean, default=False)
    user = db.relationship('User', backref='password_resets')


class AttendanceLock(db.Model):
    __tablename__ = 'attendance_locks'
    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey('schools.id'), nullable=True)
    month = db.Column(db.Integer, nullable=False)
    year = db.Column(db.Integer, nullable=False)
    locked_on = db.Column(db.DateTime, default=datetime.utcnow)
    locked_by = db.Column(db.String(80))
    __table_args__ = (db.UniqueConstraint('school_id', 'month', 'year', name='uq_lock_school_month_year'),)


class AppConfig(db.Model):
    __tablename__ = 'app_config'
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.Text)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @classmethod
    def get(cls, key, default=None):
        row = cls.query.filter_by(key=key).first()
        return row.value if row else default

    @classmethod
    def set(cls, key, value):
        row = cls.query.filter_by(key=key).first()
        if row:
            row.value = value
            row.updated_at = datetime.utcnow()
        else:
            row = cls(key=key, value=value)
            db.session.add(row)

