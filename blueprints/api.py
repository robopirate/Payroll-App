"""API endpoints for mobile app and third-party integrations."""
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from datetime import date, datetime, timezone, timedelta
from sqlalchemy import extract

from extensions import db, limiter, csrf
from services.attendance_service import (
    haversine_distance, update_attendance_timing_flags, calculate_paid_days,
    get_employee_active_school, get_employee_effective_shift,
    _compute_expected_end_time, _compute_overtime_hours
)
from models import Employee, Attendance, Leave, LeaveBalance, Payroll, Holiday

bp = Blueprint('api', __name__)


# ─── Helper: get current employee from JWT ──────────────────────────────────

def get_current_employee():
    """Return the Employee object for the currently authenticated JWT user.

    Only returns active and approved employees.
    """
    try:
        claims = get_jwt()
        if not claims:
            return None
        employee_id = claims.get('employee_id')
        if not employee_id:
            return None
        emp = db.session.get(Employee, int(employee_id))
        if not emp or not emp.is_active or not emp.is_approved:
            return None
        return emp
    except Exception:
        return None


def require_employee():
    """Return (employee, error_response) tuple."""
    emp = get_current_employee()
    if not emp:
        return None, (jsonify({'success': False, 'message': 'Employee not found or not authorized.'}), 403)
    return emp, None


# ─── GPS Punch ───────────────────────────────────────────────────────────────

@bp.route('/api/punch', methods=['POST'])
@csrf.exempt
@jwt_required(optional=True)
def api_punch():
    """
    Mobile GPS punch-in/punch-out.
    ---
    tags:
      - Attendance
    summary: GPS Punch In/Out
    description: |
      Record attendance via GPS punch. Supports BOTH session-based auth (web portal)
      AND JWT auth (mobile app). For JWT, include `Authorization: Bearer <token>` header.
      Geofence validation checks if the punch is within the assigned school's radius.
    consumes:
      - application/json
    produces:
      - application/json
    security:
      - Bearer: []
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          properties:
            lat:
              type: number
              description: GPS latitude
              example: 18.5
            lng:
              type: number
              description: GPS longitude
              example: 73.8
            action:
              type: string
              enum: [in, out]
              default: in
              description: Punch action - 'in' or 'out'
              example: in
          required:
            - lat
            - lng
    responses:
      200:
        description: Punch recorded successfully
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: true
            message:
              type: string
              example: Punched IN at 09:30
            location_type:
              type: string
              enum: [school, field]
              example: school
      400:
        description: Missing GPS coordinates or already punched
      401:
        description: Unauthorized - no valid session or JWT
    """
    from flask_login import current_user
    
    emp = None
    
    # Try JWT first
    jwt_claims = get_jwt()
    if jwt_claims:
        emp = get_current_employee()
    
    # Fall back to session-based auth (for existing web portal users)
    if not emp and current_user.is_authenticated and not current_user.is_admin:
        emp = db.session.get(Employee, current_user.employee_id)
        if emp and (not emp.is_active or not emp.is_approved):
            emp = None

    if not emp:
        return jsonify({'success': False, 'message': 'Unauthorized. Please login.'}), 401

    data = request.get_json(silent=True) or {}
    lat = data.get('lat')
    lng = data.get('lng')
    action = data.get('action', 'in')

    if lat is None or lng is None:
        return jsonify({'success': False, 'message': 'GPS coordinates not received.'})

    # Geofence check — determine if school or field punch (active schools only)
    assigned_schools = [s for s in emp.schools if s.is_active and s.latitude and s.longitude]
    location_type = 'field'
    closest_school = None
    min_distance = float('inf')

    if assigned_schools:
        for school in assigned_schools:
            dist = haversine_distance(lat, lng, school.latitude, school.longitude)
            if dist < min_distance:
                min_distance = dist
                closest_school = school

        if closest_school and min_distance <= closest_school.geofence_radius:
            location_type = 'school'

    ist = timezone(timedelta(hours=5, minutes=30))
    today = datetime.now(ist).date()
    now_time = datetime.now(ist).strftime('%H:%M')
    att = Attendance.query.filter_by(employee_id=emp.id, date=today).first()

    if action == 'in':
        if att and att.check_in:
            return jsonify({'success': False, 'message': f'Already punched IN at {att.check_in}.'})
        field_note = ''
        if location_type == 'field' and closest_school:
            field_note = f'Field punch — {int(min_distance)}m from {closest_school.name}'
        if att:
            att.check_in = now_time
            att.status = 'present'
            att.gps_lat = lat
            att.gps_lng = lng
            att.gps_verified = True
            att.location_type = location_type
            if field_note:
                att.notes = field_note
        else:
            att = Attendance(
                employee_id=emp.id, date=today, status='present',
                check_in=now_time, gps_lat=lat, gps_lng=lng,
                gps_verified=True, location_type=location_type,
                notes=field_note or None
            )
            db.session.add(att)
        update_attendance_timing_flags(att, employee=emp)
        db.session.commit()
        msg = f'Punched IN at {now_time}'
        if location_type == 'field':
            msg += ' (Field)'
        return jsonify({'success': True, 'message': msg, 'location_type': location_type})
    else:
        if not att or not att.check_in:
            return jsonify({'success': False, 'message': 'No punch-in record found for today.'})
        if att.check_out:
            return jsonify({'success': False, 'message': f'Already punched OUT at {att.check_out}.'})
        att.check_out = now_time
        att.auto_checkout = False
        shift_start, shift_end, working_hours = get_employee_effective_shift(emp)
        expected_end = _compute_expected_end_time(att.check_in, shift_end, working_hours)
        att.overtime_hours = _compute_overtime_hours(now_time, expected_end)
        update_attendance_timing_flags(att, employee=emp)
        db.session.commit()
        msg = f'Punched OUT at {now_time}'
        if att.location_type == 'field':
            msg += ' (Field)'
        return jsonify({'success': True, 'message': msg, 'location_type': att.location_type or 'school'})


