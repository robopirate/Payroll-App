# Robo Pirate HR — Incident Autopsy: `/payroll` Internal Server Error

**Date:** 14 June 2026  
**Reporter:** Omkar Singh  
**Affected URL:** `https://payroll-app-xd1d.onrender.com/payroll`  
**Environment:** Render (free) + PostgreSQL 15  
**Codebase commit at time of incident:** `de9e170`  

---

## 1. Symptom

- Admin dashboard (`/dashboard`) loads successfully and shows recent payroll activity.
- Navigating to **Payroll Management** (`/payroll`) returns:
  > `Internal Server Error — The server encountered an internal error and was unable to complete your request.`
- Screenshot shows June 2026 payroll figures are still using the **old** ESI rate (1.75%) and do **not** show PT/TDS/LWF yet.

---

## 2. What Changed Recently

| Commit | Change | Risk |
|---|---|---|
| `580c702` / `b4413a2` | Added `TaxDeclaration` model, TDS calculation, LWF constants | New table + new columns in `payrolls` |
| `c7af2c3` / `f2c9ef5` | Updated ESI rate, added PT, removed Quick Mark panel, leave delete buttons | New columns in `payrolls`, DB schema drift |
| `de9e170` | Added `prelaunch_check.py` + test PDF | Low/no runtime impact |

The payroll model now expects these columns on the `payrolls` table:

```text
pt_deduction
lwf_deduction
tds_deduction
```

`app.py::safe_migrate()` attempts to add them on startup, but on Render this depends on the deploy actually running the newest container and the migration not failing silently.

---

## 3. Most Likely Root Causes (ranked)

### 🔴 #1 — Database schema drift on `payrolls`

**Why:** The code was updated to read/write `pt_deduction`, `lwf_deduction`, and `tds_deduction`, but the live PostgreSQL table may still be missing one or more of these columns. SQLAlchemy then raises an `OperationalError` as soon as `Payroll.query.filter_by(...).all()` runs on `/payroll`.

**Supporting evidence:**
- Old payroll numbers are still visible on the dashboard, meaning the rows exist and were calculated before the new columns existed.
- The crash happens on the payroll list route, which only queries `Payroll` and renders it — no complex math.
- Local SQLite and pre-launch checklist pass, so the code itself is not broken; the divergence is between the deployed model and the live DB.

**Fix:** Run this SQL directly on the Render Postgres DB:

```sql
ALTER TABLE payrolls
  ADD COLUMN IF NOT EXISTS pt_deduction FLOAT DEFAULT 0.0,
  ADD COLUMN IF NOT EXISTS lwf_deduction FLOAT DEFAULT 0.0,
  ADD COLUMN IF NOT EXISTS tds_deduction FLOAT DEFAULT 0.0;
```

Also verify `tax_declarations` table exists:

```sql
SELECT tablename FROM pg_tables WHERE schemaname='public';
```

If it is missing, create it (or redeploy — `db.create_all()` should create it on startup).

---

### 🟡 #2 — Render container is still running an older build

**Why:** Adding an environment variable can trigger a redeploy, but Render sometimes serves the previous build if the new one fails or is still in progress.

**Check:** Open the Render dashboard → `payroll-pro` → **Events / Logs**. Confirm the latest deploy succeeded and is running commit `de9e170`.

**Fix:** If in doubt, redeploy manually or push a trivial no-op commit.

---

### 🟡 #3 — Stale payroll row references a deleted/invalid employee

**Why:** The payroll list template does `p.employee.name`. If an employee was deleted but their payroll rows remain, `p.employee` is `None` and the page crashes.

**Evidence against:** The dashboard recent-payroll widget also renders `p.employee.name` and it loads fine, so the rows likely have valid employee links.

**Fix anyway:** Add a defensive fallback in `templates/payroll/list.html` and `templates/dashboard.html`:

```jinja2
{{ p.employee.name if p.employee else 'Unknown/Deleted' }}
```

---

## 4. Immediate Action Plan

1. **Get the exact traceback** from Render logs (dashboard → `payroll-pro` → Logs). This will confirm which of the above is the real cause.
2. **Apply the schema fix** if the log says `column payrolls.xxx does not exist`.
3. **Regenerate June 2026 payrolls** after the schema is correct (click **Generate All Payrolls**) so the old ESI/math is overwritten with PT/TDS/LWF.
4. **Hard refresh** the browser (`Ctrl + Shift + R`) to clear the PWA service-worker cache.

---

## 5. Preventive Recommendations

| Issue | Recommendation |
|---|---|
| No real migration framework | Adopt **Flask-Migrate / Alembic** instead of hand-written `ALTER TABLE` in `safe_migrate()`. |
| No error visibility | Add a logging handler (e.g., Render logs are fine, but also email/Sentry for 500s). |
| Schema mismatch can crash pages | Add a `/health` endpoint that verifies all expected tables/columns exist on startup. |
| Stale cached portal pages | Change `sw.js` to a **network-first** strategy. |
| Deleted employees leave orphan payrolls | Add `ON DELETE CASCADE` or soft-delete for employees. |

---

## 6. Verdict

**Primary suspected cause:** PostgreSQL `payrolls` table is missing `pt_deduction`, `lwf_deduction`, or `tds_deduction` on the live Render DB, causing SQLAlchemy to throw an `OperationalError` the moment the payroll list is queried.

**Next step:** Paste the Render error log here, or run the `ALTER TABLE` statement above and redeploy.
