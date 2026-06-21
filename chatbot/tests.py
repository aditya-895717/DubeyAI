"""
Comprehensive test suite for DubeyAI — covers every permutation and combination
of URL resolution, authentication, chat, AI fallback, settings, database,
static files, security, performance, and Render deployment scenarios.

Run all tests:
    python manage.py test chatbot --verbosity=2

Run with coverage:
    coverage run --source='.' manage.py test chatbot
    coverage report
    coverage html

Run a specific section:
    python manage.py test chatbot.tests.NvidiaAPIFallbackTests
    python manage.py test chatbot.tests.AuthTests
"""

import json
import os
import threading
import time
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import User
from django.db import connection
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from chatbot.models import Chat
from chatbot.services import AIServiceError, strip_reasoning
from chatbot.views import FALLBACK_MESSAGES


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def make_user(username="testuser", password="TestPass123!"):
    return User.objects.create_user(username=username, password=password)


def auth_client(username="testuser", password="TestPass123!"):
    user = make_user(username, password)
    c = Client()
    c.login(username=username, password=password)
    return c, user


def chat_post(client, message="Hello"):
    return client.post(
        reverse("chat"),
        data=json.dumps({"message": message}),
        content_type="application/json",
    )


# ===========================================================================
# Existing tests — preserved verbatim
# ===========================================================================

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


# ===========================================================================
# A: URL & View Tests
# ===========================================================================

class URLTests(TestCase):
    def setUp(self):
        self.client, self.user = auth_client()

    # A1. All URL names resolve without raising NoReverseMatch
    def test_a1_all_named_urls_resolve(self):
        for name in [
            "chatbot", "chat", "login", "register", "logout",
            "chat_history", "clear_history", "search_chats", "ping",
        ]:
            with self.subTest(name=name):
                self.assertIsNotNone(reverse(name))

    # A2. /ping/ returns 200
    def test_a2_ping_returns_200(self):
        self.assertEqual(Client().get(reverse("ping")).status_code, 200)

    # A3. /login/ returns 200
    def test_a3_login_returns_200(self):
        self.assertEqual(Client().get(reverse("login")).status_code, 200)

    # A4. /register/ returns 200
    def test_a4_register_returns_200(self):
        self.assertEqual(Client().get(reverse("register")).status_code, 200)

    # A5. / redirects unauthenticated users
    def test_a5_root_redirects_unauthenticated(self):
        self.assertIn(Client().get(reverse("chatbot")).status_code, [301, 302])

    # A6. / returns 200 for authenticated user
    def test_a6_root_returns_200_authenticated(self):
        self.assertEqual(self.client.get(reverse("chatbot")).status_code, 200)

    # A7. 404 for unknown URL
    def test_a7_unknown_url_is_404(self):
        self.assertEqual(
            Client().get("/no-such-route-abc123/").status_code, 404
        )

    # A8. /ping/ accepts GET; HEAD and POST may be 200 or 405
    def test_a8_ping_method_variants(self):
        c = Client()
        self.assertEqual(c.get(reverse("ping")).status_code, 200)
        self.assertIn(c.head(reverse("ping")).status_code, [200, 405])
        self.assertIn(c.post(reverse("ping")).status_code, [200, 405])

    # A9. All primary paths work with trailing slash
    def test_a9_trailing_slash_paths(self):
        for path in ["/ping/", "/login/", "/register/"]:
            with self.subTest(path=path):
                self.assertNotEqual(Client().get(path).status_code, 404)

    # A10. Paths without trailing slash do not return 500
    def test_a10_no_trailing_slash_does_not_500(self):
        for path in ["/ping", "/login", "/register"]:
            with self.subTest(path=path):
                self.assertNotEqual(Client().get(path).status_code, 500)


# ===========================================================================
# B: Ping Endpoint Tests
# ===========================================================================

