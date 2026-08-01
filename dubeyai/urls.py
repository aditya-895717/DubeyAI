from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from core import views as core_views


urlpatterns = [
    path("admin/", admin.site.urls),
    path("control-panel/", include("core.urls")),
    # PWA — served from the domain root deliberately, not under /control-panel/
    # or /static/, so manifest scope and service worker scope can both be "/".
    path("manifest.json", core_views.manifest_json, name="manifest_json"),
    path("service-worker.js", core_views.service_worker, name="service_worker"),
    path("offline/", core_views.offline_page, name="offline_page"),
    path("api/push/subscribe/", core_views.save_push_subscription, name="push_subscribe"),
    # Local companion script API (Phase 5) — X-DubeyAI-Key authenticated.
    path("api/pending-commands/", core_views.pending_commands, name="pending_commands"),
    path("api/pending-reminders/", core_views.pending_reminders, name="pending_reminders"),
    path("api/mark-command-done/<int:pk>/", core_views.mark_command_done, name="mark_command_done"),
    path("api/mark-reminder-done/<int:pk>/", core_views.mark_reminder_done, name="mark_reminder_done"),
    path("", include("chatbot.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
