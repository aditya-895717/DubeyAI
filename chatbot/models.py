from django.contrib.auth.models import User
from django.db import models


def upload_to_user_folder(instance, filename):
    """Store uploads under a per-user folder inside MEDIA_ROOT."""
    return f"uploads/user_{instance.user_id}/{filename}"


class Chat(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="chats")
    message = models.TextField()
    response = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(
                fields=["user", "-created_at"],
                name="chatbot_cha_user_id_23596f_idx",
            )
        ]

    def __str__(self):
        return f"{self.user.username}: {self.message[:60]}"


class UploadedDocument(models.Model):
    """A file the user attached in chat, plus the text extracted from it.

    The project has no Conversation model — chat is a flat per-user log — so
    documents are scoped to the user and carried into the prompt while
    `is_active` is True. Starting a new conversation deactivates them.
    """

    class Status(models.TextChoices):
        PROCESSING = "processing", "Processing"
        READY = "ready", "Ready"
        FAILED = "failed", "Failed"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="documents")
    # Local-development storage only. In production the binary lives in
    # Cloudinary and this stays empty — Vercel's filesystem is ephemeral.
    file = models.FileField(upload_to=upload_to_user_folder, blank=True, null=True)
    filename = models.CharField(max_length=255)

    # Cloudinary metadata. resource_type must be stored, not guessed: deleting
    # an asset requires the same type it was uploaded with, and a raw file
    # requested as an image 404s.
    cloudinary_public_id = models.CharField(max_length=300, blank=True)
    cloudinary_resource_type = models.CharField(max_length=20, blank=True)
    cloudinary_url = models.URLField(max_length=800, blank=True)
    cloudinary_version = models.CharField(max_length=40, blank=True)
    extracted_text = models.TextField(blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PROCESSING
    )
    error_message = models.CharField(max_length=300, blank=True)
    # Cleared when the user starts a new conversation, so an old attachment is
    # never silently injected into an unrelated question.
    is_active = models.BooleanField(default=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-uploaded_at"]
        indexes = [models.Index(fields=["user", "-uploaded_at"])]

    @property
    def stored_in_cloudinary(self):
        return bool(self.cloudinary_public_id)

    @property
    def download_url(self):
        """Public URL for the stored binary, or "" when there is none.

        Prefers Cloudinary so production never hands out a /media/ path that
        Vercel cannot serve.
        """
        if self.cloudinary_url:
            return self.cloudinary_url
        if self.file:
            try:
                return self.file.url
            except ValueError:
                return ""
        return ""

    def __str__(self):
        return f"{self.user.username}: {self.filename} ({self.status})"