# ─── Employee Profile ────────────────────────────────────────────────────────

@bp.route('/api/v1/employee/profile', methods=['GET'])
@jwt_required()
def api_employee_profile():
    """
    Get current employee's profile.
    ---
    tags:
      - Employee
    summary: Employee Profile
    description: Returns detailed profile information for the authenticated employee.
    security:
      - Bearer: []
    produces:
      - application/json
    responses:
      200:
        description: Profile retrieved successfully
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: true
            employee:
              type: object
              properties:
                id:
                  type: integer
                emp_id:
                  type: string
                name:
                  type: string
                phone:
                  type: string
                email:
                  type: string
                designation:
                  type: string
                department:
                  type: string
                basic_salary:
                  type: number
                joining_date:
                  type: string
                  format: date
                bank_name:
                  type: string
                account_number:
                  type: string
                ifsc_code:
                  type: string
                pan_number:
                  type: string
                aadhar_number:
                  type: string
                schools:
                  type: array
                  items:
                    type: object
                    properties:
                      id:
                        type: integer
                      name:
                        type: string
      401:
        description: Missing or invalid JWT token
      403:
        description: Employee not found or not authorized
    """
    emp, error = require_employee()
    if error:
        return error

    return jsonify({
        'success': True,
        'employee': {
            'id': emp.id,
            'emp_id': emp.emp_id,
            'name': emp.name,
            'phone': emp.phone,
            'email': emp.email,
            'designation': emp.designation,
            'department': emp.dept.name if emp.dept else None,
            'basic_salary': emp.basic_salary,
            'joining_date': emp.joining_date.isoformat() if emp.joining_date else None,
            'bank_name': emp.bank_name,
            'account_number': emp.account_number,
            'ifsc_code': emp.ifsc_code,
            'pan_number': emp.pan_number,
            'aadhar_number': emp.aadhar_number,
            'schools': [{'id': s.id, 'name': s.name} for s in emp.schools if s.is_active],
        }
    }), 200


# ─── Attendance ──────────────────────────────────────────────────────────────

