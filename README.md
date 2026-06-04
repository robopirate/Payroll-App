# PayrollPro — HR & Payroll Management System

A Python Flask web application for managing payroll, attendance, and HR operations for small businesses.

---

## Features

- **Employee Records** — Name, phone, email, department, designation, salary, bank details, PAN, Aadhar
- **Daily Attendance Tracking** — Present, Absent, Half Day, Overtime, Leave, Holiday
- **Auto Salary Calculation** — Basic + HRA + Overtime − PF − ESI − Advances
- **PDF Payslip Generation** — Download professional payslips per employee per month
- **Leave Management** — Apply, approve/reject, track balances (Casual / Sick / Earned)
- **Salary Advances** — Record, approve, deduct from payroll
- **SMS Alerts** — Via Fast2SMS API (salary credited, custom messages)
- **Admin Dashboard** — Stats, quick actions, recent payroll overview
- **SQLite Database** — No separate database server required

---

## Requirements

- Python 3.9 or higher
- Windows 10/11 (also works on Linux/Mac)
- Internet connection (for Bootstrap CDN and SMS)

---

## Quick Start (Windows)

### Option 1 — Double-click batch file (easiest)

1. Open `C:\Users\omkar\payroll_app\` in File Explorer
2. Double-click `run.bat`
3. Wait for dependencies to install (first run only)
4. Open your browser at **http://localhost:5000**

### Option 2 — Manual setup

```cmd
cd C:\Users\omkar\payroll_app

# Create virtual environment
python -m venv venv
venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run the app
python app.py
```

Open **http://localhost:5000** in your browser.

---

## Default Login

| Username | Password  |
|----------|-----------|
| admin    | admin123  |

**Change the password immediately** in Settings after first login.

---

## SMS Setup (Fast2SMS)

1. Register at [fast2sms.com](https://www.fast2sms.com)
2. Get your API key from the dashboard
3. In the app: go to **Settings → Fast2SMS API Key** and enter it

For permanent configuration, set an environment variable before running:

```cmd
set FAST2SMS_API_KEY=your_api_key_here
python app.py
```

---

## Salary Calculation Formula

```
Daily Rate      = Basic Salary / Working Days in Month
Earned Basic    = Daily Rate × Days Present (half-day = 0.5)
HRA             = 40% of Earned Basic
Overtime Pay    = (Basic / 26 / 8) × 2 × Overtime Hours
Gross Salary    = Earned Basic + HRA + Overtime Pay

PF Deduction    = 12% of Earned Basic
ESI Deduction   = 1.75% of Gross (only if Gross ≤ Rs.21,000)
Advance Deduct  = Approved advance amount for this month

Net Salary      = Gross − PF − ESI − Advance
```

---

## File Structure

```
payroll_app/
├── app.py              # Main Flask application & routes
├── models.py           # SQLAlchemy database models
├── config.py           # Configuration settings
├── pdf_service.py      # PDF payslip generation (ReportLab)
├── sms_service.py      # Fast2SMS integration
├── requirements.txt    # Python dependencies
├── run.bat             # Windows one-click launcher
├── payroll.db          # SQLite database (auto-created)
├── templates/
│   ├── base.html
│   ├── login.html
│   ├── dashboard.html
│   ├── departments.html
│   ├── advances.html
│   ├── sms.html
│   ├── settings.html
│   ├── employees/
│   │   ├── list.html
│   │   ├── form.html
│   │   └── detail.html
│   ├── attendance/
│   │   ├── mark.html
│   │   └── report.html
│   ├── leaves/
│   │   ├── list.html
│   │   ├── apply.html
│   │   └── balances.html
│   └── payroll/
│       └── list.html
└── static/
    ├── css/style.css
    └── js/main.js
```

---

## How to Use

### 1. Add Departments
Go to **Employees → Departments** and add your departments (e.g., HR, Finance, IT).

### 2. Add Employees
Go to **Employees → Add Employee**. Fill in personal details, department, salary, and bank details.

### 3. Mark Attendance
Go to **Attendance** daily. Select a date, mark each employee's status, and save.
- Use "All Present" for quick marking
- Set overtime hours when status = Overtime

### 4. Manage Leaves
- **Apply Leave**: Submit leave applications for employees
- **Manage Leaves**: Approve or reject pending applications
- **Leave Balances**: View remaining leave days per employee

### 5. Record Advances
Go to **Advances**. Record advance amounts and specify which month to deduct them. Approve pending advances.

### 6. Generate Payroll
Go to **Payroll**. Select month/year and click "Generate All Payrolls". The system auto-calculates based on attendance. Then:
- **Finalize** → locks the payroll
- **Mark Paid** → records payment date
- **Download PDF** → generates the payslip
- **Send SMS** → notifies employee via Fast2SMS

---

## Troubleshooting

**Port already in use:**
```cmd
set FLASK_RUN_PORT=5001
python app.py
```

**Module not found errors:**
```cmd
venv\Scripts\activate
pip install -r requirements.txt
```

**Database reset (caution — deletes all data):**
```cmd
del payroll.db
python app.py
```
