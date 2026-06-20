# PHASE 3: Bug Fix Sprint + SaaS Readiness
## Kimi Code Execution Prompt — Copy-Paste This Into Kimi Code

---

## PROJECT CONTEXT

**Project:** Robo Pirate Payroll App — A B2B HR/Attendance/Payroll SaaS for Indian schools
**Location:** `C:\Users\itsom\OneDrive\Documents\GitHub\Payroll App`
**Python:** `venv_new/Scripts/python.exe` (Windows)
**GitHub:** `https://github.com/robopirate/Payroll-App`
**Live Deploy:** `https://itsrobopirate.pythonanywhere.com`
**Current Commit:** `23cb0b7` (Phase 2 Complete with JWT + Swagger)

**Tech Stack:** Flask 3.0.3, SQLAlchemy 2.0.31, SQLite/PostgreSQL, Jinja2, Bootstrap 5, Flask-JWT-Extended, Flasgger (Swagger)

---

## WHAT WAS DONE IN PHASE 1 & 2

### Phase 1 — Security Fixes (Commit `0d7f7fc`)
- Rate limiting lowered to 10/min, 50/hr, 200/day
- CSRF exemption on `/api/punch` for mobile
- Payroll generation with explicit CSRF token
- Session cookies: Secure, SameSite=Lax, HttpOnly
- Employee self-registration gated with `is_approved=False`
- Admin approval workflow added
- Phone uniqueness validation
- Removed 110 lines of dead/duplicate code from `app.py`

### Phase 2 — JWT API + Swagger (Commit `e75e575` + `23cb0b7`)
- Flask-JWT-Extended with access/refresh tokens
- JWT auth endpoints: `/api/v1/auth/login`, `/refresh`, `/logout`, `/me`
- Mobile API v1: `profile`, `attendance`, `leaves`, `payroll`, `holidays`
- CSRF-exempt GPS punch with geofence (school vs field)
- Swagger/OpenAPI docs at `/api/docs/`
- Schema migrations via `safe_migrate()` (20+ missing columns)
- Per-employee shift override
- Employee types: `full_time`, `contract`, `part_time`
- Statutory deductions: PF, ESI, PT, LWF, TDS (new regime)
- Tax Declaration model (old/new regime)
- Bank payout CSV export
- Mobile portal PWA (glassmorphism UI)

---

## PHASE 3 SCOPE — FIX THESE IN ORDER

### PART A: CRITICAL BUG FIXES (Do First)

#### A1. Fix Duplicate/Shadowed Functions in `app.py` (C1, C2)
**File:** `C:\Users\itsom\OneDrive\Documents\GitHub\Payroll App\app.py`
**Problem:** `app.py` contains duplicate function definitions that shadow `services/` imports. The `services/attendance_service.py` and `services/payroll_service.py` have the "real" versions, but `app.py` has its own copies that get used instead.

**Specific issues to fix:**
1. Remove the `haversine_distance()` function from `app.py` — it already exists in `services/attendance_service.py`
2. Remove the `count_working_days_between()` function from `app.py` — it already exists in `services/attendance_service.py`
3. Remove any other duplicate functions you find in `app.py` that also exist in `services/`
4. Ensure all imports from `services/` are actually used and not redefined locally

**How to find them:**
```python
# Search for these patterns in app.py
def haversine_distance(
def count_working_days_between(
def calculate_overtime_pay(
# etc.
```

**After fixing:** `app.py` should ONLY import these functions from `services/`, never redefine them.

#### A2. Add Missing Imports in `app.py` (C1)
**File:** `C:\Users\itsom\OneDrive\Documents\GitHub\Payroll App\app.py`
**Problem:** Lines 112+ use `calendar`, `date`, `timedelta`, `math` but they may not be imported.

**Fix:** Add these imports at the top of `app.py` if not already present:
```python
import calendar
import math
from datetime import date, timedelta
```

**Verify:** Search for any usage of `calendar.`, `math.`, `date()`, `timedelta()` in `app.py` and ensure the imports exist.

#### A3. Fix Database Backup Route (C4)
**File:** `C:\Users\itsom\OneDrive\Documents\GitHub\Payroll App\blueprints\admin.py`
**Problem:** The backup route looks for the database in the project root, but the actual DB is at `~/payroll.db` (outside the project folder).

