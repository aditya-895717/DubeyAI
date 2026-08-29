import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.templatetags.static import static as static_url
from django.views.decorators.http import require_GET, require_POST

from core.decorators import companion_key_required, superuser_required
from core.forms import AIProviderForm, ContentBlockForm, SiteSettingsForm
from core.models import (
    AIProvider,
    ChatMessage,
    Command,
    ContentBlock,
    LoginLog,
    PushSubscription,
    Reminder,
    SiteSettings,
)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@superuser_required
def dashboard(request):
    context = {
        "active_nav": "dashboard",
        "total_users": User.objects.count(),
        "total_chat_messages": ChatMessage.objects.count(),
        "pending_reminders": Reminder.objects.filter(status=Reminder.Status.PENDING).count(),
        "pending_commands": Command.objects.filter(status=Command.Status.PENDING).count(),
        "active_provider": AIProvider.objects.filter(is_active=True).first(),
    }
    return render(request, "control_panel/dashboard.html", context)


# ---------------------------------------------------------------------------
# Site settings
# ---------------------------------------------------------------------------

@superuser_required
def site_settings_view(request):
    instance = SiteSettings.load()
    form = SiteSettingsForm(request.POST or None, request.FILES or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Site settings updated.")
        return redirect("control_panel:site_settings")
    return render(
        request,
        "control_panel/site_settings.html",
        {"active_nav": "settings", "form": form, "settings_obj": instance},
    )


# ---------------------------------------------------------------------------
# Content blocks
# ---------------------------------------------------------------------------

@superuser_required
def content_list(request):
    blocks = ContentBlock.objects.order_by("key")
    return render(request, "control_panel/content_list.html", {"active_nav": "content", "blocks": blocks})


@superuser_required
def content_create(request):
    form = ContentBlockForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Content block created.")
        return redirect("control_panel:content_list")
    return render(
        request,
        "control_panel/content_form.html",
        {"active_nav": "content", "form": form, "is_new": True},
    )


@superuser_required
def content_edit(request, pk):
    block = get_object_or_404(ContentBlock, pk=pk)
    form = ContentBlockForm(request.POST or None, instance=block)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Content block updated.")
        return redirect("control_panel:content_list")
    return render(
        request,
        "control_panel/content_form.html",
        {"active_nav": "content", "form": form, "is_new": False, "block": block},
    )


@superuser_required
@require_POST
def content_delete(request, pk):
    block = get_object_or_404(ContentBlock, pk=pk)
    block.delete()
    messages.success(request, "Content block deleted.")
    return redirect("control_panel:content_list")


# ---------------------------------------------------------------------------
# AI providers
# ---------------------------------------------------------------------------

@superuser_required
def ai_provider_list(request):
    providers = AIProvider.objects.all()
    return render(
        request,
        "control_panel/ai_provider_list.html",
        {"active_nav": "ai_providers", "providers": providers},
    )


@superuser_required
def ai_provider_create(request):
    form = AIProviderForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        is_first = not AIProvider.objects.exists()
        provider = form.save(commit=False)
        # The very first provider becomes active automatically — otherwise the
        # app would still report "no active provider" right after setup.
        provider.is_active = is_first
        provider.save()
        messages.success(
            request,
            "AI provider added and set active." if is_first else "AI provider added.",
        )
        return redirect("control_panel:ai_provider_list")
    return render(
        request,
        "control_panel/ai_provider_form.html",
        {"active_nav": "ai_providers", "form": form, "is_new": True},
    )


@superuser_required
def ai_provider_edit(request, pk):
    provider = get_object_or_404(AIProvider, pk=pk)
    form = AIProviderForm(request.POST or None, instance=provider)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "AI provider updated.")
        return redirect("control_panel:ai_provider_list")
    return render(
        request,
        "control_panel/ai_provider_form.html",
        {"active_nav": "ai_providers", "form": form, "is_new": False, "provider": provider},
    )


@superuser_required
@require_POST
def ai_provider_delete(request, pk):
    provider = get_object_or_404(AIProvider, pk=pk)
    was_active = provider.is_active
    provider.delete()
    messages.success(request, "AI provider deleted.")
    if was_active and not AIProvider.objects.filter(is_active=True).exists():
        messages.warning(
            request,
            "That was the active provider — AI replies will fail until you set another one active.",
        )
    return redirect("control_panel:ai_provider_list")


