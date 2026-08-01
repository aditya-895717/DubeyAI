from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver

from core.models import LoginLog


def _client_ip(request):
    if request is None:
        return None
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


@receiver(user_logged_in)
def create_login_log(sender, request, user, **kwargs):
    LoginLog.objects.create(user=user, ip_address=_client_ip(request))
