import datetime
import io
import json
import logging
import os

from django.conf import settings
from django.core.files.base import ContentFile
from django.contrib import auth, messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from core import storage as cloudinary_storage
from core.models import Command, Reminder, VoiceCommand
from core.services import classify_intent

from .documents import (
    ALLOWED_EXTENSIONS,
    MAX_UPLOAD_BYTES,
    DocumentExtractionError,
    extract_text,
    validate_upload,
)
from .forms import LoginForm, RegisterForm
from .models import Chat, UploadedDocument
from .services import AIServiceError, generate_reply

# How many attached documents ride along with a single chat message. Extracted
# text is already capped per document, so this bounds total injected context.
MAX_DOCUMENTS_PER_MESSAGE = 3


logger = logging.getLogger(__name__)

FALLBACK_MESSAGES = {
    "timeout": "The AI is taking longer than usual. Please try again in 30 seconds.",
    "connection": "Unable to reach AI service. Please check back shortly.",
    "http_error": "AI service returned an error. Please try again.",
    "api_key": "AI service configuration error. Admin has been notified.",
    "generic": "Something went wrong. Please try again.",
    "warmup": "Service is warming up after inactivity. Please retry in 30 seconds.",
}

# Web-based fallback for open_app commands that work directly from a browser
# tab without the local companion script (Phase 5).
WEB_FALLBACK_URLS = {
    "whatsapp": "https://wa.me/",
    "facebook": "https://facebook.com/",
    "youtube": "https://youtube.com/",
    "instagram": "https://instagram.com/",
    "twitter": "https://twitter.com/",
    "gmail": "https://mail.google.com/",
    "spotify": "https://open.spotify.com/",
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
        if next_url:
            return redirect(next_url)
        if user.is_superuser:
            return redirect("control_panel:dashboard")
        return redirect("chatbot")

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
            "upload_accept": ",".join(sorted(ALLOWED_EXTENSIONS)),
            "upload_max_bytes": MAX_UPLOAD_BYTES,
            "active_documents": UploadedDocument.objects.filter(
                user=request.user,
                is_active=True,
            ).order_by("-uploaded_at")[:MAX_DOCUMENTS_PER_MESSAGE],
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

    # Intent Engine pre-filter — open_app/set_alarm are handled here and never
    # reach the AI at all. Ordinary messages fall straight through to the
    # unchanged query path below (classify_intent returns "query" for them).
    intent_result = classify_intent(message)
    intent = intent_result.get("intent", "query")

    if intent == "open_app":
        app_name = intent_result["entities"].get("app", "")
        command = Command.objects.create(
            user=request.user,
            command_type=Command.CommandType.OPEN_APP,
            target=app_name,
        )
        return JsonResponse(
            {
                "success": True,
                "intent": "open_app",
                "command": {"id": command.id, "target": command.target},
                "message": f"Command sent — will open {app_name} shortly.",
                "web_fallback_url": WEB_FALLBACK_URLS.get(app_name),
            }
        )

    if intent == "set_alarm":
        target_time = intent_result["entities"].get("target_time")
        if target_time is None:
            return json_error(
                "I couldn't understand the time for that reminder. "
                "Try something like 'remind me tomorrow at 9am'."
            )
        reminder = Reminder.objects.create(user=request.user, raw_text=message, target_time=target_time)
        local_time = timezone.localtime(reminder.target_time)
        return JsonResponse(
            {
                "success": True,
                "intent": "set_alarm",
                "reminder": {"id": reminder.id, "target_time": reminder.target_time.isoformat()},
                "message": f"Reminder set for {local_time:%A, %b %d at %I:%M %p}.",
            }
        )

    # Build conversation history (oldest → newest)
    history = list(
        Chat.objects.filter(user=request.user)
        .order_by("-created_at")[: settings.CHAT_HISTORY_LIMIT]
    )
    history.reverse()

    # Documents the user attached earlier in this conversation. They stay active
    # until "New conversation" clears them, so follow-up questions about the same
    # file keep working without re-uploading it.
    documents = list(
        UploadedDocument.objects.filter(
            user=request.user,
            is_active=True,
            status=UploadedDocument.Status.READY,
        ).order_by("-uploaded_at")[:MAX_DOCUMENTS_PER_MESSAGE]
    )

    try:
        response_text = generate_reply(message, history, documents)
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
            "intent": "query",
            "chat": {
                "id": chat_record.id,
                "message": chat_record.message,
                "response": chat_record.response,
                "created_at": chat_record.created_at.isoformat(),
            },
        }
    )


# ---------------------------------------------------------------------------
# File upload / document API views
# ---------------------------------------------------------------------------

def _document_payload(document):
    return {
        "id": document.id,
        "filename": document.filename,
        "status": document.status,
        "characters": len(document.extracted_text),
        "error": document.error_message,
        "uploaded_at": document.uploaded_at.isoformat(),
        "url": document.download_url,
        "storage": "cloudinary" if document.stored_in_cloudinary else "local",
    }


def _fail_document(document, message):
    """Mark a document failed and return the error response.

    The stored binary is deliberately KEPT: the upload itself succeeded, and
    the asset is what makes the extraction failure diagnosable. The row is
    marked failed so it is never injected as AI context.
    """
    document.status = UploadedDocument.Status.FAILED
    document.error_message = message[:300]
    document.save(update_fields=["status", "error_message"])
    return JsonResponse(
        {"success": False, "error": message, "document": _document_payload(document)},
        status=400,
    )