@bp.route('/api/v1/attendance/today', methods=['GET'])
@jwt_required()
def api_attendance_today():
    """
    Get today's attendance record for current employee.
    ---
    tags:
      - Attendance
    summary: Today's Attendance
    description: Returns the attendance record for the current day.
    security:
      - Bearer: []
    produces:
      - application/json
    responses:
      200:
        description: Attendance record retrieved
        schema:
          type: object
          properties:
            success:
              type: boolean
            date:
              type: string
              format: date
            status:
              type: string
              enum: [present, absent, half_day, holiday, leave, not_marked]
            check_in:
              type: string
              example: "09:30"
            check_out:
              type: string
              example: "18:00"
            overtime_hours:
              type: number
            gps_verified:
              type: boolean
            location_type:
              type: string
              enum: [school, field]
            notes:
              type: string
      401:
        description: Unauthorized
      403:
        description: Employee not found
    """
    emp, error = require_employee()
    if error:
        return error

    today = date.today()
    att = Attendance.query.filter_by(employee_id=emp.id, date=today).first()

    if not att:
        return jsonify({
            'success': True,
            'date': today.isoformat(),
            'status': 'not_marked',
            'check_in': None,
            'check_out': None,
        }), 200

    return jsonify({
        'success': True,
        'date': att.date.isoformat(),
        'status': att.status,
        'check_in': att.check_in,
        'check_out': att.check_out,
        'overtime_hours': att.overtime_hours,
        'late_minutes': att.late_minutes,
        'early_minutes': att.early_minutes,
        'gps_verified': att.gps_verified,
        'location_type': att.location_type,
        'notes': att.notes,
    }), 200


@bp.route('/api/v1/attendance/monthly', methods=['GET'])
@jwt_required()
def api_attendance_monthly():
    """
    Get monthly attendance summary.
    ---
    tags:
      - Attendance
    summary: Monthly Attendance
    description: Returns attendance records and summary for a given month/year.
    security:
      - Bearer: []
    produces:
      - application/json
    parameters:
      - in: query
        name: month
        type: integer
        default: 6
        description: Month (1-12)
      - in: query
        name: year
        type: integer
        default: 2026
        description: Year
    responses:
      200:
        description: Monthly attendance data
        schema:
          type: object
          properties:
            success:
              type: boolean
            month:
              type: integer
            year:
              type: integer
            summary:
              type: object
              properties:
                present:
                  type: number
                absent:
                  type: integer
                overtime_hours:
                  type: number
                total_days:
                  type: integer
            records:
              type: array
              items:
                type: object
                properties:
                  date:
                    type: string
                    format: date
                  status:
                    type: string
                  check_in:
                    type: string
                  check_out:
                    type: string
                  overtime_hours:
                    type: number
      401:
        description: Unauthorized
      403:
        description: Employee not found
    """
    emp, error = require_employee()
    if error:
        return error

    month = int(request.args.get('month', date.today().month))
    year = int(request.args.get('year', date.today().year))

    import calendar
    _, days_in_month = calendar.monthrange(year, month)

    atts = Attendance.query.filter_by(employee_id=emp.id).filter(
        extract('year', Attendance.date) == year,
        extract('month', Attendance.date) == month
    ).all()

    paid_days = calculate_paid_days(emp, year, month)
    absent = sum(1 for a in atts if a.status == 'absent')
    ot = sum(a.overtime_hours or 0 for a in atts)

    return jsonify({
        'success': True,
        'month': month,
        'year': year,
        'summary': {
            'present': paid_days,
            'absent': absent,
            'overtime_hours': ot,
            'total_days': days_in_month,
        },
        'records': [
            {
                'date': a.date.isoformat(),
                'status': a.status,
                'check_in': a.check_in,
                'check_out': a.check_out,
                'overtime_hours': a.overtime_hours,
                'late_minutes': a.late_minutes,
                'early_minutes': a.early_minutes,
            }
            for a in atts
        ],
    }), 200


# ─── Leaves ──────────────────────────────────────────────────────────────────

