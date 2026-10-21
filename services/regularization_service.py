"""Missed punch-out corrections ("regularization").

Rules (industry standard, as in Keka / greytHR / Zoho People):
  * An employee can ask for a correction only within a short window after the day.
  * Corrections per month are capped.
  * An admin approves or rejects; a rejection needs a note.
  * Every change is written to the audit log (who, what, old value, new value).
  * Nothing changes once the month is locked or that month's salary is finalized/paid.
"""
from datetime import datetime, timedelta, timezone

from models import (
    db, Attendance, AttendanceLock, AuditLog, AppConfig, Payroll,
    AttendanceRegularization, Employee, Holiday, Leave,
)
from services.attendance_service import (
    today_ist, now_ist, update_attendance_timing_flags, get_employee_effective_shift,
    _compute_expected_end_time, _compute_overtime_hours, _time_to_minutes,
)
from sms_service import send_sms

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
    return {'status': att.status or '', 'check_in': att.check_in or '',
            'check_out': att.check_out or '', 'overtime': att.overtime_hours or 0.0}


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


def correctable_days(employee, today=None):
    """Recent days this employee can still ask to correct (used for the portal banner)."""
    today = today or today_ist()
    atts = Attendance.query.filter(
        Attendance.employee_id == employee.id,
        Attendance.date >= today - timedelta(days=window_days()),
        Attendance.date < today,
    ).order_by(Attendance.date.desc()).all()
    return [a for a in atts if check_can_request(employee, a, today)[0]]


# ─── End-of-shift reminder ────────────────────────────────────────────────────

REMINDER_SETTING = 'missed_punch_reminder_enabled'
REMINDER_DELAY_MINUTES = 30      # after the expected end of the employee's day
REMINDER_LATEST_MINUTE = 23 * 60 + 30


def reminder_enabled():
    """Off unless an admin switches it on in Settings (SMS costs money)."""
    return (AppConfig.get(REMINDER_SETTING) or '0') == '1'


def send_missed_punch_reminders(now=None):
    """SMS employees who punched in today but have not punched out, once per day.

    Runs every few minutes from the scheduler. Skips Sundays, holidays and
    approved leave days. The "already reminded" marker is an AuditLog row that
    is saved BEFORE the SMS goes out, so a person is never texted twice a day.
    Returns the number of SMS sent.
    """
    if not reminder_enabled():
        return 0
    now = now or now_ist()
    today = now.date()
    if today.weekday() == 6 or Holiday.query.filter_by(date=today, is_active=True).first():
        return 0
    now_minutes = now.hour * 60 + now.minute
    if now_minutes > REMINDER_LATEST_MINUTE:
        return 0

    rows = (Attendance.query.join(Employee, Attendance.employee_id == Employee.id)
            .filter(Attendance.date == today, Attendance.check_in.isnot(None),
                    Attendance.check_in != '',
                    db.or_(Attendance.check_out.is_(None), Attendance.check_out == ''),
                    Employee.is_active == True, Employee.is_approved == True)  # noqa: E712
            .all())
    sent = 0
    for att in rows:
        emp = att.employee
        on_leave = Leave.query.filter(
            Leave.employee_id == emp.id, Leave.status == 'approved',
            Leave.start_date <= today, Leave.end_date >= today).first()
        if on_leave:
            continue
        _start, shift_end, hours = get_employee_effective_shift(emp)
        end_minutes = _time_to_minutes(_compute_expected_end_time(att.check_in, shift_end, hours))
        if end_minutes is None or now_minutes < end_minutes + REMINDER_DELAY_MINUTES:
            continue
        entity = f'Attendance:{att.id}'
        if AuditLog.query.filter_by(action='punch_reminder', affected_entity=entity).first():
            continue
        marker = AuditLog(action='punch_reminder', user='system', affected_entity=entity,
                          details=f'{today} reminder to {emp.name}')
        db.session.add(marker)
        db.session.commit()          # claim first, then send
        ok, info = send_sms(emp.phone, (
            f'Hi {emp.name}, you punched in at {att.check_in} but have not punched out. '
            'Please punch out in the portal. - HR Team'))
        if ok:
            sent += 1
        else:
            marker.details = (marker.details + f' (SMS failed: {info})')[:500]
            db.session.commit()
    return sent
