from models import db, User


def test_login_page(client):
    resp = client.get('/login')
    assert resp.status_code == 200


def test_portal_login_page(client):
    resp = client.get('/portal/login')
    assert resp.status_code == 200


def test_admin_login(client, app):
    with app.app_context():
        admin = User(username='admin', is_admin=True)
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()

    resp = client.post('/login', data={
        'username': 'admin',
        'password': 'admin123',
    }, follow_redirects=True)
    assert resp.status_code == 200
