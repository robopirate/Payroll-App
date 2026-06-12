# Robo Pirate HR — Full Autopsy, Market Comparison & Maturity Scorecard

**Scope:** Architecture · UI/UX · Feature Set · Payroll Logic & Maths · Security · Indian Market Fit · Open-Source Benchmark  
**Prepared for:** Omkar Singh / Robo Pirate  
**Date:** 04 June 2026  
**Codebase:** `C:\Users\itsom\OneDrive\Documents\GitHub\Payroll App`  
**Live deployment:** `https://payroll-app-xd1d.onrender.com` (Render + PostgreSQL)  

> **Headline:** The app is a **polished, mobile-first MVP** that already covers the “daily ops” of a small school/institute better than many open-source HRMS starters. But it is still a **payroll calculator, not a statutory payroll engine**. For Indian teachers/employees the biggest risk is **incorrect/incomplete salary math** (missing PT, TDS, LWF, employer contributions, LOP logic).

---

## 1. Executive Summary — Where We Are

| Dimension | Current State | Maturity (1–5) | Verdict |
|-----------|---------------|----------------|---------|
| **Architecture** | Flask monolith, blueprints, SQLite locally / Postgres on Render | 3.0 | Solid for < 100 employees, needs factory pattern + migrations at scale |
| **UI / Ease of Use** | Glassmorphism PWA, mobile-first portal, big touch targets | 4.0 | Better than many Indian SMB tools; teachers can punch/mark/download payslip easily |
| **Features (HR ops)** | Employees, attendance, leave, advances, holidays, schools/locations | 3.5 | Covers core ops; missing shift roster, asset/expense, document vault |
| **Payroll Engine** | Basic + HRA + OT + PF + (old) ESI + advances | 2.0 | **Not India-compliant**; missing PT/TDS/LWF/employer contributions/LOP |
| **Security & Compliance** | CSRF, hashed passwords, rate limiting (memory), JWT, file brute-force | 2.5 | High-severity gaps: default admin password, DB backup exposes PII, in-memory JWT blacklist |
| **Mobile / ESS** | PWA + JWT API + GPS punch + WhatsApp-style SMS | 3.5 | Good employee self-service; API CSRF fixed, JWT blacklist ephemeral |
| **Test Coverage** | 8 tests (auth + payroll) | 1.5 | Far below market baseline; no attendance/leave/API/export tests |
| **DevOps / Deploy** | Render + PostgreSQL, single-worker Gunicorn, manual backups | 2.5 | Better than PythonAnywhere; still single worker, no CI/CD |

**Overall Maturity Score: 2.8 / 5** — “Functional MVP ready for a single small institute, not yet a product.”

---

## 2. Architecture Autopsy

### 2.1 Stack & Pattern

```
Browser / PWA / Mobile
        ↓
   Jinja2 + Bootstrap 5 + Custom Glassmorphism CSS
        ↓
   Flask Monolith (app.py creates app at import time)
        ↓
   Blueprints: auth · admin · portal · api · jwt_auth
        ↓
   Services: payroll · attendance/geo · notification · login protection
        ↓
   SQLAlchemy ORM → SQLite (dev) / PostgreSQL + psycopg v3 (Render)
        ↓
   External: Fast2SMS, Google Maps Places
```

### 2.2 What’s Good
- **Blueprints** keep admin, employee portal, and API separate.
- **Service layer** for payroll and attendance calculation (after recent cleanup).
- **PWA manifest + service worker** give an app-like feel.
- **Dual base templates** (`base.html` for admin, `portal/base.html` for employees) are mobile-aware.
- **PostgreSQL migration completed** — better concurrency than SQLite.

### 2.3 What’s Weak / Useless

