"""Attendance and geolocation utilities."""
from datetime import date, timedelta, datetime
import calendar
import math

from models import db, Holiday, Employee, Attendance, Leave


def get_working_days_in_month(year, month):
    _, days_in_month = calendar.monthrange(year, month)
    first_day = date(year, month, 1)
    last_day = date(year, month, days_in_month)
    holidays = {h.date for h in Holiday.query.filter(
        Holiday.date >= first_day,
        Holiday.date <= last_day,
        Holiday.is_active == True
    ).all()}
    working = 0
    for d in range(1, days_in_month + 1):
        current_date = date(year, month, d)
        if current_date.weekday() < 6 and current_date not in holidays:
            working += 1
    return working


def count_working_days_between(start_date, end_date):
    """Count working days (Mon-Sat) between two dates, excluding holidays."""
    holidays = {h.date for h in Holiday.query.filter(
        Holiday.date >= start_date,
        Holiday.date <= end_date,
        Holiday.is_active == True
    ).all()}
    days = 0
    current = start_date
    while current <= end_date:
        if current.weekday() < 6 and current not in holidays:
            days += 1
        current += timedelta(days=1)
    return days


def haversine_distance(lat1, lng1, lat2, lng2):
    """Return distance in metres between two GPS coordinates."""
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ─── Shift timing helpers ─────────────────────────────────────────────────────

def _time_to_minutes(value):
    """Convert 'HH:MM' string to minutes since midnight."""
    if not value or ':' not in str(value):
        return None
    try:
        parts = str(value).strip().split(':')
        hours = int(parts[0])
        minutes = int(parts[1])
        if not (0 <= hours <= 23 and 0 <= minutes <= 59):
            return None
        return hours * 60 + minutes
    except (ValueError, IndexError):
        return None


def _minutes_to_time(minutes):
    """Convert minutes since midnight to 'HH:MM' string."""
    if minutes is None:
        return None
    minutes = max(0, int(minutes)) % (24 * 60)
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def get_employee_active_school(employee):
    """Return the employee's first active assigned school, or None."""
    if not employee:
        return None
    for school in employee.schools:
        if school.is_active:
            return school
    return None


def get_employee_effective_shift(employee):
    """Return the effective (shift_start, shift_end, working_hours_per_day) for an employee.

    Employee-level values override the school's default values. Falls back to
    the application config working hours when no value is available anywhere.
    """
    from flask import current_app
    school = get_employee_active_school(employee)
    shift_start = (
        employee.shift_start if employee and employee.shift_start is not None
        else (school.shift_start if school else None)
    )
    shift_end = (
        employee.shift_end if employee and employee.shift_end is not None
        else (school.shift_end if school else None)
    )
    working_hours = (
        employee.working_hours_per_day if employee and employee.working_hours_per_day is not None
        else (school.working_hours_per_day if school else None)
    )
    if working_hours is None:
        working_hours = current_app.config.get('WORKING_HOURS_PER_DAY', 8.0)
    return shift_start, shift_end, working_hours


def compute_late_minutes(check_in, shift_start, grace_minutes=0):
    """Return minutes late after shift_start + grace."""
    check_mins = _time_to_minutes(check_in)
    start_mins = _time_to_minutes(shift_start)
    if check_mins is None or start_mins is None:
        return 0
    threshold = start_mins + (grace_minutes or 0)
    return max(0, check_mins - threshold)


def compute_early_minutes(check_out, shift_end):
    """Return minutes left before shift_end."""
    out_mins = _time_to_minutes(check_out)
    end_mins = _time_to_minutes(shift_end)
    if out_mins is None or end_mins is None:
        return 0
    return max(0, end_mins - out_mins)


def ensure_absent_attendance(date_obj):
    """Create status='absent' attendance rows for active employees who have no
    record for a working day. Skips Sundays, holidays, approved leaves, and
    days before the employee's joining date. Idempotent.
    """
    if date_obj.weekday() == 6:
        return
    is_holiday = Holiday.query.filter_by(date=date_obj, is_active=True).first() is not None
    if is_holiday:
        return

    employees = Employee.query.filter_by(is_active=True, is_approved=True).all()
    existing = {a.employee_id for a in Attendance.query.filter_by(date=date_obj).all()}
    on_leave = {
        l.employee_id for l in Leave.query.filter(
            Leave.status == 'approved',
            Leave.start_date <= date_obj,
            Leave.end_date >= date_obj
        ).all()
    }

    added = False
    for emp in employees:
        if emp.id in existing or emp.id in on_leave:
            continue
        if date_obj < emp.joining_date:
            continue
        db.session.add(Attendance(
            employee_id=emp.id,
            date=date_obj,
            status='absent',
            admin_override=False,
            late_minutes=0,
            early_minutes=0
        ))
        added = True

    if added:
        db.session.commit()


