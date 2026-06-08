"""Payroll calculation service."""
from datetime import date
import calendar

from flask import current_app
from sqlalchemy import extract
from models import db, Attendance, Leave, Advance
from services.attendance_service import get_working_days_in_month, count_working_days_between


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
        elif att.status == 'leave':
            present_days += 1.0
        overtime_hours += (att.overtime_hours or 0.0)

    # Also count approved leave days that may not have attendance records
    approved_leaves = Leave.query.filter_by(
        employee_id=employee.id, status='approved'
    ).filter(
        extract('year', Leave.start_date) == year,
        extract('month', Leave.start_date) == month
    ).all()
    leave_days_in_month = 0.0
    for leave in approved_leaves:
        month_start = date(year, month, 1)
        _, dim = calendar.monthrange(year, month)
        month_end = date(year, month, dim)
        start = max(leave.start_date, month_start)
        end = min(leave.end_date, month_end)
        if start <= end:
            leave_days_in_month += count_working_days_between(start, end)
    present_days += leave_days_in_month

    daily_rate = employee.basic_salary / working_days if working_days > 0 else 0
    earned_basic = daily_rate * present_days
    hourly_rate = (
        employee.basic_salary
        / current_app.config['WORKING_DAYS_PER_MONTH']
        / current_app.config['WORKING_HOURS_PER_DAY']
    )
    overtime_pay = hourly_rate * current_app.config['OVERTIME_RATE_MULTIPLIER'] * overtime_hours
    hra = earned_basic * current_app.config['HRA_RATE']
    gross = earned_basic + hra + overtime_pay
    pf = earned_basic * current_app.config['PF_RATE']
    esi = gross * current_app.config['ESI_RATE'] if gross <= current_app.config['ESI_THRESHOLD'] else 0

    advances = Advance.query.filter_by(
        employee_id=employee.id, status='approved',
        month_deducted=month, year_deducted=year
    ).all()
    advance_total = sum(a.amount for a in advances)
    total_deductions = pf + esi + advance_total
    net = gross - total_deductions

    return {
        'working_days': working_days, 'present_days': present_days,
        'basic_salary': round(earned_basic, 2), 'overtime_hours': overtime_hours,
        'overtime_pay': round(overtime_pay, 2), 'hra': round(hra, 2),
        'other_allowances': 0.0, 'gross_salary': round(gross, 2),
        'pf_deduction': round(pf, 2), 'esi_deduction': round(esi, 2),
        'advance_deduction': round(advance_total, 2), 'other_deductions': 0.0,
        'total_deductions': round(total_deductions, 2), 'net_salary': round(net, 2),
    }
