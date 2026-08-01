import os

from django.db import migrations


def seed_default_provider(apps, schema_editor):
    """Create an active NVIDIA AIProvider row from existing env vars, if none exists yet.

    Without this, a fresh `migrate` leaves AIProviderService with nothing to call —
    the NVIDIA credentials already sit in .env (used by the legacy chatbot app), so
    reuse them here instead of requiring a manual control-panel step.
    """
    AIProvider = apps.get_model("core", "AIProvider")
    if AIProvider.objects.exists():
        return

    api_key = os.getenv("NVIDIA_API_KEY", "")
    if not api_key:
        return

    AIProvider.objects.create(
        name="NVIDIA",
        api_key=api_key,
        endpoint_url=os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"),
        model_name=os.getenv("NVIDIA_MODEL", "nvidia/nemotron-3-ultra-550b-a55b"),
        is_active=True,
    )


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_default_provider, migrations.RunPython.noop),
    ]
