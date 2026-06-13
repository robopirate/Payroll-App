#!/usr/bin/env python
"""Pre-launch checklist for Payroll App."""
import sys
from datetime import datetime

from app import app, db
from models import (
    Employee, Payroll, TaxDeclaration, User, Department,
    School, Attendance, Leave, Holiday, AttendanceLock, AppConfig
)
from services.payroll_service import calculate_payroll, _calculate_tds
from config import Config
from sqlalchemy import inspect


def run_checklist():
    print('=' * 60)
    print('PAYROLL APP - PRE-LAUNCH CHECKLIST')
    print('=' * 60)

    with app.app_context():
        # 1. DATABASE SCHEMA CHECK
        print('\n[1] DATABASE SCHEMA')
        inspector = inspect(db.engine)
        tables = inspector.get_table_names()
        required_tables = [
            'employees', 'payrolls', 'attendance', 'leaves',
            'departments', 'schools', 'users', 'tax_declarations', 'app_config'
        ]
        for t in required_tables:
            status = 'OK' if t in tables else 'MISSING'
            print('  %s: %s' % (t, status))

        # Check payroll columns
        payroll_cols = [c['name'] for c in inspector.get_columns('payrolls')]
        print('\n  Payroll columns:')
        for c in ['pt_deduction', 'lwf_deduction', 'tds_deduction']:
            status = 'OK' if c in payroll_cols else 'MISSING'
            print('    %s: %s' % (c, status))

        # 2. CONFIG VALUES
        print('\n[2] CONFIG VALUES')
        print('  ESI_RATE: %s (should be 0.0075)' % Config.ESI_RATE)
        print('  PF_RATE: %s' % Config.PF_RATE)
        print('  PT_AMOUNT: %s' % Config.PT_AMOUNT)
        print('  LWF_EMPLOYEE: %s' % Config.LWF_EMPLOYEE_AMOUNT)
        print('  LWF_THRESHOLD: %s' % Config.LWF_THRESHOLD)

        # 3. TDS CALCULATION TESTS
        print('\n[3] TDS CALCULATION')
        test_cases = [
            (300000, '0 TDS (under 3L slab)'),
            (500000, '0 TDS (under 87A rebate)'),
            (700000, '0 TDS (at 87A limit)'),
            (800000, 'some TDS (above 87A)'),
            (1000000, 'higher TDS'),
            (1500000, '20% slab'),
            (2000000, '30% slab'),
        ]
        for annual, desc in test_cases:
            tds, regime = _calculate_tds(None, annual)
            print('  Annual Rs.%s -> Monthly TDS: Rs.%s (%s) [regime: %s]' % (
                '{:,}'.format(annual), '{:,}'.format(tds), desc, regime
            ))

        # 4. CHECK EXISTING EMPLOYEES
        print('\n[4] EXISTING EMPLOYEES')
        employees = Employee.query.all()
        print('  Total employees: %s' % len(employees))
        for emp in employees:
            print('  - %s (ID: %s, Basic: Rs.%s)' % (
                emp.name, emp.emp_id, emp.basic_salary
            ))

        # 5. PAYROLL GENERATION TEST
        print('\n[5] PAYROLL GENERATION TEST')
        if employees:
            emp = employees[0]
            now = datetime.now()
            result = calculate_payroll(emp, now.month, now.year)
            print('  Employee: %s' % emp.name)
            print('  Gross: Rs.%s' % '{:,.2f}'.format(result['gross_salary']))
            print('  PF: Rs.%s' % '{:,.2f}'.format(result['pf_deduction']))
            print('  ESI: Rs.%s' % '{:,.2f}'.format(result['esi_deduction']))
            print('  PT: Rs.%s' % '{:,.2f}'.format(result['pt_deduction']))
            print('  LWF: Rs.%s' % '{:,.2f}'.format(result['lwf_deduction']))
            print('  TDS: Rs.%s' % '{:,.2f}'.format(result['tds_deduction']))
            print('  Total Deductions: Rs.%s' % '{:,.2f}'.format(result['total_deductions']))
            print('  NET: Rs.%s' % '{:,.2f}'.format(result['net_salary']))
            print('  Tax Regime: %s' % result.get('tax_regime', 'N/A'))
        else:
            print('  WARNING: No employees found!')

        # 6. CHECK ADMIN USER
        print('\n[6] ADMIN USER')
        admin = User.query.filter_by(username='admin').first()
        if admin:
            print('  Admin exists: %s' % admin.username)
            print('  Must change password: %s' % admin.must_change_password)
        else:
            print('  WARNING: No admin user found!')

        # 7. CHECK SCHOOLS
        print('\n[7] SCHOOLS/LOCATIONS')
        schools = School.query.all()
        print('  Total schools: %s' % len(schools))
        for s in schools:
            print('  - %s (active: %s)' % (s.name, s.is_active))

        # 8. CHECK HOLIDAYS
        print('\n[8] HOLIDAYS')
        holidays = Holiday.query.filter_by(year=now.year).all()
        print('  Holidays for %s: %s' % (now.year, len(holidays)))

        # 9. CHECK ATTENDANCE LOCK
        print('\n[9] ATTENDANCE LOCK')
        locks = AttendanceLock.query.all()
        print('  Active locks: %s' % len(locks))

        # 10. APP CONFIG
        print('\n[10] APP CONFIG')
        sms_key = AppConfig.get('sms_api_key', 'NOT SET')
        print('  SMS API key: %s' % ('SET' if sms_key and sms_key != 'NOT SET' else 'NOT SET'))

        # 11. PDF GENERATION TEST
        print('\n[11] PDF GENERATION TEST')
        try:
            from pdf_service import generate_payslip_pdf
            if employees:
                payroll = Payroll.query.filter_by(employee_id=employees[0].id).first()
                if payroll:
                    pdf_bytes = generate_payslip_pdf(employees[0], payroll)
                    print('  PDF generated: %s bytes' % len(pdf_bytes))
                else:
                    print('  No existing payroll record - skipping PDF test')
            else:
                print('  No employees - skipping PDF test')
        except Exception as e:
            print('  ERROR: %s' % str(e))

        # 12. API ENDPOINTS CHECK
        print('\n[12] API ENDPOINTS')
        from app import app as flask_app
        client = flask_app.test_client()
        
        # Check login page
        r = client.get('/login')
        print('  GET /login: %s' % r.status_code)
        
        # Check portal login
        r = client.get('/portal/login')
        print('  GET /portal/login: %s' % r.status_code)
        
        # Check API docs
        r = client.get('/api/docs/')
        print('  GET /api/docs/: %s' % r.status_code)

    print('\n' + '=' * 60)
    print('CHECKLIST COMPLETE')
    print('=' * 60)


if __name__ == '__main__':
    run_checklist()
