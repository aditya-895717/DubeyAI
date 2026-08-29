"""Tests for Cloudinary-backed media storage.

Cloudinary is fully mocked here so the suite runs with no credentials — local
development must never require production keys. A real authorized integration
check is done separately against a live deployment.

Run:
    python manage.py test chatbot.test_cloudinary --verbosity=2
"""

import io
import shutil
import tempfile
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from chatbot.models import UploadedDocument
from chatbot.test_uploads_voice import make_docx, make_pdf_bytes
from core import storage as cloudinary_storage

MEDIA_ROOT = tempfile.mkdtemp(prefix="dubeyai-cloudinary-test-")

CLOUDINARY_ON = {
    "CLOUDINARY_ENABLED": True,
    "CLOUDINARY_CLOUD_NAME": "test-cloud",
    "CLOUDINARY_API_KEY": "test-key",
    "CLOUDINARY_API_SECRET": "test-secret",
    "CLOUDINARY_FOLDER": "dubeyai-test",
}


def fake_asset(public_id="dubeyai-test/user_1/report_abc123", resource_type="raw"):
    return {
        "public_id": public_id,
        "resource_type": resource_type,
        "url": f"https://res.cloudinary.com/test-cloud/{resource_type}/upload/v17/{public_id}",
        "version": "17",
        "bytes": 1234,
    }


class ResourceTypeTests(TestCase):
    """Cloudinary resource types are not interchangeable — verify the mapping."""

    def test_documents_are_raw(self):
        for name in ("report.pdf", "brief.docx", "notes.txt"):
            with self.subTest(name=name):
                self.assertEqual(cloudinary_storage.resource_type_for(name), "raw")

    def test_images_are_image(self):
        for name in ("photo.png", "photo.jpg", "photo.JPEG", "art.webp"):
            with self.subTest(name=name):
                self.assertEqual(cloudinary_storage.resource_type_for(name), "image")

    def test_videos_are_video(self):
        for name in ("clip.mp4", "clip.mov", "clip.webm"):
            with self.subTest(name=name):
                self.assertEqual(cloudinary_storage.resource_type_for(name), "video")

    def test_unknown_extension_defaults_to_raw(self):
        # Defaulting to raw is the safe choice: Cloudinary will not try to
        # transform it, and it is always retrievable.
        self.assertEqual(cloudinary_storage.resource_type_for("mystery.bin"), "raw")
        self.assertEqual(cloudinary_storage.resource_type_for("noextension"), "raw")

    @override_settings(**CLOUDINARY_ON)
    def test_is_enabled_true_when_configured(self):
        self.assertTrue(cloudinary_storage.is_enabled())

    @override_settings(CLOUDINARY_ENABLED=False)
    def test_is_enabled_false_without_credentials(self):
        self.assertFalse(cloudinary_storage.is_enabled())


@override_settings(**CLOUDINARY_ON)
class StorageModuleTests(TestCase):

    @patch("cloudinary.uploader.upload")
    def test_upload_returns_metadata(self, mock_upload):
        mock_upload.return_value = {
            "public_id": "dubeyai-test/user_5/report_x",
            "resource_type": "raw",
            "secure_url": "https://res.cloudinary.com/test-cloud/raw/upload/v9/report_x",
            "version": 9,
            "bytes": 4096,
        }
        result = cloudinary_storage.upload(io.BytesIO(b"data"), "report.pdf", owner_id=5)

        self.assertEqual(result["public_id"], "dubeyai-test/user_5/report_x")
        self.assertEqual(result["resource_type"], "raw")
        self.assertTrue(result["url"].startswith("https://"))
        self.assertEqual(result["version"], "9")

    @patch("cloudinary.uploader.upload")
    def test_upload_namespaces_by_user(self, mock_upload):
        mock_upload.return_value = {"public_id": "x", "resource_type": "raw", "version": 1}
        cloudinary_storage.upload(io.BytesIO(b"data"), "a.pdf", owner_id=42)
        self.assertEqual(mock_upload.call_args.kwargs["folder"], "dubeyai-test/user_42")

    @patch("cloudinary.uploader.upload")
    def test_upload_sends_correct_resource_type_for_image(self, mock_upload):
        mock_upload.return_value = {"public_id": "x", "resource_type": "image", "version": 1}
        cloudinary_storage.upload(io.BytesIO(b"data"), "photo.png", owner_id=1)
        self.assertEqual(mock_upload.call_args.kwargs["resource_type"], "image")

    @patch("cloudinary.uploader.upload", side_effect=RuntimeError("network down"))
    def test_upload_failure_raises_safe_error(self, _mock):
        with self.assertRaises(cloudinary_storage.CloudinaryError) as ctx:
            cloudinary_storage.upload(io.BytesIO(b"data"), "a.pdf", owner_id=1)
        # The user-facing message must not leak the underlying exception.
        self.assertNotIn("network down", str(ctx.exception))

    @patch("cloudinary.uploader.upload", return_value={"resource_type": "raw"})
    def test_upload_without_public_id_is_a_failure(self, _mock):
        with self.assertRaises(cloudinary_storage.CloudinaryError):
            cloudinary_storage.upload(io.BytesIO(b"data"), "a.pdf", owner_id=1)

    @patch("cloudinary.uploader.destroy", return_value={"result": "ok"})
    def test_delete_success(self, mock_destroy):
        self.assertTrue(cloudinary_storage.delete("folder/asset", "raw"))
        self.assertEqual(mock_destroy.call_args.kwargs["resource_type"], "raw")

    @patch("cloudinary.uploader.destroy", return_value={"result": "not found"})
    def test_delete_already_gone_is_success(self, _mock):
        # Idempotent: an asset that is already gone is the desired end state.
        self.assertTrue(cloudinary_storage.delete("folder/asset", "raw"))

    @patch("cloudinary.uploader.destroy", side_effect=RuntimeError("boom"))
    def test_delete_never_raises(self, _mock):
        # Deletion runs during user-facing cleanup — an outage must not 500.
        self.assertFalse(cloudinary_storage.delete("folder/asset", "raw"))

    def test_delete_without_public_id_is_noop(self):
        self.assertFalse(cloudinary_storage.delete("", "raw"))