def calculate_paid_days(employee, year, month):
    """Return the number of paid days for an employee in a given month,
    using the same rules as payroll:
      - present / overtime / holiday attendance
      - half_day counts as 0.5
      - approved leave working days
      - unrecorded Sundays and holidays
    Joining date is respected.
    """
    _, dim = calendar.monthrange(year, month)
    month_start = date(year, month, 1)
    month_end = date(year, month, dim)

    if employee.joining_date and employee.joining_date > month_end:
        return 0.0

    effective_start = max(month_start, employee.joining_date or month_start)

    attendances = Attendance.query.filter_by(employee_id=employee.id).filter(
        Attendance.date >= effective_start,
        Attendance.date <= month_end
    ).all()

    paid_days = 0.0
    attended_dates = {a.date for a in attendances}
    for att in attendances:
        if att.status in ('present', 'overtime', 'holiday'):
            paid_days += 1.0
        elif att.status == 'half_day':
            paid_days += 0.5

    # Approved leave working days
    approved_leaves = Leave.query.filter_by(
        employee_id=employee.id, status='approved'
    ).filter(
        Leave.start_date <= month_end,
        Leave.end_date >= effective_start
    ).all()
    for leave in approved_leaves:
        start = max(leave.start_date, effective_start)
        end = min(leave.end_date, month_end)
        if start <= end:
            paid_days += count_working_days_between(start, end)

    # Unrecorded Sundays / holidays
    holidays = {h.date for h in Holiday.query.filter(
        Holiday.date >= effective_start,
        Holiday.date <= month_end,
        Holiday.is_active == True
    ).all()}

    current = effective_start
    while current <= month_end:
        if current not in attended_dates and (current.weekday() == 6 or current in holidays):
            paid_days += 1.0
        current += timedelta(days=1)

    return paid_days


def backfill_absent_attendance(year, month):
    """Backfill absent records for all missing working days in the month up to
    yesterday. If the current day is past the configured cutoff hour, include it.
    """
    from flask import current_app
    _, dim = calendar.monthrange(year, month)
    today = date.today()
    cutoff = current_app.config.get('ABSENT_MARK_CUTOFF_HOUR', 18)

    for d in range(1, dim + 1):
        d_obj = date(year, month, d)
        if d_obj > today:
            continue
        if d_obj == today and datetime.now().hour < cutoff:
            continue
        ensure_absent_attendance(d_obj)


def ensure_sunday_attendance(date_obj):
    """For a Sunday, auto-create status='present' attendance rows for all active
    employees who do not already have a record for that date, unless the date is
    a declared holiday or the employee has an approved leave.
    """
    if date_obj.weekday() != 6:
        return

    is_holiday = Holiday.query.filter_by(date=date_obj, is_active=True).first() is not None
    if is_holiday:
        return

    employees = Employee.query.filter_by(is_active=True, is_approved=True).all()
    existing = {a.employee_id for a in Attendance.query.filter_by(date=date_obj).all()}
    on_leave = {
        l.employee_id for l in Leave.query.filter(
            Leave.status == 'approved',
            Leave.start_date <= date_obj,
            Leave.end_date >= date_obj
        ).all()
    }

    added = False
    for emp in employees:
        if emp.id in existing or emp.id in on_leave:
            continue
        if date_obj < emp.joining_date:
            continue
        db.session.add(Attendance(employee_id=emp.id, date=date_obj, status='present'))
        added = True

    if added:
        db.session.commit()


def _compute_expected_end_time(check_in, shift_end, working_hours):
    """Return the expected end-of-day time for an employee.

    Uses the later of shift_end and (check_in + working_hours) so latecomers
    who complete their full shift are not penalised.
    """
    check_mins = _time_to_minutes(check_in)
    if check_mins is None:
        return shift_end
    required_minutes = int((working_hours or 8.0) * 60)
    expected_from_checkin = _minutes_to_time(check_mins + required_minutes)
    end_mins = _time_to_minutes(shift_end)
    if end_mins is None:
        return expected_from_checkin
    return expected_from_checkin if _time_to_minutes(expected_from_checkin) > end_mins else shift_end


def _compute_overtime_hours(check_out, expected_end):
    """Return overtime hours worked past the expected end time."""
    out_mins = _time_to_minutes(check_out)
    end_mins = _time_to_minutes(expected_end)
    if out_mins is None or end_mins is None:
        return 0.0
    return max(0.0, (out_mins - end_mins) / 60.0)


def auto_close_missing_checkouts(date_obj):
    """Close attendance records that have a check_in but no check_out.

    Sets check_out to the employee's shift_end, flags the record as auto-closed,
    and leaves overtime at zero. Returns the number of records closed.
    """
    records = Attendance.query.filter(
        Attendance.date == date_obj,
        Attendance.check_in.isnot(None),
        db.or_(
            Attendance.check_out.is_(None),
            Attendance.check_out == ''
        )
    ).all()
    closed = 0
    for att in records:
        emp = att.employee
        shift_start, shift_end, working_hours = get_employee_effective_shift(emp)
        if shift_end:
            att.check_out = shift_end
        elif att.check_in:
            att.check_out = _compute_expected_end_time(att.check_in, None, working_hours)
        else:
            continue
        att.auto_checkout = True
        att.overtime_hours = 0.0
        update_attendance_timing_flags(att, employee=emp)
        closed += 1
    if closed:
        db.session.commit()
    return closed


def update_attendance_timing_flags(attendance, employee=None):
    """Set late_minutes / early_minutes based on effective shift timings."""
    if not attendance:
        return
    attendance.late_minutes = 0
    attendance.early_minutes = 0
    emp = employee if employee is not None else attendance.employee
    shift_start, shift_end, _ = get_employee_effective_shift(emp)
    school = get_employee_active_school(emp)
    grace_minutes = school.grace_minutes if school else 0
    if attendance.check_in and shift_start:
        attendance.late_minutes = compute_late_minutes(
            attendance.check_in, shift_start, grace_minutes
        )
    if attendance.check_out and shift_end:
        attendance.early_minutes = compute_early_minutes(
            attendance.check_out, shift_end
        )
