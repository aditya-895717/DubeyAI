from django.contrib import admin

from .models import Chat


@admin.register(Chat)
class ChatAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "message_preview", "created_at")
    list_filter = ("created_at",)
    search_fields = ("user__username", "message", "response")
    readonly_fields = ("created_at",)

    @admin.display(description="Message")
    def message_preview(self, obj):
        return obj.message[:80]