@bp.route('/api/v1/leaves', methods=['GET'])
@jwt_required()
def api_leaves():
    """
    Get current employee's leave history and balances.
    ---
    tags:
      - Leaves
    summary: Leave History & Balances
    description: Returns all leave applications and current year leave balances.
    security:
      - Bearer: []
    produces:
      - application/json
    responses:
      200:
        description: Leave data retrieved
        schema:
          type: object
          properties:
            success:
              type: boolean
            balances:
              type: array
              items:
                type: object
                properties:
                  leave_type:
                    type: string
                  total_days:
                    type: number
                  used_days:
                    type: number
                  remaining_days:
                    type: number
            leaves:
              type: array
              items:
                type: object
                properties:
                  id:
                    type: integer
                  leave_type:
                    type: string
                  start_date:
                    type: string
                    format: date
                  end_date:
                    type: string
                    format: date
                  days:
                    type: number
                  reason:
                    type: string
                  status:
                    type: string
                    enum: [pending, approved, rejected]
                  applied_on:
                    type: string
                    format: date-time
      401:
        description: Unauthorized
      403:
        description: Employee not found
    """
    emp, error = require_employee()
    if error:
        return error

    year = date.today().year
    balances = LeaveBalance.query.filter_by(employee_id=emp.id, year=year).all()
    leaves = Leave.query.filter_by(employee_id=emp.id).order_by(Leave.applied_on.desc()).all()

    return jsonify({
        'success': True,
        'balances': [
            {
                'leave_type': b.leave_type,
                'total_days': b.total_days,
                'used_days': b.used_days,
                'remaining_days': b.remaining_days,
            }
            for b in balances
        ],
        'leaves': [
            {
                'id': l.id,
                'leave_type': l.leave_type,
                'start_date': l.start_date.isoformat(),
                'end_date': l.end_date.isoformat(),
                'days': l.days,
                'reason': l.reason,
                'status': l.status,
                'applied_on': l.applied_on.isoformat() if l.applied_on else None,
            }
            for l in leaves
        ],
    }), 200


@bp.route('/api/v1/leaves/apply', methods=['POST'])
@jwt_required()
def api_apply_leave():
    """
    Apply for leave via API.
    ---
    tags:
      - Leaves
    summary: Apply for Leave
    description: |
      Submit a leave application. Requires sufficient leave balance.
      Admin approval is required before the leave is finalized.
    consumes:
      - application/json
    produces:
      - application/json
    security:
      - Bearer: []
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          properties:
            leave_type:
              type: string
              enum: [casual, sick, earned, unpaid]
              example: casual
            start_date:
              type: string
              format: date
              description: YYYY-MM-DD
              example: "2026-06-15"
            end_date:
              type: string
              format: date
              description: YYYY-MM-DD
              example: "2026-06-17"
            reason:
              type: string
              example: Family function
            half_day:
              type: boolean
              default: false
              description: If true, only 0.5 day is deducted
          required:
            - leave_type
            - start_date
            - end_date
    responses:
      201:
        description: Leave application submitted
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: true
            message:
              type: string
              example: Leave application submitted. Pending admin approval.
            leave_id:
              type: integer
              example: 5
      400:
        description: Invalid input or insufficient balance
      401:
        description: Unauthorized
      403:
        description: Employee not found
    """
    emp, error = require_employee()
    if error:
        return error

    data = request.get_json(silent=True) or {}
    leave_type = data.get('leave_type')
    start_date_str = data.get('start_date')
    end_date_str = data.get('end_date')
    reason = data.get('reason', '')
    is_half_day = data.get('half_day', False)

    if not all([leave_type, start_date_str, end_date_str]):
        return jsonify({'success': False, 'message': 'leave_type, start_date, and end_date are required.'}), 400

    try:
        from services.attendance_service import count_working_days_between
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'success': False, 'message': 'Invalid date format. Use YYYY-MM-DD.'}), 400

    if is_half_day:
        days = 0.5
    else:
        days = count_working_days_between(start_date, end_date)

    if days <= 0:
        return jsonify({'success': False, 'message': 'Leave range contains no working days.'}), 400

    year = date.today().year
    balance = LeaveBalance.query.filter_by(employee_id=emp.id, leave_type=leave_type, year=year).first()
    if balance and balance.remaining_days < days:
        return jsonify({
            'success': False,
            'message': f'Insufficient leave balance. Available: {balance.remaining_days} days.',
        }), 400

    leave = Leave(
        employee_id=emp.id,
        leave_type=leave_type,
        start_date=start_date,
        end_date=end_date,
        days=days,
        reason=reason,
    )
    db.session.add(leave)
    db.session.commit()

    return jsonify({
        'success': True,
        'message': 'Leave application submitted. Pending admin approval.',
        'leave_id': leave.id,
    }), 201


