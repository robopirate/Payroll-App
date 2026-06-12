import os
import pytest

# Force the app to use an in-memory SQLite database during tests.
os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
os.environ['TESTING'] = '1'

from app import app as flask_app, db as database  # noqa: E402
from extensions import limiter  # noqa: E402
from services.login_protection import DEFAULT_FILE  # noqa: E402


@pytest.fixture
def app():
    flask_app.config.update({
        'TESTING': True,
        'WTF_CSRF_ENABLED': False,
        'FAST2SMS_API_KEY': '',
    })
    # Disable Flask-Limiter in tests; file-based brute-force tests enable it explicitly.
    limiter.enabled = False
    with flask_app.app_context():
        database.create_all()
        yield flask_app
        database.session.remove()
        database.drop_all()


@pytest.fixture(autouse=True)
def clean_brute_force_file():
    """Remove stale file-based brute-force state between test runs."""
    try:
        if os.path.exists(DEFAULT_FILE):
            os.remove(DEFAULT_FILE)
    except Exception:
        pass


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def runner(app):
    return app.test_cli_runner()
