from django.contrib.auth.models import User
from django.db import models


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
