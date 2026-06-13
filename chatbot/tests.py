import json
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Chat
from .services import strip_reasoning


class ChatViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice", "alice@example.com", "StrongPass123!")
        self.other_user = User.objects.create_user("bob", "bob@example.com", "StrongPass123!")

    def test_chat_page_requires_authentication(self):
        response = self.client.get(reverse("chatbot"))
        self.assertRedirects(response, f"{reverse('login')}?next={reverse('chatbot')}")

    def test_authenticated_chat_page_renders_production_ui(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("chatbot"))
        self.assertContains(response, "How can I help you move forward?")
        self.assertContains(response, reverse("chat"))
        self.assertContains(response, "/static/chatbot/css/app.")
        self.assertContains(response, "csrfmiddlewaretoken")

    def test_empty_message_is_rejected(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("chat"),
            data=json.dumps({"message": "   "}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["success"])

    @patch("chatbot.views.generate_reply", return_value="A safe final answer.")
    def test_chat_saves_and_returns_reply(self, generate_reply):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("chat"),
            data=json.dumps({"message": "Hello"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["chat"]["response"], "A safe final answer.")
        self.assertTrue(Chat.objects.filter(user=self.user, message="Hello").exists())
        generate_reply.assert_called_once()

    def test_history_is_scoped_to_authenticated_user(self):
        Chat.objects.create(user=self.user, message="mine", response="yes")
        Chat.objects.create(user=self.other_user, message="private", response="no")
        self.client.force_login(self.user)
        response = self.client.get(reverse("chat_history"))
        messages = [item["message"] for item in response.json()["chats"]]
        self.assertEqual(messages, ["mine"])

    def test_logout_requires_post(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("logout"))
        self.assertEqual(response.status_code, 405)

    def test_login_does_not_redirect_to_external_host(self):
        response = self.client.post(
            f"{reverse('login')}?next=https://example.com/phishing",
            {"username": "alice", "password": "StrongPass123!"},
        )
        self.assertRedirects(response, reverse("chatbot"))

    @override_settings(CHAT_MAX_MESSAGE_LENGTH=5)
    def test_message_length_is_limited(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("chat"),
            data=json.dumps({"message": "123456"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)


class AIServiceTests(TestCase):
    def test_reasoning_blocks_are_removed(self):
        value = strip_reasoning("<think>private reasoning</think>\nFinal answer")
        self.assertEqual(value, "Final answer")
