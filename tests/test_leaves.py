"""Tests for leave cancellation/deletion from admin and employee portal."""
from datetime import date, timedelta

from models import db, User, Employee, Department, Leave, LeaveBalance


def _create_admin(app, password='admin123'):
    with app.app_context():
        admin = User(username='admin', is_admin=True, role='admin')
        admin.set_password(password)
        db.session.add(admin)
        db.session.commit()
        return admin


def _login_admin(client, password='admin123'):
    return client.post('/login', data={
        'username': 'admin',
        'password': password,
    }, follow_redirects=True)


def _create_employee(app, emp_id='EMP001', phone='9876543210', name='Test Employee'):
    with app.app_context():
        dept = Department.query.filter_by(name='Test Dept').first()
        if not dept:
            dept = Department(name='Test Dept')
            db.session.add(dept)
            db.session.commit()
        emp = Employee(
            emp_id=emp_id,
            name=name,
            phone=phone,
            department_id=dept.id,
            basic_salary=25000,
            joining_date=date(2024, 1, 1),
            is_active=True,
            is_approved=True,
        )
        db.session.add(emp)
        db.session.commit()
        portal_user = User(username=emp_id.lower(), employee_id=emp.id, is_admin=False)
        portal_user.set_password('portal123')
        db.session.add(portal_user)
        db.session.commit()
        return emp.id


def _login_portal(client, phone='9876543210', password='portal123'):
    return client.post('/portal/login', data={
        'phone': phone,
        'password': password,
    }, follow_redirects=True)


def test_admin_delete_leave_restores_balance(client, app):
    """Deleting an approved leave from admin should restore used balance."""
    _create_admin(app)
    emp_id = _create_employee(app)
    with app.app_context():
        emp = Employee.query.get(emp_id)
        balance = LeaveBalance(employee_id=emp.id, leave_type='casual', total_days=10, year=2025)
        leave = Leave(
            employee_id=emp.id,
            leave_type='casual',
            start_date=date(2025, 6, 1),
            end_date=date(2025, 6, 5),
            days=5.0,
            status='approved',
        )
        db.session.add_all([balance, leave])
        db.session.commit()
        leave_id = leave.id
        balance.used_days = 5.0
        db.session.commit()

    _login_admin(client)
    resp = client.post(f'/leaves/{leave_id}/delete', follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        assert Leave.query.get(leave_id) is None
        balance = LeaveBalance.query.filter_by(employee_id=emp_id, leave_type='casual', year=2025).first()
        assert balance.used_days == 0


def test_portal_cancel_pending_leave(client, app):
    """Employee can cancel their own pending leave."""
    emp_id = _create_employee(app)
    with app.app_context():
        emp = Employee.query.get(emp_id)
        leave = Leave(
            employee_id=emp.id,
            leave_type='sick',
            start_date=date(2025, 8, 1),
            end_date=date(2025, 8, 2),
            days=2.0,
            status='pending',
        )
        db.session.add(leave)
        db.session.commit()
        leave_id = leave.id

    _login_portal(client)
    resp = client.post(f'/portal/leaves/{leave_id}/cancel', follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        assert Leave.query.get(leave_id) is None


def test_portal_cancel_approved_future_restores_balance(client, app):
    """Cancelling an approved future leave restores used balance."""
    emp_id = _create_employee(app)
    with app.app_context():
        emp = Employee.query.get(emp_id)
        start = date.today() + timedelta(days=5)
        end = date.today() + timedelta(days=7)
        balance = LeaveBalance(employee_id=emp.id, leave_type='casual', total_days=10, year=start.year)
        leave = Leave(
            employee_id=emp.id,
            leave_type='casual',
            start_date=start,
            end_date=end,
            days=3.0,
            status='approved',
        )
        db.session.add_all([balance, leave])
        db.session.commit()
        leave_id = leave.id
        balance.used_days = 3.0
        db.session.commit()

    _login_portal(client)
    resp = client.post(f'/portal/leaves/{leave_id}/cancel', follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        assert Leave.query.get(leave_id) is None
        balance = LeaveBalance.query.filter_by(employee_id=emp_id, leave_type='casual', year=start.year).first()
        assert balance.used_days == 0


def test_portal_cancel_approved_past_blocked(client, app):
    """Employee cannot cancel an approved leave whose start date has passed."""
    emp_id = _create_employee(app)
    with app.app_context():
        emp = Employee.query.get(emp_id)
        balance = LeaveBalance(employee_id=emp.id, leave_type='casual', total_days=10, year=2020)
        leave = Leave(
            employee_id=emp.id,
            leave_type='casual',
            start_date=date(2020, 1, 1),
            end_date=date(2020, 1, 3),
            days=3.0,
            status='approved',
        )
        db.session.add_all([balance, leave])
        db.session.commit()
        leave_id = leave.id
        balance.used_days = 3.0
        db.session.commit()

    _login_portal(client)
    resp = client.post(f'/portal/leaves/{leave_id}/cancel', follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        assert Leave.query.get(leave_id) is not None
        balance = LeaveBalance.query.filter_by(employee_id=emp_id, leave_type='casual', year=2020).first()
        assert balance.used_days == 3.0


def test_portal_cannot_cancel_other_employee_leave(client, app):
    """Employee cannot cancel a leave belonging to someone else."""
    emp1_id = _create_employee(app, emp_id='EMP001', phone='9876543210', name='Employee One')
    emp2_id = _create_employee(app, emp_id='EMP002', phone='9876543211', name='Employee Two')
    with app.app_context():
        emp2 = Employee.query.get(emp2_id)
        leave = Leave(
            employee_id=emp2.id,
            leave_type='sick',
            start_date=date(2025, 9, 1),
            end_date=date(2025, 9, 2),
            days=2.0,
            status='pending',
        )
        db.session.add(leave)
        db.session.commit()
        leave_id = leave.id

    _login_portal(client, phone='9876543210')
    resp = client.post(f'/portal/leaves/{leave_id}/cancel', follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        assert Leave.query.get(leave_id) is not None


def test_portal_leaves_page_shows_cancel_button(client, app):
    """Pending leaves should display a Cancel button on the portal leaves page."""
    emp_id = _create_employee(app)
    with app.app_context():
        emp = Employee.query.get(emp_id)
        leave = Leave(
            employee_id=emp.id,
            leave_type='casual',
            start_date=date(2025, 10, 1),
            end_date=date(2025, 10, 2),
            days=2.0,
            status='pending',
        )
        db.session.add(leave)
        db.session.commit()

    _login_portal(client)
    resp = client.get('/portal/leaves')
    assert resp.status_code == 200
    assert b'Cancel' in resp.data


def test_admin_leaves_page_shows_delete_button(client, app):
    """Admin leave list should display a delete action for each leave."""
    _create_admin(app)
    emp_id = _create_employee(app)
    with app.app_context():
        emp = Employee.query.get(emp_id)
        leave = Leave(
            employee_id=emp.id,
            leave_type='sick',
            start_date=date(2025, 10, 5),
            end_date=date(2025, 10, 6),
            days=2.0,
            status='approved',
        )
        db.session.add(leave)
        db.session.commit()

    _login_admin(client)
    resp = client.get('/leaves?status=all')
    assert resp.status_code == 200
    assert b'bi-trash' in resp.data
