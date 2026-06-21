import datetime
import json
import logging
import os

from django.conf import settings
from django.contrib import auth, messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .forms import LoginForm, RegisterForm
from .models import Chat
from .services import AIServiceError, generate_reply


logger = logging.getLogger(__name__)

FALLBACK_MESSAGES = {
    "timeout": "The AI is taking longer than usual. Please try again in 30 seconds.",
    "connection": "Unable to reach AI service. Please check back shortly.",
    "http_error": "AI service returned an error. Please try again.",
    "api_key": "AI service configuration error. Admin has been notified.",
    "generic": "Something went wrong. Please try again.",
    "warmup": "Service is warming up after inactivity. Please retry in 30 seconds.",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def json_error(message, status=400):
    """Return a uniform JSON error response without leaking tracebacks."""
    return JsonResponse({"success": False, "error": message}, status=status)


def _safe_next(request):
    """Return the ?next= URL only when it is safe to redirect to it."""
    next_url = request.GET.get("next", "").strip()
    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return next_url
    return None


# ---------------------------------------------------------------------------
# Auth views
# ---------------------------------------------------------------------------

@require_http_methods(["GET", "POST"])
def login_view(request):
    if request.user.is_authenticated:
        return redirect("chatbot")

    # Pass request as keyword arg — AuthenticationForm requires it
    form = LoginForm(request=request, data=request.POST or None)

    if request.method == "POST" and form.is_valid():
        user = form.get_user()
        auth.login(request, user)
        next_url = _safe_next(request)
        return redirect(next_url or "chatbot")

    return render(request, "login.html", {"form": form})


@require_http_methods(["GET", "POST"])
def register_view(request):
    if request.user.is_authenticated:
        return redirect("chatbot")

    form = RegisterForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        user = form.save()
        # Explicitly specify the backend so login() never raises ValueError
        # when multiple authentication backends are installed.
        auth.login(
            request,
            user,
            backend="django.contrib.auth.backends.ModelBackend",
        )
        messages.success(request, "Your workspace is ready. Welcome!")
        return redirect("chatbot")

    return render(request, "register.html", {"form": form})


@login_required
@require_POST
def logout_view(request):
    auth.logout(request)
    return redirect("login")


# ---------------------------------------------------------------------------
# Chat views
# ---------------------------------------------------------------------------

@login_required
@require_GET
def chatbot(request):
    chats = Chat.objects.filter(user=request.user).order_by("created_at")
    return render(
        request,
        "chatbot.html",
        {
            "chats": chats,
            "total_chats": chats.count(),
            "chat_endpoint": "/chat/",
            "max_message_length": settings.CHAT_MAX_MESSAGE_LENGTH,
        },
    )


@login_required
@require_POST
def chat(request):
    # Enforce JSON content-type
    content_type = request.content_type or ""
    if not content_type.startswith("application/json"):
        return json_error("Content-Type must be application/json.", status=415)

    try:
        payload = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return json_error("Invalid JSON in request body.")

    message = payload.get("message", "")
    if not isinstance(message, str):
        return json_error("Message must be a text string.")

    message = message.strip()
    if not message:
        return json_error("Please enter a message before sending.")

    max_len = settings.CHAT_MAX_MESSAGE_LENGTH
    if len(message) > max_len:
        return json_error(
            f"Message must be {max_len:,} characters or fewer."
        )

    # Build conversation history (oldest → newest)
    history = list(
        Chat.objects.filter(user=request.user)
        .order_by("-created_at")[: settings.CHAT_HISTORY_LIMIT]
    )
    history.reverse()

    try:
        response_text = generate_reply(message, history)
        chat_record = Chat.objects.create(
            user=request.user,
            message=message,
            response=response_text,
        )
    except AIServiceError as exc:
        logger.warning("AI service error: %s", exc)
        return JsonResponse(
            {"error": False, "response": str(exc), "fallback": True},
            status=200,
        )
    except Exception:
        logger.exception("Unexpected failure in /chat/ endpoint")
        return JsonResponse(
            {"error": False, "response": FALLBACK_MESSAGES["generic"], "fallback": True},
            status=200,
        )

    return JsonResponse(
        {
            "success": True,
            "chat": {
                "id": chat_record.id,
                "message": chat_record.message,
                "response": chat_record.response,
                "created_at": chat_record.created_at.isoformat(),
            },
        }
    )


# ---------------------------------------------------------------------------
# History / utility API views
# ---------------------------------------------------------------------------

@login_required
@require_GET
def get_chat_history(request):
    chats = Chat.objects.filter(user=request.user).order_by("-created_at")[
        : settings.CHAT_HISTORY_LIMIT
    ]
    return JsonResponse(
        {
            "success": True,
            "chats": [
                {
                    "id": item.id,
                    "message": item.message,
                    "response": item.response,
                    "created_at": item.created_at.isoformat(),
                }
                for item in chats
            ],
        }
    )


@login_required
@require_POST
def clear_chat_history(request):
    deleted_count, _ = Chat.objects.filter(user=request.user).delete()
    return JsonResponse({"success": True, "deleted": deleted_count})


@login_required
@require_POST
def delete_chat(request, chat_id):
    chat_record = get_object_or_404(Chat, id=chat_id, user=request.user)
    chat_record.delete()
    return JsonResponse({"success": True})


@login_required
@require_GET
def search_chats(request):
    query = request.GET.get("q", "").strip()
    if not query:
        return JsonResponse({"success": True, "chats": []})
    if len(query) > 200:
        return json_error("Search query is too long.")

    chats = (
        Chat.objects.filter(user=request.user)
        .filter(Q(message__icontains=query) | Q(response__icontains=query))
        .order_by("-created_at")[:20]
    )
    return JsonResponse(
        {
            "success": True,
            "chats": [
                {
                    "id": item.id,
                    "message": item.message,
                    "created_at": item.created_at.isoformat(),
                }
                for item in chats
            ],
        }
    )


# ---------------------------------------------------------------------------
# Health check — no auth required (used by Render uptime monitors and UptimeRobot)
# ---------------------------------------------------------------------------

@require_GET
def ping(request):
    nvidia_key = os.environ.get("NVIDIA_API_KEY", "")
    secret_key = os.environ.get("SECRET_KEY", "")
    allowed_hosts = os.environ.get("ALLOWED_HOSTS", "NOT SET")

    return JsonResponse(
        {
            "status": "ok",
            "service": "DubeyAI",
            "timestamp": str(datetime.datetime.now()),
            "env_check": {
                "nvidia_key_loaded": bool(nvidia_key),
                "secret_key_loaded": bool(secret_key)
                and secret_key != "unsafe-dev-key-change-in-prod",
                "allowed_hosts": allowed_hosts,
                "debug_mode": os.environ.get("DEBUG", "False"),
                "database": "sqlite",
            },
        }
    )
