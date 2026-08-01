from django.contrib import admin

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

admin.site.register(SiteSettings)
admin.site.register(AIProvider)
admin.site.register(ContentBlock)
admin.site.register(LoginLog)
admin.site.register(ChatMessage)
admin.site.register(Reminder)
admin.site.register(Command)
admin.site.register(PushSubscription)
