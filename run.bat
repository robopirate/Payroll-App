@echo off
echo ================================================
echo   PayrollPro - HR & Payroll Management System
echo ================================================
echo.

REM Check if virtual environment exists
if not exist "venv_new\Scripts\activate.bat" (
    echo Creating virtual environment...
    python -m venv venv_new
    echo.
)

REM Activate virtual environment
call venv_new\Scripts\activate.bat

REM Install dependencies
echo Installing dependencies...
pip install -r requirements.txt --quiet
echo.

REM Run the app in development mode
echo Starting PayrollPro on http://localhost:5000
echo Default login: admin / admin123
echo Press Ctrl+C to stop.
echo.
set FLASK_ENV=development
python app.py
pause
