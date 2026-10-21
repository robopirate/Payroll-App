"""Tests for missed punch-out corrections (regularization)."""
from datetime import date, timedelta

from models import (
    db, User, Employee, Department, Attendance, AttendanceLock, AuditLog,
    AppConfig, Payroll, AttendanceRegularization,
)
from services import regularization_service as svc
from services.attendance_service import today_ist, calculate_paid_days

TODAY = date(2026, 3, 10)


def _employee(app, phone='9876500001', emp_id='EMP900'):
    dept = Department.query.filter_by(name='RegDept').first()
    if not dept:
        dept = Department(name='RegDept')
        db.session.add(dept)
        db.session.commit()
    emp = Employee(emp_id=emp_id, name='Baban', phone=phone, department_id=dept.id,
                   basic_salary=26000, joining_date=date(2026, 1, 1), is_approved=True)
    db.session.add(emp)
    db.session.commit()
    user = User(username=phone, is_admin=False, employee_id=emp.id)
    user.set_password('secret')
    db.session.add(user)
    db.session.commit()
    return emp


def _auto_closed_day(emp, day):
    """A day the system closed as a half day because of a missed punch-out."""
    att = Attendance(employee_id=emp.id, date=day, status='half_day', check_in='09:00',
                     check_out='17:00', auto_checkout=1)
    db.session.add(att)
    db.session.commit()
    return att


def _open_day(emp, day):
    """A day with a punch-in and no punch-out yet (before the nightly auto-close)."""
    att = Attendance(employee_id=emp.id, date=day, status='present', check_in='09:00')
    db.session.add(att)
    db.session.commit()
    return att


# ─── Rules ────────────────────────────────────────────────────────────────────

def test_needs_correction_for_auto_closed_and_open_days(app):
    emp = _employee(app)
    closed = _auto_closed_day(emp, TODAY - timedelta(days=2))
    opened = _open_day(emp, TODAY - timedelta(days=1))
    normal = Attendance(employee_id=emp.id, date=TODAY - timedelta(days=3),
                        status='present', check_in='09:00', check_out='17:00')
    db.session.add(normal)
    db.session.commit()
    assert svc.needs_correction(closed, TODAY)
    assert svc.needs_correction(opened, TODAY)
    assert not svc.needs_correction(normal, TODAY)
    # today's own open record is not a "missed" punch yet
    assert not svc.needs_correction(_open_day(emp, TODAY), TODAY)


def test_request_allowed_within_window_and_refused_after(app):
    emp = _employee(app)
    recent = _auto_closed_day(emp, TODAY - timedelta(days=3))
    old = _auto_closed_day(emp, TODAY - timedelta(days=4))
    assert svc.check_can_request(emp, recent, TODAY)[0] is True
    ok, msg = svc.check_can_request(emp, old, TODAY)
    assert ok is False and 'within 3 days' in msg


def test_monthly_cap_refuses_fourth_request(app):
    emp = _employee(app)
    db.session.add(AppConfig(key='regularization_window_days', value='10'))
    db.session.commit()
    days = [_auto_closed_day(emp, date(2026, 3, d)) for d in (1, 2, 3, 4)]
    for att in days[:3]:
        ok, msg = svc.submit_request(emp, att, '17:30', 'battery died', today=TODAY)
        assert ok, msg
    ok, msg = svc.submit_request(emp, days[3], '17:30', 'again', today=TODAY)
    assert ok is False and 'used all 3' in msg


def test_one_open_request_per_day(app):
    emp = _employee(app)
    att = _auto_closed_day(emp, TODAY - timedelta(days=1))
    assert svc.submit_request(emp, att, '17:30', 'reason', today=TODAY)[0]
    ok, msg = svc.submit_request(emp, att, '18:00', 'again', today=TODAY)
    assert ok is False and 'already exists' in msg


def test_locked_month_refuses_request_and_approval(app):
    emp = _employee(app)
    att = _auto_closed_day(emp, TODAY - timedelta(days=1))
    assert svc.submit_request(emp, att, '17:30', 'reason', today=TODAY)[0]
    reg = AttendanceRegularization.query.one()
    db.session.add(AttendanceLock(school_id=None, month=3, year=2026, locked_by='admin'))
    db.session.commit()
    other = _auto_closed_day(emp, TODAY - timedelta(days=2))
    assert svc.check_can_request(emp, other, TODAY)[0] is False
    ok, msg, _w = svc.approve(reg, 'admin')
    assert ok is False and 'locked' in msg
    assert db.session.get(Attendance, att.id).status == 'half_day'


def test_finalized_payroll_blocks_approval_but_draft_only_warns(app):
    emp = _employee(app)
    att = _auto_closed_day(emp, TODAY - timedelta(days=1))
    svc.submit_request(emp, att, '17:30', 'reason', today=TODAY)
    reg = AttendanceRegularization.query.one()
    pay = Payroll(employee_id=emp.id, month=3, year=2026, status='finalized')
    db.session.add(pay)
    db.session.commit()
    ok, msg, _w = svc.approve(reg, 'admin')
    assert ok is False and 'finalized or paid' in msg

    pay.status = 'draft'
    db.session.commit()
    ok, msg, warning = svc.approve(reg, 'admin')
    assert ok is True and 'Regenerate' in warning