**Fix:** Update the backup route to use the correct DB path. Find the route that handles `/backup` or similar and fix the path to use:
```python
import os
db_path = os.path.expanduser('~/payroll.db')  # or from app.config['SQLALCHEMY_DATABASE_URI']
```

**Also ensure:** The backup download works correctly and the file is readable.

#### A4. Fix Settings API Key Persistence (C5)
**File:** `C:\Users\itsom\OneDrive\Documents\GitHub\Payroll App\blueprints\admin.py` (settings route)
**Problem:** The `FAST2SMS_API_KEY` is loaded from `AppConfig` on startup via `load_persisted_config()`, but when admin saves settings, the new API key may not be written back to `AppConfig`.

**Fix:** 
1. Find the settings route that handles POST to `/settings`
2. Ensure when the form is saved, the API key is stored in `AppConfig` table:
```python
from models import AppConfig
# ... in the POST handler:
api_key = request.form.get('fast2sms_api_key', '').strip()
if api_key:
    config = AppConfig.query.filter_by(key='FAST2SMS_API_KEY').first()
    if not config:
        config = AppConfig(key='FAST2SMS_API_KEY', value=api_key)
        db.session.add(config)
    else:
        config.value = api_key
    db.session.commit()
```
3. Also ensure the settings page pre-populates the API key from `AppConfig` when loaded (GET request).

#### A5. Remove/Fix Hardcoded Default Admin Password (H1)
**File:** `C:\Users\itsom\OneDrive\Documents\GitHub\Payroll App\app.py` (DB init section)
**Problem:** If the database is reset, the default admin password is printed to the HTML/console as `admin123`.

**Fix:**
1. In the DB init section where the admin user is created, generate a random password instead of using `admin123`:
```python
import secrets
# Generate a random 12-character password
default_password = secrets.token_urlsafe(12)
```
2. Print it to the console (not the web response) so the developer can see it once:
```python
print(f'Admin password: {default_password}')
```
3. Set `must_change_password = True` so the admin MUST change it on first login.

**Note:** Do NOT change the existing admin password if the admin user already exists (only on first DB creation).

---

### PART B: HIGH PRIORITY FIXES (Do After Critical)

#### B1. Fix Employee Self-Registration Approval Gate (H5)
**File:** `C:\Users\itsom\OneDrive\Documents\GitHub\Payroll App\blueprints\portal.py` (register route)
**Problem:** Employee self-registration allows anyone to register. The `is_approved=False` flag is set, but there's no clear admin UI to approve pending employees, and the employee might be able to log in before approval.

**Fix:**
1. In the registration POST handler, ensure the employee is created with `is_approved=False` and `is_active=False` (or just `is_approved=False`).
2. In the employee portal login route, check `is_approved=True` before allowing login. If `is_approved=False`, show a message like: "Your account is pending admin approval."
3. In the admin employee list (`/employees`), add a "Pending Approval" filter that shows only `is_approved=False` employees.
4. Ensure the admin can approve an employee by clicking a button (this was added in Phase 1, verify it still works).

#### B2. Add Phone Uniqueness at DB Level (H6)
**File:** `C:\Users\itsom\OneDrive\Documents\GitHub\Payroll App\models.py`
**Problem:** `Employee.phone` is not marked as `unique=True` at the database level, so duplicate phones can be created via import or direct DB inserts.

**Fix:**
1. In `models.py`, find the `Employee` model:
```python
class Employee(db.Model):
    # ...
    phone = db.Column(db.String(15), unique=True, nullable=False)  # Add unique=True if missing
```
2. If `unique=True` is already there, verify it in the DB schema. If not, add it to `safe_migrate()` in `app.py`:
```python
# In safe_migrate():
# Note: SQLite doesn't support ALTER TABLE ADD COLUMN with UNIQUE via ALTER
# So we need to handle this carefully - just add the validation in Python for now
# and document it for PostgreSQL migration
```
3. Also ensure `add_employee` and `edit_employee` routes validate phone uniqueness before saving.