| Issue | Why It Hurts | Fix Priority |
|-------|--------------|--------------|
| `app.py` creates app at import time and runs `init_db()` | Import side-effects break tests, migrations, WSGI reloads | High |
| `admin.py` is ~1,300 lines doing everything | Hard to maintain; violates single-responsibility | Medium |
| `pdf_service.py` & `sms_service.py` live at root while other services are in `services/` | Inconsistent structure | Low |
| `sms_service.py` exports `get_month_name()` used by PDF service | Wrong ownership; needs shared utility | Low |
| `services/__init__.py` empty | Could expose public API for cleaner imports | Low |
| Many unused imports (`flash`, `logout_user`, `timedelta`, `db` in services, etc.) | Noise, minor perf, lint debt | Low |
| No database migration framework (Alembic/Flask-Migrate) | `safe_migrate()` is f-string ALTER TABLE; risky | High |
| Single Gunicorn worker (`Procfile`) | PDF/SMS blocks all traffic | Medium |
| SQLite `check_same_thread` not set for local dev | Threading warnings | Low |

### 2.4 Architecture Comparison

| Capability | Our App | Indian SaaS (greytHR/Keka) | Open Source (ERPNext/Frappe HR/Odoo) |
|---|---|---|---|
| Modular code | Blueprints (good) | Micro-services/modules | Modular apps/plugins |
| Migration system | None (manual `safe_migrate`) | Managed | Alembic / Frappe migrations |
| Multi-tenancy | None | Yes | Yes |
| Multi-company / multi-location | Schools (M2M employees) | Yes | Yes |
| API | JWT + session | REST + webhooks | REST + RPC |
| Background jobs | None | Yes | RQ/Celery / Frappe scheduler |
| Audit trail | Table exists, not indexed | Comprehensive | Extensive |

---

## 3. Feature Inventory vs Market

### 3.1 Feature Comparison Matrix

| Feature Area | Our App | Indian Market Baseline* | Open-Source Baseline** | Gap |
|---|---|---|---|---|
| **Employee Master** | Name, phone, email, dept, designation, bank, PAN, Aadhar, joining date | Same + dependents, documents, job history, salary structures | Same + documents, skills, exit workflow | Medium |
| **Attendance** | Web punch, GPS geofence, admin bulk mark, half-day, overtime, field/office | + biometric, selfie, shift/roster, grace time, miss-punch regularization | + biometric APIs, roster, geo-fencing | Medium |
| **Leave** | Apply, approve, balances (manual setup), casual/sick/earned, multi-month overlap | + accrual rules, carry-forward, encashment, sandwich/comp-off, unpaid/LOP | + accrual, encashment, workflows | High |
| **Payroll** | Basic + HRA + OT + PF + ESI + advances, PDF payslip | Full statutory engine + TDS + PT + LWF + bonus + gratuity + arrears + reimbursements | Full configurable salary structures + statutory reports | Very High |
| **Statutory Reports** | None | Form 16, 24Q, ECR, challans, PT/state reports | Country-specific localizations | Very High |
| **Advances/Loans** | One-time deduction | EMI-style recovery, interest | Configurable | Medium |
| **Holidays / Calendar** | Manual + national holiday populate | State/branch specific calendars | Configurable | Low |
| **School/Location Mgmt** | Geofence, radius, schedule | Branch/cost-center mapping | Cost centers | Good |
| **Self-Service Portal** | Mobile-first dashboard, punch, payslips, leaves | Same + tax declarations, helpdesk | Same + profile docs | Medium |
| **Mobile App** | PWA + JWT API | Native apps (Android/iOS) | PWA / native | Medium |
| **Notifications** | SMS (Fast2SMS), flash messages | Email, WhatsApp, in-app, push | Email + in-app | Medium |
| **Reports & Exports** | Basic tables, Excel export of attendance/payroll/employees | Custom reports, dashboards, analytics | BI, custom reports | High |
| **Role-Based Access** | Admin vs Employee only | HR, Finance, Manager, School Head, Employee | Fine-grained roles | High |
| **Document Vault** | None | Offer letters, IDs, policies | Yes | High |
| **Recruitment / Onboarding** | None | ATS, offer mgmt | Yes | Very High |
| **Performance / Appraisals** | None | Yes | Yes | Very High |
| **Accounting Integration** | None | Tally, Zoho Books, QuickBooks | Native (ERPNext/Odoo) | High |
| **Backup & Security** | Admin downloads SQLite/Postgres dump | Encrypted cloud backups | Self-managed | High |

