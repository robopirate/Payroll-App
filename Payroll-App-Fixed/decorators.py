"""Shared decorators to avoid circular imports."""
from functools import wraps
from flask import redirect, url_for, request
from flask_login import current_user, logout_user


def portal_required(f):
    """Restrict route to authenticated employee (non-admin) users."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('portal.portal_login'))
        if current_user.is_admin:
            return redirect(url_for('admin.dashboard'))
        if not current_user.employee_id:
            logout_user()
            return redirect(url_for('portal.portal_login'))
        return f(*args, **kwargs)
    return decorated
