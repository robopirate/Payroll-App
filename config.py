import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'payroll-secret-key-change-in-production')
    # Store database outside project folder so code updates don't wipe data
    DB_PATH = os.environ.get('DB_PATH', os.path.join(os.path.expanduser('~'), 'payroll.db'))
    _database_url = os.environ.get('DATABASE_URL')
    if _database_url and _database_url.startswith('postgres://'):
        # Render provides postgres:// URLs; SQLAlchemy defaults to psycopg2.
        # Use psycopg 3 dialect (psycopg[binary]) which works on Python 3.14.
        _database_url = _database_url.replace('postgres://', 'postgresql+psycopg://', 1)
    SQLALCHEMY_DATABASE_URI = _database_url or 'sqlite:///' + DB_PATH
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # Session security
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = os.environ.get('SESSION_COOKIE_SECURE', 'False').lower() == 'true'
    SESSION_COOKIE_SAMESITE = 'Lax'
    PERMANENT_SESSION_LIFETIME = 86400  # 24 hours
    # JWT Configuration
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY', SECRET_KEY)
    JWT_ACCESS_TOKEN_EXPIRES = 900  # 15 minutes
    JWT_REFRESH_TOKEN_EXPIRES = 604800  # 7 days
    JWT_TOKEN_LOCATION = ['headers']
    JWT_HEADER_NAME = 'Authorization'
    JWT_HEADER_TYPE = 'Bearer'
    # Fast2SMS API Key
    FAST2SMS_API_KEY = os.environ.get('FAST2SMS_API_KEY', '')
    # Google Maps API Key (for Places Autocomplete on location form)
    GOOGLE_MAPS_API_KEY = os.environ.get('GOOGLE_MAPS_API_KEY', '')
    # Payroll settings
    OVERTIME_RATE_MULTIPLIER = 2.0   # overtime hourly rate = (basic/26/8) * multiplier
    PF_RATE = 0.12                   # 12% of basic
    ESI_RATE = 0.0175                # 1.75% of gross (if gross <= 21000)
    ESI_THRESHOLD = 21000
    HRA_RATE = 0.40                  # 40% of basic
    WORKING_DAYS_PER_MONTH = 26
    WORKING_HOURS_PER_DAY = 8
