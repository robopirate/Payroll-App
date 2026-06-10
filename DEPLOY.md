# Phase 2 Deployment Guide — PythonAnywhere

**Commit:** `540da75` — Phase 2: JWT Authentication API + Schema Fixes + Swagger Docs  
**Date:** 10 June 2026

---

## ⚡ Quick Deploy (Copy-Paste into PythonAnywhere Bash Console)

```bash
cd ~/Payroll-App && git pull origin main && source venv/bin/activate && pip install -r requirements.txt && echo "--- Deploy ready ---"
```

Then **reload your web app** from the PythonAnywhere Web tab.

---

## 📋 Step-by-Step Deployment

### Step 1: Open PythonAnywhere Bash Console

1. Log in to [pythonanywhere.com](https://www.pythonanywhere.com)
2. Go to **Consoles** → **Bash**
3. Or use the existing console if you have one open

### Step 2: Pull Latest Code

```bash
cd ~/Payroll-App
git pull origin main
```

If you get a merge conflict, run:
```bash
cd ~/Payroll-App
git stash
git pull origin main
git stash pop
```

### Step 3: Install New Dependencies

```bash
cd ~/Payroll-App
source venv/bin/activate
pip install -r requirements.txt
```

**New packages:**
- `Flask-JWT-Extended==4.6.0` — JWT authentication
- `flasgger==0.9.7.1` — Swagger/OpenAPI documentation

### Step 4: Reload Web App

1. Go to **Web** tab in PythonAnywhere
2. Click **Reload** button for `itsrobopirate.pythonanywhere.com`
3. Wait 10–20 seconds for the app to restart

---

## ⚠️ CRITICAL: Post-Deployment Actions

### Action 1: Approve Existing Employees (If Not Done in Phase 1)

The `is_approved` column defaults to `0` (pending) for all existing employees.

1. Log in as admin: `https://itsrobopirate.pythonanywhere.com/login`
2. Go to **Employees**
3. Change the **Status** filter from "Approved" to **"Pending Approval"**
4. Click the green **✓ Approve** button for each employee

### Action 2: Set Portal Passwords for Employees (For JWT Login)

JWT login requires each employee to have a portal password set by admin.

1. Go to **Employees** → click any employee
2. In the **Portal Access** section, set a password
3. Click **Save**
4. The employee can now log in via mobile app using:
   - **Phone:** their registered phone number
   - **Password:** the password you just set

### Action 3: Test JWT Authentication

From Postman or curl:

**Employee Login:**
```bash
curl -X POST https://itsrobopirate.pythonanywhere.com/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"phone": "9876543210", "password": "test123"}'
```

Expected response:
```json
{
  "success": true,
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "Bearer",
  "expires_in": 900,
  "user_type": "employee",
  "employee_id": 1
}
```

**Admin Login:**
```bash
curl -X POST https://itsrobopirate.pythonanywhere.com/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "admin123"}'
```

### Action 4: Test Mobile Punch with JWT

```bash
# First get a token
curl -X POST https://itsrobopirate.pythonanywhere.com/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"phone": "9876543210", "password": "test123"}'

# Use the access_token from the response
curl -X POST https://itsrobopirate.pythonanywhere.com/api/punch \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <access_token>" \
  -d '{"lat": 18.5, "lng": 73.8, "action": "in"}'
```

Expected: `{"success": true, "message": "Punched IN at ..."}`

### Action 5: Test v1 API Endpoints

```bash
# Profile
curl https://itsrobopirate.pythonanywhere.com/api/v1/employee/profile \
  -H "Authorization: Bearer <access_token>"

# Today's attendance
curl https://itsrobopirate.pythonanywhere.com/api/v1/attendance/today \
  -H "Authorization: Bearer <access_token>"

# Monthly attendance
curl "https://itsrobopirate.pythonanywhere.com/api/v1/attendance/monthly?month=6&year=2026" \
  -H "Authorization: Bearer <access_token>"

# Leave history
curl https://itsrobopirate.pythonanywhere.com/api/v1/leaves \
  -H "Authorization: Bearer <access_token>"

# Holidays
curl https://itsrobopirate.pythonanywhere.com/api/v1/holidays \
  -H "Authorization: Bearer <access_token>"
```

### Action 6: Test Token Refresh

```bash
curl -X POST https://itsrobopirate.pythonanywhere.com/api/v1/auth/refresh \
  -H "Authorization: Bearer <refresh_token>"
```

Expected: New `access_token` with 15-minute expiry.

### Action 7: Test Logout (Token Revocation)

```bash
curl -X POST https://itsrobopirate.pythonanywhere.com/api/v1/auth/logout \
  -H "Authorization: Bearer <access_token>"
```

After logout, the same token should return `401 Token has been revoked`.

### Action 8: Test Swagger API Documentation

Open in your browser:
```
https://itsrobopirate.pythonanywhere.com/api/docs/
```

You should see an interactive Swagger UI with:
- All JWT Authentication endpoints (login, refresh, logout, me)
- All v1 API endpoints (profile, attendance, leaves, payroll, holidays)
- Request/response schemas with examples
- "Authorize" button to test with your JWT token

To test an endpoint in Swagger UI:
1. Click **Authorize** (top right)
2. Enter: `Bearer <your_access_token>`
3. Click **Authorize** → **Close**
4. Expand any endpoint → Click **Try it out** → **Execute**

---

## 🔍 Rollback Plan (If Something Breaks)

If the deployment causes issues, roll back immediately:

```bash
cd ~/Payroll-App
git reset --hard HEAD~1
git pull origin main --force  # if needed
```

Then reload the web app again.

---

## 📊 What Changed in This Deploy

| File | Change |
|------|--------|
| `requirements.txt` | Added `Flask-JWT-Extended==4.6.0`, `flasgger==0.9.7.1` |
| `config.py` | JWT config (15-min access, 7-day refresh, Bearer tokens) |
| `extensions.py` | Added `JWTManager` instance |
| `app.py` | Registered `jwt_auth` blueprint; added `location_type` migrations; Swagger init |
| `blueprints/jwt_auth.py` | **NEW** — JWT auth endpoints with Swagger docs |
| `blueprints/api.py` | CSRF-exempt punch; JWT-protected v1 endpoints with Swagger docs |

---

## ✅ Deployment Verification Checklist

After deploying, verify each feature:

- [ ] App loads without errors (`https://itsrobopirate.pythonanywhere.com/`)
- [ ] Admin login works (`admin / admin123`)
- [ ] Employee JWT login returns access + refresh tokens
- [ ] Admin JWT login returns access + refresh tokens
- [ ] `/api/v1/auth/me` returns correct user info
- [ ] Mobile punch works with JWT (no CSRF errors)
- [ ] Token refresh returns new access token
- [ ] Logout revokes token (subsequent calls return 401)
- [ ] v1 endpoints return 200 with valid JWT
- [ ] v1 endpoints return 401 without JWT
- [ ] Existing web portal (session-based) still works
- [ ] **Swagger UI loads at `/api/docs/`**
- [ ] **Can authorize and test endpoints in Swagger UI**

---

*Deploy this commit to enable secure mobile API access with JWT authentication.*
