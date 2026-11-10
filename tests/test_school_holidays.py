"""Per-school / per-office holidays."""
from datetime import date

from models import db, Employee, Department, School, Attendance, User, Holiday, Leave
from services.attendance_service import (
    ensure_absent_attendance,
    count_working_days_between,
    calculate_paid_days,
    holidays_for_employee,
)


def _setup(app):
    """Two schools (A, B) with one employee each, plus one at both, one at none."""
    dept = Department(name='Dept')
    a = School(name='School A', is_active=True)
    b = School(name='School B', is_active=True)
    db.session.add_all([dept, a, b])
    db.session.commit()

    def emp(code, phone, schools):
        e = Employee(emp_id=code, name=code, phone=phone, department_id=dept.id,
                     basic_salary=30000, joining_date=date(2024, 1, 1),
                     is_active=True, is_approved=True)
        e.schools = schools
        db.session.add(e)
        return e

    ea = emp('EA', '9000000001', [a])
    eb = emp('EB', '9000000002', [b])
    eab = emp('EAB', '9000000003', [a, b])
    en = emp('ENONE', '9000000004', [])
    db.session.commit()
    return a, b, ea, eb, eab, en


def test_scoped_holiday_only_closes_listed_school(app):
    with app.app_context():
        a, b, ea, eb, eab, en = _setup(app)
        day = date(2025, 6, 4)  # Wednesday
        db.session.add(Holiday(date=day, name='A vacation', year=2025, schools=[a]))
        db.session.commit()

        ensure_absent_attendance(day)

        have = {x.employee_id for x in Attendance.query.filter_by(date=day).all()}
        assert ea.id not in have            # School A closed -> no absent mark
        assert eb.id in have                # School B open -> absent if no punch
        assert eab.id in have               # works at A and B; B is open
        assert en.id in have                # no school -> unaffected


def test_global_holiday_closes_everyone(app):
    with app.app_context():
        a, b, ea, eb, eab, en = _setup(app)
        day = date(2025, 6, 4)
        db.session.add(Holiday(date=day, name='Natl', year=2025))
        db.session.commit()
        ensure_absent_attendance(day)
        assert Attendance.query.filter_by(date=day).count() == 0


def test_multi_school_employee_off_only_when_all_schools_closed(app):
    with app.app_context():
        a, b, ea, eb, eab, en = _setup(app)
        d1, d2 = date(2025, 6, 4), date(2025, 6, 5)
        db.session.add(Holiday(date=d1, name='A only', year=2025, schools=[a]))
        db.session.add(Holiday(date=d2, name='A and B', year=2025, schools=[a, b]))
        db.session.commit()

        assert count_working_days_between(d1, d1, eab) == 1   # B still open
        assert count_working_days_between(d2, d2, eab) == 0   # both closed
        assert count_working_days_between(d1, d1, ea) == 0
        assert count_working_days_between(d1, d1, en) == 1    # no school
        assert count_working_days_between(d1, d1) == 1        # no employee -> global only


def test_paid_days_unrecorded_scoped_holiday_counts_only_for_that_school(app):
    with app.app_context():
        a, b, ea, eb, eab, en = _setup(app)
        # June 2025: 30 days. Close School A for Mon 2 - Fri 6 June (5 days).
        for n in range(2, 7):
            db.session.add(Holiday(date=date(2025, 6, n), name='Vac', year=2025, schools=[a]))
        db.session.commit()

        # No attendance rows at all: only Sundays (5 in June 2025) + closed days are paid.
        assert calculate_paid_days(ea, 2025, 6) == 5 + 5
        assert calculate_paid_days(eb, 2025, 6) == 5


def test_holidays_for_employee_filters_list(app):
    with app.app_context():
        a, b, ea, eb, eab, en = _setup(app)
        db.session.add(Holiday(date=date(2025, 6, 4), name='Global', year=2025))
        db.session.add(Holiday(date=date(2025, 6, 5), name='A', year=2025, schools=[a]))
        db.session.add(Holiday(date=date(2025, 6, 6), name='B', year=2025, schools=[b]))
        db.session.commit()
        names = lambda e: [h.name for h in holidays_for_employee(e, date(2025, 6, 1), date(2025, 6, 30))]
        assert names(ea) == ['Global', 'A']
        assert names(eb) == ['Global', 'B']
        assert names(en) == ['Global']


