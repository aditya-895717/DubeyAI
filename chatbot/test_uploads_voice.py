"""Tests for chat file uploads (Feature 1) and voice commands (Feature 2).

Run:
    python manage.py test chatbot.test_uploads_voice --verbosity=2
"""

import io
import shutil
import tempfile
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from chatbot.documents import (
    DocumentExtractionError,
    MAX_EXTRACTED_CHARS,
    extract_text,
    truncate,
    validate_upload,
)
from chatbot.models import UploadedDocument
from chatbot.services import build_document_context, build_messages
from core.models import VoiceCommand


MEDIA_ROOT = tempfile.mkdtemp(prefix="dubeyai-test-media-")


def make_docx(paragraphs=("Project Falcon status", "Budget approved: 12 lakh")):
    import docx

    document = docx.Document()
    for paragraph in paragraphs:
        document.add_paragraph(paragraph)
    buffer = io.BytesIO()
    document.save(buffer)
    buffer.seek(0)
    return buffer


def make_pdf_bytes(text="Quarterly revenue was 42 crore rupees."):
    """Hand-build a tiny valid PDF so the test needs no extra dependency."""
    content = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for index, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode() + body + b"\nendobj\n"

    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_at}\n".encode()
        + b"%%EOF\n"
    )
    return bytes(out)


@override_settings(MEDIA_ROOT=MEDIA_ROOT, CLOUDINARY_ENABLED=False)
class DocumentExtractionTests(TestCase):
    """Extraction itself — no HTTP, no auth."""

    def test_txt_extraction(self):
        buffer = io.BytesIO("Hello from a plain text file.".encode("utf-8"))
        self.assertEqual(extract_text(buffer, ".txt"), "Hello from a plain text file.")

    def test_txt_latin1_fallback(self):
        buffer = io.BytesIO("café".encode("latin-1"))
        self.assertIn("caf", extract_text(buffer, ".txt"))

    def test_empty_txt_raises(self):
        with self.assertRaises(DocumentExtractionError):
            extract_text(io.BytesIO(b"   \n  "), ".txt")

    def test_docx_extraction(self):
        text = extract_text(make_docx(), ".docx")
        self.assertIn("Project Falcon status", text)
        self.assertIn("Budget approved: 12 lakh", text)

    def test_docx_tables_are_included(self):
        import docx

        document = docx.Document()
        table = document.add_table(rows=2, cols=2)
        table.cell(0, 0).text = "Region"
        table.cell(0, 1).text = "Sales"
        table.cell(1, 0).text = "North"
        table.cell(1, 1).text = "980"
        buffer = io.BytesIO()
        document.save(buffer)
        buffer.seek(0)

        text = extract_text(buffer, ".docx")
        self.assertIn("Region | Sales", text)
        self.assertIn("North | 980", text)

    def test_pdf_extraction(self):
        text = extract_text(io.BytesIO(make_pdf_bytes()), ".pdf")
        self.assertIn("42 crore", text)

    def test_scanned_pdf_without_text_layer_raises_clear_error(self):
        # A PDF with a page but no content stream — the scanned-document case.
        blank = make_pdf_bytes(text=" ")
        with self.assertRaises(DocumentExtractionError) as ctx:
            extract_text(io.BytesIO(blank), ".pdf")
        self.assertIn("no selectable text", str(ctx.exception))

    def test_corrupt_pdf_raises_safe_error(self):
        with self.assertRaises(DocumentExtractionError):
            extract_text(io.BytesIO(b"not a pdf at all"), ".pdf")

    def test_image_ocr_unavailable_is_graceful(self):
        # tesseract is not installed in CI or on Vercel; the code must return a
        # user-safe message rather than raising something unhandled.
        with self.assertRaises(DocumentExtractionError) as ctx:
            extract_text(io.BytesIO(b"\x89PNG\r\n\x1a\n"), ".png")
        self.assertIn("OCR", str(ctx.exception))

    def test_truncate_caps_long_text(self):
        long_text = "x" * (MAX_EXTRACTED_CHARS + 5000)
        result = truncate(long_text)
        self.assertLess(len(result), MAX_EXTRACTED_CHARS + 200)
        self.assertIn("truncated", result)

    def test_validate_rejects_unsupported_extension(self):
        upload = SimpleUploadedFile("virus.exe", b"MZ", content_type="application/octet-stream")
        with self.assertRaises(DocumentExtractionError) as ctx:
            validate_upload(upload)
        self.assertIn("Unsupported file type", str(ctx.exception))

    def test_validate_rejects_oversized_file(self):
        upload = SimpleUploadedFile("big.txt", b"x" * 100, content_type="text/plain")
        upload.size = 20 * 1024 * 1024
        with self.assertRaises(DocumentExtractionError) as ctx:
            validate_upload(upload)
        self.assertIn("too large", str(ctx.exception))

    def test_validate_rejects_empty_file(self):
        upload = SimpleUploadedFile("empty.txt", b"", content_type="text/plain")
        with self.assertRaises(DocumentExtractionError):
            validate_upload(upload)


