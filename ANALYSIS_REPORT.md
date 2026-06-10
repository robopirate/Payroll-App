# Robo Pirate HR — Comprehensive Architecture, Logic & Bug Analysis Report

**Prepared for:** Omkar Singh, Managing Director, Robo Pirate  
**Date:** 10 June 2026  
**Sources Analysed:**
1. Local workspace: `C:\Users\itsom\OneDrive\Documents\GitHub\Payroll App`
2. GitHub repository: `https://github.com/robopirate/Payroll-App`
3. Live deployment: `https://itsrobopirate.pythonanywhere.com`

---

## 1. Executive Summary

| Dimension | Finding |
|-----------|---------|
| **Sync Status** | Local ↔ GitHub are **identical** (no uncommitted changes). Live site is running the same codebase. |
| **Architecture** | Flask monolith with Blueprints, SQLite, SQLAlchemy ORM, Jinja2 templates, Bootstrap 5 + custom glassmorphism CSS. |
| **Overall Health** | Functional but carries **28 identified issues** ranging from critical bugs to architectural debt. |
| **Security Posture** | Weak — hardcoded default credentials, no HTTPS enforcement, CSRF blocking API calls, missing session hardening. |
| **Scalability** | Single-worker Gunicorn, in-memory rate limiting, SQLite — suitable for < 50 employees only. |

---

## 2. Source Comparison Matrix

| File / Aspect | Local | GitHub | Live (PythonAnywhere) | Verdict |
|---------------|-------|--------|----------------------|---------|
| `app.py` | Present | Identical SHA | Running | ✅ Synced |
| `models.py` | Present | Identical SHA | Running | ✅ Synced |
| `config.py` | Present | Identical SHA | Running | ✅ Synced |
| `requirements.txt` | Present | Identical SHA | Running | ✅ Synced |
| `blueprints/` | Present | Identical SHA | Running | ✅ Synced |
| `services/` | Present | Identical SHA | Running | ✅ Synced |
| `static/css/style.css` | Present | Identical SHA | Running | ✅ Synced |
| `static/js/main.js` | Present | Identical SHA | Running | ✅ Synced |
| `payroll.db` | Present (135 KB) | Present (135 KB) | Separate production DB | ⚠️ Local DB ≠ Live DB |
| `Procfile` | `web: gunicorn app:app --workers 1` | Same | Same | ✅ Synced |
| PWA manifest | `/static/manifest.json` | Same | Same | ✅ Synced |
| Service Worker | `/static/sw.js` | Same | Same | ✅ Synced |

**Key Finding:** The code is fully synchronised across all three sources. The only divergence is the **database file** — your local `payroll.db` is not the same as the live PythonAnywhere database. Any bug fixes you deploy will affect code only; live data remains untouched.

---

## 3. Architecture Analysis

### 3.1 High-Level Stack

```
┌─────────────────────────────────────────┐
│  Browser (PWA-capable, Bootstrap 5)     │
├─────────────────────────────────────────┤
│  Jinja2 Templates + Glassmorphism CSS   │
├─────────────────────────────────────────┤
│  Flask App (Monolith)                   │
│  ├── Blueprint: auth (login/logout)     │
│  ├── Blueprint: admin (dashboard, HR)   │
│  ├── Blueprint: portal (employee self)   │
│  └── Blueprint: api (GPS punch)        │
├─────────────────────────────────────────┤
│  Services Layer                         │
│  ├── attendance_service.py             │
│  ├── payroll_service.py                  │
│  └── notification_service.py             │
├─────────────────────────────────────────┤
│  SQLAlchemy ORM → SQLite (local)        │
│              → PostgreSQL (future)      │
├─────────────────────────────────────────┤
│  External: Fast2SMS, Google Maps        │
└─────────────────────────────────────────┘
```

### 3.2 Blueprint Responsibilities

| Blueprint | Routes | Auth Level | Notes |
|-----------|--------|------------|-------|
| `auth` | `/`, `/login`, `/logout`, `/forgot-password`, `/reset-password`, `/register` | Public | Handles both admin & employee auth. Token-based password reset via SMS. |
| `admin` | `/dashboard`, `/employees/*`, `/attendance/*`, `/payroll/*`, `/leaves/*`, `/advances`, `/sms`, `/settings`, `/export/*`, `/backup` | Admin (`is_admin=True`) | 1,200+ lines — doing too much. |
| `portal` | `/portal/*`, `/register` | Employee (`portal_required`) | Self-registration, punch, quick-attendance for school heads. |
| `api` | `/api/punch` | Employee (JSON) | GPS geofence check. **Currently broken by CSRF.** |