@login_required
@require_POST
def upload_document(request):
    """Accept one file, store the binary, extract its text, and keep it as context.

    Flow:
        browser -> validate -> Cloudinary (production) -> extract from memory
        -> extracted text + Cloudinary metadata -> PostgreSQL

    The binary is read into memory ONCE and both the upload and the extractor
    read from that buffer. Nothing depends on a file still existing on disk
    after the request, which is what makes this correct on Vercel.

    Extraction runs inline: pdfplumber/python-docx on a <=15 MB file is fast
    enough that a background worker would add more moving parts than it saves,
    and the project has no task queue.
    """
    uploaded_file = request.FILES.get("file")
    if uploaded_file is None:
        return json_error("No file was received.")

    try:
        extension = validate_upload(uploaded_file)
    except DocumentExtractionError as exc:
        return json_error(str(exc))

    filename = uploaded_file.name[:255]

    # Single in-memory copy, reused for both storage and extraction. The 15 MB
    # ceiling enforced by validate_upload is what keeps this bounded.
    try:
        uploaded_file.seek(0)
    except (AttributeError, OSError):
        pass
    payload = uploaded_file.read()

    document = UploadedDocument(
        user=request.user,
        filename=filename,
        status=UploadedDocument.Status.PROCESSING,
    )

    # ---- Store the binary --------------------------------------------------
    if cloudinary_storage.is_enabled():
        try:
            asset = cloudinary_storage.upload(
                io.BytesIO(payload), filename, owner_id=request.user.pk
            )
        except cloudinary_storage.CloudinaryError as exc:
            # Never record a half-stored document. Nothing was written, so
            # there is no orphan to clean up and no row to leave inconsistent.
            #
            # 400 when the file itself was rejected (retrying cannot help),
            # 502 when storage was unreachable (retrying might).
            logger.warning("Cloudinary upload failed for %s: %s", filename, exc)
            status = 400 if getattr(exc, "is_client_error", False) else 502
            return json_error(str(exc), status=status)

        document.cloudinary_public_id = asset["public_id"]
        document.cloudinary_resource_type = asset["resource_type"]
        document.cloudinary_url = asset["url"]
        document.cloudinary_version = asset["version"]
        document.save()
    else:
        # Local development / tests: keep using Django's FileSystemStorage.
        document.file = ContentFile(payload, name=filename)
        document.save()

    # ---- Extract the text --------------------------------------------------
    try:
        document.extracted_text = extract_text(io.BytesIO(payload), extension)
        document.status = UploadedDocument.Status.READY
        document.save(update_fields=["extracted_text", "status"])
    except DocumentExtractionError as exc:
        return _fail_document(document, str(exc))
    except Exception:
        logger.exception("Unexpected failure extracting upload %s", document.pk)
        return _fail_document(document, "That file could not be processed.")

    return JsonResponse({"success": True, "document": _document_payload(document)})


@login_required
@require_POST
def clear_documents(request):
    """Detach all active documents — called when starting a new conversation.

    This is a soft detach only: the binaries are left in place so a document
    can still be audited. Explicit removal (below) deletes the asset.
    """
    updated = UploadedDocument.objects.filter(user=request.user, is_active=True).update(
        is_active=False
    )
    return JsonResponse({"success": True, "cleared": updated})


@login_required
@require_POST
def remove_document(request, document_id):
    """Remove a document and delete its stored binary.

    SECURITY: the queryset is filtered by `user=request.user`, so the
    Cloudinary public_id used for deletion can only ever come from a row the
    requester owns. A public_id is never accepted from the request body —
    that would let one user delete another user's asset.
    """
    document = get_object_or_404(UploadedDocument, id=document_id, user=request.user)

    asset_deleted = None
    if document.cloudinary_public_id:
        asset_deleted = cloudinary_storage.delete(
            document.cloudinary_public_id,
            document.cloudinary_resource_type,
        )
        if asset_deleted:
            document.cloudinary_public_id = ""
            document.cloudinary_url = ""
            document.cloudinary_version = ""
    elif document.file:
        # Local development storage.
        try:
            document.file.delete(save=False)
            asset_deleted = True
        except Exception:
            logger.warning("Could not delete local file for document %s", document.pk)
            asset_deleted = False

    document.is_active = False
    document.save()

    # A Cloudinary outage must not block the user's removal action: the record
    # is always deactivated, and a leaked asset is reported rather than hidden.
    return JsonResponse({"success": True, "asset_deleted": asset_deleted})


# ---------------------------------------------------------------------------
# Voice command API
# ---------------------------------------------------------------------------

@login_required
@require_GET
def voice_commands(request):
    """Phrase → URL map used by the browser's voice intent matcher.

    Served from the DB so an administrator can add commands from Django admin
    without a code change or redeploy.
    """
    commands = VoiceCommand.objects.filter(is_active=True)
    return JsonResponse(
        {
            "success": True,
            "commands": [
                {
                    "phrase": command.trigger_phrase,
                    "url": command.action_url,
                    "native": command.native_scheme,
                    "label": command.display_label,
                }
                for command in commands
            ],
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

    # Report the engine actually in use rather than a hardcoded guess — this is
    # the only way to confirm from outside that a deployment reached Neon
    # instead of silently falling back to an ephemeral SQLite file.
    engine = settings.DATABASES["default"]["ENGINE"].rsplit(".", 1)[-1]
    database = "postgresql" if "postgres" in engine else engine

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
                "database": database,
                # Confirms uploads persist to Cloudinary rather than to
                # Vercel's ephemeral filesystem. Booleans only — never values.
                "cloudinary_configured": bool(settings.CLOUDINARY_ENABLED),
            },
        }
    )