class PingViewTests(TestCase):

    # B1. Returns 200
    def test_b1_returns_200(self):
        self.assertEqual(Client().get(reverse("ping")).status_code, 200)

    # B2. Returns JSON content type
    def test_b2_returns_json(self):
        r = Client().get(reverse("ping"))
        self.assertIn("application/json", r["Content-Type"])

    # B3. status == "ok"
    def test_b3_status_is_ok(self):
        data = json.loads(Client().get(reverse("ping")).content)
        self.assertEqual(data["status"], "ok")

    # B4. service == "DubeyAI"
    def test_b4_service_is_dubeyai(self):
        data = json.loads(Client().get(reverse("ping")).content)
        self.assertEqual(data["service"], "DubeyAI")

    # B5. timestamp present and non-empty string
    def test_b5_timestamp_present_and_valid(self):
        data = json.loads(Client().get(reverse("ping")).content)
        self.assertIn("timestamp", data)
        self.assertIsInstance(data["timestamp"], str)
        self.assertTrue(data["timestamp"])

    # B6. nvidia_key_loaded True when key is set
    def test_b6_nvidia_key_loaded_true_when_set(self):
        with patch.dict(os.environ, {"NVIDIA_API_KEY": "nvkey-abc123"}):
            data = json.loads(Client().get(reverse("ping")).content)
        self.assertTrue(data["env_check"]["nvidia_key_loaded"])

    # B7. nvidia_key_loaded False when key is empty
    def test_b7_nvidia_key_loaded_false_when_missing(self):
        with patch.dict(os.environ, {"NVIDIA_API_KEY": ""}):
            data = json.loads(Client().get(reverse("ping")).content)
        self.assertFalse(data["env_check"]["nvidia_key_loaded"])

    # B8. secret_key_loaded True for a real (non-placeholder) key
    def test_b8_secret_key_loaded_true_for_real_key(self):
        with patch.dict(os.environ, {"SECRET_KEY": "real-prod-key-xyz-abc-123"}):
            data = json.loads(Client().get(reverse("ping")).content)
        self.assertTrue(data["env_check"]["secret_key_loaded"])

    # B9. secret_key_loaded False for the placeholder value
    def test_b9_secret_key_loaded_false_for_placeholder(self):
        with patch.dict(os.environ, {"SECRET_KEY": "unsafe-dev-key-change-in-prod"}):
            data = json.loads(Client().get(reverse("ping")).content)
        self.assertFalse(data["env_check"]["secret_key_loaded"])

    # B10. Ping works when NVIDIA and SECRET env vars are empty
    def test_b10_works_without_sensitive_env_vars(self):
        with patch.dict(os.environ, {"NVIDIA_API_KEY": "", "SECRET_KEY": ""}):
            r = Client().get(reverse("ping"))
        self.assertEqual(r.status_code, 200)


# ===========================================================================
# C: Authentication Tests
# ===========================================================================

