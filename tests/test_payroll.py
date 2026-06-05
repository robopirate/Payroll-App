from datetime import date
from models import db, Employee, Department
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
