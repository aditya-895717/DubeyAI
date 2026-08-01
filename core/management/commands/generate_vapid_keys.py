import base64

from django.core.management.base import BaseCommand
from py_vapid import Vapid


class Command(BaseCommand):
    help = "Generate a VAPID key pair for Web Push and print .env-ready lines."

    def handle(self, *args, **options):
        vapid = Vapid()
        vapid.generate_keys()

        private_numbers = vapid.private_key.private_numbers()
        public_numbers = vapid.private_key.public_key().public_numbers()

        private_raw = private_numbers.private_value.to_bytes(32, "big")
        public_raw = (
            b"\x04"
            + public_numbers.x.to_bytes(32, "big")
            + public_numbers.y.to_bytes(32, "big")
        )

        def b64url(data):
            return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

        self.stdout.write("Add these to your .env:\n")
        self.stdout.write(f"VAPID_PUBLIC_KEY={b64url(public_raw)}")
        self.stdout.write(f"VAPID_PRIVATE_KEY={b64url(private_raw)}")