@override_settings(MEDIA_ROOT=MEDIA_ROOT, CLOUDINARY_ENABLED=False)
class UploadEndpointTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("uploader", password="strong-pass-123")
        self.client = Client()
        self.client.login(username="uploader", password="strong-pass-123")
        self.url = reverse("upload_document")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()

    def test_upload_requires_login(self):
        anonymous = Client()
        response = anonymous.post(self.url, {"file": SimpleUploadedFile("a.txt", b"hi")})
        self.assertIn(response.status_code, (302, 403))

    def test_upload_txt_extracts_and_stores(self):
        upload = SimpleUploadedFile("notes.txt", b"The launch date is 14 March.", content_type="text/plain")
        response = self.client.post(self.url, {"file": upload})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["document"]["status"], "ready")

        document = UploadedDocument.objects.get(pk=data["document"]["id"])
        self.assertEqual(document.user, self.user)
        self.assertIn("14 March", document.extracted_text)
        self.assertTrue(document.is_active)

    def test_upload_docx_extracts(self):
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

    def test_upload_pdf_extracts(self):
        upload = SimpleUploadedFile("report.pdf", make_pdf_bytes(), content_type="application/pdf")
        response = self.client.post(self.url, {"file": upload})
        self.assertEqual(response.status_code, 200)
        document = UploadedDocument.objects.get(pk=response.json()["document"]["id"])
        self.assertIn("42 crore", document.extracted_text)

    def test_upload_unsupported_type_returns_400(self):
        upload = SimpleUploadedFile("script.exe", b"MZ\x90", content_type="application/octet-stream")
        response = self.client.post(self.url, {"file": upload})
        self.assertEqual(response.status_code, 400)
        self.assertIn("Unsupported file type", response.json()["error"])

    def test_upload_with_no_file_returns_400(self):
        response = self.client.post(self.url, {})
        self.assertEqual(response.status_code, 400)

    def test_extraction_failure_marks_document_failed(self):
        upload = SimpleUploadedFile("broken.pdf", b"definitely not a pdf", content_type="application/pdf")
        response = self.client.post(self.url, {"file": upload})
        self.assertEqual(response.status_code, 400)
        document = UploadedDocument.objects.latest("uploaded_at")
        self.assertEqual(document.status, UploadedDocument.Status.FAILED)
        self.assertTrue(document.error_message)

    def test_remove_document_deactivates_it(self):
        upload = SimpleUploadedFile("notes.txt", b"content here", content_type="text/plain")
        document_id = self.client.post(self.url, {"file": upload}).json()["document"]["id"]

        response = self.client.post(reverse("remove_document", args=[document_id]))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(UploadedDocument.objects.get(pk=document_id).is_active)

    def test_cannot_remove_another_users_document(self):
        other = User.objects.create_user("intruder", password="strong-pass-123")
        document = UploadedDocument.objects.create(
            user=other, file="uploads/x.txt", filename="x.txt", extracted_text="secret"
        )
        response = self.client.post(reverse("remove_document", args=[document.pk]))
        self.assertEqual(response.status_code, 404)
        self.assertTrue(UploadedDocument.objects.get(pk=document.pk).is_active)

    def test_clear_documents_deactivates_all(self):
        for name in ("a.txt", "b.txt"):
            self.client.post(self.url, {"file": SimpleUploadedFile(name, b"data", content_type="text/plain")})

        response = self.client.post(reverse("clear_documents"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            UploadedDocument.objects.filter(user=self.user, is_active=True).count(), 0
        )


@override_settings(MEDIA_ROOT=MEDIA_ROOT, CLOUDINARY_ENABLED=False)
class DocumentContextInjectionTests(TestCase):
    """The uploaded text must actually reach the AI provider's message list."""

    def setUp(self):
        self.user = User.objects.create_user("asker", password="strong-pass-123")
        self.client = Client()
        self.client.login(username="asker", password="strong-pass-123")

    def test_build_document_context_includes_filename_and_text(self):
        document = UploadedDocument.objects.create(
            user=self.user,
            file="uploads/policy.txt",
            filename="policy.txt",
            extracted_text="Refunds are processed in 7 days.",
            status=UploadedDocument.Status.READY,
        )
        context = build_document_context([document])
        self.assertIn("policy.txt", context)
        self.assertIn("Refunds are processed in 7 days.", context)

    def test_build_document_context_empty_without_documents(self):
        self.assertIsNone(build_document_context([]))

    def test_build_messages_adds_a_second_system_message(self):
        document = UploadedDocument.objects.create(
            user=self.user,
            file="uploads/policy.txt",
            filename="policy.txt",
            extracted_text="Refunds are processed in 7 days.",
            status=UploadedDocument.Status.READY,
        )
        messages = build_messages("How long do refunds take?", [], [document])
        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[1]["role"], "system")
        self.assertIn("Refunds are processed in 7 days.", messages[1]["content"])
        self.assertEqual(messages[-1]["content"], "How long do refunds take?")

    def test_build_messages_unchanged_without_documents(self):
        messages = build_messages("Hello", [])
        self.assertEqual(len(messages), 2)  # system + user only

    @patch("chatbot.views.generate_reply", return_value="Seven days.")
    def test_chat_endpoint_passes_active_documents(self, mock_generate):
        UploadedDocument.objects.create(
            user=self.user,
            file="uploads/policy.txt",
            filename="policy.txt",
            extracted_text="Refunds are processed in 7 days.",
            status=UploadedDocument.Status.READY,
        )
        response = self.client.post(
            reverse("chat"),
            data={"message": "How long do refunds take?"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)

        documents = mock_generate.call_args[0][2]
        self.assertEqual(len(documents), 1)
        self.assertEqual(documents[0].filename, "policy.txt")

    @patch("chatbot.views.generate_reply", return_value="Sure.")
    def test_inactive_documents_are_not_injected(self, mock_generate):
        UploadedDocument.objects.create(
            user=self.user,
            file="uploads/old.txt",
            filename="old.txt",
            extracted_text="Stale content",
            status=UploadedDocument.Status.READY,
            is_active=False,
        )
        self.client.post(
            reverse("chat"), data={"message": "Hi"}, content_type="application/json"
        )
        self.assertEqual(list(mock_generate.call_args[0][2]), [])

    @patch("chatbot.views.generate_reply", return_value="Sure.")
    def test_failed_documents_are_not_injected(self, mock_generate):
        UploadedDocument.objects.create(
            user=self.user,
            file="uploads/bad.pdf",
            filename="bad.pdf",
            status=UploadedDocument.Status.FAILED,
            error_message="No text layer",
        )
        self.client.post(
            reverse("chat"), data={"message": "Hi"}, content_type="application/json"
        )
        self.assertEqual(list(mock_generate.call_args[0][2]), [])

    @patch("chatbot.views.generate_reply", return_value="Sure.")
    def test_another_users_documents_are_not_injected(self, mock_generate):
        other = User.objects.create_user("someone-else", password="strong-pass-123")
        UploadedDocument.objects.create(
            user=other,
            file="uploads/private.txt",
            filename="private.txt",
            extracted_text="Confidential salary data",
            status=UploadedDocument.Status.READY,
        )
        self.client.post(
            reverse("chat"), data={"message": "Hi"}, content_type="application/json"
        )
        self.assertEqual(list(mock_generate.call_args[0][2]), [])


class VoiceCommandTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("speaker", password="strong-pass-123")
        self.client = Client()
        self.client.login(username="speaker", password="strong-pass-123")

    def test_defaults_were_seeded_by_migration(self):
        self.assertTrue(VoiceCommand.objects.filter(trigger_phrase="open whatsapp").exists())
        self.assertTrue(VoiceCommand.objects.filter(trigger_phrase="open youtube").exists())

    def test_trigger_phrase_is_normalized_to_lowercase(self):
        command = VoiceCommand.objects.create(
            trigger_phrase="  OPEN Notion  ", action_url="https://notion.so"
        )
        self.assertEqual(command.trigger_phrase, "open notion")

    def test_display_label_falls_back_to_phrase(self):
        command = VoiceCommand.objects.create(
            trigger_phrase="open notion", action_url="https://notion.so"
        )
        self.assertEqual(command.display_label, "Open Notion")

    def test_endpoint_requires_login(self):
        anonymous = Client()
        response = anonymous.get(reverse("voice_commands"))
        self.assertIn(response.status_code, (302, 403))

    def test_endpoint_returns_active_commands(self):
        response = self.client.get(reverse("voice_commands"))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])

        phrases = {command["phrase"] for command in data["commands"]}
        self.assertIn("open whatsapp", phrases)
        self.assertIn("open youtube", phrases)

        whatsapp = next(c for c in data["commands"] if c["phrase"] == "open whatsapp")
        self.assertEqual(whatsapp["url"], "https://web.whatsapp.com")
        self.assertEqual(whatsapp["native"], "whatsapp://send")
        self.assertEqual(whatsapp["label"], "WhatsApp")

    def test_inactive_commands_are_excluded(self):
        VoiceCommand.objects.filter(trigger_phrase="open youtube").update(is_active=False)
        response = self.client.get(reverse("voice_commands"))
        phrases = {command["phrase"] for command in response.json()["commands"]}
        self.assertNotIn("open youtube", phrases)

    def test_admin_added_command_appears_without_code_change(self):
        VoiceCommand.objects.create(
            trigger_phrase="open notion", action_url="https://notion.so", label="Notion"
        )
        response = self.client.get(reverse("voice_commands"))
        phrases = {command["phrase"] for command in response.json()["commands"]}
        self.assertIn("open notion", phrases)


@override_settings(MEDIA_ROOT=MEDIA_ROOT, CLOUDINARY_ENABLED=False)
class ChatPageRenderTests(TestCase):
    """The chat page must expose the new controls and not regress."""

    def setUp(self):
        self.user = User.objects.create_user("viewer", password="strong-pass-123")
        self.client = Client()
        self.client.login(username="viewer", password="strong-pass-123")

    def test_page_contains_attach_and_mic_controls(self):
        response = self.client.get(reverse("chatbot"))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        for marker in ('id="attachButton"', 'id="micButton"', 'id="fileInput"', 'id="ttsToggleButton"'):
            self.assertIn(marker, html)

    def test_page_exposes_upload_and_voice_urls(self):
        response = self.client.get(reverse("chatbot"))
        html = response.content.decode()
        self.assertIn('data-upload-url="/api/upload/"', html)
        self.assertIn('data-voice-commands-url="/api/voice-commands/"', html)

    def test_active_documents_render_as_chips(self):
        UploadedDocument.objects.create(
            user=self.user,
            file="uploads/report.pdf",
            filename="report.pdf",
            extracted_text="data",
            status=UploadedDocument.Status.READY,
        )
        response = self.client.get(reverse("chatbot"))
        self.assertContains(response, "report.pdf")
