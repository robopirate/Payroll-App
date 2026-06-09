"""Notification service wrapper (SMS, future WhatsApp/Email)."""
from sms_service import send_salary_credited_sms, send_sms, get_month_name


def notify_salary_credited(employee, payroll):
    """Send salary credited SMS to an employee."""
    success, msg = send_salary_credited_sms(employee, payroll)
    return success, msg


def notify_leave_status(employee, leave, status):
    """Send leave approval/rejection SMS."""
    if status == 'approved':
        message = (
            f"Your {leave.leave_type} leave for {leave.start_date.strftime('%d %b')} - "
            f"{leave.end_date.strftime('%d %b')} has been APPROVED. Enjoy!"
        )
    else:
        message = (
            f"Your {leave.leave_type} leave for {leave.start_date.strftime('%d %b')} - "
            f"{leave.end_date.strftime('%d %b')} has been REJECTED. Please contact admin for details."
        )
    return send_sms(employee.phone, message)


def notify_custom(phones, message):
    """Send bulk or single custom SMS."""
    return send_sms(phones, message)
