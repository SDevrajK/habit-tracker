"""
Shared HTTP Basic Auth module for Flask blueprints.
"""
import base64

from flask import Response, request

from configs.config import Config


def require_dashboard_auth():
    """Check HTTP Basic Auth. Returns None if OK, or a 401 Response."""
    if not Config.DASHBOARD_USER or not Config.DASHBOARD_PASS:
        return None
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Basic "):
        return _challenge()
    try:
        user, _, pw = base64.b64decode(auth[6:]).decode().partition(":")
    except Exception:
        return _challenge()
    if user != Config.DASHBOARD_USER or pw != Config.DASHBOARD_PASS:
        return _challenge()
    return None


def _challenge():
    return Response(
        "Authentication required.",
        401,
        {"WWW-Authenticate": 'Basic realm="Habit Tracker"'},
    )
