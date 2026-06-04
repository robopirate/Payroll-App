@echo off
echo ================================================
echo   PayrollPro - HR & Payroll Management System
echo ================================================
echo.

REM Check if virtual environment exists
if not exist "venv\Scripts\activate.bat" (
    echo Creating virtual environment...
    python -m venv venv
    echo.
)

REM Activate virtual environment
call venv\Scripts\activate.bat

REM Install dependencies
echo Installing dependencies...
pip install -r requirements.txt --quiet
echo.

REM Run the app
echo Starting PayrollPro on http://localhost:5000
echo Default login: admin / admin123
echo Press Ctrl+C to stop.
echo.
python app.py
pause