\* Indian market baseline = Zoho Payroll, RazorpayX Payroll, greytHR, Keka, factoHR, Pocket HRMS  
\** Open-source baseline = ERPNext/Frappe HR, Odoo, Horilla, OrangeHRM, IceHRM

### 3.2 Useless / Redundant Things to Remove or Rethink

1. **Hardcoded `admin / admin123` default account** — Security risk; replace with random initial password + force-change flag.
2. **`/backup` route returning raw DB** — Any admin can exfiltrate PAN/Aadhar/bank data. Encrypt or remove.
3. **In-memory JWT blacklist (`_token_blacklist`)** — Logout is meaningless across restarts. Use Redis or DB-backed blacklist.
4. **In-memory Flask-Limiter (`memory://`)** — Rate limits reset on restart and don’t work across workers. Use Redis or SQLite backend.
5. **`'leave'` status in Attendance table** — Causes double-counting with `Leave` model; mark as deprecated/ignore in payroll.
6. **PWA emoji icons in `manifest.json`** — iOS/Android may not render; use real PNGs.
7. **Cache-only service worker** — Users see stale pages after deploy; switch to network-first + cache fallback.
8. **Old analysis report assumptions** — Some items (CSRF API, settings persistence, registration approval) are already fixed; avoid re-fixing.

---

## 4. UI / UX Autopsy — Teacher & Employee Ease of Use

### 4.1 What Works Well for Non-Technical Users

| Screen | Goodness |
|---|---|
| **Portal dashboard** | Big punch button, clear status pill, leave balance cards, latest payslip with download CTA |
| **Bottom navigation** | Home · Punch · Attendance · Payslips · Quick Mark · Leaves — thumb-friendly |
| **Punch flow** | One-tap, GPS feedback messages in plain English, spinner while locating |
| **Admin dashboard** | Gradient stat cards + quick-action grid; visually appealing |
| **Slide-in sidebar** | Mobile-first nav, sections labelled (Main, Leave, Organization, Finance, Account) |
| **Forms** | Bootstrap 5 + rounded inputs + focus rings + inline validation |
| **Alerts / flash messages** | Icons + color-coded + dismissible |

### 4.2 UX Friction Points for Teachers/Employees

| Issue | Why It Confuses | Recommendation |
|---|---|---|
| **Portal login uses phone number** | Teachers may forget which phone is registered; no “forgot portal password” self-flow | Add forgot-password via SMS/OTP |
| **No in-app help / tooltips** | First-time admin may not know “School Schedule” vs “Locations” | Add contextual help or onboarding tour |
| **Payroll page shows only list** | No visual “Run Payroll” wizard or progress | Step-by-step wizard: select month → select employees → preview → finalize |
| **Leave balance setup is manual** | Admin must set balances per employee per year per type | Bulk import / default annual credit |
| **No attendance calendar view** | Teachers can’t see month-at-a-glance | Calendar heat-map like Google Calendar |
| **Error pages are generic Flask** | 404/500 not styled; breaks trust | Custom branded error pages |
| **Admin sidebar has too many items** | 15+ links; new users hunt | Collapsible sub-menus or role-based menu |
| **No WhatsApp/Email payslip** | SMS cost adds up; teachers prefer WhatsApp | Add email/WhatsApp integration |
| **No dark mode / accessibility** | Glassmorphism can reduce contrast | WCAG contrast audit |

### 4.3 UI Comparison with Indian Tools

| Aspect | Our App | Keka | greytHR | Zoho Payroll |
|---|---|---|---|---|
| Mobile-first | ✅ Excellent | Good | Dated | Good |
| Visual polish | Modern glassmorphism | Clean modern | Functional/dated | Clean |
| Teacher self-service | Punch + payslip + leave | Full ESS | Full ESS | ESS via Zoho People |
| One-tap actions | Punch, quick attendance | Limited | Limited | Limited |
| Onboarding help | None | Moderate | Heavy text docs | Moderate |

