import os
import requests
import re
import time

BASE = 'https://payroll-app-xd1d.onrender.com'
ADMIN_PASSWORD = os.environ.get('LIVE_ADMIN_PASSWORD', 'Om@090909')
EMP_PHONE = os.environ.get('LIVE_EMP_PHONE', '7039368447')
EMP_PASSWORD = os.environ.get('LIVE_EMP_PASSWORD', 'Omkar@123')
print('='*60)
print('LIVE RENDER SITE FEATURE TEST')
print(f'URL: {BASE}')
print('='*60)
print()

# The live app may still be serving a cached/old dashboard, so accept both
# the pre-redesign labels and the current glassmorphism labels.
def has_any(text, *labels):
    return any(label in text for label in labels)

def first_match(text, *labels):
    for label in labels:
        if label in text:
            return label
    return 'none'

def safe_get(session, url, timeout=30, backoff=15):
    """GET with a single retry on HTTP 429 (rate limit)."""
    r = session.get(url, timeout=timeout)
    if r.status_code == 429:
        print(f'   RATE LIMIT ({url}), waiting {backoff}s...')
        time.sleep(backoff)
        r = session.get(url, timeout=timeout)
    return r

# Give any previous run's rate-limit window time to cool down.
print('Waiting 10s to clear any prior rate-limit window...')
time.sleep(10)

# === ADMIN LOGIN ===
s = requests.Session()
r = s.get(f'{BASE}/login', timeout=30)
csrf = re.search(r'csrf_token.*value="([^"]+)"', r.text).group(1)
print(f'1. GET /login: {r.status_code} (CSRF ok: {len(csrf)>0})')

time.sleep(1.5)
r = s.post(f'{BASE}/login', data={'username': 'admin', 'password': ADMIN_PASSWORD, 'csrf_token': csrf},
           headers={'Referer': f'{BASE}/login'}, timeout=30)
admin_logged_in = r.url.rstrip('/').endswith('/dashboard')
print(f'2. POST /login: {r.status_code}, URL: {r.url}')
print(f'   Login success: {admin_logged_in}')
if not admin_logged_in:
    print('   WARNING: admin login failed - admin panel checks will be skipped.')
print()

# === ADMIN DASHBOARD ===
print('=== ADMIN DASHBOARD ===')
if admin_logged_in:
    time.sleep(1.5)
    r = s.get(f'{BASE}/dashboard', timeout=30)
    print(f'3. GET /dashboard: {r.status_code}')
    print(f'   Has Dashboard text: {"Dashboard" in r.text}')
    print(f'   Has employee stat: {has_any(r.text, "Active Employees", "Total Employees")} ({first_match(r.text, "Active Employees", "Total Employees")})')
    print(f'   Has Present Today: {"Present Today" in r.text}')
    print(f'   Has Pending Leaves: {"Pending Leaves" in r.text}')
    print(f'   Has Pending Advances / Absent Today: {has_any(r.text, "Pending Advances", "Absent Today")}')
    print(f'   Has location stat: {has_any(r.text, "Locations", "Schools")} ({first_match(r.text, "Locations", "Schools")})')
    print(f'   Has Recent Payroll: {"Recent Payroll" in r.text}')
    print(f'   Has Mark Attendance: {"Mark Attendance" in r.text}')
    print(f'   Has Add Employee: {"Add Employee" in r.text}')
    print(f'   Has Manage Leaves: {"Manage Leaves" in r.text}')
    print(f'   Has Generate Payroll: {"Generate Payroll" in r.text}')
    print(f'   Has Track Advances: {"Track Advances" in r.text}')
    print(f'   Has Manage Locations: {"Manage Locations" in r.text}')
    print(f'   Has Send SMS: {"Send SMS" in r.text}')
    print(f'   Has Departments: {"Departments" in r.text}')
    print(f'   Has Settings: {"Settings" in r.text}')
    print(f'   Page size: {len(r.text)} bytes')

    emp_match = re.search(r'(Active Employees|Total Employees)[\s\S]*?(\d+)', r.text)
    present_match = re.search(r'Present Today[\s\S]*?(\d+)', r.text)
    leave_match = re.search(r'Pending Leaves[\s\S]*?(\d+)', r.text)
    absent_match = re.search(r'Absent Today[\s\S]*?(\d+)', r.text)
    adv_match = re.search(r'Pending Advances[\s\S]*?(\d+)', r.text)
    print(f'   Stats: Active/Total={emp_match.group(2) if emp_match else "N/A"}, '
          f'Present={present_match.group(1) if present_match else "N/A"}, '
          f'PendingLeaves={leave_match.group(1) if leave_match else "N/A"}, '
          f'Absent={absent_match.group(1) if absent_match else "N/A"}, '
          f'PendingAdvances={adv_match.group(1) if adv_match else "N/A"}')
else:
    print('3. GET /dashboard: skipped (admin not logged in)')
print()

