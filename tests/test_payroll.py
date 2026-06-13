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