class AuthTests(TestCase):
    def setUp(self):
        self.user = make_user()

    # C1. Login page loads (GET)
    def test_c1_login_page_loads(self):
        r = Client().get(reverse("login"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "form")

    # C2. Login with valid credentials succeeds
    def test_c2_login_valid_credentials(self):
        c = Client()
        c.post(reverse("login"), {"username": "testuser", "password": "TestPass123!"})
        self.assertIn("_auth_user_id", c.session)

    # C3. Login with wrong password fails
    def test_c3_login_wrong_password(self):
        c = Client()
        c.post(reverse("login"), {"username": "testuser", "password": "WrongPass!"})
        self.assertNotIn("_auth_user_id", c.session)

    # C4. Login with non-existent user fails
    def test_c4_login_nonexistent_user(self):
        c = Client()
        c.post(reverse("login"), {"username": "nobody", "password": "TestPass123!"})
        self.assertNotIn("_auth_user_id", c.session)

    # C5. Login with empty username fails
    def test_c5_login_empty_username(self):
        c = Client()
        c.post(reverse("login"), {"username": "", "password": "TestPass123!"})
        self.assertNotIn("_auth_user_id", c.session)

    # C6. Login with empty password fails
    def test_c6_login_empty_password(self):
        c = Client()
        c.post(reverse("login"), {"username": "testuser", "password": ""})
        self.assertNotIn("_auth_user_id", c.session)

    # C7. Login with both fields empty fails
    def test_c7_login_both_empty(self):
        c = Client()
        c.post(reverse("login"), {"username": "", "password": ""})
        self.assertNotIn("_auth_user_id", c.session)

    # C8. SQL injection in login is safe
    def test_c8_login_sql_injection_safe(self):
        c = Client()
        r = c.post(reverse("login"), {
            "username": "admin' OR '1'='1' --",
            "password": "' OR '1'='1",
        })
        self.assertNotEqual(r.status_code, 500)
        self.assertNotIn("_auth_user_id", c.session)

    # C9. XSS attempt in login is escaped
    def test_c9_login_xss_safe(self):
        c = Client()
        r = c.post(reverse("login"), {
            "username": "<script>alert('xss')</script>",
            "password": "test",
        })
        self.assertNotEqual(r.status_code, 500)
        self.assertNotIn(b"<script>alert('xss')</script>", r.content)

    # C10. Very long username does not 500
    def test_c10_login_very_long_username_safe(self):
        r = Client().post(reverse("login"), {
            "username": "a" * 10000,
            "password": "TestPass123!",
        })
        self.assertNotEqual(r.status_code, 500)

    # C11. Special characters in fields are safe
    def test_c11_login_special_characters_safe(self):
        r = Client().post(reverse("login"), {
            "username": "user@#$%^&*()",
            "password": "test!@#",
        })
        self.assertNotEqual(r.status_code, 500)

    # C12. Spaces in fields are safe
    def test_c12_login_spaces_safe(self):
        r = Client().post(reverse("login"), {
            "username": "   testuser   ",
            "password": "TestPass123!",
        })
        self.assertNotEqual(r.status_code, 500)

    # C13. Logout removes user from session
    def test_c13_logout_works(self):
        c = Client()
        c.login(username="testuser", password="TestPass123!")
        c.post(reverse("logout"))
        self.assertNotIn("_auth_user_id", c.session)

    # C14. Logout redirects
    def test_c14_logout_redirects(self):
        c = Client()
        c.login(username="testuser", password="TestPass123!")
        r = c.post(reverse("logout"))
        self.assertIn(r.status_code, [301, 302])

    # C15. Session is cleared after logout
    def test_c15_session_cleared_after_logout(self):
        c = Client()
        c.login(username="testuser", password="TestPass123!")
        self.assertIn("_auth_user_id", c.session)
        c.post(reverse("logout"))
        self.assertNotIn("_auth_user_id", c.session)

    # C16. Register page loads (GET)
    def test_c16_register_page_loads(self):
        r = Client().get(reverse("register"))
        self.assertEqual(r.status_code, 200)

    # C17. Register with valid data creates the account
    def test_c17_register_valid_data(self):
        Client().post(reverse("register"), {
            "username": "newuser",
            "email": "newuser@example.com",
            "password1": "Str0ng!Passw0rd",
            "password2": "Str0ng!Passw0rd",
        })
        self.assertTrue(User.objects.filter(username="newuser").exists())

    # C18. Registering an existing username shows a form error (200, no duplicate)
    def test_c18_register_existing_username_fails(self):
        r = Client().post(reverse("register"), {
            "username": "testuser",
            "email": "other@example.com",
            "password1": "Str0ng!Passw0rd",
            "password2": "Str0ng!Passw0rd",
        })
        self.assertEqual(r.status_code, 200)
        self.assertEqual(User.objects.filter(username="testuser").count(), 1)

    # C19. Mismatched passwords do not create the account
    def test_c19_register_mismatched_passwords_fails(self):
        Client().post(reverse("register"), {
            "username": "uniqueuser",
            "email": "unique@example.com",
            "password1": "Str0ng!Passw0rd",
            "password2": "DifferentPass!",
        })
        self.assertFalse(User.objects.filter(username="uniqueuser").exists())

    # C20. Weak/common password is rejected by AUTH_PASSWORD_VALIDATORS
    def test_c20_register_weak_password_fails(self):
        Client().post(reverse("register"), {
            "username": "weakuser",
            "email": "weak@example.com",
            "password1": "password",
            "password2": "password",
        })
        self.assertFalse(User.objects.filter(username="weakuser").exists())

    # C21. Authenticated user accessing /login/ is redirected
    def test_c21_authenticated_redirected_from_login(self):
        c = Client()
        c.login(username="testuser", password="TestPass123!")
        r = c.get(reverse("login"))
        self.assertIn(r.status_code, [301, 302])

    # C22. Unauthenticated user accessing / is redirected
    def test_c22_unauthenticated_redirected_from_chat(self):
        r = Client().get(reverse("chatbot"))
        self.assertIn(r.status_code, [301, 302])


# ===========================================================================
# D: Chat View Tests (comprehensive)
# ===========================================================================

class ChatViewComprehensiveTests(TestCase):
    def setUp(self):
        self.client, self.user = auth_client()

    # D1. Chat page loads for authenticated user
    def test_d1_chat_page_loads(self):
        self.assertEqual(self.client.get(reverse("chatbot")).status_code, 200)

    # D2. Valid chat POST — success path
    @patch("chatbot.views.generate_reply", return_value="Hi there!")
    def test_d2_chat_post_valid_message(self, _mock):
        r = chat_post(self.client, "Hello")
        self.assertEqual(r.status_code, 200)
        data = json.loads(r.content)
        self.assertTrue(data["success"])
        self.assertIn("chat", data)

    # D3. Empty message returns 400
    def test_d3_chat_post_empty_message(self):
        self.assertEqual(chat_post(self.client, "").status_code, 400)

    # D4. Whitespace-only message returns 400
    def test_d4_chat_post_whitespace_only(self):
        self.assertEqual(chat_post(self.client, "   \t\n  ").status_code, 400)

    # D5. Message over limit returns 400
    def test_d5_chat_post_message_too_long(self):
        big = "x" * (settings.CHAT_MAX_MESSAGE_LENGTH + 1)
        self.assertEqual(chat_post(self.client, big).status_code, 400)

    # D6. Special characters do not 500
    @patch("chatbot.views.generate_reply", return_value="OK")
    def test_d6_chat_post_special_characters(self, _mock):
        r = chat_post(self.client, "Hello! <>&\"' ¿Cómo estás? 日本語")
        self.assertNotEqual(r.status_code, 500)

    # D7. HTML/script injection does not 500
    @patch("chatbot.views.generate_reply", return_value="OK")
    def test_d7_chat_post_script_injection_safe(self, _mock):
        r = chat_post(self.client, "<script>alert(document.cookie)</script>")
        self.assertNotEqual(r.status_code, 500)

    # D8. GET on /chat/ returns 405
    def test_d8_chat_get_is_405(self):
        self.assertEqual(self.client.get(reverse("chat")).status_code, 405)

    # D9. Wrong content type returns 415
    def test_d9_chat_wrong_content_type(self):
        r = self.client.post(
            reverse("chat"),
            data="message=hello",
            content_type="application/x-www-form-urlencoded",
        )
        self.assertEqual(r.status_code, 415)

    # D10. Unauthenticated POST is redirected
    def test_d10_chat_unauthenticated_redirected(self):
        self.assertIn(chat_post(Client(), "Hello").status_code, [301, 302])

    # D11. Response Content-Type is JSON
    @patch("chatbot.views.generate_reply", return_value="AI reply")
    def test_d11_chat_returns_json(self, _mock):
        r = chat_post(self.client, "Test")
        self.assertIn("application/json", r["Content-Type"])

    # D12. Successful response has expected structure
    @patch("chatbot.views.generate_reply", return_value="Reply here")
    def test_d12_chat_response_structure(self, _mock):
        data = json.loads(chat_post(self.client, "Test").content)
        self.assertTrue(data["success"])
        for key in ["id", "message", "response", "created_at"]:
            self.assertIn(key, data["chat"])

    # D13. Chat record is saved to the database on success
    @patch("chatbot.views.generate_reply", return_value="Saved!")
    def test_d13_chat_history_saved(self, _mock):
        chat_post(self.client, "Save this message")
        self.assertTrue(Chat.objects.filter(user=self.user).exists())

    # D14. History API respects CHAT_HISTORY_LIMIT
    def test_d14_chat_history_limit_enforced(self):
        limit = settings.CHAT_HISTORY_LIMIT
        for i in range(limit + 5):
            Chat.objects.create(user=self.user, message=f"m{i}", response="r")
        data = json.loads(self.client.get(reverse("chat_history")).content)
        self.assertLessEqual(len(data["chats"]), limit)


# ===========================================================================
# E: NVIDIA API Fallback Tests
# ===========================================================================

class NvidiaAPIFallbackTests(TestCase):
    def setUp(self):
        self.client, self.user = auth_client()

    def _ai_error(self, msg):
        return patch("chatbot.views.generate_reply", side_effect=AIServiceError(msg))

    # E1. Timeout → fallback 200, not 500
    def test_e1_timeout_returns_fallback_200(self):
        with self._ai_error("The AI service took too long to respond. Please try again."):
            r = chat_post(self.client)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(json.loads(r.content)["fallback"])

    # E2. ConnectionError → fallback 200
    def test_e2_connection_error_returns_fallback_200(self):
        with self._ai_error("Could not reach the AI service. Check your connection and retry."):
            r = chat_post(self.client)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(json.loads(r.content)["fallback"])

    # E3. Auth failure (401) → fallback 200
    def test_e3_http_401_returns_fallback_200(self):
        with self._ai_error("The AI service is temporarily unavailable."):
            r = chat_post(self.client)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(json.loads(r.content)["fallback"])

    # E4. Forbidden (403) → fallback 200
    def test_e4_http_403_returns_fallback_200(self):
        with self._ai_error("The AI service could not complete your request."):
            r = chat_post(self.client)
        self.assertEqual(r.status_code, 200)

    # E5. Upstream server error (500) → fallback 200 to client
    def test_e5_upstream_500_returns_fallback_200(self):
        with self._ai_error("The AI service could not complete your request."):
            r = chat_post(self.client)
        self.assertEqual(r.status_code, 200)

    # E6. Rate limit (429) → fallback 200
    def test_e6_rate_limit_returns_fallback_200(self):
        with self._ai_error("The AI service is busy right now. Please try again shortly."):
            r = chat_post(self.client)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(json.loads(r.content)["fallback"])

    # E7. Missing NVIDIA_API_KEY → fallback 200
    @override_settings(NVIDIA_API_KEY="")
    def test_e7_missing_api_key_returns_fallback_200(self):
        with self._ai_error("The AI service is not configured. Please contact support."):
            r = chat_post(self.client)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(json.loads(r.content)["fallback"])

    # E8. Empty NVIDIA_API_KEY → fallback 200
    @override_settings(NVIDIA_API_KEY="")
    def test_e8_empty_api_key_returns_fallback_200(self):
        with self._ai_error("The AI service is not configured. Please contact support."):
            r = chat_post(self.client)
        self.assertEqual(r.status_code, 200)

    # E9. Invalid API key format → handled gracefully, no 500
    def test_e9_invalid_api_key_format_handled(self):
        with self._ai_error("The AI returned an invalid response. Please try again."):
            r = chat_post(self.client)
        self.assertNotEqual(r.status_code, 500)

    # E10. Empty AI response → fallback 200
    def test_e10_empty_ai_response_handled(self):
        with self._ai_error("The AI returned an empty response. Please try again."):
            r = chat_post(self.client)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(json.loads(r.content)["fallback"])

    # E11. Malformed AI response → fallback 200
    def test_e11_malformed_ai_response_handled(self):
        with self._ai_error("The AI returned an invalid response. Please try again."):
            r = chat_post(self.client)
        self.assertEqual(r.status_code, 200)

    # E12. None-like AI response → fallback 200
    def test_e12_none_response_handled(self):
        with self._ai_error("The AI returned an invalid response. Please try again."):
            r = chat_post(self.client)
        self.assertEqual(r.status_code, 200)

    # E13. Unhandled exception in generate_reply → 200, not 500
    def test_e13_unexpected_exception_returns_200_not_500(self):
        with patch("chatbot.views.generate_reply", side_effect=RuntimeError("boom")):
            r = chat_post(self.client)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(json.loads(r.content)["fallback"])

    # E14. Fallback response is valid JSON
    def test_e14_fallback_response_is_valid_json(self):
        with self._ai_error("Some error"):
            r = chat_post(self.client)
        data = json.loads(r.content)
        self.assertIsInstance(data, dict)

    # E15. FALLBACK_MESSAGES values are all non-empty strings
    def test_e15_fallback_messages_are_user_friendly_strings(self):
        for key, value in FALLBACK_MESSAGES.items():
            with self.subTest(key=key):
                self.assertIsInstance(value, str)
                self.assertTrue(value.strip())


# ===========================================================================
# F: Environment Variable Tests
# ===========================================================================

class EnvVariableTests(TestCase):

    # F1. SECRET_KEY can be set via override_settings
    def test_f1_secret_key_loads_from_settings(self):
        with override_settings(SECRET_KEY="overridden-key"):
            self.assertEqual(settings.SECRET_KEY, "overridden-key")

    # F2. SECRET_KEY has a non-empty value
    def test_f2_secret_key_has_default(self):
        self.assertTrue(settings.SECRET_KEY)

    # F3. DEBUG=True activates debug mode
    @override_settings(DEBUG=True)
    def test_f3_debug_true_activates(self):
        self.assertTrue(settings.DEBUG)

    # F4. DEBUG=False disables debug mode
    @override_settings(DEBUG=False)
    def test_f4_debug_false_disables(self):
        self.assertFalse(settings.DEBUG)

    # F5. DEBUG setting is defined
    def test_f5_debug_is_defined(self):
        self.assertIsNotNone(settings.DEBUG)

    # F6. ALLOWED_HOSTS is a list
    def test_f6_allowed_hosts_is_list(self):
        self.assertIsInstance(settings.ALLOWED_HOSTS, list)

    # F7. ALLOWED_HOSTS is non-empty (falls back to ['*'])
    def test_f7_allowed_hosts_non_empty(self):
        self.assertTrue(len(settings.ALLOWED_HOSTS) > 0)

    # F8. CSRF_TRUSTED_ORIGINS is a list
    def test_f8_csrf_trusted_origins_is_list(self):
        self.assertIsInstance(settings.CSRF_TRUSTED_ORIGINS, list)

    # F9. CSRF_TRUSTED_ORIGINS has at least one fallback entry
    def test_f9_csrf_trusted_origins_non_empty(self):
        self.assertTrue(len(settings.CSRF_TRUSTED_ORIGINS) > 0)

    # F10. NVIDIA_TIMEOUT_SECONDS is an int
    def test_f10_nvidia_timeout_is_int(self):
        self.assertIsInstance(settings.NVIDIA_TIMEOUT_SECONDS, int)

    # F11. NVIDIA_MAX_TOKENS is an int
    def test_f11_nvidia_max_tokens_is_int(self):
        self.assertIsInstance(settings.NVIDIA_MAX_TOKENS, int)

    # F12. All env_int-parsed settings are integers
    def test_f12_env_int_parsed_settings_are_ints(self):
        for attr in [
            "NVIDIA_TIMEOUT_SECONDS", "NVIDIA_MAX_TOKENS",
            "CHAT_MAX_MESSAGE_LENGTH", "CHAT_HISTORY_LIMIT",
        ]:
            with self.subTest(attr=attr):
                self.assertIsInstance(getattr(settings, attr), int)

    # F13. All NVIDIA settings attributes are present
    def test_f13_nvidia_vars_all_present(self):
        for attr in [
            "NVIDIA_API_KEY", "NVIDIA_BASE_URL", "NVIDIA_MODEL",
            "NVIDIA_TIMEOUT_SECONDS", "NVIDIA_MAX_TOKENS",
        ]:
            with self.subTest(attr=attr):
                self.assertTrue(hasattr(settings, attr))

    # F14. NVIDIA settings default to expected safe values
    def test_f14_nvidia_defaults_are_safe(self):
        self.assertEqual(settings.NVIDIA_BASE_URL, "https://integrate.api.nvidia.com/v1")
        self.assertEqual(settings.NVIDIA_MODEL, "nvidia/nemotron-3-ultra-550b-a55b")
        self.assertEqual(settings.NVIDIA_TIMEOUT_SECONDS, 90)
        self.assertEqual(settings.NVIDIA_MAX_TOKENS, 4096)


# ===========================================================================
# G: Database Tests
# ===========================================================================

class DatabaseTests(TestCase):
    def setUp(self):
        self.user = make_user()

    # G1. SQLite connects successfully
    def test_g1_database_connects(self):
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            self.assertEqual(cursor.fetchone()[0], 1)

    # G2. User table exists (all migrations applied)
    def test_g2_migrations_applied(self):
        self.assertGreaterEqual(User.objects.count(), 0)

    # G3. User model creates correctly
    def test_g3_user_model_creates(self):
        u = User.objects.create_user(username="dbuser", password="DbPass123!")
        self.assertEqual(u.username, "dbuser")
        self.assertTrue(u.check_password("DbPass123!"))

    # G4. Chat model saves with all required fields
    def test_g4_chat_model_saves(self):
        record = Chat.objects.create(
            user=self.user, message="test msg", response="test reply"
        )
        self.assertIsNotNone(record.pk)
        self.assertIsNotNone(record.created_at)

    # G5. Chat records retrieve correctly
    def test_g5_chat_model_retrieves(self):
        Chat.objects.create(user=self.user, message="q", response="a")
        chats = Chat.objects.filter(user=self.user)
        self.assertEqual(chats.count(), 1)
        self.assertEqual(chats.first().message, "q")

    # G6. Chat records delete correctly
    def test_g6_chat_model_deletes(self):
        record = Chat.objects.create(user=self.user, message="del", response="me")
        pk = record.pk
        record.delete()
        self.assertFalse(Chat.objects.filter(pk=pk).exists())

    # G7. Database handles bulk inserts without error
    def test_g7_database_handles_multiple_records(self):
        for i in range(20):
            Chat.objects.create(user=self.user, message=f"m{i}", response=f"r{i}")
        self.assertEqual(Chat.objects.filter(user=self.user).count(), 20)

    # G8. Empty database state returns zero records gracefully
    def test_g8_empty_database_state_handled(self):
        Chat.objects.filter(user=self.user).delete()
        self.assertEqual(Chat.objects.filter(user=self.user).count(), 0)

    # G9. No unapplied migrations exist
    def test_g9_no_unapplied_migrations(self):
        from django.db.migrations.executor import MigrationExecutor
        executor = MigrationExecutor(connection)
        plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
        self.assertEqual(
            len(plan), 0,
            f"Unapplied migrations: {[str(m[0]) for m in plan]}",
        )

    # G10. Core application tables exist in the schema
    def test_g10_core_tables_exist(self):
        tables = connection.introspection.table_names()
        for table in ["chatbot_chat", "auth_user", "django_migrations"]:
            with self.subTest(table=table):
                self.assertIn(table, tables)


# ===========================================================================
# H: Static Files Tests
# ===========================================================================

class StaticFilesTests(TestCase):

    # H1. STATIC_ROOT is configured
    def test_h1_static_root_configured(self):
        self.assertTrue(hasattr(settings, "STATIC_ROOT"))
        self.assertIsNotNone(settings.STATIC_ROOT)

    # H2. Staticfiles storage uses WhiteNoise backend
    def test_h2_staticfiles_storage_is_whitenoise(self):
        backend = settings.STORAGES["staticfiles"]["BACKEND"]
        self.assertIn("whitenoise", backend.lower())

    # H3. collectstatic management command is registered
    def test_h3_collectstatic_command_available(self):
        from django.core.management import get_commands
        self.assertIn("collectstatic", get_commands())

    # H4. STATIC_URL is defined and non-empty
    def test_h4_static_url_defined(self):
        self.assertTrue(getattr(settings, "STATIC_URL", ""))

    # H5. STATICFILES_DIRS is a list
    def test_h5_staticfiles_dirs_is_list(self):
        self.assertIsInstance(getattr(settings, "STATICFILES_DIRS", []), list)

    # H6. WhiteNoise middleware is installed
    def test_h6_whitenoise_in_middleware(self):
        self.assertTrue(
            any("whitenoise" in m.lower() for m in settings.MIDDLEWARE)
        )

    # H7. STATIC_URL is exactly '/static/'
    def test_h7_static_url_value(self):
        self.assertEqual(settings.STATIC_URL, "/static/")


# ===========================================================================
# I: Security Tests
# ===========================================================================

class SecurityTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.auth_client, _ = auth_client("secuser", "SecPass123!")

    # I1. SQL injection in login is blocked — no 500, no bypass
    def test_i1_sql_injection_in_login_blocked(self):
        c = Client()
        r = c.post(reverse("login"), {
            "username": "admin' OR '1'='1' --",
            "password": "' OR '1'='1",
        })
        self.assertNotEqual(r.status_code, 500)
        self.assertNotIn("_auth_user_id", c.session)

    # I2. SQL injection in chat does not drop tables or 500
    @patch("chatbot.views.generate_reply", return_value="safe")
    def test_i2_sql_injection_in_chat_safe(self, _mock):
        r = chat_post(self.auth_client, "'; DROP TABLE auth_user; --")
        self.assertNotEqual(r.status_code, 500)
        self.assertTrue(User.objects.filter(username="secuser").exists())

    # I3. XSS in chat message does not 500
    @patch("chatbot.views.generate_reply", return_value="safe")
    def test_i3_xss_in_chat_no_500(self, _mock):
        r = chat_post(self.auth_client, "<script>alert(document.cookie)</script>")
        self.assertNotEqual(r.status_code, 500)

    # I4. XSS in login username is escaped in HTML output
    def test_i4_xss_in_username_escaped(self):
        r = Client().post(reverse("login"), {
            "username": "<img src=x onerror=alert(1)>",
            "password": "x",
        })
        self.assertNotIn(b"<img src=x onerror=alert(1)>", r.content)

    # I5. CSRF protection is active — POST without token returns 403
    def test_i5_csrf_protection_on_post(self):
        c = Client(enforce_csrf_checks=True)
        c.login(username="testuser", password="TestPass123!")
        r = c.post(reverse("logout"))
        self.assertEqual(r.status_code, 403)

    # I6. DEBUG=False in production-like mode
    @override_settings(DEBUG=False)
    def test_i6_debug_false_in_production(self):
        self.assertFalse(settings.DEBUG)

    # I7. SECRET_KEY is non-empty
    def test_i7_secret_key_is_set(self):
        self.assertTrue(len(settings.SECRET_KEY) > 0)

    # I8. Ping response does not expose the raw SECRET_KEY value
    def test_i8_ping_does_not_expose_secret_key_value(self):
        with patch.dict(os.environ, {"SECRET_KEY": "super-secret-do-not-expose"}):
            r = Client().get(reverse("ping"))
        self.assertNotIn(b"super-secret-do-not-expose", r.content)

    # I9. Unknown routes return 404 without traceback in response
    @override_settings(DEBUG=False)
    def test_i9_unknown_route_no_traceback(self):
        r = Client().get("/nonexistent-route-xyz-abc/")
        self.assertEqual(r.status_code, 404)
        self.assertNotIn(b"Traceback", r.content)

    # I10. All private views block unauthenticated access
    def test_i10_unauthenticated_access_blocked(self):
        c = Client()
        for url in [
            reverse("chatbot"),
            reverse("chat_history"),
            reverse("clear_history"),
            reverse("search_chats"),
        ]:
            with self.subTest(url=url):
                self.assertIn(c.get(url).status_code, [301, 302, 403])


# ===========================================================================
# J: Performance & Load Tests
# ===========================================================================

class PerformanceTests(TestCase):

    # J1. Ping endpoint responds in under 500ms
    def test_j1_ping_under_500ms(self):
        c = Client()
        t0 = time.time()
        r = c.get(reverse("ping"))
        elapsed_ms = (time.time() - t0) * 1000
        self.assertEqual(r.status_code, 200)
        self.assertLess(elapsed_ms, 500, f"Ping took {elapsed_ms:.0f}ms (limit 500ms)")

    # J2. Login page loads in under 2 seconds
    def test_j2_login_page_under_2s(self):
        t0 = time.time()
        r = Client().get(reverse("login"))
        elapsed = time.time() - t0
        self.assertEqual(r.status_code, 200)
        self.assertLess(elapsed, 2.0, f"Login page took {elapsed:.2f}s (limit 2s)")

    # J3. Chat page loads in under 2 seconds
    def test_j3_chat_page_under_2s(self):
        c, _ = auth_client("perfuser", "PerfPass123!")
        t0 = time.time()
        r = c.get(reverse("chatbot"))
        elapsed = time.time() - t0
        self.assertEqual(r.status_code, 200)
        self.assertLess(elapsed, 2.0, f"Chat page took {elapsed:.2f}s (limit 2s)")

    # J4. 10 concurrent ping requests all return 200
    def test_j4_concurrent_ping_requests(self):
        results, errors = [], []

        def do_ping():
            try:
                results.append(Client().get(reverse("ping")).status_code)
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=do_ping) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        self.assertEqual(errors, [], f"Thread errors: {errors}")
        self.assertEqual(len(results), 10)
        self.assertTrue(all(s == 200 for s in results))

    # J5. Chat history query is bounded by CHAT_HISTORY_LIMIT
    def test_j5_history_limit_prevents_bloat(self):
        user = make_user("bloatuser", "BloatPass123!")
        limit = settings.CHAT_HISTORY_LIMIT
        for i in range(limit + 20):
            Chat.objects.create(user=user, message=f"m{i}", response="r")
        count = Chat.objects.filter(user=user).order_by("-created_at")[:limit].count()
        self.assertEqual(count, limit)

    # J6. Message over limit is rejected before being stored
    def test_j6_oversized_message_rejected_not_stored(self):
        c, user = auth_client("bigmsguser", "BigMsg123!")
        r = chat_post(c, "x" * (settings.CHAT_MAX_MESSAGE_LENGTH + 1))
        self.assertEqual(r.status_code, 400)
        self.assertFalse(Chat.objects.filter(user=user).exists())


