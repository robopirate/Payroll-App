"""Remove TestUser employees and all their related data from the database.

Run this in the Render shell (or locally) after setting DATABASE_URL:

    python scripts/remove_test_users.py
"""
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from app import app
from models import db, Employee, Payroll, Attendance, Leave, Advance, LeaveBalance, User


def remove_test_users():
    with app.app_context():
        test_emps = Employee.query.filter(Employee.name.ilike('TestUser')).all()
        if not test_emps:
            print('No TestUser employees found.')
            return

        for emp in test_emps:
            print(f'Removing {emp.name} ({emp.emp_id}, id={emp.id}) ...')
            Payroll.query.filter_by(employee_id=emp.id).delete()
            Attendance.query.filter_by(employee_id=emp.id).delete()
            Leave.query.filter_by(employee_id=emp.id).delete()
            Advance.query.filter_by(employee_id=emp.id).delete()
            LeaveBalance.query.filter_by(employee_id=emp.id).delete()
            User.query.filter_by(employee_id=emp.id).delete()
            db.session.delete(emp)

        db.session.commit()
        print(f'Deleted {len(test_emps)} TestUser employee(s) and all related data.')


if __name__ == '__main__':
    remove_test_users()