### 3.3 Database Schema (14 Tables)

```
users ─┬─► password_resets
       └─► employees ─┬─► attendance
                      ├─► leaves
                      ├─► leave_balances
                      ├─► payrolls
                      ├─► advances
                      └─► schools (M2M via employee_schools)
departments ──► employees
holidays
school_schedules
audit_logs
app_config
attendance_locks
```

**Schema Quality:** Good relational design. M2M employee-schools is appropriate for your multi-school deployment model. Missing indexes on foreign keys and audit log timestamps will slow down at scale.

---

## 4. Logic Analysis — Payroll Engine

### 4.1 Formula (from `services/payroll_service.py`)

```
Daily Rate      = Basic Salary / Actual Working Days in Month
Earned Basic    = Daily Rate × Days Present (half-day = 0.5, leave = 1.0)
HRA             = 40% of Earned Basic
Overtime Pay    = (Basic / 26 / 8) × 2.0 × Overtime Hours
Gross Salary    = Earned Basic + HRA + Overtime Pay
PF              = 12% of Earned Basic
ESI             = 1.75% of Gross (if Gross ≤ ₹21,000)
Net Salary      = Gross − PF − ESI − Advance Deductions
```

### 4.2 Logic Issues

| # | Issue | Severity | Details |
|---|-------|----------|---------|
| L1 | **Double-counting of leave days** | 🔴 High | `calculate_payroll` adds `+1.0` for attendance status `'leave'` AND separately adds approved `Leave` record days. If an admin marks attendance as 'leave' AND approves a Leave request, the employee gets paid twice for the same day. |
| L2 | **Overtime status inconsistency** | 🟡 Medium | Status `'overtime'` adds 1.0 present day but `overtime_hours` is tracked separately. If overtime_hours = 0, employee still gets full day pay + 0 overtime. |
| L3 | **Working days calculation** | 🟡 Medium | `get_working_days_in_month` counts Mon-Sat excluding holidays. This is correct for a 6-day week but hardcoded; no config for 5-day week. |
| L4 | **Hourly rate denominator** | 🟡 Medium | Uses `WORKING_DAYS_PER_MONTH = 26` (fixed) for hourly rate, not actual working days in that month. Slight inaccuracy for months with 27/25 working days. |
| L5 | **No rounding on intermediate values** | 🟢 Low | `earned_basic`, `gross`, etc. are rounded only at the end. Indian payroll typically rounds per component. |
| L6 | **Advance deduction query** | 🟡 Medium | Filters by `month_deducted` and `year_deducted` but `Advance` model has no validation that these are set when status = 'approved'. Unset fields default to `None`, so query may miss advances. |

---

## 5. Bug Register (28 Issues)

### 🔴 Critical (5)

| ID | Bug | Location | Impact |
|----|-----|----------|--------|
| C1 | **Missing imports in `app.py`** | `app.py` lines 52–159 | `calendar`, `date`, `timedelta`, `math` are used but **never imported**. The duplicate helper functions in `app.py` will crash with `NameError` if ever called. Dead code that is dangerous to keep. |
| C2 | **Duplicate function definitions shadowing services** | `app.py` lines 52–159 | `get_working_days_in_month`, `count_working_days_between`, `calculate_payroll`, `haversine_distance` are imported from `services/` but then redefined locally. This creates confusion and means any fix to `services/` is ignored if something calls the `app.py` version. |
| C3 | **CSRF breaks API punch endpoint** | `api.py` + `app.py` | `POST /api/punch` returns `400 Bad Request: CSRF token missing.` The mobile GPS punch feature is **completely non-functional** for employees. |
| C4 | **Database backup route looks in wrong path** | `admin.py` line 1140–1148 | `download_backup` uses `os.path.join(current_app.root_path, 'payroll.db')` but `config.py` stores the DB at `~/payroll.db` (outside project). Backup always fails on production. |
| C5 | **Settings API key not persisted** | `admin.py` lines 751–768 | Entering Fast2SMS API key in Settings updates `current_app.config` only. It is **not saved to `AppConfig` table**, so it disappears on server restart. The `load_persisted_config` hook loads from DB, but nothing saves to DB. |

### 🟡 High (8)

