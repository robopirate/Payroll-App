from datetime import date

from models import db, Employee, Department, School, Attendance, User
from services.attendance_service import (
    compute_late_minutes,
    compute_early_minutes,
    update_attendance_timing_flags,
)


def test_compute_late_minutes_with_grace():
    # Shift starts at 09:00, grace 15 min -> threshold 09:15
    assert compute_late_minutes('09:10', '09:00', 15) == 0
    assert compute_late_minutes('09:15', '09:00', 15) == 0
    assert compute_late_minutes('09:20', '09:00', 15) == 5
    assert compute_late_minutes('10:00', '09:00', 15) == 45


def test_compute_early_minutes():
    # Shift ends at 18:00
    assert compute_early_minutes('18:00', '18:00') == 0
    assert compute_early_minutes('17:30', '18:00') == 30
    assert compute_early_minutes('12:00', '18:00') == 360


def test_update_attendance_timing_flags(app):
    with app.app_context():
        dept = Department(name='Test Dept')
        db.session.add(dept)
        db.session.commit()

        school = School(
            name='Baner Office',
            shift_start='09:00',
            shift_end='18:00',
            grace_minutes=15,
            is_active=True,
        )
        db.session.add(school)
        db.session.commit()

        emp = Employee(
            emp_id='EMP007',
            name='Shift Employee',
            phone='9876543215',
            department_id=dept.id,
            basic_salary=30000,
            joining_date=date(2024, 1, 1),
        )
        emp.schools.append(school)
        db.session.add(emp)
        db.session.commit()

        att = Attendance(
            employee_id=emp.id,
            date=date(2025, 1, 6),
            status='present',
            check_in='09:30',
            check_out='17:00',
        )
        db.session.add(att)
        db.session.commit()

        update_attendance_timing_flags(att)

        assert att.late_minutes == 15
        assert att.early_minutes == 60


def test_update_attendance_timing_flags_uses_employee_shift_override(app):
    with app.app_context():
        dept = Department(name='Override Dept')
        db.session.add(dept)
        db.session.commit()

        school = School(
            name='Default Shift Office',
            shift_start='09:00',
            shift_end='18:00',
            grace_minutes=15,
            is_active=True,
        )
        db.session.add(school)
        db.session.commit()

        emp = Employee(
            emp_id='EMP009',
            name='Prasad',
            phone='9876543217',
            department_id=dept.id,
            basic_salary=30000,
            joining_date=date(2024, 1, 1),
            shift_start='14:00',
            shift_end='20:00',
        )
        emp.schools.append(school)
        db.session.add(emp)
        db.session.commit()

        att = Attendance(
            employee_id=emp.id,
            date=date(2025, 1, 6),
            status='present',
            check_in='14:05',
            check_out='19:55',
        )
        db.session.add(att)
        db.session.commit()

        update_attendance_timing_flags(att)

        # Within 14:15 grace window, and left 5 min before 20:00
        assert att.late_minutes == 0
        assert att.early_minutes == 5


def test_admin_attendance_save_computes_late_and_early(client, app):
    with app.app_context():
        admin = User(username='admin', is_admin=True, role='admin')
        admin.set_password('admin123')
        db.session.add(admin)

        dept = Department(name='Test Dept')
        db.session.add(dept)
        db.session.commit()

        school = School(
            name='Baner Office',
            shift_start='09:00',
            shift_end='18:00',
            grace_minutes=15,
            is_active=True,
        )
        db.session.add(school)
        db.session.commit()

        emp = Employee(
            emp_id='EMP008',
            name='Admin Shift Employee',
            phone='9876543216',
            department_id=dept.id,
            basic_salary=30000,
            joining_date=date(2024, 1, 1),
        )
        emp.schools.append(school)
        db.session.add(emp)
        db.session.commit()
        emp_id = emp.id

    client.post('/login', data={
        'username': 'admin',
        'password': 'admin123',
    }, follow_redirects=True)

    selected_date = '2025-01-06'
    resp = client.post('/attendance', data={
        f'status_{emp_id}': 'present',
        f'checkin_{emp_id}': '09:35',
        f'checkout_{emp_id}': '17:10',
        f'ot_{emp_id}': '0',
    }, query_string={'date': selected_date}, follow_redirects=True)

    assert resp.status_code == 200

    with app.app_context():
        att = Attendance.query.filter_by(employee_id=emp_id, date=date(2025, 1, 6)).first()
        assert att is not None
        assert att.late_minutes == 20
        assert att.early_minutes == 50
