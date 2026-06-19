"""Payroll calculation service."""
from datetime import date
import calendar

from flask import current_app
from sqlalchemy import extract, and_
from config import Config
from models import db, Attendance, Leave, Advance, TaxDeclaration
from services.attendance_service import get_working_days_in_month, count_working_days_between


def _round_money(value):
    """Round a monetary value to the nearest rupee (Indian payroll norm)."""
    return round(value)


def _get_working_hours_per_day(employee):
    """Return working hours configured for the employee's active location."""
    for school in employee.schools:
        if school.is_active:
            return school.working_hours_per_day or current_app.config['WORKING_HOURS_PER_DAY']
    return current_app.config['WORKING_HOURS_PER_DAY']


def _calculate_tds(employee, gross_annual):
    """Calculate monthly TDS for an employee based on projected annual income.
    
    Uses new tax regime by default (as of FY 2024-25).
    Returns: (monthly_tds, tax_regime_used)
    """
    if gross_annual <= 0:
        return 0, 'new'
    
    # Get tax declaration for current financial year
    current_year = date.today().year
    fy_start = current_year if date.today().month >= 4 else current_year - 1
    
    tax_decl = None
    if employee and hasattr(employee, 'id'):
        tax_decl = TaxDeclaration.query.filter_by(
            employee_id=employee.id, year=fy_start
        ).first()
    
    regime = tax_decl.tax_regime if tax_decl else 'new'
    standard_deduction = tax_decl.standard_deduction if tax_decl else Config.TDS_STANDARD_DEDUCTION
    
    # Calculate taxable income
    if regime == 'new':
        # New regime: standard deduction only, no other exemptions
        taxable_income = max(0, gross_annual - standard_deduction)
    else:
        # Old regime: all investments + HRA + standard deduction
        inv_80c = min(tax_decl.investment_80c if tax_decl else 0, 150000)
        inv_80d = min(tax_decl.investment_80d if tax_decl else 0, 25000)
        inv_80eea = min(tax_decl.investment_80eea if tax_decl else 0, 150000)
        hra_ex = tax_decl.hra_exemption if tax_decl else 0
        other_inv = tax_decl.other_investments if tax_decl else 0
        
        total_deductions = standard_deduction + inv_80c + inv_80d + inv_80eea + hra_ex + other_inv
        taxable_income = max(0, gross_annual - total_deductions)
    
    # Calculate tax using slabs
    tax = 0
    remaining = taxable_income
    for min_val, max_val, rate in Config.TDS_SLABS:
        slab_amount = min(max_val - min_val, remaining - min_val)
        if slab_amount > 0:
            tax += slab_amount * rate
        if remaining <= max_val:
            break
    
    # Rebate under 87A - if taxable income <= 7L, tax = 0 (up to ₹25,000 tax credit)
    if taxable_income <= Config.TDS_REBATE_87A_LIMIT:
        tax = max(0, tax - Config.TDS_REBATE_87A_AMOUNT)
    
    # Add 4% cess
    tax = tax * 1.04
    
    # Divide by 12 for monthly TDS
    monthly_tds = _round_money(tax / 12)
    return monthly_tds, regime


def calculate_payroll(employee, month, year):
    working_days = get_working_days_in_month(year, month)
    attendances = Attendance.query.filter_by(employee_id=employee.id).filter(
        extract('year', Attendance.date) == year,
        extract('month', Attendance.date) == month
    ).all()

    present_days = 0.0
    overtime_hours = 0.0
    for att in attendances:
        if att.status == 'present':
            present_days += 1.0
        elif att.status == 'half_day':
            present_days += 0.5
        elif att.status == 'overtime':
            present_days += 1.0
        # NOTE: 'leave' status in attendance table is just a marker;
        # approved leave days are counted separately from Leave model
        overtime_hours += (att.overtime_hours or 0.0)

    # Count approved leave days overlapping this month.
    # Important: use start_date <= month_end AND end_date >= month_start
    # so multi-month leaves are counted in every month they span.
    month_start = date(year, month, 1)
    _, dim = calendar.monthrange(year, month)
    month_end = date(year, month, dim)

    approved_leaves = Leave.query.filter_by(
        employee_id=employee.id, status='approved'
    ).filter(
        and_(
            Leave.start_date <= month_end,
            Leave.end_date >= month_start
        )
    ).all()

    leave_days_in_month = 0.0
    for leave in approved_leaves:
        start = max(leave.start_date, month_start)
        end = min(leave.end_date, month_end)
        if start <= end:
            leave_days_in_month += count_working_days_between(start, end)
    present_days += leave_days_in_month

    daily_rate = employee.basic_salary / working_days if working_days > 0 else 0
    earned_basic = _round_money(daily_rate * present_days)
    hourly_rate = (
        employee.basic_salary
        / current_app.config['WORKING_DAYS_PER_MONTH']
        / _get_working_hours_per_day(employee)
    )
    overtime_pay = _round_money(
        hourly_rate * current_app.config['OVERTIME_RATE_MULTIPLIER'] * overtime_hours
    )
    hra = _round_money(earned_basic * current_app.config['HRA_RATE'])
    gross = _round_money(earned_basic + hra + overtime_pay)

    emp_type = getattr(employee, 'employee_type', 'full_time')
    is_contract_or_parttime = emp_type in ('contract', 'part_time')

    if is_contract_or_parttime:
        # Contract / part-time employees do not get statutory deductions
        pf = 0
        esi = 0
        pt_deduction = 0
        lwf_deduction = 0
        tds_deduction = 0
        tax_regime = 'n/a'
    else:
        pf = _round_money(earned_basic * current_app.config['PF_RATE'])
        esi = _round_money(gross * current_app.config['ESI_RATE']) if gross <= current_app.config['ESI_THRESHOLD'] else 0
        pt_deduction = Config.PT_AMOUNT if gross >= Config.PT_THRESHOLD else 0
        # LWF (Labour Welfare Fund) - only if gross <= threshold
        lwf_deduction = Config.LWF_EMPLOYEE_AMOUNT if gross <= Config.LWF_THRESHOLD else 0
        # TDS calculation - project annual gross based on current month
        projected_annual = gross * 12
        tds_deduction, tax_regime = _calculate_tds(employee, projected_annual)

    advances = Advance.query.filter_by(
        employee_id=employee.id, status='approved',
        month_deducted=month, year_deducted=year
    ).all()
    advance_total = sum(a.amount for a in advances)
    total_deductions = _round_money(pf + esi + pt_deduction + lwf_deduction + tds_deduction + advance_total)
    net_raw = gross - total_deductions
    net_negative_clamped = net_raw < 0
    net = _round_money(max(net_raw, 0))

    return {
        'working_days': working_days, 'present_days': present_days,
        'basic_salary': earned_basic, 'overtime_hours': overtime_hours,
        'overtime_pay': overtime_pay, 'hra': hra,
        'other_allowances': 0, 'gross_salary': gross,
        'pf_deduction': pf, 'esi_deduction': esi,
        'pt_deduction': pt_deduction,
        'lwf_deduction': lwf_deduction,
        'tds_deduction': tds_deduction,
        'tax_regime': tax_regime,
        'advance_deduction': round(advance_total, 2), 'other_deductions': 0,
        'total_deductions': total_deductions, 'net_salary': net,
        'net_negative_clamped': net_negative_clamped,
    }
