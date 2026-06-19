"""Tests for admin security hardening (Phase 1 stabilization)."""
from io import BytesIO
import csv

from models import db, User, Employee, Department


def _create_admin(app, password='admin123', must_change=False):
    with app.app_context():
        admin = User(username='admin', is_admin=True, role='admin', must_change_password=must_change)
        admin.set_password(password)
        db.session.add(admin)
        db.session.commit()
        return admin


def _login(client, password='admin123'):
    return client.post('/login', data={
        'username': 'admin',
        'password': password,
    }, follow_redirects=True)


def test_admin_force_password_change(client, app):
    """First login with must_change_password=True redirects to settings."""
    _create_admin(app, password='temppass', must_change=True)
    resp = _login(client, password='temppass')
    assert resp.status_code == 200
    assert b'Change Password' in resp.data or b'Settings' in resp.data

    # Change password via settings
    resp = client.post('/settings', data={
        'new_password': 'NewStrongPass1',
        'confirm_password': 'NewStrongPass1',
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b'Password updated' in resp.data

    # Flag should now be cleared
    with app.app_context():
        admin = User.query.filter_by(username='admin').first()
        assert admin.must_change_password is False
        assert admin.check_password('NewStrongPass1') is True


def test_employee_list_masks_phone(client, app):
    """Phone numbers in employee list are masked."""
    _create_admin(app)
    with app.app_context():
        dept = Department(name='Test Dept')
        db.session.add(dept)
        db.session.commit()
        emp = Employee(
            emp_id='EMP101', name='Test Teacher', phone='9876543210',
            department_id=dept.id, basic_salary=25000, is_approved=True
        )
        db.session.add(emp)
        db.session.commit()

    _login(client)
    resp = client.get('/employees')
    assert resp.status_code == 200
    assert b'98****3210' in resp.data
    assert b'9876543210' not in resp.data


def test_employee_export_masks_pii(client, app):
    """CSV export masks phone, PAN, Aadhar and account number."""
    _create_admin(app)
    with app.app_context():
        dept = Department(name='Test Dept')
        db.session.add(dept)
        db.session.commit()
        emp = Employee(
            emp_id='EMP102', name='Test Teacher', phone='9876543210',
            department_id=dept.id, basic_salary=25000, is_approved=True,
            account_number='12345678901', pan_number='ABCDE1234F',
            aadhar_number='123456789012'
        )
        db.session.add(emp)
        db.session.commit()

    _login(client)
    resp = client.get('/export/employees')
    assert resp.status_code == 200
    rows = list(csv.reader(BytesIO(resp.data).read().decode().splitlines()))
    # Header + 1 data row
    assert len(rows) == 2
    data = rows[1]
    assert data[2] == '98****3210'
    assert data[9].startswith('12') and '*' in data[9]
    assert data[11] == 'AB****234F'
    assert data[12] == '1234 **** ****'


def test_backup_route_disabled(client, app):
    """The insecure backup download route is removed."""
    _create_admin(app)
    _login(client)
    resp = client.get('/backup')
    assert resp.status_code == 404
