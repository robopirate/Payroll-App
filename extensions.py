"""Flask extensions initialized here to avoid circular imports."""
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_jwt_extended import JWTManager
from config import Config

db = SQLAlchemy()
login_manager = LoginManager()
csrf = CSRFProtect()
jwt = JWTManager()
limiter = Limiter(
    get_remote_address,
    default_limits=["200 per day", "50 per hour", "10 per minute"],
    storage_uri=Config.RATELIMIT_STORAGE_URI,
)
