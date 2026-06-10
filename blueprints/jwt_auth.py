"""JWT Authentication API for mobile and third-party integrations."""
from flask import Blueprint, request, jsonify
from flask_jwt_extended import (
    create_access_token, create_refresh_token,
    jwt_required, get_jwt_identity, get_jwt
)
from datetime import datetime, timedelta

from extensions import db, jwt, csrf
from models import User, Employee

bp = Blueprint('jwt_auth', __name__, url_prefix='/api/v1/auth')

# Exempt all JWT auth routes from CSRF (they use Bearer tokens, not cookies)
csrf.exempt(bp)

# In-memory token blacklist (use Redis in production)
_token_blacklist = set()


@jwt.token_in_blocklist_loader
def check_if_token_revoked(jwt_header, jwt_payload):
    """Check if a JWT token has been revoked (logged out)."""
    jti = jwt_payload['jti']
    return jti in _token_blacklist


@bp.route('/login', methods=['POST'])
def api_login():
    """
    Authenticate and receive JWT access + refresh tokens.
    
    Body (JSON):
        - For admin: {"username": "admin", "password": "admin123"}
        - For employee: {"phone": "9876543210", "password": "password123"}
    
    Returns:
        {"access_token": "...", "refresh_token": "...", "user_type": "admin|employee"}
    """
    data = request.get_json(silent=True) or {}
    
    # Admin login via username
    username = data.get('username', '').strip()
    phone = data.get('phone', '').strip()
    password = data.get('password', '')
    
    if not password:
        return jsonify({'success': False, 'message': 'Password is required.'}), 400
    
    user = None
    user_type = None
    
    if username:
        user = User.query.filter_by(username=username, is_admin=True).first()
        if user and user.check_password(password):
            user_type = 'admin'
    
    if not user and phone:
        emp = Employee.query.filter_by(phone=phone, is_active=True, is_approved=True).first()
        if emp:
            user = User.query.filter_by(employee_id=emp.id, is_admin=False).first()
            if user and user.check_password(password):
                user_type = 'employee'
    
    if not user or not user_type:
        return jsonify({'success': False, 'message': 'Invalid credentials.'}), 401
    
    # Create tokens with user metadata in claims
    additional_claims = {
        'user_type': user_type,
        'is_admin': user.is_admin,
        'employee_id': user.employee_id,
    }
    
    access_token = create_access_token(
        identity=str(user.id),
        additional_claims=additional_claims
    )
    refresh_token = create_refresh_token(
        identity=str(user.id),
        additional_claims=additional_claims
    )
    
    return jsonify({
        'success': True,
        'access_token': access_token,
        'refresh_token': refresh_token,
        'token_type': 'Bearer',
        'expires_in': 900,  # 15 minutes
        'user_type': user_type,
        'user_id': user.id,
        'employee_id': user.employee_id,
    }), 200


@bp.route('/refresh', methods=['POST'])
@jwt_required(refresh=True)
def api_refresh():
    """
    Refresh an expired access token using a refresh token.
    
    Header: Authorization: Bearer <refresh_token>
    
    Returns:
        {"access_token": "...", "expires_in": 900}
    """
    user_id = get_jwt_identity()
    user = User.query.get(int(user_id))
    
    if not user:
        return jsonify({'success': False, 'message': 'User not found.'}), 404
    
    additional_claims = {
        'user_type': 'admin' if user.is_admin else 'employee',
        'is_admin': user.is_admin,
        'employee_id': user.employee_id,
    }
    
    new_access_token = create_access_token(
        identity=user_id,
        additional_claims=additional_claims
    )
    
    return jsonify({
        'success': True,
        'access_token': new_access_token,
        'token_type': 'Bearer',
        'expires_in': 900,
    }), 200


@bp.route('/logout', methods=['POST'])
@jwt_required()
def api_logout():
    """
    Revoke the current access token (logout).
    
    Header: Authorization: Bearer <access_token>
    
    Returns:
        {"success": True, "message": "Successfully logged out."}
    """
    jti = get_jwt()['jti']
    _token_blacklist.add(jti)
    return jsonify({'success': True, 'message': 'Successfully logged out.'}), 200


@bp.route('/me', methods=['GET'])
@jwt_required()
def api_me():
    """
    Get current authenticated user info.
    
    Header: Authorization: Bearer <access_token>
    
    Returns:
        {"user_id": 1, "user_type": "admin", "employee_id": null, ...}
    """
    user_id = int(get_jwt_identity())
    claims = get_jwt()
    user = User.query.get(user_id)
    
    if not user:
        return jsonify({'success': False, 'message': 'User not found.'}), 404
    
    result = {
        'success': True,
        'user_id': user.id,
        'username': user.username,
        'is_admin': user.is_admin,
        'user_type': claims.get('user_type'),
        'employee_id': user.employee_id,
    }
    
    if user.employee_id:
        emp = Employee.query.get(user.employee_id)
        if emp:
            result['employee'] = {
                'id': emp.id,
                'emp_id': emp.emp_id,
                'name': emp.name,
                'phone': emp.phone,
                'designation': emp.designation,
                'department': emp.dept.name if emp.dept else None,
            }
    
    return jsonify(result), 200
