import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    TESTING = os.environ.get('TESTING', 'False').lower() in ('true', '1')
    SECRET_KEY = os.environ.get('SECRET_KEY', 'payroll-secret-key-change-in-production')
    # Store database outside project folder so code updates don't wipe data
    DB_PATH = os.environ.get('DB_PATH', os.path.join(os.path.expanduser('~'), 'payroll.db'))
    _database_url = os.environ.get('DATABASE_URL')
    if _database_url:
        # Render provides postgres:// or postgresql:// URLs.
        # SQLAlchemy defaults to psycopg2, which does not work on Python 3.14.
        # Force the psycopg 3 dialect (installed via psycopg[binary]).
        if _database_url.startswith('postgres://'):
            _database_url = _database_url.replace('postgres://', 'postgresql+psycopg://', 1)
        elif _database_url.startswith('postgresql://'):
            _database_url = _database_url.replace('postgresql://', 'postgresql+psycopg://', 1)
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
    ESI_RATE = 0.0075                # employee contribution 0.75% of gross (if gross <= 21000)
    ESI_EMPLOYER_RATE = 0.0325       # employer contribution 3.25% of gross
    ESI_THRESHOLD = 21000
    PT_THRESHOLD = 7501              # Professional Tax deduction threshold
    PT_AMOUNT = 200                  # Professional Tax amount when gross >= threshold
    # LWF (Labour Welfare Fund) - Maharashtra rates (configurable per state)
    LWF_EMPLOYEE_AMOUNT = 25         # Employee contribution per month
    LWF_EMPLOYER_AMOUNT = 50         # Employer contribution per month
    LWF_THRESHOLD = 25000            # Only applicable if gross <= this amount

    # TDS (Income Tax) - FY 2024-25 New Regime Slabs
    TDS_STANDARD_DEDUCTION = 50000
    TDS_REBATE_87A_LIMIT = 700000    # Rebate under 87A - full tax waiver if taxable income <= 7L
    TDS_REBATE_87A_AMOUNT = 25000
    # Tax slabs: (min, max, rate)
    TDS_SLABS = [
        (0, 300000, 0.0),
        (300000, 600000, 0.05),
        (600000, 900000, 0.10),
        (900000, 1200000, 0.15),
        (1200000, 1500000, 0.20),
        (1500000, float('inf'), 0.30),
    ]
    HRA_RATE = 0.40                  # 40% of basic
    WORKING_DAYS_PER_MONTH = 26
    WORKING_HOURS_PER_DAY = 8
