"""Missed punch-out corrections ("regularization").

Rules (industry standard, as in Keka / greytHR / Zoho People):
  * An employee can ask for a correction only within a short window after the day.
  * Corrections per month are capped.
  * An admin approves or rejects; a rejection needs a note.
  * Every change is written to the audit log (who, what, old value, new value).
  * Nothing changes once the month is locked or that month's salary is finalized/paid.
"""
from datetime import datetime, timezone

from models import (
    db, AttendanceLock, AuditLog, AppConfig, Payroll, AttendanceRegularization,
)
from services.attendance_service import (
    today_ist, update_attendance_timing_flags, get_employee_effective_shift,
    _compute_expected_end_time, _compute_overtime_hours, _time_to_minutes,
)

DEFAULT_WINDOW_DAYS = 3
DEFAULT_MAX_PER_MONTH = 3


def get_int_setting(key, default):
    """Read a whole-number setting from AppConfig, falling back to the default."""
    try:
        value = AppConfig.get(key)
        return int(value) if value not in (None, '') else default
    except (TypeError, ValueError):
        return default


def window_days():
    return get_int_setting('regularization_window_days', DEFAULT_WINDOW_DAYS)


def max_per_month():
    return get_int_setting('regularization_max_per_month', DEFAULT_MAX_PER_MONTH)


def needs_correction(att, today=None):
    """True for a past day with a punch-in but no real punch-out (open or auto-closed)."""
    today = today or today_ist()
    if not att or att.date >= today or not att.check_in:
        return False
    return bool(att.auto_checkout) or not att.check_out


def is_period_locked(employee, day):
    """True if this month is locked for all locations or for one of the employee's."""
    locks = AttendanceLock.query.filter_by(month=day.month, year=day.year).all()
    school_ids = {s.id for s in employee.schools}
    return any(lk.school_id is None or lk.school_id in school_ids for lk in locks)


def payroll_status(employee, day):
    """Status of the employee's payroll row for that month, or None if none exists."""
    row = Payroll.query.filter_by(
        employee_id=employee.id, month=day.month, year=day.year).first()
    return row.status if row else None


def _month_request_count(employee, day):
    return AttendanceRegularization.query.filter(
        AttendanceRegularization.employee_id == employee.id,
        db.extract('month', AttendanceRegularization.date) == day.month,
        db.extract('year', AttendanceRegularization.date) == day.year,
    ).count()


def check_can_request(employee, att, today=None):
    """Return (ok, plain-language message) for a new correction request."""
    today = today or today_ist()
    if not att or att.employee_id != employee.id:
        return False, 'Attendance record not found.'
    if not needs_correction(att, today):
        return False, 'This day does not need a correction.'
    age = (today - att.date).days
    if age > window_days():
        return False, (f'Corrections can only be requested within {window_days()} days. '
                       'Please contact your admin.')
    if is_period_locked(employee, att.date):
        return False, 'Attendance for this month is locked. Please contact your admin.'
    if payroll_status(employee, att.date) in ('finalized', 'paid'):
        return False, 'Salary for this month is already processed. Please contact your admin.'
    open_req = AttendanceRegularization.query.filter(
        AttendanceRegularization.attendance_id == att.id,
        AttendanceRegularization.status.in_(['pending', 'approved'])).first()
    if open_req:
        return False, 'A correction request already exists for this day.'
    if _month_request_count(employee, att.date) >= max_per_month():
        return False, (f'You have used all {max_per_month()} correction requests '
                       'for that month.')
    return True, ''


def submit_request(employee, att, requested_time, reason, today=None):
    """Create a pending request. Returns (ok, message)."""
    ok, msg = check_can_request(employee, att, today)
    if not ok:
        return False, msg
    reason = (reason or '').strip()
    if not reason:
        return False, 'Please write a short reason.'
    out_mins = _time_to_minutes(requested_time)
    in_mins = _time_to_minutes(att.check_in)
    if out_mins is None:
        return False, 'Please enter the time you left, like 17:30.'
    if in_mins is not None and out_mins <= in_mins:
        return False, 'Leaving time must be after your punch-in time.'
    db.session.add(AttendanceRegularization(
        employee_id=employee.id, attendance_id=att.id, date=att.date,
        requested_check_out=f'{out_mins // 60:02d}:{out_mins % 60:02d}',
        reason=reason[:300],
    ))
    db.session.commit()
    return True, 'Correction request sent. Your admin will review it.'


def snapshot(att):
    """The attendance fields we track in the audit log."""
    return {'status': att.status, 'check_in': att.check_in,
            'check_out': att.check_out, 'overtime': att.overtime_hours or 0.0}


def log_attendance_change(att, old, new, username, action='attendance_edit'):
    """Add one audit row listing only the fields that really changed.

    Returns True if something changed (and a row was added), else False.
    """
    changes = [f'{k}: {old.get(k) or "-"} -> {new.get(k) or "-"}'
               for k in new if old.get(k) != new.get(k)]
    if not changes:
        return False
    db.session.add(AuditLog(
        action=action, user=username, affected_entity=f'Attendance:{att.id}',
        details=(f'{att.date} | ' + '; '.join(changes))[:500]))
    return True


def approve(reg, admin_username, note=''):
    """Approve a request. Returns (ok, message, warning)."""
    if reg.status != 'pending':
        return False, 'This request was already decided.', ''
    att = reg.attendance
    emp = reg.employee
    if is_period_locked(emp, att.date):
        return False, 'Attendance for this month is locked.', ''
    pay_status = payroll_status(emp, att.date)
    if pay_status in ('finalized', 'paid'):
        return False, 'Salary for this month is already finalized or paid.', ''

    old = snapshot(att)
    att.check_out = reg.requested_check_out
    att.status = 'present'
    att.auto_checkout = 0
    att.admin_override = True
    _start, shift_end, hours = get_employee_effective_shift(emp)
    att.overtime_hours = _compute_overtime_hours(
        att.check_out, _compute_expected_end_time(att.check_in, shift_end, hours))
    update_attendance_timing_flags(att, employee=emp)
    stamp = f'Regularized by {admin_username}'
    att.notes = ((att.notes[:150] + ' | ') if att.notes else '') + stamp

    reg.status = 'approved'
    reg.decided_by = admin_username
    reg.decided_on = datetime.now(timezone.utc)
    reg.admin_note = (note or '').strip()[:300] or None
    log_attendance_change(att, old, snapshot(att), admin_username, 'regularize_approve')
    db.session.commit()

    warning = ''
    if pay_status == 'draft':
        warning = ('Payroll for this month is already generated as a draft. '
                   'Regenerate it so the corrected day is counted.')
    return True, 'Approved. The day now counts as a full day.', warning


def reject(reg, admin_username, note):
    """Reject a request; a note is required. Returns (ok, message)."""
    if reg.status != 'pending':
        return False, 'This request was already decided.'
    note = (note or '').strip()
    if not note:
        return False, 'Please write a reason for rejecting.'
    reg.status = 'rejected'
    reg.decided_by = admin_username
    reg.decided_on = datetime.now(timezone.utc)
    reg.admin_note = note[:300]
    db.session.add(AuditLog(
        action='regularize_reject', user=admin_username,
        affected_entity=f'Attendance:{reg.attendance_id}',
        details=f'{reg.date} | rejected request for {reg.requested_check_out}: {note}'[:500]))
    db.session.commit()
    return True, 'Request rejected.'
