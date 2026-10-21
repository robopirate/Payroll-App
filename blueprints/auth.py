from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_user, logout_user, login_required, current_user
from datetime import datetime, timezone, timedelta
import secrets

from extensions import db, limiter
from models import User, Employee, AuditLog, PasswordReset
from sms_service import send_sms
from flask_limiter.util import get_remote_address
from services.login_protection import is_allowed

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
@limiter.limit("10 per minute")
def login():
    if current_user.is_authenticated:
        return redirect(url_for('.index'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username, is_admin=True).first()
        if user and user.check_password(password):
            login_user(user, remember=request.form.get('remember'))
            # Force password change on first login or when admin requests it
            if user.must_change_password:
                flash('You must change your password before continuing.', 'warning')
                return redirect(url_for('admin.settings'))
            return redirect(request.args.get('next') or url_for('admin.dashboard'))

        # Record failed attempt and enforce brute-force protection
        client_ip = get_remote_address()
        if not is_allowed(client_ip, limit=5, window=60):
            flash('Too many login attempts. Please try again in a minute.', 'danger')
        else:
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
@limiter.limit("5 per hour")
def forgot_password():
    """Request password reset via phone number.

    The reset link is ONLY ever sent by SMS to the employee's own phone. It is
    never shown on screen or put in the redirect URL, otherwise anyone who
    knows a phone number could take over that account. The reply is the same
    whether or not the number is registered, so it can't be used to find out
    who works here.
    """
    if request.method == 'POST':
        phone = request.form.get('phone', '').strip()
        emp = Employee.query.filter_by(phone=phone).first()
        # Portal (employee) accounts only; never reset an admin account this way.
        user = (User.query.filter_by(employee_id=emp.id, is_admin=False).first()
                if emp else None)

        if user:
            # Invalidate any previous unused tokens for this user
            PasswordReset.query.filter_by(user_id=user.id, is_used=False).update(
                {'is_used': True}, synchronize_session=False
            )

            token = secrets.token_urlsafe(32)
            link = url_for('.reset_password', token=token, _external=True)
            message = f"Password reset link (valid 1 hour, do not share): {link}"
            sms_success, sms_message = send_sms(emp.phone, message)

            if sms_success:
                db.session.add(PasswordReset(
                    user_id=user.id,
                    token=token,
                    expires_at=datetime.now(timezone.utc) + timedelta(hours=1)
                ))
                db.session.add(AuditLog(
                    action='password_reset_request',
                    user=emp.name,
                    affected_entity=f'User:{user.id}',
                    details='Password reset requested via phone'
                ))
                db.session.commit()
            else:
                db.session.rollback()
                current_app.logger.warning('Password reset SMS failed: %s', sms_message)

        flash('If that number is registered, a reset link has been sent by SMS. '
              'Please check your phone.', 'info')
        return redirect(url_for('.forgot_password'))

    return render_template('forgot_password.html')


@bp.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    """Reset password using token sent via SMS."""
    if request.method == 'POST':
        token = request.form.get('token', '').strip()
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')

        reset = PasswordReset.query.filter_by(token=token, is_used=False).first()
        # The database hands back times without a time zone; treat them as UTC.
        expires_at = reset.expires_at if reset else None
        if expires_at is not None and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if not reset or expires_at < datetime.now(timezone.utc):
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

    token = request.args.get('token', '')
    return render_template('reset_password.html', token=token)


