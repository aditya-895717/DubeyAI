import datetime
import json
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import AIProvider, Command, PushSubscription, Reminder, SiteSettings
from core.push import send_push_notification
from core.services import (
    AIProviderError,
    AIProviderService,
    classify_intent,
    get_active_ai_client,
    parse_target_time,
)


def make_provider(name="Test Provider", is_active=True):
    return AIProvider.objects.create(
        name=name,
        api_key="test-key-123",
        endpoint_url="https://example.test/v1",
        model_name="test-model",
        is_active=is_active,
    )


class AIProviderServiceTests(TestCase):
    def test_raises_when_no_active_provider(self):
        AIProvider.objects.all().delete()
        with self.assertRaises(AIProviderError):
            AIProviderService()

    def test_uses_the_active_provider_not_an_inactive_one(self):
        make_provider(name="Inactive", is_active=False)
        active = make_provider(name="Active", is_active=True)
        service = AIProviderService()
        self.assertEqual(service.provider.id, active.id)

    @patch("core.services.OpenAI")
    def test_get_response_strips_reasoning_blocks(self, mock_openai_cls):
        make_provider()
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        completion = MagicMock()
        completion.choices[0].message.content = "<think>secret chain of thought</think>Final answer"
        mock_client.chat.completions.create.return_value = completion

        reply = AIProviderService().get_response("Hello")
        self.assertEqual(reply, "Final answer")

    @patch("core.services.OpenAI")
    def test_empty_reply_raises_ai_provider_error(self, mock_openai_cls):
        make_provider()
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        completion = MagicMock()
        completion.choices[0].message.content = ""
        mock_client.chat.completions.create.return_value = completion

        with self.assertRaises(AIProviderError):
            AIProviderService().get_response("Hello")

    @patch("core.services.OpenAI")
    def test_malformed_response_raises_ai_provider_error(self, mock_openai_cls):
        make_provider()
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        completion = MagicMock()
        completion.choices = []  # triggers IndexError internally
        mock_client.chat.completions.create.return_value = completion

        with self.assertRaises(AIProviderError):
            AIProviderService().get_response("Hello")

    @patch("core.services.OpenAI")
    def test_client_is_configured_from_the_active_provider_row(self, mock_openai_cls):
        provider = make_provider()
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        completion = MagicMock()
        completion.choices[0].message.content = "ok"
        mock_client.chat.completions.create.return_value = completion

        AIProviderService().get_response("Hello")

        _, kwargs = mock_openai_cls.call_args
        self.assertEqual(kwargs["base_url"], provider.endpoint_url)
        self.assertEqual(kwargs["api_key"], provider.api_key)
        create_kwargs = mock_client.chat.completions.create.call_args.kwargs
        self.assertEqual(create_kwargs["model"], provider.model_name)


class IntentEngineTests(TestCase):
    def test_known_app_keyword_matches_directly(self):
        result = classify_intent("open whatsapp")
        self.assertEqual(result, {"intent": "open_app", "entities": {"app": "whatsapp"}})

    def test_hinglish_open_keyword_matches_known_app(self):
        result = classify_intent("khol do facebook")
        self.assertEqual(result["intent"], "open_app")
        self.assertEqual(result["entities"]["app"], "facebook")

    def test_plain_query_has_no_keyword_overlap(self):
        result = classify_intent("What is the capital of France?")
        self.assertEqual(result, {"intent": "query", "entities": {}})

    def test_alarm_keyword_with_parseable_time(self):
        result = classify_intent("kal 9 baje uthana")
        self.assertEqual(result["intent"], "set_alarm")
        self.assertIsInstance(result["entities"]["target_time"], datetime.datetime)

    def test_alarm_keyword_without_parseable_time_falls_back_to_query(self):
        result = classify_intent("remind me about that thing we discussed")
        self.assertEqual(result["intent"], "query")

    def test_open_app_keyword_with_unknown_app_and_no_provider_falls_back_to_query(self):
        AIProvider.objects.all().delete()
        result = classify_intent("please open my special app")
        self.assertEqual(result["intent"], "query")


