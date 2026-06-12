"""Simple file-based brute-force protection for login endpoints.

Flask-Limiter's memory storage resets on worker restart. This helper persists
failed login attempts to a JSON file so brute-force protection survives reloads.
"""
import os
import time
import json
from pathlib import Path

# fcntl is Unix-only; PythonAnywhere uses Linux so it is available there.
# On Windows (local dev/tests) we skip file locking because this is low-contention.
try:
    import fcntl
    _HAS_FCNTL = True
except ImportError:
    fcntl = None
    _HAS_FCNTL = False

DEFAULT_FILE = os.path.join(os.path.expanduser('~'), 'login_attempts.json')


def _load_data(filepath):
    if not os.path.exists(filepath):
        return {}
    try:
        with open(filepath, 'r') as f:
            if _HAS_FCNTL:
                fcntl.flock(f, fcntl.LOCK_SH)
            data = json.load(f)
            if _HAS_FCNTL:
                fcntl.flock(f, fcntl.LOCK_UN)
            return data
    except Exception:
        return {}


def _save_data(filepath, data):
    Path(filepath).parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, 'w') as f:
        if _HAS_FCNTL:
            fcntl.flock(f, fcntl.LOCK_EX)
        json.dump(data, f)
        if _HAS_FCNTL:
            fcntl.flock(f, fcntl.LOCK_UN)


def is_allowed(key, limit=5, window=60, filepath=DEFAULT_FILE):
    """Return True if the key is allowed to attempt login.

    key: identifier, e.g. IP address or username
    limit: maximum attempts allowed within the window
    window: time window in seconds
    """
    now = time.time()
    data = _load_data(filepath)
    attempts = data.get(key, [])
    # Keep only attempts within the window
    attempts = [t for t in attempts if now - t < window]
    if len(attempts) >= limit:
        return False
    attempts.append(now)
    data[key] = attempts
    _save_data(filepath, data)
    return True
