"""Payroll calculation service."""
from datetime import date
import calendar

from flask import current_app
from sqlalchemy import extract, and_
from config import Config
from models import db, Attendance, Leave, Advance, School
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
    pf = _round_money(earned_basic * current_app.config['PF_RATE'])
    esi = _round_money(gross * current_app.config['ESI_RATE']) if gross <= current_app.config['ESI_THRESHOLD'] else 0
    pt_deduction = Config.PT_AMOUNT if gross >= Config.PT_THRESHOLD else 0

    advances = Advance.query.filter_by(
        employee_id=employee.id, status='approved',
        month_deducted=month, year_deducted=year
    ).all()
    advance_total = sum(a.amount for a in advances)
    total_deductions = _round_money(pf + esi + pt_deduction + advance_total)
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
        'advance_deduction': round(advance_total, 2), 'other_deductions': 0,
        'total_deductions': total_deductions, 'net_salary': net,
        'net_negative_clamped': net_negative_clamped,
    }
