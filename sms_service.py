import requests
from flask import current_app


def send_sms(phone_numbers, message):
    """
    Send SMS via Fast2SMS API.
    phone_numbers: list of phone numbers or a single number string
    message: SMS text
    Returns: (success: bool, response_message: str)
    """
    api_key = current_app.config.get('FAST2SMS_API_KEY', '')
    if not api_key:
        return False, "Fast2SMS API key not configured"

    if isinstance(phone_numbers, list):
        numbers = ','.join(str(n) for n in phone_numbers)
    else:
        numbers = str(phone_numbers)

    url = "https://www.fast2sms.com/dev/bulkV2"
    payload = {
        "route": "q",
        "message": message,
        "language": "english",
        "flash": 0,
        "numbers": numbers,
    }
    headers = {
        "authorization": api_key,
        "Content-Type": "application/json"
    }

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        data = response.json()
        if data.get('return') is True:
            return True, "SMS sent successfully"
        else:
            return False, data.get('message', 'SMS sending failed')
    except requests.exceptions.RequestException as e:
        return False, f"Network error: {str(e)}"
    except Exception as e:
        return False, f"Error: {str(e)}"


def send_salary_credited_sms(employee, payroll):
    message = (
        f"Dear {employee.name}, your salary of Rs.{payroll.net_salary:.2f} "
        f"for {get_month_name(payroll.month)} {payroll.year} has been credited "
        f"to your bank account. - HR Team"
    )
    return send_sms(employee.phone, message)


def send_attendance_summary_sms(employee, month, year, present_days, total_days):
    message = (
        f"Dear {employee.name}, your attendance for {get_month_name(month)} {year}: "
        f"Present: {present_days}/{total_days} days. - HR Team"
    )
    return send_sms(employee.phone, message)


def get_month_name(month_num):
    months = [
        '', 'January', 'February', 'March', 'April', 'May', 'June',
        'July', 'August', 'September', 'October', 'November', 'December'
    ]
    return months[month_num] if 1 <= month_num <= 12 else str(month_num)
