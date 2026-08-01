from django.conf import settings

from core.models import ContentBlock, SiteSettings


def site_settings(request):
    """Expose the singleton SiteSettings row to every template as `site_settings`."""
    return {"site_settings": SiteSettings.load()}


def vapid_public_key(request):
    """Expose the VAPID public key so any page can wire up push subscription."""
    return {"vapid_public_key": settings.VAPID_PUBLIC_KEY}


def content_blocks(request):
    """Expose all ContentBlock key/value pairs to every template as `content`.

    Templates read `{{ content.some_key|default:"fallback copy" }}` so pages
    keep working with their original copy until an admin configures that key.
    """
    return {"content": {block.key: block.value for block in ContentBlock.objects.all()}}
