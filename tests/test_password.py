from datetime import date

from models import db, User, Employee, Department, PasswordReset


def _login_admin(client):
    client.post('/login', data={
        'username': 'admin',
        'password': 'admin123',
    }, follow_redirects=True)


def _make_admin(app):
    with app.app_context():
        admin = User(username='admin', is_admin=True, role='admin')
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()


def test_forgot_password_fails_without_sms_config(client, app):
    """If SMS cannot be sent, no token should be saved and an error is shown."""
    _make_admin(app)
    with app.app_context():
        dept = Department(name='HRPwd')
        db.session.add(dept)
        db.session.commit()
        emp = Employee(
            emp_id='EMP100', name='Test', phone='9876543210',
            department_id=dept.id, basic_salary=10000, joining_date=date(2024, 1, 1),
        )
        db.session.add(emp)
        db.session.commit()
        user = User(username='9876543210', employee_id=emp.id, is_admin=False)
        user.set_password('oldpass')
        db.session.add(user)
        db.session.commit()

    resp = client.post('/forgot-password', data={'phone': '9876543210'}, follow_redirects=True)
    assert resp.status_code == 200
    assert b'Could not send reset SMS' in resp.data

    with app.app_context():
        assert PasswordReset.query.count() == 0


def test_forgot_password_success_with_mock_sms(client, app, monkeypatch):
    """When SMS succeeds, a token is saved and user is redirected to reset page."""
    _make_admin(app)
    with app.app_context():
        dept = Department(name='HRPwd')
        db.session.add(dept)
        db.session.commit()
        emp = Employee(
            emp_id='EMP101', name='Test', phone='9876543211',
            department_id=dept.id, basic_salary=10000, joining_date=date(2024, 1, 1),
        )
        db.session.add(emp)
        db.session.commit()
        user = User(username='9876543211', employee_id=emp.id, is_admin=False)
        user.set_password('oldpass')
        db.session.add(user)
        db.session.commit()

    monkeypatch.setattr('blueprints.auth.send_sms', lambda phone, msg: (True, 'Sent'))

    resp = client.post('/forgot-password', data={'phone': '9876543211'}, follow_redirects=False)
    assert resp.status_code == 302
    assert '/reset-password?token=' in resp.location

    with app.app_context():
        assert PasswordReset.query.count() == 1


def test_admin_add_employee_with_password(client, app):
    _make_admin(app)
    with app.app_context():
        dept = Department(name='HRPwd')
        db.session.add(dept)
        db.session.commit()

    _login_admin(client)
    resp = client.post('/employees/add', data={
        'emp_id': 'EMP102',
        'name': 'New Hire',
        'phone': '9876543212',
        'department_id': '',
        'basic_salary': '20000',
        'password': 'hirepass123',
    }, follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        emp = Employee.query.filter_by(emp_id='EMP102').first()
        assert emp is not None
        user = User.query.filter_by(employee_id=emp.id).first()
        assert user is not None
        assert user.check_password('hirepass123')


def test_admin_edit_employee_with_password(client, app):
    _make_admin(app)
    with app.app_context():
        dept = Department(name='HRPwd')
        db.session.add(dept)
        db.session.commit()
        emp = Employee(
            emp_id='EMP103', name='Existing', phone='9876543213',
            department_id=dept.id, basic_salary=20000, joining_date=date(2024, 1, 1),
        )
        db.session.add(emp)
        db.session.commit()
        emp_id = emp.id

    _login_admin(client)
    resp = client.post(f'/employees/{emp_id}/edit', data={
        'name': 'Existing Updated',
        'phone': '9876543213',
        'basic_salary': '25000',
        'password': 'updatedpass',
    }, follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        user = User.query.filter_by(employee_id=emp_id).first()
        assert user is not None
        assert user.check_password('updatedpass')


def test_admin_set_employee_password(client, app):
    _make_admin(app)
    with app.app_context():
        dept = Department(name='HRPwd')
        db.session.add(dept)
        db.session.commit()
        emp = Employee(
            emp_id='EMP104', name='No User', phone='9876543214',
            department_id=dept.id, basic_salary=20000, joining_date=date(2024, 1, 1),
        )
        db.session.add(emp)
        db.session.commit()
        emp_id = emp.id

    _login_admin(client)
    resp = client.post(f'/employees/{emp_id}/set_password', data={
        'new_password': 'portalpass',
    }, follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        user = User.query.filter_by(employee_id=emp_id).first()
        assert user is not None
        assert user.check_password('portalpass')