**Verdict:** UI is a **competitive advantage** for small institutes. Keep it simple; don’t over-feature the admin UI.

---

## 5. Payroll Logic & Maths Autopsy

### 5.1 Current Formula (as of latest code)

```
Working Days    = Mon–Sat in month − active holidays
Present Days    = present (1.0) + half_day (0.5) + overtime (1.0) + approved leave working days
Daily Rate      = Basic Salary / Working Days
Earned Basic    = Daily Rate × Present Days  (rounded to ₹)
Overtime Pay    = (Basic / 26 / 8) × 2.0 × OT Hours  (rounded)
HRA             = Earned Basic × 0.40  (rounded)
Gross Salary    = Earned Basic + HRA + Overtime Pay  (rounded)
PF (employee)   = Earned Basic × 0.12  (rounded)
ESI (employee)  = Gross × 0.0175  if Gross ≤ ₹21,000  (rounded)   ← OUTDATED RATE
Advance Ded.    = Sum of approved advances for this month/year
Total Deductions= PF + ESI + Advance  (rounded)
Net Salary      = Gross − Total Deductions  (rounded)
```

### 5.2 Payroll Comparison with Indian Practice

| Component / Rule | Our App | Correct Indian Practice | Severity |
|---|---|---|---|
| **Employee ESI rate** | 1.75% of gross | **0.75%** since July 2019 | 🔴 Critical |
| **Employer ESI** | Not computed | **3.25%** of gross + admin charges | 🔴 Critical |
| **Employer PF** | Not computed | 12% of basic (with EPS/EPF split) | 🔴 Critical |
| **PF wage ceiling** | No ceiling | EPS capped at ₹15,000 basic | 🟡 High |
| **Professional Tax (PT)** | Not implemented | State-wise monthly slab (e.g., Maharashtra ₹200/mo) | 🔴 Critical |
| **TDS / Income Tax** | Not implemented | Section 192 withholding | 🔴 Critical |
| **Labour Welfare Fund (LWF)** | Not implemented | Monthly/half-yearly in many states | 🟡 High |
| **Statutory Bonus** | Not implemented | 8.33%–20% for eligible employees | 🟡 High |
| **Gratuity accrual** | Not implemented | 15/26 × years × (basic+DA) after 5 yrs | 🟡 High |
| **LOP / unpaid leave** | All approved leave treated paid | Deduct unpaid leave days from gross | 🔴 Critical |
| **Leave balance check** | None | Paid leave should consume balance; excess = LOP | 🟡 High |
| **Joining-date proration** | None | Mid-month joiner should be paid only for working days from DOJ | 🔴 Critical |
| **Exit/releiving date** | No field | Ex-employee should stop earning | 🟡 High |
| **Minimum wage check** | None | Validate net ≥ state/sector minimum wage | 🟡 High |
| **Arrears** | None | Salary revision back-pay | 🟡 High |
| **Reimbursements** | None | Conveyance, medical, telephone claims | 🟡 High |
| **Salary structure** | Single `basic_salary` field | Configurable CTC components (basic, HRA, DA, special allowance, etc.) | 🔴 Critical |
| **Overtime base** | Basic only | Should include DA as per Shops/Factory Act | 🟡 Medium |
| **HRA** | 40% of basic flat | Tax-exempt HRA is metro-dependent (50% metro, 40% non-metro) | 🟡 Medium |
| **Working week** | Hardcoded Mon–Sat | Schools often 5-day; should be configurable | 🟡 Medium |
| **Overtime denominator** | Fixed 26 days | Should use actual month working days for consistency | 🟢 Low |
| **Rounding** | Round per component to ₹ | Acceptable, but component rounding can cause ₹1 gross≠sum | 🟢 Low |
| **Negative net guard** | None | Advance can make net negative | 🟡 High |

### 5.3 Example of Real-World Wrong Payslip

**Teacher:** Basic ₹26,000, Gross ₹26,000 + HRA, 2 approved leave days, no advance  
**Our app computes:** Net ≈ ₹24,500  
**Correct India payroll might be:** Net ₹23,800 after PT ₹200 + correct ESI 0.75% + employer contributions on CTC side  
**Difference:** ₹700/month/employee. For 50 teachers → ₹35,000/month error; ₹4.2L/year.

