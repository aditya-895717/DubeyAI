from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
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
    """Configured AI/LLM backend. Only one row may have is_active=True at a time.

    Every supported provider is reached through the OpenAI-compatible
    chat-completions API, so switching provider is a DB change (done from the
    control panel or Django admin) rather than a redeploy — see
    core.services.get_active_ai_client.
    """

    class ProviderType(models.TextChoices):
        OPENAI = "openai", "OpenAI"
        ANTHROPIC = "anthropic", "Anthropic (Claude)"
        GEMINI = "gemini", "Google Gemini"
        GROQ = "groq", "Groq"
        NVIDIA = "nvidia", "NVIDIA NIM"
        OTHER = "other", "Other (OpenAI-compatible)"

    # Documented OpenAI-compatible base URLs, used when endpoint_url is blank.
    # "other" has no default on purpose — a custom endpoint must be given.
    DEFAULT_ENDPOINTS = {
        ProviderType.OPENAI: "https://api.openai.com/v1",
        ProviderType.ANTHROPIC: "https://api.anthropic.com/v1/",
        ProviderType.GEMINI: "https://generativelanguage.googleapis.com/v1beta/openai/",
        ProviderType.GROQ: "https://api.groq.com/openai/v1",
        ProviderType.NVIDIA: "https://integrate.api.nvidia.com/v1",
    }

    name = models.CharField(max_length=100)
    provider_type = models.CharField(
        max_length=20,
        choices=ProviderType.choices,
        default=ProviderType.OTHER,
        help_text="Selects the provider's default endpoint and request dialect.",
    )
    api_key = EncryptedTextField(
        help_text="Encrypted at rest with FIELD_ENCRYPTION_KEY; never displayed once saved."
    )
    endpoint_url = models.URLField(
        blank=True,
        help_text="Leave blank to use the selected provider type's default base URL.",
    )
    model_name = models.CharField(
        max_length=150,
        blank=True,
        help_text="Exact model ID to send, e.g. gpt-5.2, claude-opus-5, gemini-3-pro.",
    )
    is_active = models.BooleanField(
        default=False,
        help_text="Exactly one provider is active; activating this one deactivates the rest.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def resolved_endpoint_url(self):
        """The base URL to call: the explicit one, else this type's documented default."""
        return self.endpoint_url or self.DEFAULT_ENDPOINTS.get(self.provider_type, "")

    def clean(self):
        # A custom/unknown provider has no default base URL to fall back on.
        if not self.resolved_endpoint_url:
            raise ValidationError(
                {"endpoint_url": "An endpoint URL is required for this provider type."}
            )

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


class VoiceCommand(models.Model):
    """A spoken phrase that opens a URL directly, without calling the AI.

    Browsers can only navigate to URLs — a web page cannot launch a native
    desktop or mobile application, so `action_url` should normally be an https
    web URL (e.g. https://web.whatsapp.com). `native_scheme` is an optional
    best-effort custom scheme (e.g. whatsapp://send): it usually works on
    mobile, is unreliable on desktop, and the frontend always falls back to
    `action_url` if nothing intercepts it.
    """

    trigger_phrase = models.CharField(
        max_length=120,
        unique=True,
        help_text="Lowercase phrase to match in speech, e.g. 'open whatsapp' or 'whatsapp khol do'.",
    )
    action_url = models.URLField(
        max_length=500,
        help_text="Web URL opened in a new tab, e.g. https://web.whatsapp.com",
    )
    native_scheme = models.CharField(
        max_length=200,
        blank=True,
        help_text="Optional custom scheme tried first on mobile, e.g. whatsapp://send",
    )
    label = models.CharField(
        max_length=80,
        blank=True,
        help_text="Shown in the toast, e.g. 'WhatsApp'. Defaults to the trigger phrase.",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["trigger_phrase"]
        verbose_name = "voice command"

    def save(self, *args, **kwargs):
        self.trigger_phrase = self.trigger_phrase.strip().lower()
        super().save(*args, **kwargs)

    @property
    def display_label(self):
        return self.label or self.trigger_phrase.title()

    def __str__(self):
        return f"{self.trigger_phrase} -> {self.action_url}"
