import hmac
from functools import wraps

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.http import JsonResponse
from django.shortcuts import render


def superuser_required(view_func):
    """Restrict a view to authenticated superusers.

    Anonymous users are sent to the login page (with ?next= back here);
    authenticated non-superusers get a 403 rather than a redirect loop.
    """

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not request.user.is_superuser:
            return render(request, "control_panel/403.html", status=403)
        return view_func(request, *args, **kwargs)

    return wrapper


def companion_key_required(view_func):
    """Restrict a view to requests carrying a valid X-DubeyAI-Key header.

    Used by the local companion script's polling/callback endpoints — these
    are machine-to-machine, not session-authenticated.
    """

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        expected = settings.COMPANION_API_KEY
        provided = request.headers.get("X-DubeyAI-Key", "")
        if not expected or not hmac.compare_digest(provided, expected):
            return JsonResponse({"success": False, "error": "Invalid or missing X-DubeyAI-Key."}, status=401)
        return view_func(request, *args, **kwargs)

    return wrapper