@superuser_required
@require_POST
def ai_provider_activate(request, pk):
    provider = get_object_or_404(AIProvider, pk=pk)
    provider.is_active = True
    provider.save()  # AIProvider.save() deactivates every other row
    messages.success(request, f"{provider.name} is now the active AI provider.")
    return redirect("control_panel:ai_provider_list")


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

@superuser_required
def user_list(request):
    users = User.objects.order_by("-date_joined")
    return render(request, "control_panel/user_list.html", {"active_nav": "users", "users": users})


@superuser_required
def user_detail(request, pk):
    user_obj = get_object_or_404(User, pk=pk)
    logs = LoginLog.objects.filter(user=user_obj).order_by("-timestamp")
    return render(
        request,
        "control_panel/user_detail.html",
        {"active_nav": "users", "user_obj": user_obj, "logs": logs},
    )


# ---------------------------------------------------------------------------
# PWA — manifest, service worker, offline fallback, push subscriptions
# ---------------------------------------------------------------------------

@require_GET
def manifest_json(request):
    """Build manifest.json from SiteSettings on every request, so branding
    changes in the control panel take effect without a redeploy."""
    site = SiteSettings.load()
    site_name = site.site_name or "DubeyAI"
    manifest = {
        "name": site_name,
        "short_name": site_name[:12],
        "description": f"{site_name} — your personal AI assistant",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "theme_color": site.primary_color,
        "background_color": site.secondary_color,
        "icons": [
            {"src": static_url("core/icons/icon-192.png"), "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": static_url("core/icons/icon-512.png"), "sizes": "512x512", "type": "image/png", "purpose": "any"},
        ],
    }
    return JsonResponse(manifest, content_type="application/manifest+json")


@require_GET
def service_worker(request):
    response = render(request, "service-worker.js", content_type="application/javascript")
    # Served from the domain root deliberately (not /static/) so its default
    # scope covers the whole site; this header makes that explicit too.
    response["Service-Worker-Allowed"] = "/"
    return response


@require_GET
def offline_page(request):
    return render(request, "offline.html")


@login_required
@require_POST
def save_push_subscription(request):
    try:
        payload = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return HttpResponseBadRequest("Invalid JSON.")

    endpoint = payload.get("endpoint", "")
    keys = payload.get("keys", {})
    p256dh = keys.get("p256dh", "")
    auth = keys.get("auth", "")

    if not (endpoint and p256dh and auth):
        return HttpResponseBadRequest("Missing subscription fields.")

    PushSubscription.objects.update_or_create(
        endpoint=endpoint,
        defaults={"user": request.user, "p256dh_key": p256dh, "auth_key": auth},
    )
    return JsonResponse({"success": True})


# ---------------------------------------------------------------------------
# Local companion script API — machine-to-machine, authenticated via
# X-DubeyAI-Key rather than session/login. Global (not per-user): the
# companion script runs on one person's machine and executes whatever
# commands/reminders are pending across the system it's polling.
# ---------------------------------------------------------------------------

@companion_key_required
@require_GET
def pending_commands(request):
    commands = Command.objects.filter(status=Command.Status.PENDING).order_by("created_at")
    return JsonResponse(
        {
            "commands": [
                {
                    "id": command.id,
                    "user": command.user.username,
                    "command_type": command.command_type,
                    "target": command.target,
                    "created_at": command.created_at.isoformat(),
                }
                for command in commands
            ]
        }
    )


@companion_key_required
@require_GET
def pending_reminders(request):
    reminders = Reminder.objects.filter(status=Reminder.Status.PENDING).order_by("target_time")
    return JsonResponse(
        {
            "reminders": [
                {
                    "id": reminder.id,
                    "user": reminder.user.username,
                    "raw_text": reminder.raw_text,
                    "target_time": reminder.target_time.isoformat(),
                    "created_at": reminder.created_at.isoformat(),
                }
                for reminder in reminders
            ]
        }
    )


@companion_key_required
@require_POST
def mark_command_done(request, pk):
    command = get_object_or_404(Command, pk=pk)
    command.status = Command.Status.EXECUTED
    command.save(update_fields=["status"])
    return JsonResponse({"success": True})


@companion_key_required
@require_POST
def mark_reminder_done(request, pk):
    reminder = get_object_or_404(Reminder, pk=pk)
    reminder.status = Reminder.Status.COMPLETED
    reminder.save(update_fields=["status"])
    return JsonResponse({"success": True})
