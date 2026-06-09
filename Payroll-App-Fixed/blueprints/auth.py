from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from datetime import datetime, timedelta
import secrets

from extensions import db, limiter
from models import User, Employee, AuditLog, PasswordReset
from sms_service import send_sms

bp = Blueprint('auth', __name__)

# ─── Auth ────────────────────────────────────────────────────────────────────

@bp.route('/')
def index():
    if current_user.is_authenticated:
        if current_user.is_admin:
            return redirect(url_for('admin.dashboard'))
        return redirect(url_for('portal.portal_dashboard'))
    return redirect(url_for('.login'))


@bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('.index'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username, is_admin=True).first()
        if user and user.check_password(password):
            login_user(user, remember=request.form.get('remember'))
            return redirect(request.args.get('next') or url_for('admin.dashboard'))
        flash('Invalid username or password.', 'danger')
    return render_template('login.html')


@bp.route('/logout')
@login_required
def logout():
    was_employee = not current_user.is_admin
    logout_user()
    flash('You have been logged out.', 'info')
    if was_employee:
        return redirect(url_for('portal.portal_login'))
    return redirect(url_for('.login'))


@bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    """Request password reset via phone number."""
    if request.method == 'POST':
        phone = request.form.get('phone', '').strip()
        emp = Employee.query.filter_by(phone=phone).first()
        if not emp:
            flash('Phone number not found.', 'warning')
            return redirect(url_for('.forgot_password'))

        user = User.query.filter_by(employee_id=emp.id).first()
        if not user:
            flash('No login account found for this employee.', 'warning')
            return redirect(url_for('.forgot_password'))

        # Generate reset token
        token = secrets.token_urlsafe(32)
        reset = PasswordReset(
            user_id=user.id,
            token=token,
            expires_at=datetime.utcnow() + timedelta(hours=1)
        )
        db.session.add(reset)
        db.session.commit()

        # Send SMS with reset token
        message = f"Your password reset token: {token}. Valid for 1 hour. Do not share this token."
        send_sms(emp.phone, message)

        # Log audit trail
        audit = AuditLog(
            action='password_reset_request',
            user=emp.name,
            affected_entity=f'User:{user.id}',
            details=f'Password reset requested via phone'
        )
        db.session.add(audit)
        db.session.commit()

        flash('Reset token sent via SMS. Check your phone.', 'success')
        return redirect(url_for('.reset_password'))

    return render_template('forgot_password.html')


@bp.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    """Reset password using token sent via SMS."""
    if request.method == 'POST':
        token = request.form.get('token', '').strip()
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')

        reset = PasswordReset.query.filter_by(token=token, is_used=False).first()
        if not reset or reset.expires_at < datetime.utcnow():
            flash('Invalid or expired reset token.', 'danger')
            return redirect(url_for('.reset_password'))

        if len(new_password) < 6:
            flash('Password must be at least 6 characters.', 'danger')
            return redirect(url_for('.reset_password'))

        if new_password != confirm_password:
            flash('Passwords do not match.', 'danger')
            return redirect(url_for('.reset_password'))

        user = reset.user
        user.set_password(new_password)
        reset.is_used = True
        db.session.commit()

        # Log audit trail
        audit = AuditLog(
            action='password_reset_complete',
            user=user.username,
            affected_entity=f'User:{user.id}',
            details=f'Password reset completed'
        )
        db.session.add(audit)
        db.session.commit()

        flash('Password reset successfully. Please login with your new password.', 'success')
        return redirect(url_for('.login'))

    return render_template('reset_password.html')


