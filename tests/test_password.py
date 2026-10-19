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


def _make_portal_user(app, emp_id, phone):
    """Create an employee with a portal login; return the user id."""
    with app.app_context():
        dept = Department.query.filter_by(name='HRPwd').first()
        if not dept:
            dept = Department(name='HRPwd')
            db.session.add(dept)
            db.session.commit()
        emp = Employee(
            emp_id=emp_id, name='Test', phone=phone,
            department_id=dept.id, basic_salary=10000, joining_date=date(2024, 1, 1),
        )
        db.session.add(emp)
        db.session.commit()
        user = User(username=phone, employee_id=emp.id, is_admin=False)
        user.set_password('oldpass')
        db.session.add(user)
        db.session.commit()
        return user.id


GENERIC = b'If that number is registered'


def test_forgot_password_sms_failure_saves_no_token(client, app):
    """If SMS cannot be sent, no token is saved and the reply stays generic."""
    _make_admin(app)
    _make_portal_user(app, 'EMP100', '9876543210')

    resp = client.post('/forgot-password', data={'phone': '9876543210'}, follow_redirects=True)
    assert resp.status_code == 200
    assert GENERIC in resp.data
    assert b'Could not send' not in resp.data

    with app.app_context():
        assert PasswordReset.query.count() == 0


def test_forgot_password_never_exposes_token_to_requester(client, app, monkeypatch):
    """The reset link goes ONLY to the phone by SMS, never to the browser."""
    _make_admin(app)
    _make_portal_user(app, 'EMP101', '9876543211')
    sent = []
    monkeypatch.setattr('blueprints.auth.send_sms', lambda phone, msg: (sent.append((phone, msg)) or (True, 'Sent')))

    resp = client.post('/forgot-password', data={'phone': '9876543211'}, follow_redirects=False)
    assert resp.status_code == 302
    assert 'token' not in resp.location

    with app.app_context():
        reset = PasswordReset.query.one()
        token = reset.token

    assert len(sent) == 1 and sent[0][0] == '9876543211'
    assert token in sent[0][1]

    page = client.post('/forgot-password', data={'phone': '9876543211'}, follow_redirects=True)
    assert token not in page.get_data(as_text=True)
    assert token not in resp.get_data(as_text=True)


def test_forgot_password_same_reply_for_unknown_number(client, app, monkeypatch):
    """Unknown numbers get the same reply and trigger no SMS (no account probing)."""
    _make_admin(app)
    sent = []
    monkeypatch.setattr('blueprints.auth.send_sms', lambda phone, msg: (sent.append(phone) or (True, 'Sent')))

    resp = client.post('/forgot-password', data={'phone': '9000000000'}, follow_redirects=True)
    assert GENERIC in resp.data
    assert sent == []
    with app.app_context():
        assert PasswordReset.query.count() == 0


def test_forgot_password_does_not_reset_admin_account(client, app, monkeypatch):
    """An admin login linked to an employee must not be resettable by phone."""
    with app.app_context():
        dept = Department(name='HRPwd')
        db.session.add(dept)
        db.session.commit()
        emp = Employee(emp_id='EMP105', name='Boss', phone='9876543215',
                       department_id=dept.id, basic_salary=1, joining_date=date(2024, 1, 1))
        db.session.add(emp)
        db.session.commit()
        boss = User(username='boss', employee_id=emp.id, is_admin=True, role='admin')
        boss.set_password('bosspass')
        db.session.add(boss)
        db.session.commit()
    sent = []
    monkeypatch.setattr('blueprints.auth.send_sms', lambda phone, msg: (sent.append(phone) or (True, 'Sent')))

    client.post('/forgot-password', data={'phone': '9876543215'}, follow_redirects=True)
    assert sent == []
    with app.app_context():
        assert PasswordReset.query.count() == 0


def test_reset_password_with_sms_token_works_once(client, app, monkeypatch):
    """Full flow: token from the SMS resets the password, and only once."""
    _make_admin(app)
    user_id = _make_portal_user(app, 'EMP106', '9876543216')
    monkeypatch.setattr('blueprints.auth.send_sms', lambda phone, msg: (True, 'Sent'))
    client.post('/forgot-password', data={'phone': '9876543216'})
    with app.app_context():
        token = PasswordReset.query.one().token

    resp = client.post('/reset-password', data={
        'token': token, 'new_password': 'brandnew1', 'confirm_password': 'brandnew1',
    }, follow_redirects=True)
    assert b'Password reset successfully' in resp.data
    with app.app_context():
        assert db.session.get(User, user_id).check_password('brandnew1')

    again = client.post('/reset-password', data={
        'token': token, 'new_password': 'another22', 'confirm_password': 'another22',
    }, follow_redirects=True)
    assert b'Invalid or expired' in again.data
    with app.app_context():
        assert db.session.get(User, user_id).check_password('brandnew1')


def test_reset_password_rejects_expired_token(client, app):
    from datetime import datetime, timedelta
    _make_admin(app)
    user_id = _make_portal_user(app, 'EMP107', '9876543217')
    with app.app_context():
        db.session.add(PasswordReset(
            user_id=user_id, token='expired-token',
            expires_at=datetime.utcnow() - timedelta(hours=2)))
        db.session.commit()

    resp = client.post('/reset-password', data={
        'token': 'expired-token', 'new_password': 'brandnew1', 'confirm_password': 'brandnew1',
    }, follow_redirects=True)
    assert b'Invalid or expired' in resp.data
    with app.app_context():
        assert db.session.get(User, user_id).check_password('oldpass')


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
