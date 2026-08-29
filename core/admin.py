from django.contrib import admin

from core.forms import AIProviderAdminForm
from core.models import (
    AIProvider,
    ChatMessage,
    Command,
    ContentBlock,
    LoginLog,
    PushSubscription,
    Reminder,
    SiteSettings,
    VoiceCommand,
)


@admin.register(AIProvider)
class AIProviderAdmin(admin.ModelAdmin):
    """Admin for AI providers.

    SECURITY: AIProvider.api_key is transparently decrypted on read, so it must
    never reach a template. The custom form renders it write-only, and the
    changelist shows only whether a key is present — never any key material.
    Bulk-edit surfaces (list_editable / custom queryset.update actions) are
    deliberately absent: they would bypass AIProvider.save() and could leave
    two rows active at once.
    """

    form = AIProviderAdminForm
    list_display = ("name", "provider_type", "is_active", "api_key_status", "model_name", "updated_at")
    list_filter = ("provider_type", "is_active")
    search_fields = ("name", "model_name", "endpoint_url")
    readonly_fields = ("created_at", "updated_at", "api_key_status", "resolved_endpoint_url")
    fields = (
        "name",
        "provider_type",
        "api_key",
        "api_key_status",
        "endpoint_url",
        "resolved_endpoint_url",
        "model_name",
        "is_active",
        "created_at",
        "updated_at",
    )

    @admin.display(description="API key")
    def api_key_status(self, obj):
        if obj is None or not obj.pk:
            return "not set"
        return "•••••••• (set)" if obj.api_key else "not set"

    @admin.display(description="Effective endpoint")
    def resolved_endpoint_url(self, obj):
        if obj is None or not obj.pk:
            return "—"
        return obj.resolved_endpoint_url or "—"


admin.site.register(SiteSettings)
admin.site.register(ContentBlock)
admin.site.register(LoginLog)
admin.site.register(ChatMessage)
admin.site.register(Reminder)
admin.site.register(Command)
admin.site.register(PushSubscription)


@admin.register(VoiceCommand)
class VoiceCommandAdmin(admin.ModelAdmin):
    list_display = ("trigger_phrase", "action_url", "native_scheme", "is_active")
    list_filter = ("is_active",)
    list_editable = ("is_active",)
    search_fields = ("trigger_phrase", "action_url", "label")
