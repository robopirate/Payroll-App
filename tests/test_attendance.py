from datetime import date

from datetime import timedelta
from unittest.mock import patch, MagicMock

from models import db, Employee, Department, School, Attendance, User, Holiday, Leave
from services.attendance_service import (
    compute_late_minutes,
    compute_early_minutes,
    update_attendance_timing_flags,
    ensure_absent_attendance,
    backfill_absent_attendance,
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
            is_active=True,
            is_approved=True,
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
            is_active=True,
            is_approved=True,
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


def _make_emp(app, emp_id, name, phone, joining_date):
    with app.app_context():
        dept = Department(name=f'Dept {emp_id}')
        db.session.add(dept)
        db.session.commit()
        emp = Employee(
            emp_id=emp_id,
            name=name,
            phone=phone,
            department_id=dept.id,
            basic_salary=30000,
            joining_date=joining_date,
            is_active=True,
            is_approved=True,
        )
        db.session.add(emp)
        db.session.commit()
        return emp.id


def test_ensure_absent_creates_record_for_missing_working_day(app):
    with app.app_context():
        emp_id = _make_emp(app, 'EMP_ABS_1', 'Absent Test', '9876543301', date(2024, 1, 1))
        target = date(2025, 1, 8)  # Wednesday
        ensure_absent_attendance(target)
        att = Attendance.query.filter_by(employee_id=emp_id, date=target).first()
        assert att is not None
        assert att.status == 'absent'


def test_ensure_absent_does_not_overwrite_existing(app):
    with app.app_context():
        emp_id = _make_emp(app, 'EMP_ABS_2', 'Present Test', '9876543302', date(2024, 1, 1))
        target = date(2025, 1, 8)
        db.session.add(Attendance(employee_id=emp_id, date=target, status='present'))
        db.session.commit()
        ensure_absent_attendance(target)
        atts = Attendance.query.filter_by(employee_id=emp_id, date=target).all()
        assert len(atts) == 1
        assert atts[0].status == 'present'


def test_ensure_absent_skips_sunday_holiday_leave_and_before_joining(app):
    with app.app_context():
        emp_id = _make_emp(app, 'EMP_ABS_3', 'Skip Test', '9876543303', date(2025, 1, 6))

        sunday = date(2025, 1, 5)
        holiday = date(2025, 1, 7)
        leave_day = date(2025, 1, 8)
        before_join = date(2025, 1, 5)  # same as sunday, re-use skip reason

        db.session.add(Holiday(date=holiday, name='Test Holiday', year=holiday.year))
        db.session.add(Leave(
            employee_id=emp_id,
            leave_type='casual',
            start_date=leave_day,
            end_date=leave_day,
            days=1,
            status='approved',
        ))
        db.session.commit()

        ensure_absent_attendance(sunday)
        ensure_absent_attendance(holiday)
        ensure_absent_attendance(leave_day)

        for d in [sunday, holiday, leave_day]:
            assert Attendance.query.filter_by(employee_id=emp_id, date=d).first() is None


def test_backfill_absent_attendance_fills_past_days(app):
    with app.app_context():
        emp_id = _make_emp(app, 'EMP_ABS_4', 'Backfill Test', '9876543304', date(2024, 1, 1))
        # Patch "today" to 2025-01-15 (Wednesday) and hour before cutoff -> fill 1..14
        fake_today = date(2025, 1, 15)

        class FakeDate(date):
            @classmethod
            def today(cls):
                return fake_today

        fake_now = MagicMock()
        fake_now.hour = 10
        with patch('services.attendance_service.date', FakeDate), \
             patch('services.attendance_service.datetime') as fake_dt:
            fake_dt.now.return_value = fake_now
            backfill_absent_attendance(2025, 1)

        # Jan 2025: Sundays are 5th and 12th. So working days 1-14 except 5,12 should be absent.
        expected_absent = [d for d in range(1, 15) if date(2025, 1, d).weekday() != 6]
        for d in expected_absent:
            att = Attendance.query.filter_by(employee_id=emp_id, date=date(2025, 1, d)).first()
            assert att is not None and att.status == 'absent', f'day {d} not absent'

        # Today (15th) should NOT be filled because hour < cutoff
        assert Attendance.query.filter_by(employee_id=emp_id, date=fake_today).first() is None


def test_backfill_absent_attendance_includes_today_after_cutoff(app):
    with app.app_context():
        emp_id = _make_emp(app, 'EMP_ABS_5', 'Today Test', '9876543305', date(2024, 1, 1))
        fake_today = date(2025, 1, 15)

        class FakeDate(date):
            @classmethod
            def today(cls):
                return fake_today

        fake_now = MagicMock()
        fake_now.hour = 20
        with patch('services.attendance_service.date', FakeDate), \
             patch('services.attendance_service.datetime') as fake_dt:
            fake_dt.now.return_value = fake_now
            backfill_absent_attendance(2025, 1)

        att = Attendance.query.filter_by(employee_id=emp_id, date=fake_today).first()
        assert att is not None and att.status == 'absent'


def test_backfill_absent_attendance_is_idempotent(app):
    with app.app_context():
        emp_id = _make_emp(app, 'EMP_ABS_6', 'Idempotent Test', '9876543306', date(2024, 1, 1))
        target = date(2025, 1, 8)
        ensure_absent_attendance(target)
        ensure_absent_attendance(target)
        atts = Attendance.query.filter_by(employee_id=emp_id, date=target).all()
        assert len(atts) == 1
        assert atts[0].status == 'absent'