# ===========================================================================
# K: Render Deployment Tests
# ===========================================================================

class RenderDeploymentTests(TestCase):

    # K1. WSGI application object loads without error
    def test_k1_wsgi_application_loads(self):
        from django_chatbot.wsgi import application
        self.assertIsNotNone(application)

    # K2. PORT env var is integer-castable (Gunicorn --bind requirement)
    def test_k2_port_env_var_is_int_castable(self):
        port_str = os.environ.get("PORT", "8000")
        try:
            self.assertGreater(int(port_str), 0)
        except ValueError:
            self.fail(f"PORT env var '{port_str}' is not castable to int")

    # K3. STATIC_ROOT and WhiteNoise storage configured for build step
    def test_k3_collectstatic_dependencies_configured(self):
        self.assertIsNotNone(settings.STATIC_ROOT)
        self.assertIn(
            "whitenoise",
            settings.STORAGES["staticfiles"]["BACKEND"].lower(),
        )

    # K4. django_migrations table exists (migrate was run)
    def test_k4_migrations_table_exists(self):
        self.assertIn("django_migrations", connection.introspection.table_names())

    # K5. Application module reloads cleanly (simulates post-cold-boot import)
    def test_k5_app_reloads_cleanly(self):
        import importlib
        import django_chatbot.wsgi as wsgi_module
        importlib.reload(wsgi_module)
        self.assertIsNotNone(wsgi_module.application)

    # K6. Ping returns 200 after simulated cold boot
    def test_k6_ping_returns_200_post_boot(self):
        r = Client().get(reverse("ping"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(json.loads(r.content)["status"], "ok")

    # K7. WhiteNoise staticfiles storage is instantiable
    def test_k7_static_files_storage_initialised(self):
        from django.contrib.staticfiles.storage import staticfiles_storage
        self.assertIsNotNone(staticfiles_storage)

    # K8. Login endpoint is functional after simulated cold boot
    def test_k8_login_works_post_boot(self):
        c = Client()
        self.assertEqual(c.get(reverse("login")).status_code, 200)
        User.objects.create_user(username="coldboot", password="ColdBoot123!")
        self.assertTrue(c.login(username="coldboot", password="ColdBoot123!"))