# ─── Payroll ─────────────────────────────────────────────────────────────────

@bp.route('/api/v1/payroll', methods=['GET'])
@jwt_required()
def api_payroll():
    """
    Get current employee's payroll history.
    ---
    tags:
      - Payroll
    summary: Payroll History
    description: Returns all payroll records for the authenticated employee.
    security:
      - Bearer: []
    produces:
      - application/json
    responses:
      200:
        description: Payroll records retrieved
        schema:
          type: object
          properties:
            success:
              type: boolean
            payrolls:
              type: array
              items:
                type: object
                properties:
                  id:
                    type: integer
                  month:
                    type: integer
                  year:
                    type: integer
                  working_days:
                    type: number
                  present_days:
                    type: number
                  basic_salary:
                    type: number
                  hra:
                    type: number
                  overtime_pay:
                    type: number
                  gross_salary:
                    type: number
                  pf_deduction:
                    type: number
                  esi_deduction:
                    type: number
                  advance_deduction:
                    type: number
                  total_deductions:
                    type: number
                  net_salary:
                    type: number
                  status:
                    type: string
                    enum: [draft, finalized, paid]
                  paid_on:
                    type: string
                    format: date
      401:
        description: Unauthorized
      403:
        description: Employee not found
    """
    emp, error = require_employee()
    if error:
        return error

    payrolls = Payroll.query.filter_by(employee_id=emp.id).order_by(
        Payroll.year.desc(), Payroll.month.desc()
    ).all()

    return jsonify({
        'success': True,
        'payrolls': [
            {
                'id': p.id,
                'month': p.month,
                'year': p.year,
                'working_days': p.working_days,
                'present_days': p.present_days,
                'basic_salary': p.basic_salary,
                'hra': p.hra,
                'overtime_pay': p.overtime_pay,
                'gross_salary': p.gross_salary,
                'pf_deduction': p.pf_deduction,
                'esi_deduction': p.esi_deduction,
                'advance_deduction': p.advance_deduction,
                'total_deductions': p.total_deductions,
                'net_salary': p.net_salary,
                'status': p.status,
                'paid_on': p.paid_on.isoformat() if p.paid_on else None,
            }
            for p in payrolls
        ],
    }), 200


# ─── Holidays ────────────────────────────────────────────────────────────────

@bp.route('/api/v1/holidays', methods=['GET'])
@jwt_required()
def api_holidays():
    """
    Get upcoming holidays.
    ---
    tags:
      - Holidays
    summary: Upcoming Holidays
    description: Returns all upcoming holidays from today onwards.
    security:
      - Bearer: []
    produces:
      - application/json
    responses:
      200:
        description: Holiday list retrieved
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: true
            holidays:
              type: array
              items:
                type: object
                properties:
                  id:
                    type: integer
                  date:
                    type: string
                    format: date
                  name:
                    type: string
                  description:
                    type: string
      401:
        description: Unauthorized
    """
    today = date.today()
    upcoming = Holiday.query.filter(
        Holiday.date >= today,
        Holiday.is_active == True
    ).order_by(Holiday.date).all()

    return jsonify({
        'success': True,
        'holidays': [
            {
                'id': h.id,
                'date': h.date.isoformat(),
                'name': h.name,
                'description': h.description,
            }
            for h in upcoming
        ],
    }), 200