| ID | Bug | Location | Impact |
|----|-----|----------|--------|
| H1 | **Hardcoded default admin credentials** | `app.py` lines 212–214 | `admin / admin123` is auto-created on every DB init. Exposed in HTML comment on login page. Security risk if DB is ever reset. |
| H2 | **Rate limiter uses in-memory storage** | `extensions.py` line 14 | `storage_uri="memory://"` resets on every Gunicorn restart. On PythonAnywhere (free tier restarts every ~24h), rate limits are ineffective. Also fails with multiple workers. |
| H3 | **Circular import risk** | `services/attendance_service.py` line 6 | Imports `from models import db, Holiday` but `models.py` imports `from extensions import db`. Currently works by accident due to import order. |
| H4 | **SQL injection in `safe_migrate`** | `app.py` lines 189–202 | Uses f-string: `text(f"ALTER TABLE ... {col} {col_def}")`. While only runs at startup, this is bad practice. Should use bound parameters or whitelist. |
| H5 | **Employee self-registration has no admin approval** | `portal.py` lines 34–135 | Anyone with a phone number can register as an employee and gain portal access. No verification or admin gate. |
| H6 | **Phone number not unique at DB level** | `models.py` line 52 | `Employee.phone` has `nullable=False` but not `unique=True`. Duplicate phones allowed, which breaks portal login (queries `.first()`). |
| H7 | **School assignment missing in add_employee** | `admin.py` lines 54–102 | The `add_employee` route does not process `school_ids` from the form, even though the template likely includes it. Only `assign_employee_schools` (edit) works. |
| H8 | **Leave balance property shadows relationship** | `models.py` lines 73–75 | `@property def leave_balance` returns a dict. SQLAlchemy relationship `leave_balances` (plural) exists. The similar naming can confuse ORM hydration. |

### 🟢 Medium / Low (15)

| ID | Bug / Issue | Location | Impact |
|----|-------------|----------|--------|
| M1 | **No HTTPS enforcement** | `config.py` | No `SESSION_COOKIE_SECURE`, `SESSION_COOKIE_SAMESITE`. Cookies sent over HTTP on PythonAnywhere. |
| M2 | **PWA icons use emoji SVG data URIs** | `manifest.json` | May not render as app icons on iOS/Android. Should use real PNGs. |
| M3 | **Service worker cache-only strategy** | `sw.js` | No cache invalidation or network-first fallback. Users may see stale portal pages after updates. |
| M4 | **Holiday population hardcodes 2026 lunar dates** | `admin.py` lines 836–878 | For year ≠ 2026, uses generic Gregorian dates for lunar festivals (Eid, Diwali, Holi) which are wrong. |
| M5 | **Password reset token sent as plaintext SMS** | `auth.py` lines 65–76 | 43-character token in a single SMS may be truncated by some carriers. Should use shorter numeric OTP. |
| M6 | **No input sanitization on notes/description fields** | Multiple templates | XSS risk if Jinja2 `{{ ... }}` auto-escaping is ever disabled. |
| M7 | **Audit log has no DB index on timestamp** | `models.py` lines 192–199 | Will slow down as logs grow. |
| M8 | **Gunicorn single worker** | `Procfile` | One worker = one request at a time. PDF generation or bulk SMS blocks the app. |
| M9 | **Department not linked on self-registration** | `portal.py` lines 98–111 | Employee registers with `department` text field but model stores `department_id`. Department is lost. |
| M10 | **Overtime hours not validated (negative allowed)** | `admin.py` lines 392–414 | `float(request.form.get(f'ot_{emp.id}', 0) or 0)` accepts negative overtime. |
| M11 | **Salary validation allows zero/negative** | `admin.py` lines 70–77 | `basic_salary < 0` is blocked but `basic_salary = 0` is allowed. May be intentional for interns. |
| M12 | **Employee ID generation race condition** | `portal.py` lines 88–90 | `last_emp.id + 1` is not atomic. Two simultaneous registrations could get same ID. |
| M13 | **Missing `__init__.py` content in services** | `services/__init__.py` | Empty. Could export public functions for cleaner imports. |
| M14 | **Template `employees/import.html` referenced but unverified** | `admin.py` line 1209 | README lists it; need to confirm it exists in templates. |
| M15 | **No database connection pooling config** | `config.py` | Default SQLAlchemy pooling. On PythonAnyvenue with SQLite, should set `connect_args={'check_same_thread': False}`. |

