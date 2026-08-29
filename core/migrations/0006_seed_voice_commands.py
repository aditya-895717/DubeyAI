"""Seed the default voice commands.

These are only starting points — an administrator can add, edit, or disable any
of them from Django admin without a redeploy.
"""

from django.db import migrations


DEFAULTS = [
    # (trigger_phrase, action_url, native_scheme, label)
    ("open whatsapp", "https://web.whatsapp.com", "whatsapp://send", "WhatsApp"),
    ("whatsapp khol do", "https://web.whatsapp.com", "whatsapp://send", "WhatsApp"),
    ("open youtube", "https://www.youtube.com", "", "YouTube"),
    ("youtube khol do", "https://www.youtube.com", "", "YouTube"),
    ("open gmail", "https://mail.google.com", "", "Gmail"),
    ("gmail khol do", "https://mail.google.com", "", "Gmail"),
    ("open google", "https://www.google.com", "", "Google"),
    ("google khol do", "https://www.google.com", "", "Google"),
    ("open maps", "https://maps.google.com", "", "Google Maps"),
    ("open instagram", "https://www.instagram.com", "", "Instagram"),
    ("open spotify", "https://open.spotify.com", "spotify://", "Spotify"),
    ("open twitter", "https://twitter.com", "", "Twitter"),
    ("open facebook", "https://www.facebook.com", "", "Facebook"),
    ("open linkedin", "https://www.linkedin.com", "", "LinkedIn"),
    ("open github", "https://github.com", "", "GitHub"),
]


def seed(apps, schema_editor):
    VoiceCommand = apps.get_model("core", "VoiceCommand")
    for phrase, url, native, label in DEFAULTS:
        VoiceCommand.objects.get_or_create(
            trigger_phrase=phrase,
            defaults={"action_url": url, "native_scheme": native, "label": label},
        )


def unseed(apps, schema_editor):
    VoiceCommand = apps.get_model("core", "VoiceCommand")
    VoiceCommand.objects.filter(
        trigger_phrase__in=[phrase for phrase, _, _, _ in DEFAULTS]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [("core", "0005_voicecommand")]

    operations = [migrations.RunPython(seed, unseed)]