#### B3. Fix `add_employee` Route to Process `school_ids` (H7)
**File:** `C:\Users\itsom\OneDrive\Documents\GitHub\Payroll App\blueprints\admin.py` (add_employee route)
**Problem:** The `add_employee` route doesn't process `school_ids` from the form, so employees can't be assigned to schools during creation. The `edit_employee` route handles `school_ids` but `add_employee` doesn't.

**Fix:**
1. Find the `add_employee` POST handler in `admin.py`
2. Add this after creating the employee:
```python
school_ids = request.form.getlist('school_ids', type=int)
if school_ids:
    schools = School.query.filter(School.id.in_(school_ids)).all()
    emp.schools = schools
    db.session.commit()
```
3. Ensure the `add_employee.html` template includes the school selection checkbox (check if it's already there or if `edit_employee.html` has it and copy it).

#### B4. Fix Rate Limiter Storage (H2)
**File:** `C:\Users\itsom\OneDrive\Documents\GitHub\Payroll App\extensions.py` and `config.py`
**Problem:** Rate limiter uses `memory://` storage which resets on every restart. On PythonAnywhere free tier, this means the rate limit is essentially ineffective.

**Fix:**
1. In `config.py`, add a Redis URL config (fallback to memory if Redis not available):
```python
RATELIMIT_STORAGE_URI = os.environ.get('RATELIMIT_STORAGE_URI', 'memory://')
```
2. In `extensions.py`, update the `Limiter` to use the config:
```python
from config import Config
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour", "10 per minute"],
    storage_uri=Config.RATELIMIT_STORAGE_URI,
    # ...
)
```
3. Document in `DEPLOY.md` that for production, Redis should be configured.

**Note:** Don't actually require Redis (keep memory fallback), but make it configurable.

#### B5. Add HTTPS Enforcement for Cookies
**File:** `C:\Users\itsom\OneDrive\Documents\GitHub\Payroll App\config.py`
**Problem:** `SESSION_COOKIE_SECURE` is set from env, but if env is not set, it defaults to `False` which is insecure in production.

**Fix:**
1. In `config.py`, ensure:
```python
SESSION_COOKIE_SECURE = os.environ.get('SESSION_COOKIE_SECURE', 'False').lower() == 'true'
# For production, default to True if not explicitly set to False
# Or make it clearer:
ENV = os.environ.get('FLASK_ENV', 'production')
SESSION_COOKIE_SECURE = ENV == 'production'
```
2. Document that `FLASK_ENV=production` should be set on PythonAnywhere.

---

### PART C: CODE QUALITY & ARCHITECTURE

#### C1. Clean Up `app.py` — Remove All Dead Code
**File:** `C:\Users\itsom\OneDrive\Documents\GitHub\Payroll App\app.py`
**Problem:** `app.py` has dead code (commented out, unused imports, duplicate functions).

**Fix:**
1. Remove ALL unused imports
2. Remove ALL commented-out code blocks
3. Remove ALL functions that are shadowed by `services/` imports
4. Ensure `app.py` is ONLY: Flask init, config loading, extension init, blueprint registration, `safe_migrate()`, and DB init

#### C2. Add `__init__.py` to `services/`
**File:** `C:\Users\itsom\OneDrive\Documents\GitHub\Payroll App\services/__init__.py`
**Problem:** `services/` is a Python package but may be missing `__init__.py`.

**Fix:**
```python
# services/__init__.py
from .attendance_service import haversine_distance, count_working_days_between, get_employee_effective_shift
from .payroll_service import calculate_payroll, calculate_tds

__all__ = [
    'haversine_distance',
    'count_working_days_between', 
    'get_employee_effective_shift',
    'calculate_payroll',
    'calculate_tds',
]
```

#### C3. Add Input Sanitization to Notes Fields
**File:** `C:\Users\itsom\OneDrive\Documents\GitHub\Payroll App\blueprints/*.py`
**Problem:** Notes fields in forms might not be sanitized, creating XSS risk if Jinja auto-escaping is disabled.

**Fix:** Ensure all text fields are stripped and basic HTML escaping is done. Flask's Jinja2 auto-escaping should already handle this, but verify that `| safe` filter is NOT used on user input anywhere.

---

### PART D: TESTING REQUIREMENTS

After every fix, verify:

1. **App starts without errors:**
```bash
cd "C:\Users\itsom\OneDrive\Documents\GitHub\Payroll App"
venv_new/Scripts/python.exe -c "from app import app; print('OK')"
```

2. **No import errors:**
```bash
venv_new/Scripts/python.exe -c "import app; import blueprints.admin; import blueprints.api; import blueprints.jwt_auth; import blueprints.portal; import blueprints.auth; print('All imports OK')"
```

3. **JWT auth still works:**
```bash
venv_new/Scripts/python.exe -c "
from app import app
with app.test_client() as client:
    # Admin login
    r = client.post('/api/v1/auth/login', json={'username': 'admin', 'password': 'admin123'})
    print('Admin login:', r.status_code)
    # Employee login (if test employee exists)
    r = client.post('/api/v1/auth/login', json={'phone': '7039368447', 'password': 'omkar123'})
    print('Employee login:', r.status_code)
"
```

4. **Swagger still loads:**
```bash
venv_new/Scripts/python.exe -c "
from app import app
with app.test_client() as client:
    r = client.get('/api/docs/')
    print('Swagger:', r.status_code)
    r = client.get('/apispec_1.json')
    print('API spec:', r.status_code)
"
```

5. **Web portal still works:**
```bash
venv_new/Scripts/python.exe -c "
from app import app
with app.test_client() as client:
    r = client.get('/login')
    print('Login page:', r.status_code)
    r = client.get('/portal/login')
    print('Portal login:', r.status_code)
"
```

---

## COMMIT MESSAGE TEMPLATE

After all fixes, commit with:

```
Phase 3: Bug Fix Sprint — Critical + High Priority

Fixes:
- Remove duplicate functions from app.py (use services/ imports)
- Add missing imports (calendar, math, datetime)
- Fix DB backup path (use ~/payroll.db)
- Fix settings API key persistence (save to AppConfig)
- Generate random admin password on first init (not hardcoded)
- Fix employee registration approval gate (is_approved check)
- Add phone uniqueness validation at DB level
- Fix add_employee to process school_ids
- Make rate limiter storage configurable (Redis ready)
- Enforce HTTPS cookies in production
- Clean up dead code in app.py
- Add services/__init__.py exports
- Verify XSS sanitization on user inputs
```

---

## DELIVERABLES

After completing Phase 3, the following must be true:

1. ✅ `app.py` has no duplicate functions — everything imported from `services/`
2. ✅ No missing imports in `app.py`
3. ✅ DB backup downloads the correct file from `~/payroll.db`
4. ✅ Settings API key is saved to `AppConfig` and loaded on startup
5. ✅ Admin password is randomly generated on first DB init (not hardcoded)
6. ✅ Employee registration requires admin approval (`is_approved=True`)
7. ✅ Phone number is unique at DB level (or at least validated in Python)
8. ✅ Adding an employee allows assigning schools
9. ✅ Rate limiter storage is configurable (Redis ready, memory fallback)
10. ✅ HTTPS cookies enforced in production
11. ✅ `services/__init__.py` exists with proper exports
12. ✅ No dead code in `app.py`
13. ✅ App starts without errors
14. ✅ All imports work
15. ✅ JWT auth still works
16. ✅ Swagger still loads
17. ✅ Web portal still works

---

## IMPORTANT NOTES

1. **DO NOT change existing working features** — JWT, Swagger, payroll, attendance, etc. must continue to work exactly as before.
2. **DO NOT rename existing routes** — backward compatibility is critical.
3. **DO NOT remove existing models or columns** — only add new ones if needed.
4. **ALWAYS test after each fix** — don't batch too many changes without testing.
5. **If a fix is complex, split it into smaller commits** — easier to rollback.
6. **Use `Edit` tool for small changes, `Write` for new files** — never use `sed` or `awk`.
7. **Read before you write** — always read the current file content before editing.
8. **Keep `safe_migrate()` updated** — if you add new model columns, add them to `safe_migrate()` too.

---

## HOW TO RUN TESTS

Use this command to verify the app starts:
```bash
cd "C:\Users\itsom\OneDrive\Documents\GitHub\Payroll App"
venv_new/Scripts/python.exe -c "from app import app; print('APP LOADED OK')"
```

If it fails, read the error, fix it, and retry.

---

Good luck! Fix these bugs and make the codebase production-ready. 🚀