### 5.4 Payroll Engine Score

| Engine Capability | Score |
|---|---|
| Basic gross-to-net | 7/10 |
| Indian statutory deductions | 2/10 |
| Employer contributions / CTC | 0/10 |
| Leave/LOP correctness | 3/10 |
| Configurability | 1/10 |
| Audit & reversibility | 2/10 |
| **Overall** | **3/10** |

---

## 6. Security Autopsy

### 6.1 What’s Already Fixed vs Old Reports

| Old Issue | Status |
|---|---|
| CSRF blocking `/api/punch` | ✅ Fixed (`@csrf.exempt` on API punch + proper headers) |
| Fast2SMS API key not persisted | ✅ Fixed (saved to `AppConfig` table) |
| Duplicate helpers in `app.py` | ✅ Removed / commented out |
| Employee self-registration immediate access | ✅ Fixed (`is_approved=False`) |
| `now()` Jinja error | ✅ Fixed via context processor |

### 6.2 Still Open High-Risk Issues

| Issue | Risk | Mitigation |
|---|---|---|
| Default `admin / admin123` | Account takeover on fresh deploy | Random initial password + force-change flag |
| `/backup` downloads full DB | PII leak (PAN/Aadhar/bank) | Encrypt or restrict to super-admin / remove |
| JWT blacklist in memory | Logout ineffective across restarts | DB/Redis blacklist or short token expiry |
| Rate limiter `memory://` | Resets on restart, no multi-worker state | SQLite/Redis backend + file brute-force layer |
| No explicit `admin_required` decorator | Portal user could hit admin routes accidentally | Add decorator |
| `SESSION_COOKIE_SECURE` off by default | Cookie over HTTP on local/non-HTTPS | Enable in production env |
| No HSTS / CSP / X-Frame-Options | XSS/clickjacking vectors | Flask-Talisman or manual headers |
| `safe_migrate` uses f-string SQL | SQL injection surface at startup | Whitelist columns or use Alembic |
| Phone not unique at DB level | Duplicate portal accounts | `unique=True` + migration |
| No input length limits on notes | Minor XSS/storage risk | Add server-side validators |

### 6.3 Security Score: 2.5 / 5

---

## 7. Market Comparison: Where We Sit in India

### 7.1 Competitive Positioning Map

```
                    High Compliance
                           │
           greytHR    factoHR    RazorpayX
              │           │           │
              │           │           │
   Horilla ───┼───────────┼───────────┼── Keka
  (open src)  │           │           │   (UX)
              │           │           │
              │   Robo Pirate HR     │
              │   (YOU ARE HERE)     │
              │           │           │
              │           │           │
         Zoho Payroll    sumHR    SalaryBox
                           │
                    Low Compliance
                           
        Low Ease of Use ←────────→ High Ease of Use
```

**You are here:** High ease-of-use, low compliance. The closest competitors are **Zoho Payroll** (simple, low-cost) and **SalaryBox** (mobile-first for schools). Your differentiator could be **“simplest school payroll app with GPS attendance.”**

### 7.2 Pricing Comparison (Indicative for ~50 employees)

| Product | Monthly Cost (≈50 employees) | Free Tier |
|---|---|---|
| **Our App (self-hosted Render)** | Server cost (~$7–19/mo) + SMS | N/A |
| greytHR | ₹2,495–3,495 + ₹45/emp extra | Up to 25 free |
| Zoho Payroll | ₹1,000–3,000 org/mo | Up to 10 free |
| RazorpayX Payroll | ₹2,999–5,999/mo | Free plan limited |
| Keka | ₹6,999–9,999 flat | Trial only |
| factoHR | ₹4,999 + ₹69/emp | Trial |
| Pocket HRMS | ₹2,995 + ₹60/emp | Trial |
| SalaryBox | Low-cost mobile-first | Limited free |
| Horilla (open source) | Self-hosting only | Free |
| ERPNext/Frappe HR | Self-host / Frappe Cloud | Free self-host |

