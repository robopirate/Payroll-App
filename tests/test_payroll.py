from datetime import date
from models import db, Employee, Department, Leave, Advance, Attendance, School
from services.payroll_service import calculate_payroll


def test_calculate_payroll_basic(app):
    with app.app_context():
        dept = Department(name='Test Dept')
        db.session.add(dept)
        db.session.commit()

        emp = Employee(
            emp_id='EMP001',
            name='Test Employee',
            phone='9876543210',
            department_id=dept.id,
            basic_salary=26000,
            joining_date=date(2024, 1, 1),
        )
        db.session.add(emp)
        db.session.commit()

        result = calculate_payroll(emp, month=1, year=2025)
        assert result['working_days'] > 0
        assert result['basic_salary'] >= 0
        assert result['gross_salary'] >= result['basic_salary']
        assert result['net_salary'] <= result['gross_salary']
        assert result['pf_deduction'] >= 0


def test_calculate_payroll_multimonth_leave(app):
    """A leave spanning two months must be counted in both months."""
    with app.app_context():
        dept = Department(name='Test Dept')
        db.session.add(dept)
        db.session.commit()

        emp = Employee(
            emp_id='EMP002',
            name='Test Employee 2',
            phone='9876543211',
            department_id=dept.id,
            basic_salary=26000,
            joining_date=date(2024, 1, 1),
        )
        db.session.add(emp)
        db.session.commit()

        # June 25 to July 5: 25,26,27,28,29,30 June + 1,2,3,4,5 July
        # Working days in June portion: exclude Sunday if any.
        leave = Leave(
            employee_id=emp.id,
            leave_type='casual',
            start_date=date(2025, 6, 25),
            end_date=date(2025, 7, 5),
            days=8.0,
            status='approved',
        )
        db.session.add(leave)
        db.session.commit()

        june = calculate_payroll(emp, month=6, year=2025)
        july = calculate_payroll(emp, month=7, year=2025)

        assert june['present_days'] > 0, 'June payroll should include leave days'
        assert july['present_days'] > 0, 'July payroll should include leave days'
        assert june['present_days'] != july['present_days'] or june['present_days'] > 0


def test_calculate_payroll_negative_net_is_clamped(app):
    """Net salary should never be negative; large advances are clamped to zero."""
    with app.app_context():
        dept = Department(name='Test Dept')
        db.session.add(dept)
        db.session.commit()

        emp = Employee(
            emp_id='EMP003',
            name='Test Employee 3',
            phone='9876543212',
            department_id=dept.id,
            basic_salary=10000,
            joining_date=date(2024, 1, 1),
        )
        db.session.add(emp)
        db.session.commit()

        # Large advance that would make net negative
        advance = Advance(
            employee_id=emp.id,
            amount=50000,
            status='approved',
            month_deducted=1,
            year_deducted=2025,
        )
        db.session.add(advance)
        db.session.commit()

        result = calculate_payroll(emp, month=1, year=2025)
        assert result['net_salary'] == 0
        assert result['net_negative_clamped'] is True


def test_calculate_payroll_uses_location_working_hours(app):
    """Overtime pay must use the employee's location working hours per day."""
    with app.app_context():
        dept = Department(name='Test Dept')
        db.session.add(dept)
        db.session.commit()

        school = School(
            name='Baner Office',
            working_hours_per_day=7.0,
            is_active=True,
        )
        db.session.add(school)
        db.session.commit()

        emp = Employee(
            emp_id='EMP004',
            name='Test Employee 4',
            phone='9876543213',
            department_id=dept.id,
            basic_salary=26000,
            joining_date=date(2024, 1, 1),
        )
        emp.schools.append(school)
        db.session.add(emp)
        db.session.commit()

        # Default 8-hour location employee for comparison
        emp_default = Employee(
            emp_id='EMP005',
            name='Test Employee 5',
            phone='9876543214',
            department_id=dept.id,
            basic_salary=26000,
            joining_date=date(2024, 1, 1),
        )
        db.session.add(emp_default)
        db.session.commit()

        # Record one present day with 1 overtime hour for both employees
        db.session.add(Attendance(
            employee_id=emp.id,
            date=date(2025, 1, 6),
            status='present',
            overtime_hours=1.0,
        ))
        db.session.add(Attendance(
            employee_id=emp_default.id,
            date=date(2025, 1, 6),
            status='present',
            overtime_hours=1.0,
        ))
        db.session.commit()

        result = calculate_payroll(emp, month=1, year=2025)
        result_default = calculate_payroll(emp_default, month=1, year=2025)

        # 26000 / 26 / 7 * 2 ≈ 285.71 -> rounded 286
        # 26000 / 26 / 8 * 2 = 250
        assert result['overtime_pay'] > result_default['overtime_pay']
        assert result['overtime_pay'] == 286
        assert result_default['overtime_pay'] == 250


