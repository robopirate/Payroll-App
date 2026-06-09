"""Attendance and geolocation utilities."""
from datetime import date, timedelta
import calendar
import math

from models import db, Holiday


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