@override_settings(MEDIA_ROOT=MEDIA_ROOT, **CLOUDINARY_ON)
class UploadEndpointCloudinaryTests(TestCase):
    """The upload endpoint must route binaries to Cloudinary, text to the DB."""

    def setUp(self):
        self.user = User.objects.create_user("cloud-user", password="strong-pass-123")
        self.client = Client()
        self.client.login(username="cloud-user", password="strong-pass-123")
        self.url = reverse("upload_document")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()

    @patch("core.storage.upload")
    def test_pdf_goes_to_cloudinary_and_text_to_database(self, mock_upload):
        mock_upload.return_value = fake_asset()
        upload = SimpleUploadedFile("report.pdf", make_pdf_bytes(), content_type="application/pdf")

        response = self.client.post(self.url, {"file": upload})
        self.assertEqual(response.status_code, 200)

        document = UploadedDocument.objects.get(pk=response.json()["document"]["id"])
        # Binary metadata in Postgres, binary itself in Cloudinary.
        self.assertEqual(document.cloudinary_public_id, fake_asset()["public_id"])
        self.assertEqual(document.cloudinary_resource_type, "raw")
        self.assertTrue(document.cloudinary_url.startswith("https://"))
        self.assertEqual(document.status, UploadedDocument.Status.READY)
        # Extracted text still lands in the database.
        self.assertIn("42 crore", document.extracted_text)
        # Nothing written to the local filesystem in production mode.
        self.assertFalse(document.file)

    @patch("core.storage.upload")
    def test_docx_extraction_still_works_through_cloudinary(self, mock_upload):
        mock_upload.return_value = fake_asset(resource_type="raw")
        buffer = make_docx()
        upload = SimpleUploadedFile(
            "brief.docx",
            buffer.read(),
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        response = self.client.post(self.url, {"file": upload})
        self.assertEqual(response.status_code, 200)

        document = UploadedDocument.objects.get(pk=response.json()["document"]["id"])
        self.assertIn("Project Falcon", document.extracted_text)
        self.assertTrue(document.stored_in_cloudinary)

    @patch("core.storage.upload")
    def test_image_uses_image_resource_type(self, mock_upload):
        mock_upload.return_value = fake_asset(resource_type="image")
        upload = SimpleUploadedFile("photo.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 50, content_type="image/png")

        # OCR is unavailable, so this fails extraction — but the binary is still
        # stored, and the failure must be graceful rather than a 500.
        response = self.client.post(self.url, {"file": upload})
        self.assertEqual(response.status_code, 400)
        self.assertIn("OCR", response.json()["error"])

        document = UploadedDocument.objects.latest("uploaded_at")
        self.assertEqual(document.status, UploadedDocument.Status.FAILED)
        self.assertTrue(document.stored_in_cloudinary)

    @patch("core.storage.upload", side_effect=cloudinary_storage.CloudinaryError("Storage unavailable."))
    def test_cloudinary_failure_creates_no_document(self, _mock):
        upload = SimpleUploadedFile("report.pdf", make_pdf_bytes(), content_type="application/pdf")
        response = self.client.post(self.url, {"file": upload})

        self.assertEqual(response.status_code, 502)
        # No half-stored row: nothing was persisted, so nothing to clean up.
        self.assertEqual(UploadedDocument.objects.count(), 0)

    @patch("core.storage.upload")
    def test_response_exposes_cloudinary_url_not_media_path(self, mock_upload):
        mock_upload.return_value = fake_asset()
        upload = SimpleUploadedFile("report.pdf", make_pdf_bytes(), content_type="application/pdf")
        payload = self.client.post(self.url, {"file": upload}).json()["document"]

        self.assertEqual(payload["storage"], "cloudinary")
        self.assertTrue(payload["url"].startswith("https://res.cloudinary.com/"))
        self.assertNotIn("/media/", payload["url"])


@override_settings(MEDIA_ROOT=MEDIA_ROOT, CLOUDINARY_ENABLED=False)
class LocalFallbackTests(TestCase):
    """With no credentials the app must still work — that is local dev and CI."""

    def setUp(self):
        self.user = User.objects.create_user("local-user", password="strong-pass-123")
        self.client = Client()
        self.client.login(username="local-user", password="strong-pass-123")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()

    def test_upload_falls_back_to_local_storage(self):
        upload = SimpleUploadedFile("notes.txt", b"Local dev still works.", content_type="text/plain")
        response = self.client.post(reverse("upload_document"), {"file": upload})

        self.assertEqual(response.status_code, 200)
        document = UploadedDocument.objects.get(pk=response.json()["document"]["id"])
        self.assertTrue(document.file)
        self.assertEqual(document.cloudinary_public_id, "")
        self.assertIn("Local dev still works.", document.extracted_text)
        self.assertEqual(response.json()["document"]["storage"], "local")


@override_settings(MEDIA_ROOT=MEDIA_ROOT, **CLOUDINARY_ON)
class DocumentDeletionTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("owner", password="strong-pass-123")
        self.other = User.objects.create_user("attacker", password="strong-pass-123")
        self.client = Client()
        self.client.login(username="owner", password="strong-pass-123")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()

    def make_document(self, user=None, public_id="dubeyai-test/user_1/doc_a"):
        return UploadedDocument.objects.create(
            user=user or self.user,
            filename="report.pdf",
            extracted_text="content",
            status=UploadedDocument.Status.READY,
            cloudinary_public_id=public_id,
            cloudinary_resource_type="raw",
            cloudinary_url=f"https://res.cloudinary.com/test-cloud/raw/upload/{public_id}",
        )

    @patch("core.storage.delete", return_value=True)
    def test_removal_deletes_cloudinary_asset(self, mock_delete):
        document = self.make_document()
        response = self.client.post(reverse("remove_document", args=[document.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["asset_deleted"])
        mock_delete.assert_called_once_with("dubeyai-test/user_1/doc_a", "raw")

        document.refresh_from_db()
        self.assertFalse(document.is_active)
        self.assertEqual(document.cloudinary_public_id, "")

    @patch("core.storage.delete", return_value=False)
    def test_cloudinary_outage_still_deactivates_record(self, _mock):
        document = self.make_document()
        response = self.client.post(reverse("remove_document", args=[document.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["asset_deleted"])
        document.refresh_from_db()
        self.assertFalse(document.is_active)
        # public_id is retained so the leaked asset remains traceable.
        self.assertEqual(document.cloudinary_public_id, "dubeyai-test/user_1/doc_a")

    @patch("core.storage.delete")
    def test_user_cannot_delete_another_users_asset(self, mock_delete):
        victim = self.make_document(user=self.other, public_id="dubeyai-test/user_2/secret")
        response = self.client.post(reverse("remove_document", args=[victim.pk]))

        self.assertEqual(response.status_code, 404)
        # The critical assertion: no Cloudinary call was made at all, so one
        # user can never destroy another user's stored file.
        mock_delete.assert_not_called()

        victim.refresh_from_db()
        self.assertTrue(victim.is_active)
        self.assertEqual(victim.cloudinary_public_id, "dubeyai-test/user_2/secret")

    def test_user_cannot_read_another_users_document_metadata(self):
        victim = self.make_document(user=self.other, public_id="dubeyai-test/user_2/secret")
        response = self.client.get(reverse("chatbot"))
        self.assertNotContains(response, "dubeyai-test/user_2/secret")
        self.assertNotContains(response, victim.cloudinary_url)

    @patch("core.storage.delete", return_value=True)
    def test_clear_documents_does_not_delete_assets(self, mock_delete):
        # "New conversation" is a soft detach — binaries must survive it.
        self.make_document()
        response = self.client.post(reverse("clear_documents"))

        self.assertEqual(response.status_code, 200)
        mock_delete.assert_not_called()
        self.assertEqual(
            UploadedDocument.objects.filter(user=self.user, is_active=True).count(), 0
        )
        self.assertTrue(UploadedDocument.objects.first().cloudinary_public_id)


class DownloadUrlTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("url-user", password="strong-pass-123")

    def test_cloudinary_url_preferred(self):
        document = UploadedDocument.objects.create(
            user=self.user,
            filename="a.pdf",
            cloudinary_public_id="x/y",
            cloudinary_url="https://res.cloudinary.com/test/raw/upload/x/y",
        )
        self.assertEqual(document.download_url, "https://res.cloudinary.com/test/raw/upload/x/y")
        self.assertTrue(document.stored_in_cloudinary)

    def test_empty_when_nothing_stored(self):
        document = UploadedDocument.objects.create(user=self.user, filename="a.pdf")
        self.assertEqual(document.download_url, "")
        self.assertFalse(document.stored_in_cloudinary)
