"""Flask extensions initialized here to avoid circular imports."""
from flask import request
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_jwt_extended import JWTManager
from flask_compress import Compress
from config import Config

db = SQLAlchemy()
login_manager = LoginManager()
csrf = CSRFProtect()
jwt = JWTManager()
compress = Compress()


def _exempt_static_and_health():
    """Default rate limits skip static assets and the uptime health ping.

    Every page view pulls many /static files, and all teachers on the same
    school network share one public IP — counting those against the API
    limit locks everyone out (10/min exhausted by one page load).
    """
    path = request.path
    return path.startswith('/static') or path == '/health'


limiter = Limiter(
    get_remote_address,
    default_limits=["3000 per day", "600 per hour", "60 per minute"],
    default_limits_exempt_when=_exempt_static_and_health,
    storage_uri=Config.RATELIMIT_STORAGE_URI,
)