# === ADMIN PANEL ROUTES ===
print('=== ADMIN PANEL ROUTES ===')
routes = [
    ('/employees', 'Employees'),
    ('/employees/add', 'Add Employee'),
    ('/attendance', 'Attendance'),
    ('/attendance?date=2026-06-20', 'Attendance with date'),
    ('/payroll', 'Payroll'),
    ('/payroll?month=6&year=2026', 'Payroll with params'),
    ('/schools', 'Schools'),
    ('/schools/add', 'Add School'),
    ('/settings', 'Settings'),
    ('/departments', 'Departments'),
    ('/holidays', 'Holidays'),
    ('/advances', 'Advances'),
    ('/sms', 'SMS Panel'),
    ('/export/employees', 'Export Employees'),
]

if admin_logged_in:
    for i, (route, name) in enumerate(routes, 4):
        time.sleep(1.5)
        r = safe_get(s, f'{BASE}{route}')
        status = 'OK' if r.status_code == 200 else f'FAIL({r.status_code})'
        print(f'{i}. GET {route}: {status} ({name})')
else:
    i = 3
    print('   (skipped - admin not logged in)')
print()

# === EMPLOYEE PORTAL ===
print('=== EMPLOYEE PORTAL ===')
emp = requests.Session()
time.sleep(1.5)
r = emp.get(f'{BASE}/portal/login', timeout=30)
csrf = re.search(r'csrf_token.*value="([^"]+)"', r.text).group(1)
print(f'{i+1}. GET /portal/login: {r.status_code}')

time.sleep(1.5)
r = emp.post(f'{BASE}/portal/login', data={'phone': EMP_PHONE, 'password': EMP_PASSWORD, 'csrf_token': csrf},
             headers={'Referer': f'{BASE}/portal/login'}, timeout=30)
portal_logged_in = r.url.rstrip('/').endswith('/portal/dashboard')
i += 1
print(f'{i+1}. POST /portal/login: {r.status_code}, URL: {r.url}')
print(f'    Login success: {portal_logged_in}')
if not portal_logged_in:
    print('    WARNING: portal login failed - portal and API checks will be skipped.')

portal_routes = [
    ('/portal/dashboard', 'Portal Dashboard'),
    ('/portal/punch', 'Portal Punch'),
    ('/portal/attendance', 'Portal Attendance'),
    ('/portal/leaves', 'Portal Leaves'),
    ('/portal/payslips', 'Portal Payslips'),
]

if portal_logged_in:
    for route, name in portal_routes:
        i += 1
        time.sleep(1.5)
        r = safe_get(emp, f'{BASE}{route}')
        status = 'OK' if r.status_code == 200 else f'FAIL({r.status_code})'
        print(f'{i+1}. GET {route}: {status} ({name})')
else:
    print('    (skipped - portal not logged in)')
print()

# === API TESTS ===
print('=== API TESTS ===')
time.sleep(1.5)
if portal_logged_in:
    r = requests.post(f'{BASE}/api/v1/auth/login', json={'phone': EMP_PHONE, 'password': EMP_PASSWORD}, timeout=30)
else:
    r = requests.Response()
    r.status_code = 0
i += 1
print(f'{i+1}. POST /api/v1/auth/login: {r.status_code}')
if r.status_code == 401:
    print('    WARNING: employee phone/password mismatch on live DB - update these credentials manually')
token = r.json().get('access_token') if r.status_code == 200 else None
print(f'    Token received: {token is not None}')

if token and portal_logged_in:
    api_endpoints = [
        ('/api/v1/auth/me', 'GET', 'Auth Me'),
        ('/api/v1/employee/profile', 'GET', 'Profile'),
        ('/api/v1/attendance/today', 'GET', 'Today'),
        ('/api/v1/attendance/monthly', 'GET', 'Monthly'),
        ('/api/v1/leaves', 'GET', 'Leaves'),
        ('/api/v1/payroll', 'GET', 'Payroll'),
        ('/api/v1/holidays', 'GET', 'Holidays'),
        ('/api/v1/auth/logout', 'POST', 'Logout'),
    ]
    for route, method, name in api_endpoints:
        i += 1
        time.sleep(1.5)
        if method == 'GET':
            r = requests.get(f'{BASE}{route}', headers={'Authorization': f'Bearer {token}'}, timeout=30)
        else:
            r = requests.post(f'{BASE}{route}', headers={'Authorization': f'Bearer {token}'}, timeout=30)
        status = 'OK' if r.status_code in [200, 201] else f'FAIL({r.status_code})'
        print(f'{i+1}. {method} {route}: {status} ({name})')
    
    i += 1
    time.sleep(1.5)
    r = requests.get(f'{BASE}/api/v1/auth/me', headers={'Authorization': f'Bearer {token}'}, timeout=30)
    print(f'{i+1}. GET /api/v1/auth/me after logout: {r.status_code} (should be 401)')
print()

# === SWAGGER ===
print('=== SWAGGER ===')
time.sleep(1.5)
r = requests.get(f'{BASE}/api/docs/', timeout=30)
print(f'GET /api/docs/: {r.status_code}')
time.sleep(1.5)
r = requests.get(f'{BASE}/apispec_1.json', timeout=30)
print(f'GET /apispec_1.json: {r.status_code}')
print()

print('='*60)
print('TEST COMPLETE')
print('='*60)
