"""API endpoints for mobile app and third-party integrations."""
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from datetime import date, datetime, timezone, timedelta
from sqlalchemy import extract

from extensions import db, limiter, csrf
from services.attendance_service import haversine_distance
from models import Employee, Attendance, Leave, LeaveBalance, Payroll, Holiday

bp = Blueprint('api', __name__)


# ─── Helper: get current employee from JWT ──────────────────────────────────

def get_current_employee():
    """Return the Employee object for the currently authenticated JWT user."""
    try:
        claims = get_jwt()
        if not claims:
            return None
        employee_id = claims.get('employee_id')
        if not employee_id:
            return None
        return Employee.query.get(int(employee_id))
    except Exception:
        return None


def require_employee():
    """Return (employee, error_response) tuple."""
    emp = get_current_employee()
    if not emp:
        return None, (jsonify({'success': False, 'message': 'Employee not found or not authorized.'}), 403)
    return emp, None


# ─── JWT Auth Endpoints (also available at /api/v1/auth via jwt_auth blueprint) ─

# ─── GPS Punch ───────────────────────────────────────────────────────────────

@bp.route('/api/punch', methods=['POST'])
@csrf.exempt
@jwt_required(optional=True)
def api_punch():
    """
    Mobile GPS punch-in/punch-out.
    
    Supports BOTH session-based auth (existing web portal) AND JWT auth.
    For JWT: Header: Authorization: Bearer <token>
    """
    from flask_login import current_user
    
    emp = None
    
    # Try JWT first
    jwt_claims = get_jwt()
    if jwt_claims:
        emp = get_current_employee()
    
    # Fall back to session-based auth (for existing web portal users)
    if not emp and current_user.is_authenticated and not current_user.is_admin:
        emp = Employee.query.get(current_user.employee_id)
    
    if not emp:
        return jsonify({'success': False, 'message': 'Unauthorized. Please login.'}), 401

    data = request.get_json(silent=True) or {}
    lat = data.get('lat')
    lng = data.get('lng')
    action = data.get('action', 'in')

    if lat is None or lng is None:
        return jsonify({'success': False, 'message': 'GPS coordinates not received.'})

    # Geofence check — determine if school or field punch
    assigned_schools = [s for s in emp.schools if s.latitude and s.longitude]
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
        db.session.commit()
        msg = f'Punched IN at {now_time} ✓'
        if location_type == 'field':
            msg += ' (Field)'
        return jsonify({'success': True, 'message': msg, 'location_type': location_type})
    else:
        if not att or not att.check_in:
            return jsonify({'success': False, 'message': 'No punch-in record found for today.'})
        if att.check_out:
            return jsonify({'success': False, 'message': f'Already punched OUT at {att.check_out}.'})
        att.check_out = now_time
        db.session.commit()
        msg = f'Punched OUT at {now_time} ✓'
        if att.location_type == 'field':
            msg += ' (Field)'
        return jsonify({'success': True, 'message': msg, 'location_type': att.location_type or 'school'})


# ─── Employee Profile ────────────────────────────────────────────────────────

@bp.route('/api/v1/employee/profile', methods=['GET'])
@jwt_required()
def api_employee_profile():
    """Get current employee's profile."""
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
    """Get today's attendance record for current employee."""
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
        'gps_verified': att.gps_verified,
        'location_type': att.location_type,
        'notes': att.notes,
    }), 200


@bp.route('/api/v1/attendance/monthly', methods=['GET'])
@jwt_required()
def api_attendance_monthly():
    """Get monthly attendance summary."""
    emp, error = require_employee()
    if error:
        return error

    month = int(request.args.get('month', date.today().month))
    year = int(request.args.get('year', date.today().year))

    atts = Attendance.query.filter_by(employee_id=emp.id).filter(
        extract('year', Attendance.date) == year,
        extract('month', Attendance.date) == month
    ).all()

    present = sum(1 for a in atts if a.status == 'present')
    half = sum(0.5 for a in atts if a.status == 'half_day')
    absent = sum(1 for a in atts if a.status == 'absent')
    ot = sum(a.overtime_hours or 0 for a in atts)

    return jsonify({
        'success': True,
        'month': month,
        'year': year,
        'summary': {
            'present': present + half,
            'absent': absent,
            'overtime_hours': ot,
            'total_days': len(atts),
        },
        'records': [
            {
                'date': a.date.isoformat(),
                'status': a.status,
                'check_in': a.check_in,
                'check_out': a.check_out,
                'overtime_hours': a.overtime_hours,
            }
            for a in atts
        ],
    }), 200


# ─── Leaves ──────────────────────────────────────────────────────────────────

@bp.route('/api/v1/leaves', methods=['GET'])
@jwt_required()
def api_leaves():
    """Get current employee's leave history and balances."""
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
    """Apply for leave via API."""
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
    """Get current employee's payroll history."""
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
    """Get upcoming holidays."""
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
