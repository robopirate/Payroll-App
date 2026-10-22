"""Two guards: paid payslips are never rewritten, and a leave is decided only once."""
from datetime import date

from models import db, User, Employee, Department, Leave, LeaveBalance, Payroll, Attendance


def _admin_login(client, app):
    with app.app_context():
        admin = User(username='admin', is_admin=True, role='admin')
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()
    client.post('/login', data={'username': 'admin', 'password': 'admin123'},
                follow_redirects=True)


def _employee(app, emp_id='EMP001', phone='9876543210', name='Test Employee', salary=26000):
    with app.app_context():
        dept = Department.query.filter_by(name='GuardDept').first()
        if not dept:
            dept = Department(name='GuardDept')
            db.session.add(dept)
            db.session.commit()
        emp = Employee(emp_id=emp_id, name=name, phone=phone, department_id=dept.id,
                       basic_salary=salary, joining_date=date(2024, 1, 1), is_approved=True)
        db.session.add(emp)
        db.session.commit()
        return emp.id


# ─── Payroll lock ─────────────────────────────────────────────────────────────

def test_regenerating_payroll_leaves_paid_and_finalized_untouched(client, app):
    _admin_login(client, app)
    paid_id = _employee(app, 'EMP001', '9876543210', 'Paid Person')
    final_id = _employee(app, 'EMP002', '9876543211', 'Final Person')
    with app.app_context():
        for emp_id, status in ((paid_id, 'paid'), (final_id, 'finalized')):
            db.session.add(Payroll(employee_id=emp_id, month=1, year=2025, status=status,
                                   basic_salary=11111, gross_salary=11111, net_salary=11111))
        db.session.commit()

    resp = client.post('/payroll/generate', data={'month': '1', 'year': '2025'},
                       follow_redirects=True)
    assert b'Skipped' in resp.data and b'Paid Person' in resp.data and b'Final Person' in resp.data
    with app.app_context():
        rows = {p.employee_id: p for p in Payroll.query.all()}
        assert rows[paid_id].net_salary == 11111 and rows[paid_id].status == 'paid'
        assert rows[final_id].net_salary == 11111 and rows[final_id].status == 'finalized'


def test_regenerating_payroll_still_updates_drafts_and_creates_missing(client, app):
    _admin_login(client, app)
    draft_id = _employee(app, 'EMP001', '9876543210', 'Draft Person')
    new_id = _employee(app, 'EMP002', '9876543211', 'New Person')
    with app.app_context():
        db.session.add(Payroll(employee_id=draft_id, month=1, year=2025, status='draft',
                               basic_salary=1, gross_salary=1, net_salary=1))
        db.session.commit()

    client.post('/payroll/generate', data={'month': '1', 'year': '2025'}, follow_redirects=True)
    with app.app_context():
        rows = {p.employee_id: p for p in Payroll.query.all()}
        assert rows[draft_id].net_salary != 1          # recalculated
        assert rows[draft_id].status == 'draft'
        assert new_id in rows                           # created


# ─── Leave decided only once ──────────────────────────────────────────────────

def _pending_leave(app, days=2.0):
    emp_id = _employee(app)
    with app.app_context():
        year = date.today().year
        db.session.add(LeaveBalance(employee_id=emp_id, leave_type='casual',
                                    total_days=10, used_days=0, year=year))
        leave = Leave(employee_id=emp_id, leave_type='casual', days=days,
                      start_date=date(year, 6, 2), end_date=date(year, 6, 3), status='pending')
        db.session.add(leave)
        db.session.commit()
        return leave.id


def _used(app):
    with app.app_context():
        return LeaveBalance.query.one().used_days


def test_approving_twice_deducts_balance_only_once(client, app):
    _admin_login(client, app)
    leave_id = _pending_leave(app, days=2.0)

    client.post(f'/leaves/{leave_id}/approve', follow_redirects=True)
    assert _used(app) == 2.0
    resp = client.post(f'/leaves/{leave_id}/approve', follow_redirects=True)   # double click
    assert b'already approved' in resp.data
    assert _used(app) == 2.0


def test_cannot_reject_an_already_approved_leave(client, app):
    _admin_login(client, app)
    leave_id = _pending_leave(app, days=2.0)
    client.post(f'/leaves/{leave_id}/approve', follow_redirects=True)

    resp = client.post(f'/leaves/{leave_id}/reject', follow_redirects=True)
    assert b'already approved' in resp.data
    with app.app_context():
        assert db.session.get(Leave, leave_id).status == 'approved'
    assert _used(app) == 2.0                      # balance not left out of step


def test_delete_still_undoes_an_approved_leave(client, app):
    _admin_login(client, app)
    leave_id = _pending_leave(app, days=2.0)
    client.post(f'/leaves/{leave_id}/approve', follow_redirects=True)
    client.post(f'/leaves/{leave_id}/delete', follow_redirects=True)
    assert _used(app) == 0.0
