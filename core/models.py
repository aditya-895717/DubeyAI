from django.contrib.auth.models import User
from django.db import models

from core.fields import EncryptedTextField


class SiteSettings(models.Model):
    """Singleton: branding/theme configuration for the site. Only pk=1 ever exists."""

    site_name = models.CharField(max_length=100, default="DubeyAI")
    logo = models.ImageField(upload_to="branding/", blank=True, null=True)
    primary_color = models.CharField(max_length=7, default="#0a0a0a")
    secondary_color = models.CharField(max_length=7, default="#111111")
    accent_color = models.CharField(max_length=7, default="#C41A1A")
    font_family = models.CharField(max_length=100, default="Inter, system-ui, sans-serif")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Site Settings"
        verbose_name_plural = "Site Settings"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        pass

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return self.site_name


class AIProvider(models.Model):
    """Configured AI/LLM backend. Only one row may have is_active=True at a time."""

    name = models.CharField(max_length=100)
    api_key = EncryptedTextField()
    endpoint_url = models.URLField()
    model_name = models.CharField(max_length=150)
    is_active = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if self.is_active:
            AIProvider.objects.exclude(pk=self.pk).update(is_active=False)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({'active' if self.is_active else 'inactive'})"


class ContentBlock(models.Model):
    """Admin-editable key/value text block for dynamic, non-hardcoded site copy."""

    key = models.CharField(max_length=100, unique=True)
    value = models.TextField()
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.key


class LoginLog(models.Model):
    """Audit record created automatically on every successful login."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="login_logs")
    timestamp = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self):
        return f"{self.user.username} @ {self.timestamp:%Y-%m-%d %H:%M}"


class ChatMessage(models.Model):
    class Intent(models.TextChoices):
        QUERY = "query", "Query"
        OPEN_APP = "open_app", "Open App"
        SET_ALARM = "set_alarm", "Set Alarm"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="chat_messages")
    message = models.TextField()
    response = models.TextField(blank=True)
    intent = models.CharField(max_length=20, choices=Intent.choices, default=Intent.QUERY)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["timestamp"]
        indexes = [models.Index(fields=["user", "-timestamp"])]

    def __str__(self):
        return f"{self.user.username}: {self.message[:60]}"


class Reminder(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        COMPLETED = "completed", "Completed"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="reminders")
    raw_text = models.TextField()
    target_time = models.DateTimeField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["target_time"]

    def __str__(self):
        return f"{self.user.username}: {self.raw_text[:40]} ({self.status})"


class Command(models.Model):
    class CommandType(models.TextChoices):
        OPEN_APP = "open_app", "Open App"
        OPEN_WEB = "open_web", "Open Web"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        EXECUTED = "executed", "Executed"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="commands")
    command_type = models.CharField(max_length=20, choices=CommandType.choices)
    target = models.CharField(max_length=200)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user.username}: {self.command_type} -> {self.target} ({self.status})"


class PushSubscription(models.Model):
    """A browser's Web Push subscription (one per device/browser a user has enabled)."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="push_subscriptions")
    endpoint = models.URLField(max_length=500, unique=True)
    p256dh_key = models.CharField(max_length=255)
    auth_key = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username}: {self.endpoint[:60]}"
