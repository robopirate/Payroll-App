from flask import Blueprint, request, jsonify
from flask_login import current_user
from datetime import date, datetime

from extensions import db, limiter
from services.attendance_service import haversine_distance
from models import Employee, Attendance

bp = Blueprint('api', __name__)

@bp.route('/api/punch', methods=['POST'])
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

    # Geofence check
    assigned_schools = [s for s in emp.schools if s.latitude and s.longitude]
    if assigned_schools:
        closest_school = None
        min_distance = float('inf')
        for school in assigned_schools:
            dist = haversine_distance(lat, lng, school.latitude, school.longitude)
            if dist < min_distance:
                min_distance = dist
                closest_school = school

        if closest_school and min_distance > closest_school.geofence_radius:
            return jsonify({
                'success': False,
                'message': (f'You are not at your assigned location. '
                            f'You are {int(min_distance)}m away from {closest_school.name} '
                            f'(allowed radius: {int(closest_school.geofence_radius)}m).')
            })

    today = date.today()
    now_time = datetime.now().strftime('%H:%M')
    att = Attendance.query.filter_by(employee_id=emp.id, date=today).first()

    if action == 'in':
        if att and att.check_in:
            return jsonify({'success': False, 'message': f'Already punched IN at {att.check_in}.'})
        if att:
            att.check_in = now_time
            att.status = 'present'
            att.gps_lat = lat
            att.gps_lng = lng
            att.gps_verified = True
        else:
            att = Attendance(employee_id=emp.id, date=today, status='present',
                             check_in=now_time, gps_lat=lat, gps_lng=lng, gps_verified=True)
            db.session.add(att)
        db.session.commit()
        return jsonify({'success': True, 'message': f'Punched IN at {now_time} ✓'})
    else:
        if not att or not att.check_in:
            return jsonify({'success': False, 'message': 'No punch-in record found for today.'})
        if att.check_out:
            return jsonify({'success': False, 'message': f'Already punched OUT at {att.check_out}.'})
        att.check_out = now_time
        db.session.commit()
        return jsonify({'success': True, 'message': f'Punched OUT at {now_time} ✓'})


