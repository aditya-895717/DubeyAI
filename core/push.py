"""
core.push — Web Push (VAPID) delivery.

Used by the companion script's reminder-fire confirmation flow (Phase 5) and
by Django itself for any server-triggered notifications.
"""

import json
import logging

from django.conf import settings
from pywebpush import WebPushException, webpush

from core.models import PushSubscription

logger = logging.getLogger(__name__)


def send_push_notification(user, title, body):
    """Send a push notification to every device `user` has subscribed on.

    Returns the number of subscriptions successfully notified. Expired/invalid
    subscriptions (404/410 from the push service) are removed automatically.
    """
    if not settings.VAPID_PRIVATE_KEY:
        logger.warning("VAPID_PRIVATE_KEY is not configured — cannot send push notifications.")
        return 0

    sent = 0
    for subscription in PushSubscription.objects.filter(user=user):
        try:
            webpush(
                subscription_info={
                    "endpoint": subscription.endpoint,
                    "keys": {
                        "p256dh": subscription.p256dh_key,
                        "auth": subscription.auth_key,
                    },
                },
                data=json.dumps({"title": title, "body": body}),
                vapid_private_key=settings.VAPID_PRIVATE_KEY,
                vapid_claims={"sub": f"mailto:{settings.VAPID_CLAIM_EMAIL}"},
            )
            sent += 1
        except WebPushException as exc:
            status_code = exc.response.status_code if exc.response is not None else None
            logger.warning("Push failed for subscription %s: %s", subscription.id, exc)
            if status_code in (404, 410):
                subscription.delete()  # endpoint expired or was unsubscribed client-side
    return sent