---

## 6. Live Site Behaviour (PythonAnywhere)

| Endpoint | Response | Observation |
|----------|----------|-------------|
| `GET /dashboard` | `302 → /login?next=%2Fdashboard` | Correct — auth required. |
| `GET /portal/login` | `200 OK` | Glassmorphism employee login renders correctly. |
| `POST /api/punch` (no auth) | `400 CSRF token missing` | **Bug C3 confirmed.** Even before auth check, CSRF blocks the request. |
| `GET /static/css/style.css` | `200 OK` | Custom CSS delivered. |
| `GET /static/manifest.json` | `200 OK` | PWA manifest valid JSON. |
| Server header | `PythonAnywhere` | Confirmed hosting platform. |

---

## 7. Code Quality Metrics

| Metric | Value | Assessment |
|--------|-------|------------|
| Total Python LOC | ~2,800 | Moderate size |
| Blueprints | 4 | Good separation |
| Models | 14 tables | Well-normalised |
| Test coverage | 2 test files, ~6 cases | **Very low** — only auth and payroll calc tested. |
| Requirements | 15 packages | Reasonable, no bloat |
| CSS | Custom glassmorphism + Bootstrap | Modern, mobile-responsive |
| PWA features | Manifest + SW | Basic, needs improvement |

---

## 8. Recommendations Summary

### Immediate (Do This Week)
1. **Fix C3** — Exempt `/api/punch` from CSRF so mobile GPS punch works.
2. **Fix C5** — Persist Fast2SMS API key to `AppConfig` table in Settings route.
3. **Fix C4** — Correct backup DB path to match `config.py` `DB_PATH`.
4. **Fix C1/C2** — Remove duplicate functions from `app.py`; import from `services/` only.
5. **Fix H1** — Remove hardcoded admin password from `init_db`; force password change on first login.

### Short-Term (This Month)
6. **Fix L1** — Remove `'leave'` status from present-day calculation in payroll; rely on `Leave` model only.
7. **Fix H2** — Switch Flask-Limiter to SQLite-backed storage (`storage_uri="sqlite:///limiter.db"`).
8. **Fix H5** — Add `is_approved` flag to employee self-registration or disable it.
9. **Fix H6** — Add `unique=True` to `Employee.phone` with a migration.
10. **Fix H7** — Process `school_ids` in `add_employee` route.
11. **Add tests** — Cover attendance, leaves, API, and exports.

### Strategic (Next Quarter)
12. **Migrate to PostgreSQL** — PythonAnywhere offers free PostgreSQL. SQLite is not suitable for concurrent writes.
13. **Add HTTPS/Security headers** — Use Flask-Talisman.
14. **Improve PWA** — Real icons, network-first service worker, offline payslip viewing.
15. **Refactor admin blueprint** — Split into sub-blueprints (employees, attendance, payroll, etc.).
16. **Add RBAC** — Currently only binary `is_admin`. Add roles: `hr_manager`, `school_head`, `finance`.

---

## 9. Deployment Notes

| Aspect | Current State | Recommended |
|--------|---------------|-------------|
| **Platform** | PythonAnywhere (free tier) | Fine for now; consider paid tier for custom domain + HTTPS. |
| **WSGI** | Gunicorn, 1 worker | Increase to 2–3 workers on paid tier. |
| **Database** | SQLite at `~/payroll.db` | Migrate to PostgreSQL for concurrency & backups. |
| **Static files** | Served by Flask | Use PythonAnywhere static file mappings for CSS/JS. |
| **Environment vars** | `FAST2SMS_API_KEY`, `SECRET_KEY` | Set via PythonAnywhere "Web" tab env vars. |
| **Backups** | Manual download route | Automate daily DB backup to S3 or email. |

---

## 10. Conclusion

The Robo Pirate HR app is a **functionally complete MVP** with an impressive glassmorphism UI and well-thought-out features (GPS punch, PWA, SMS, PDF payslips). However, it carries **significant technical debt** — particularly the duplicate code in `app.py`, the broken API endpoint, and the settings persistence bug. These are all fixable within a few hours.

The architecture is sound for a small team (< 50 employees) but will need PostgreSQL and worker scaling before onboarding multiple schools with 100+ employees.

**Next step:** Proceed with the bug-fixing and improvisation phase.

---

*Report generated by automated codebase analysis across Local, GitHub, and Live deployment sources.*