class TimeParsingTests(TestCase):
    def setUp(self):
        self.now = timezone.make_aware(datetime.datetime(2026, 7, 31, 10, 0, 0))

    def test_kal_9_baje_resolves_to_tomorrow_9am(self):
        result = parse_target_time("kal 9 baje uthana", now=self.now)
        self.assertIsNotNone(result)
        self.assertEqual(result.date(), (self.now + datetime.timedelta(days=1)).date())
        self.assertEqual(result.hour, 9)

    def test_abhi_se_2_ghante_baad_resolves_to_now_plus_2h(self):
        result = parse_target_time("abhi se 2 ghante baad", now=self.now)
        self.assertIsNotNone(result)
        self.assertEqual(result, self.now + datetime.timedelta(hours=2))

    def test_no_recognisable_time_returns_none(self):
        result = parse_target_time("this has no time information at all", now=self.now)
        self.assertIsNone(result)


@override_settings(ALLOWED_HOSTS=["testserver"])
class PWATests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("pwauser", password="PwaPass123!")

    # --- manifest.json -----------------------------------------------------

    def test_manifest_reflects_site_settings(self):
        site = SiteSettings.load()
        site.site_name = "MyAssistant"
        site.primary_color = "#111111"
        site.secondary_color = "#222222"
        site.save()

        response = self.client.get(reverse("manifest_json"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/manifest+json")
        data = response.json()
        self.assertEqual(data["name"], "MyAssistant")
        self.assertEqual(data["theme_color"], "#111111")
        self.assertEqual(data["background_color"], "#222222")
        self.assertEqual(data["display"], "standalone")
        self.assertEqual(data["start_url"], "/")
        sizes = {icon["sizes"] for icon in data["icons"]}
        self.assertEqual(sizes, {"192x192", "512x512"})

    # --- service-worker.js ---------------------------------------------------

    def test_service_worker_served_at_root_with_correct_headers(self):
        response = self.client.get(reverse("service_worker"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/javascript")
        self.assertEqual(response["Service-Worker-Allowed"], "/")
        self.assertIn(b"addEventListener(\"push\"", response.content)
        self.assertIn(b"addEventListener(\"notificationclick\"", response.content)

    # --- offline fallback page ----------------------------------------------

    def test_offline_page_loads_without_auth(self):
        response = self.client.get(reverse("offline_page"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "You're offline")

    # --- push subscription endpoint ------------------------------------------

    def test_push_subscribe_requires_login(self):
        response = self.client.post(
            reverse("push_subscribe"),
            data=json.dumps({"endpoint": "https://example.test/ep", "keys": {"p256dh": "a", "auth": "b"}}),
            content_type="application/json",
        )
        self.assertIn(response.status_code, [301, 302])

    def test_push_subscribe_saves_subscription(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("push_subscribe"),
            data=json.dumps({"endpoint": "https://example.test/ep1", "keys": {"p256dh": "abc", "auth": "def"}}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        sub = PushSubscription.objects.get(endpoint="https://example.test/ep1")
        self.assertEqual(sub.user, self.user)
        self.assertEqual(sub.p256dh_key, "abc")

    def test_push_subscribe_missing_fields_is_bad_request(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("push_subscribe"),
            data=json.dumps({"endpoint": "https://example.test/ep2"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_push_subscribe_updates_existing_endpoint_not_duplicates(self):
        self.client.force_login(self.user)
        payload = {"endpoint": "https://example.test/ep3", "keys": {"p256dh": "a", "auth": "b"}}
        self.client.post(reverse("push_subscribe"), data=json.dumps(payload), content_type="application/json")
        payload["keys"]["p256dh"] = "updated"
        self.client.post(reverse("push_subscribe"), data=json.dumps(payload), content_type="application/json")
        self.assertEqual(PushSubscription.objects.filter(endpoint="https://example.test/ep3").count(), 1)
        self.assertEqual(
            PushSubscription.objects.get(endpoint="https://example.test/ep3").p256dh_key, "updated"
        )


class SendPushNotificationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("pushrecipient", password="PushPass123!")

    @override_settings(VAPID_PRIVATE_KEY="")
    def test_returns_zero_when_vapid_not_configured(self):
        PushSubscription.objects.create(
            user=self.user, endpoint="https://example.test/x", p256dh_key="a", auth_key="b"
        )
        self.assertEqual(send_push_notification(self.user, "Hi", "there"), 0)

    @override_settings(VAPID_PRIVATE_KEY="test-private-key", VAPID_CLAIM_EMAIL="admin@example.com")
    @patch("core.push.webpush")
    def test_sends_to_every_subscription(self, mock_webpush):
        PushSubscription.objects.create(
            user=self.user, endpoint="https://example.test/x1", p256dh_key="a1", auth_key="b1"
        )
        PushSubscription.objects.create(
            user=self.user, endpoint="https://example.test/x2", p256dh_key="a2", auth_key="b2"
        )
        sent = send_push_notification(self.user, "Reminder", "Time's up")
        self.assertEqual(sent, 2)
        self.assertEqual(mock_webpush.call_count, 2)

    @override_settings(VAPID_PRIVATE_KEY="test-private-key", VAPID_CLAIM_EMAIL="admin@example.com")
    @patch("core.push.webpush")
    def test_expired_subscription_is_deleted(self, mock_webpush):
        from pywebpush import WebPushException

        sub = PushSubscription.objects.create(
            user=self.user, endpoint="https://example.test/gone", p256dh_key="a", auth_key="b"
        )
        response = MagicMock(status_code=410)
        mock_webpush.side_effect = WebPushException("gone", response=response)

        sent = send_push_notification(self.user, "Hi", "there")
        self.assertEqual(sent, 0)
        self.assertFalse(PushSubscription.objects.filter(pk=sub.pk).exists())


@override_settings(ALLOWED_HOSTS=["testserver"], COMPANION_API_KEY="test-companion-key")
class CompanionAPITests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("companionuser", password="CompanionPass123!")
        self.headers = {"HTTP_X_DUBEYAI_KEY": "test-companion-key"}

    # --- auth ---------------------------------------------------------------

    def test_missing_key_is_rejected(self):
        response = self.client.get(reverse("pending_commands"))
        self.assertEqual(response.status_code, 401)

    def test_wrong_key_is_rejected(self):
        response = self.client.get(reverse("pending_commands"), HTTP_X_DUBEYAI_KEY="wrong")
        self.assertEqual(response.status_code, 401)

    @override_settings(COMPANION_API_KEY="")
    def test_unconfigured_key_rejects_everything(self):
        response = self.client.get(reverse("pending_commands"), HTTP_X_DUBEYAI_KEY="")
        self.assertEqual(response.status_code, 401)

    # --- pending-commands -----------------------------------------------------

    def test_pending_commands_lists_only_pending(self):
        pending = Command.objects.create(
            user=self.user, command_type=Command.CommandType.OPEN_APP, target="whatsapp"
        )
        Command.objects.create(
            user=self.user,
            command_type=Command.CommandType.OPEN_APP,
            target="notepad",
            status=Command.Status.EXECUTED,
        )
        response = self.client.get(reverse("pending_commands"), **self.headers)
        self.assertEqual(response.status_code, 200)
        ids = [c["id"] for c in response.json()["commands"]]
        self.assertIn(pending.id, ids)
        self.assertEqual(len(ids), 1)

    # --- pending-reminders ------------------------------------------------------

    def test_pending_reminders_lists_only_pending(self):
        pending = Reminder.objects.create(
            user=self.user, raw_text="wake me up", target_time=timezone.now() + datetime.timedelta(minutes=5)
        )
        Reminder.objects.create(
            user=self.user,
            raw_text="already done",
            target_time=timezone.now(),
            status=Reminder.Status.COMPLETED,
        )
        response = self.client.get(reverse("pending_reminders"), **self.headers)
        self.assertEqual(response.status_code, 200)
        ids = [r["id"] for r in response.json()["reminders"]]
        self.assertIn(pending.id, ids)
        self.assertEqual(len(ids), 1)

    # --- mark-command-done ----------------------------------------------------

    def test_mark_command_done_updates_status(self):
        command = Command.objects.create(
            user=self.user, command_type=Command.CommandType.OPEN_APP, target="whatsapp"
        )
        response = self.client.post(reverse("mark_command_done", args=[command.id]), **self.headers)
        self.assertEqual(response.status_code, 200)
        command.refresh_from_db()
        self.assertEqual(command.status, Command.Status.EXECUTED)

    def test_mark_command_done_requires_post(self):
        command = Command.objects.create(
            user=self.user, command_type=Command.CommandType.OPEN_APP, target="whatsapp"
        )
        response = self.client.get(reverse("mark_command_done", args=[command.id]), **self.headers)
        self.assertEqual(response.status_code, 405)

    # --- mark-reminder-done -----------------------------------------------------

    def test_mark_reminder_done_updates_status(self):
        reminder = Reminder.objects.create(
            user=self.user, raw_text="wake me up", target_time=timezone.now()
        )
        response = self.client.post(reverse("mark_reminder_done", args=[reminder.id]), **self.headers)
        self.assertEqual(response.status_code, 200)
        reminder.refresh_from_db()
        self.assertEqual(reminder.status, Reminder.Status.COMPLETED)