def test_request_validation(app):
    emp = _employee(app)
    att = _auto_closed_day(emp, TODAY - timedelta(days=1))
    assert 'reason' in svc.submit_request(emp, att, '17:30', '  ', today=TODAY)[1]
    assert 'after your punch-in' in svc.submit_request(emp, att, '08:00', 'x', today=TODAY)[1]
    assert 'like 17:30' in svc.submit_request(emp, att, 'abc', 'x', today=TODAY)[1]
    assert AttendanceRegularization.query.count() == 0


# ─── Approve / reject ─────────────────────────────────────────────────────────

def test_approve_makes_full_day_and_logs_it(app):
    emp = _employee(app)
    day = date(2026, 3, 9)
    att = _auto_closed_day(emp, day)
    before = calculate_paid_days(emp, 2026, 3)
    svc.submit_request(emp, att, '17:30', 'battery died', today=TODAY)
    reg = AttendanceRegularization.query.one()

    ok, msg, warning = svc.approve(reg, 'admin', 'ok')
    assert ok and warning == ''
    att = db.session.get(Attendance, att.id)
    assert (att.status, att.check_out, att.auto_checkout) == ('present', '17:30', 0)
    assert att.admin_override is True
    assert 'Regularized by admin' in att.notes
    assert calculate_paid_days(emp, 2026, 3) == before + 0.5

    log = AuditLog.query.filter_by(action='regularize_approve').one()
    assert log.user == 'admin' and log.affected_entity == f'Attendance:{att.id}'
    assert 'half_day -> present' in log.details

    # cannot be decided twice
    assert svc.approve(reg, 'admin')[0] is False


def test_reject_needs_note_and_keeps_half_day(app):
    emp = _employee(app)
    att = _auto_closed_day(emp, TODAY - timedelta(days=1))
    svc.submit_request(emp, att, '17:30', 'reason', today=TODAY)
    reg = AttendanceRegularization.query.one()
    assert svc.reject(reg, 'admin', '  ')[0] is False
    assert svc.reject(reg, 'admin', 'no proof')[0] is True
    assert db.session.get(Attendance, att.id).status == 'half_day'
    assert reg.admin_note == 'no proof'
    assert AuditLog.query.filter_by(action='regularize_reject').count() == 1


# ─── Employee screens and punch-out message ───────────────────────────────────

def _portal_login(client, phone):
    client.post('/portal/login', data={'phone': phone, 'password': 'secret'},
                follow_redirects=True)


def test_portal_shows_request_link_and_form_saves_request(client, app):
    emp = _employee(app)
    day = today_ist() - timedelta(days=1)
    att = _auto_closed_day(emp, day)
    _portal_login(client, emp.phone)

    page = client.get(f'/portal/attendance?month={day.month}&year={day.year}')
    assert b'Request correction' in page.data

    form = client.get(f'/portal/attendance/{att.id}/correct')
    assert form.status_code == 200 and b'What time did you leave' in form.data

    resp = client.post(f'/portal/attendance/{att.id}/correct',
                       data={'check_out': '17:30', 'reason': 'battery died'},
                       follow_redirects=True)
    assert b'Correction request sent' in resp.data
    assert AttendanceRegularization.query.one().status == 'pending'

    page = client.get(f'/portal/attendance?month={day.month}&year={day.year}')
    assert b'Correction pending' in page.data


def test_employee_cannot_open_someone_elses_day(client, app):
    mine = _employee(app, '9876500001', 'EMP900')
    other = _employee(app, '9876500002', 'EMP901')
    att = _auto_closed_day(other, today_ist() - timedelta(days=1))
    _portal_login(client, mine.phone)
    assert client.get(f'/portal/attendance/{att.id}/correct').status_code == 404
    resp = client.post(f'/portal/attendance/{att.id}/correct',
                       data={'check_out': '17:30', 'reason': 'x'})
    assert resp.status_code == 404
    assert AttendanceRegularization.query.count() == 0


def test_late_punch_out_points_to_request_correction(client, app):
    emp = _employee(app)
    yesterday = today_ist() - timedelta(days=1)
    open_day = _open_day(emp, yesterday)
    _portal_login(client, emp.phone)

    resp = client.post('/api/punch', json={'lat': 18.5, 'lng': 73.8, 'action': 'out'})
    data = resp.get_json()
    assert data['success'] is False
    assert 'Request correction' in data['message']
    # yesterday's record is untouched and no record was invented for today
    assert db.session.get(Attendance, open_day.id).check_out is None
    assert Attendance.query.filter_by(employee_id=emp.id, date=today_ist()).count() == 0