def test_calculate_payroll_uses_employee_working_hours_override(app):
    """Employee-level working_hours_per_day must override the school's value."""
    with app.app_context():
        dept = Department(name='Override Dept')
        db.session.add(dept)
        db.session.commit()

        school = School(
            name='Eight Hour Office',
            working_hours_per_day=8.0,
            is_active=True,
        )
        db.session.add(school)
        db.session.commit()

        emp = Employee(
            emp_id='EMP006',
            name='Part Timer',
            phone='9876543215',
            department_id=dept.id,
            basic_salary=26000,
            joining_date=date(2024, 1, 1),
            working_hours_per_day=6.0,
        )
        emp.schools.append(school)
        db.session.add(emp)
        db.session.commit()

        # Default employee at same school, no override
        emp_default = Employee(
            emp_id='EMP007',
            name='Full Timer',
            phone='9876543216',
            department_id=dept.id,
            basic_salary=26000,
            joining_date=date(2024, 1, 1),
        )
        emp_default.schools.append(school)
        db.session.add(emp_default)
        db.session.commit()

        db.session.add(Attendance(
            employee_id=emp.id,
            date=date(2025, 1, 6),
            status='present',
            overtime_hours=1.0,
        ))
        db.session.add(Attendance(
            employee_id=emp_default.id,
            date=date(2025, 1, 6),
            status='present',
            overtime_hours=1.0,
        ))
        db.session.commit()

        result = calculate_payroll(emp, month=1, year=2025)
        result_default = calculate_payroll(emp_default, month=1, year=2025)

        # 26000 / 26 / 6 * 2 ≈ 333.33 -> rounded 333
        # 26000 / 26 / 8 * 2 = 250
        assert result['overtime_pay'] > result_default['overtime_pay']
        assert result['overtime_pay'] == 333
        assert result_default['overtime_pay'] == 250


def _free_leave_employee(app):
    dept = Department(name='FL Dept')
    db.session.add(dept)
    db.session.commit()
    emp = Employee(emp_id='EMPFL', name='FL', phone='9876500001',
                   department_id=dept.id, basic_salary=30000,
                   joining_date=date(2024, 1, 1))
    db.session.add(emp)
    db.session.commit()
    return emp


def _mark_month(emp, year, month, absent_days):
    """Present on every Mon-Sat except absent_days (Absent)."""
    from calendar import monthrange
    from models import Attendance
    for d in range(1, monthrange(year, month)[1] + 1):
        day = date(year, month, d)
        if day.weekday() == 6:
            continue
        db.session.add(Attendance(
            employee_id=emp.id, date=day,
            status='absent' if d in absent_days else 'present'))
    db.session.commit()


def test_one_absent_day_is_paid(app):
    from services.attendance_service import calculate_paid_days
    with app.app_context():
        emp = _free_leave_employee(app)
        _mark_month(emp, 2026, 10, absent_days={7})
        # 31 days - 0 unpaid (1 absent is free)
        assert calculate_paid_days(emp, 2026, 10) == 31.0


def test_extra_absent_days_are_cut(app):
    from services.attendance_service import calculate_paid_days
    with app.app_context():
        emp = _free_leave_employee(app)
        _mark_month(emp, 2026, 10, absent_days={7, 8, 9})
        # 3 absent: 1 free, 2 cut -> 31 - 2
        assert calculate_paid_days(emp, 2026, 10) == 29.0


def test_leave_and_absent_share_the_one_free_day(app):
    from services.attendance_service import calculate_paid_days
    with app.app_context():
        emp = _free_leave_employee(app)
        _mark_month(emp, 2026, 10, absent_days={7, 8})
        db.session.add(Leave(employee_id=emp.id, leave_type='casual',
                             start_date=date(2026, 10, 7), end_date=date(2026, 10, 7),
                             days=1.0, status='approved'))
        db.session.commit()
        # Oct 7 (leave+absent same day) and Oct 8 absent: 2 off days, 1 free
        assert calculate_paid_days(emp, 2026, 10) == 30.0
