from flask import Blueprint, request, jsonify
from flask_login import current_user
from datetime import date, datetime, timezone, timedelta

from extensions import db, limiter, csrf
from services.attendance_service import haversine_distance
from models import Employee, Attendance

bp = Blueprint('api', __name__)

@bp.route('/api/punch', methods=['POST'])
@csrf.exempt
def api_punch():
    if not current_user.is_authenticated or current_user.is_admin:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401

    data = request.get_json(silent=True) or {}
    lat = data.get('lat')
    lng = data.get('lng')
    action = data.get('action', 'in')

    if lat is None or lng is None:
        return jsonify({'success': False, 'message': 'GPS coordinates not received.'})

    emp = Employee.query.get(current_user.employee_id)
    if not emp:
        return jsonify({'success': False, 'message': 'Employee not found.'})

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


