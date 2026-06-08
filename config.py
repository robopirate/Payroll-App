import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'payroll-secret-key-change-in-production')
    # Store database outside project folder so code updates don't wipe data
    DB_PATH = os.environ.get('DB_PATH', os.path.join(os.path.expanduser('~'), 'payroll.db'))
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'DATABASE_URL',
        'sqlite:///' + DB_PATH
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # Fast2SMS API Key
    FAST2SMS_API_KEY = os.environ.get('FAST2SMS_API_KEY', '')
    # Payroll settings
    OVERTIME_RATE_MULTIPLIER = 2.0   # overtime hourly rate = (basic/26/8) * multiplier
    PF_RATE = 0.12                   # 12% of basic
    ESI_RATE = 0.0175                # 1.75% of gross (if gross <= 21000)
    ESI_THRESHOLD = 21000
    HRA_RATE = 0.40                  # 40% of basic
    WORKING_DAYS_PER_MONTH = 26
    WORKING_HOURS_PER_DAY = 8