**Your cost advantage is real** if you can self-host on Render. But you must close the statutory gap or you’ll spend more on CA corrections than the SaaS fee.

---

## 8. Open-Source Benchmark

| Project | Stars | Best For | What We Can Borrow |
|---|---|---|---|
| **ERPNext / Frappe HR** | ~22k / ~1.5k | Full Indian SME payroll + accounting | Salary structure builder, statutory reports, Form 16 |
| **Odoo** | ~41k | Modular ERP | Leave accrual, role-based access, accounting connector |
| **Horilla** | ~1k | Modern Python/Django HRMS with biometrics | ZKTeco/eSSL biometric integration, responsive ESS |
| **OrangeHRM** | ~2.5k | Standalone HRMS | Leave policy templates, PIM |
| **IceHRM** | ~700 | Simple SMB HRMS | Payroll add-on structure, leave accrual |
| **Sentrifugo** | ~600 | Avoid — stale PHP | — |

**Key takeaway:** Most mature open-source HRMS have a **configurable salary component engine**. That is the single architectural upgrade that would close 80% of your Indian payroll gaps.

---

## 9. Maturity Scorecard (1–5)

| Area | Score | Trend vs Old Report |
|---|---|---|
| Code organization | 3.0 | ↑ (services separated, duplicates removed) |
| Database design | 3.5 | → |
| Web UI / admin | 4.0 | → |
| Mobile / ESS | 4.0 | ↑ (CSRF fixed, PWA stable) |
| Payroll correctness | 2.0 | → (multi-month leave fixed, but statutory gaps remain) |
| Security | 2.5 | ↑ (rate limiter + brute force added, but core gaps remain) |
| Testing | 1.5 | → |
| DevOps / deployment | 3.0 | ↑ (Render + Postgres live) |
| Documentation | 2.5 | → |
| **Overall** | **2.9** | ↑ |

---

## 10. Strategic Recommendations (Prioritized)

### Phase 1 — Stabilize (In Progress)
1. Fix admin password / force change on first login.
2. Mask PII in admin lists (phone, PAN, Aadhar, bank).
3. Guard against negative net salary.
4. Expand tests to cover leaves, attendance, API, exports.
5. Remove/secure `/backup` route.

### Phase 2 — Indian Payroll Compliance
6. Update ESI employee rate to **0.75%** and add employer ESI **3.25%**.
7. Add **Professional Tax** engine with state slabs.
8. Separate **paid vs unpaid leave** and consume `LeaveBalance`.
9. Add **joining-date and relieving-date proration**.
10. Add configurable **salary structure** (basic, HRA, DA, special allowance, etc.).
11. Add **TDS** engine (even a simple old-regime slab).
12. Add **LWF**, **statutory bonus**, **gratuity accrual**.

### Phase 3 — Scale & Productize
13. Add shift/roster management and 5-day-week config.
14. Add document vault (offer letter, IDs, Form 16).
15. Add WhatsApp/email payslip delivery.
16. Add manager/school-head role (RBAC).
17. Implement Alembic migrations.
18. Add background job queue (RQ/Celery) for PDF/SMS/bulk payroll.
19. Build a real mobile app or improve PWA offline support.
20. Add custom reports and analytics dashboard.

---

## 11. Bottom Line

**Robo Pirate HR is a good MVP with a strong UI.** For teachers and employees, the daily experience (punch, view payslip, apply leave) is already better than many overcomplicated Indian HRMS.

**But payroll is the heart of an HRMS, and your payroll engine is not yet India-safe.** Before charging money or onboarding more schools, you must:
- Fix the **ESI rate**.
- Add **PT, TDS, LWF**.
- Handle **LOP and joining/exit proration**.
- Build a **configurable salary structure**.

Until then, treat it as a **pilot attendance + basic payroll tracker**, not a statutory payroll product. The roadmap above gives you a clear path to become competitive with Zoho Payroll / SalaryBox for schools in 3–6 months.

---

*Report generated from live codebase inspection, Indian HRMS market research, and open-source project comparison.*
