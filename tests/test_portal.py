"""Tests for the employee self-service portal."""
from models import db, User, Employee, Department, School


def _portal_login(client, phone, password='secret'):
    return client.post('/portal/login', data={
        'phone': phone,
        'password': password,
    }, follow_redirects=True)


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

        portal_user = User(username='portal_user', is_admin=False, employee_id=emp.id)
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

        portal_user = User(username='portal_user2', is_admin=False, employee_id=emp.id)
        portal_user.set_password('secret')
        db.session.add(portal_user)
        db.session.commit()

    resp = _portal_login(client, '9876543211')
    assert resp.status_code == 200

    resp = client.get('/portal/punch')
    assert resp.status_code == 200
    assert b'Not Assigned' in resp.data
