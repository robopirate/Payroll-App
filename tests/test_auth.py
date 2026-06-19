import os
import time

from models import db, User
from services.login_protection import DEFAULT_FILE


def test_login_page(client):
    resp = client.get('/login')
    assert resp.status_code == 200


def test_portal_login_page(client):
    resp = client.get('/portal/login')
    assert resp.status_code == 200


def test_admin_login(client, app):
    with app.app_context():
        admin = User(username='admin', is_admin=True, role='admin')
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()

    resp = client.post('/login', data={
        'username': 'admin',
        'password': 'admin123',
    }, follow_redirects=True)
    assert resp.status_code == 200


def test_employees_page_requires_login(client):
    resp = client.get('/employees', follow_redirects=True)
    assert resp.status_code == 200
    # Should land on login page
    assert b'Login' in resp.data or b'login' in resp.data.lower()


def test_employees_page_loads_after_login(client, app):
    """Smoke test that authenticated admin pages extending base.html render."""
    with app.app_context():
        admin = User(username='admin', is_admin=True, role='admin')
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()

    client.post('/login', data={
        'username': 'admin',
        'password': 'admin123',
    }, follow_redirects=True)

    resp = client.get('/employees')
    assert resp.status_code == 200
    # Footer with current year should render without Jinja error
    assert b'Robo Pirate' in resp.data


def test_admin_login_brute_force_throttle(client, app):
    """After 5 failed attempts the 6th should be throttled."""
    # Clear any previous attempts
    if os.path.exists(DEFAULT_FILE):
        os.remove(DEFAULT_FILE)

    with app.app_context():
        admin = User(username='admin', is_admin=True, role='admin')
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()

    for i in range(5):
        resp = client.post('/login', data={
            'username': 'admin',
            'password': 'wrongpassword',
        })
        assert resp.status_code == 200
        assert b'Too many login attempts' not in resp.data

    # 6th attempt should be throttled
    resp = client.post('/login', data={
        'username': 'admin',
        'password': 'wrongpassword',
    })
    assert resp.status_code == 200
    assert b'Too many login attempts' in resp.data

    # Cleanup
    if os.path.exists(DEFAULT_FILE):
        os.remove(DEFAULT_FILE)
