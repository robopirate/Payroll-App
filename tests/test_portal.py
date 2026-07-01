"""Tests for the employee self-service portal."""
from models import db, User, Employee, Department, School


def _portal_login(client, phone, password='secret'):
    return client.post('/portal/login', data={
        'phone': phone,
        'password': password,
    }, follow_redirects=True)


def _make_approved_employee(app, phone, emp_id='EMP201'):
    with app.app_context():
        dept = Department.query.filter_by(name='Test Dept').first()
        if not dept:
            dept = Department(name='Test Dept')
            db.session.add(dept)
            db.session.commit()

        emp = Employee(
            emp_id=emp_id, name='Portal User', phone=phone,
            department_id=dept.id, basic_salary=20000, is_approved=True
        )
        db.session.add(emp)
        db.session.commit()

        portal_user = User(username=phone, is_admin=False, employee_id=emp.id)
        portal_user.set_password('secret')
        db.session.add(portal_user)
        db.session.commit()
        return emp.id


def test_portal_punch_renders_with_location(client, app):
    """The punch page should render when employee has an assigned school."""
    with app.app_context():
        dept = Department(name='Test Dept')
        db.session.add(dept)
        db.session.commit()

        school = School(name='Test School', address='Test Address', latitude=12.34, longitude=56.78, geofence_radius=100)
        db.session.add(school)
        db.session.commit()

        emp = Employee(
            emp_id='EMP201', name='Portal User', phone='9876543210',
            department_id=dept.id, basic_salary=20000, is_approved=True
        )
        emp.schools.append(school)
        db.session.add(emp)
        db.session.commit()

        portal_user = User(username='9876543210', is_admin=False, employee_id=emp.id)
        portal_user.set_password('secret')
        db.session.add(portal_user)
        db.session.commit()

    resp = _portal_login(client, '9876543210')
    assert resp.status_code == 200

    resp = client.get('/portal/punch')
    assert resp.status_code == 200
    assert b'Punch In/Out' in resp.data
    assert b'Test School' in resp.data


def test_portal_punch_renders_without_location(client, app):
    """The punch page should render gracefully when no school is assigned."""
    with app.app_context():
        dept = Department(name='Test Dept')
        db.session.add(dept)
        db.session.commit()

        emp = Employee(
            emp_id='EMP202', name='Portal User 2', phone='9876543211',
            department_id=dept.id, basic_salary=20000, is_approved=True
        )
        db.session.add(emp)
        db.session.commit()

        portal_user = User(username='9876543211', is_admin=False, employee_id=emp.id)
        portal_user.set_password('secret')
        db.session.add(portal_user)
        db.session.commit()

    resp = _portal_login(client, '9876543211')
    assert resp.status_code == 200

    resp = client.get('/portal/punch')
    assert resp.status_code == 200
    assert b'Not Assigned' in resp.data


def test_portal_profile_renders(client, app):
    """The profile page should display editable fields for the employee."""
    _make_approved_employee(app, '9876543212', emp_id='EMP203')
    resp = _portal_login(client, '9876543212')
    assert resp.status_code == 200

    resp = client.get('/portal/profile')
    assert resp.status_code == 200
    assert b'My Profile' in resp.data
    assert b'Portal User' in resp.data
    assert b'Contact Details' in resp.data
    assert b'Bank Details' in resp.data
    assert b'ID Proofs' in resp.data


def test_portal_profile_update(client, app):
    """Employees can update their own contact, address, bank and ID details."""
    emp_id = _make_approved_employee(app, '9876543213', emp_id='EMP204')
    resp = _portal_login(client, '9876543213')
    assert resp.status_code == 200

    resp = client.post('/portal/profile', data={
        'phone': '9876543213',
        'email': 'portal.user@example.com',
        'address': '123 Test Lane, Pune',
        'bank_name': 'Test Bank',
        'account_number': '1234567890',
        'ifsc_code': 'TEST0001234',
        'pan_number': 'ABCDE1234F',
        'aadhar_number': '123456789012',
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b'Profile updated successfully' in resp.data

    with app.app_context():
        emp = Employee.query.get(emp_id)
        assert emp.email == 'portal.user@example.com'
        assert emp.address == '123 Test Lane, Pune'
        assert emp.bank_name == 'Test Bank'
        assert emp.account_number == '1234567890'
        assert emp.ifsc_code == 'TEST0001234'
        assert emp.pan_number == 'ABCDE1234F'
        assert emp.aadhar_number == '123456789012'


def test_portal_profile_cannot_update_salary(client, app):
    """The profile form must not allow editing salary or department."""
    emp_id = _make_approved_employee(app, '9876543214', emp_id='EMP205')
    resp = _portal_login(client, '9876543214')
    assert resp.status_code == 200

    # The route ignores any extra fields that are not in the allowed list.
    resp = client.post('/portal/profile', data={
        'phone': '9876543214',
        'basic_salary': '999999',
        'designation': 'CEO',
        'department_id': '99',
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b'Profile updated successfully' in resp.data

    with app.app_context():
        emp = Employee.query.get(emp_id)
        assert emp.basic_salary == 20000
        assert emp.designation is None
        assert emp.department_id != 99


def test_portal_profile_phone_unique(client, app):
    """Employees cannot change their phone number to one already in use."""
    _make_approved_employee(app, '9876543215', emp_id='EMP206')
    _make_approved_employee(app, '9876543216', emp_id='EMP207')
    resp = _portal_login(client, '9876543215')
    assert resp.status_code == 200

    resp = client.post('/portal/profile', data={
        'phone': '9876543216',
        'email': '',
        'address': '',
        'bank_name': '',
        'account_number': '',
        'ifsc_code': '',
        'pan_number': '',
        'aadhar_number': '',
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b'already registered' in resp.data or b'already linked' in resp.data


def test_portal_bottom_nav_links_present(client, app):
    """The bottom navigation and Punch FAB should appear on every portal page."""
    _make_approved_employee(app, '9876543217', emp_id='EMP208')
    resp = _portal_login(client, '9876543217')
    assert resp.status_code == 200

    for endpoint in ['/portal/dashboard', '/portal/punch', '/portal/attendance',
                     '/portal/payslips', '/portal/leaves', '/portal/profile']:
        resp = client.get(endpoint)
        assert resp.status_code == 200
        assert b'Home' in resp.data
        assert b'Attendance' in resp.data
        assert b'Payslips' in resp.data
        assert b'Leaves' in resp.data
        # The Punch FAB is a separate fixed link to /portal/punch.
        assert b'/portal/punch' in resp.data
        assert b'punch-fab' in resp.data
