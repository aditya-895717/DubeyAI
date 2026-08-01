from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import models


def _fernet():
    key = settings.FIELD_ENCRYPTION_KEY
    return Fernet(key.encode() if isinstance(key, str) else key)


class EncryptedTextField(models.TextField):
    """TextField that transparently encrypts values at rest with Fernet (AES-128-CBC + HMAC).

    Ciphertext is stored as a base64 string, so no custom DB column type is required.
    """

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if not value:
            return value
        return _fernet().encrypt(value.encode()).decode()

    def from_db_value(self, value, expression, connection):
        if not value:
            return value
        try:
            return _fernet().decrypt(value.encode()).decode()
        except InvalidToken:
            # Value predates encryption or was written with a different key.
            return value