# ── Admin page ────────────────────────────────────────────────────────────────

def _admin_client(client, app):
    with app.app_context():
        u = User(username='admin', is_admin=True, role='admin')
        u.set_password('admin123')
        db.session.add(u)
        db.session.commit()
    client.post('/login', data={'username': 'admin', 'password': 'admin123'})
    return client


def test_admin_adds_range_for_selected_school_skipping_sundays(client, app):
    with app.app_context():
        a, b, *_ = _setup(app)
        a_id, b_id = a.id, b.id
    _admin_client(client, app)

    # Mon 2 June -> Sun 8 June 2025 for School A only
    resp = client.post('/holidays', data={
        'date': '2025-06-02', 'end_date': '2025-06-08', 'name': 'Summer break',
        'scope': 'selected', 'school_ids': [str(a_id)],
    }, follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        rows = Holiday.query.order_by(Holiday.date).all()
        assert [h.date.day for h in rows] == [2, 3, 4, 5, 6, 7]   # Sunday 8th skipped
        assert all([s.id for s in h.schools] == [a_id] for h in rows)

    # School B vacation overlapping the same days extends the existing rows
    client.post('/holidays', data={
        'date': '2025-06-05', 'end_date': '2025-06-06', 'name': 'B break',
        'scope': 'selected', 'school_ids': [str(b_id)],
    })
    with app.app_context():
        h5 = Holiday.query.filter_by(date=date(2025, 6, 5)).first()
        assert {s.id for s in h5.schools} == {a_id, b_id}
        h3 = Holiday.query.filter_by(date=date(2025, 6, 3)).first()
        assert {s.id for s in h3.schools} == {a_id}


def test_admin_selected_scope_requires_a_school(client, app):
    _admin_client(client, app)
    resp = client.post('/holidays', data={
        'date': '2025-06-02', 'name': 'X', 'scope': 'selected',
    }, follow_redirects=True)
    assert b'at least one school' in resp.data
    with app.app_context():
        assert Holiday.query.count() == 0


def test_admin_default_scope_is_everyone_and_page_renders(client, app):
    _admin_client(client, app)
    client.post('/holidays', data={'date': '2025-06-02', 'name': 'Everyone day'})
    with app.app_context():
        h = Holiday.query.one()
        assert h.is_global
    resp = client.get('/holidays')
    assert resp.status_code == 200
    assert b'Everyone day' in resp.data


# ── Clearing automatic absent marks when a holiday is added late ─────────────

def test_adding_holiday_clears_only_auto_absent_for_closed_school(client, app):
    with app.app_context():
        a, b, ea, eb, eab, en = _setup(app)
        a_id = a.id
        day = date(2025, 6, 4)
        rows = {}
        # Auto-created absent marks for everyone (as the nightly job would do)
        for e in (ea, eb, en):
            r = Attendance(employee_id=e.id, date=day, status='absent', admin_override=False)
            db.session.add(r)
        # A School A teacher who really punched in and was marked absent by hand
        punched = Employee(emp_id='EP', name='EP', phone='9000000009', department_id=ea.department_id,
                           basic_salary=30000, joining_date=date(2024, 1, 1),
                           is_active=True, is_approved=True)
        punched.schools = [a]
        db.session.add(punched)
        db.session.commit()
        db.session.add(Attendance(employee_id=punched.id, date=day, status='absent', admin_override=True))
        db.session.commit()
        ids = {'ea': ea.id, 'eb': eb.id, 'en': en.id, 'p': punched.id}
    _admin_client(client, app)

    resp = client.post('/holidays', data={
        'date': '2025-06-04', 'name': 'A closed', 'scope': 'selected', 'school_ids': [str(a_id)],
    }, follow_redirects=True)
    assert b'Removed 1 automatic' in resp.data

    with app.app_context():
        left = {x.employee_id for x in Attendance.query.filter_by(date=day).all()}
        assert ids['ea'] not in left        # School A, auto-absent -> cleared
        assert ids['eb'] in left            # School B untouched
        assert ids['en'] in left            # no school untouched
        assert ids['p'] in left             # admin-edited row kept
