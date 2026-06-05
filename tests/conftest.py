import pytest
from app import app as flask_app, db as database


@pytest.fixture
def app():
    flask_app.config.update({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'WTF_CSRF_ENABLED': False,
        'FAST2SMS_API_KEY': '',
    })
    with flask_app.app_context():
        database.create_all()
        yield flask_app
        database.session.remove()
        database.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def runner(app):
    return app.test_cli_runner()
