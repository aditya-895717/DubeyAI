"""Cloudinary media storage for DubeyAI.

Architecture:
    Neon PostgreSQL  -> structured application data + Cloudinary metadata
    Cloudinary       -> the binary files themselves
    Vercel           -> stateless application runtime

The binary never goes into Postgres, and nothing persistent is written to
Vercel's ephemeral filesystem.

When Cloudinary is not configured (local development, CI, the test suite),
`is_enabled()` returns False and callers fall back to Django's local
FileSystemStorage. Local development must never require production credentials.
"""

import logging
import os

from django.conf import settings
from django.core.files.storage import Storage

logger = logging.getLogger(__name__)


class CloudinaryError(Exception):
    """A safe, user-facing Cloudinary failure."""


# Cloudinary splits assets into three delivery types and they are NOT
# interchangeable: a raw file fetched as an image 404s, and deleting requires
# the same resource_type that was used to upload. Documents must be "raw" —
# "image" would let Cloudinary try to rasterise a PDF, which is not what we
# want (we extract text ourselves with pdfplumber).
RESOURCE_TYPE_BY_EXTENSION = {
    ".pdf": "raw",
    ".docx": "raw",
    ".txt": "raw",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".gif": "image",
    ".webp": "image",
    ".mp4": "video",
    ".mov": "video",
    ".webm": "video",
}

DEFAULT_RESOURCE_TYPE = "raw"


def resource_type_for(filename):
    """Map a filename to the correct Cloudinary resource_type."""
    extension = os.path.splitext(filename or "")[1].lower()
    return RESOURCE_TYPE_BY_EXTENSION.get(extension, DEFAULT_RESOURCE_TYPE)


def is_enabled():
    """True when all three Cloudinary credentials are configured."""
    return bool(getattr(settings, "CLOUDINARY_ENABLED", False))


def _configure():
    """Configure the Cloudinary SDK from settings. Raises if unusable."""
    if not is_enabled():
        raise CloudinaryError("Cloudinary is not configured.")
    try:
        import cloudinary  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - dependency is in requirements
        raise CloudinaryError("Cloudinary support is not installed on the server.") from exc

    cloudinary.config(
        cloud_name=settings.CLOUDINARY_CLOUD_NAME,
        api_key=settings.CLOUDINARY_API_KEY,
        api_secret=settings.CLOUDINARY_API_SECRET,
        secure=True,
    )
    return cloudinary


def upload(file_obj, filename, folder=None, owner_id=None):
    """Upload a file object to Cloudinary and return its metadata.

    Returns a dict with public_id / resource_type / url / version / bytes.
    Raises CloudinaryError on any failure — callers must treat that as "the
    document was not stored" and must not mark the record ready.
    """
    cloudinary = _configure()
    import cloudinary.uploader  # noqa: PLC0415

    resource_type = resource_type_for(filename)

    # Namespace per user so listing/auditing in the Cloudinary console is
    # meaningful. This is organisational only — it is NOT an access control
    # boundary, so ownership is always re-checked in the database.
    base_folder = folder or getattr(settings, "CLOUDINARY_FOLDER", "dubeyai")
    target_folder = f"{base_folder}/user_{owner_id}" if owner_id else base_folder

    try:
        file_obj.seek(0)
    except (AttributeError, OSError):
        pass

    try:
        result = cloudinary.uploader.upload(
            file_obj,
            folder=target_folder,
            resource_type=resource_type,
            # Keep the original name visible in the console but let Cloudinary
            # add a random suffix, so two uploads of "resume.pdf" never collide.
            use_filename=True,
            unique_filename=True,
            overwrite=False,
        )
    except Exception as exc:
        logger.warning("Cloudinary upload failed for %s: %s", filename, exc)
        raise CloudinaryError(
            "The file could not be stored right now. Please try again."
        ) from exc

    public_id = result.get("public_id")
    if not public_id:
        raise CloudinaryError("The file could not be stored right now. Please try again.")

    return {
        "public_id": public_id,
        # Trust the API's echoed resource_type over our guess.
        "resource_type": result.get("resource_type") or resource_type,
        "url": result.get("secure_url") or result.get("url") or "",
        "version": str(result.get("version") or ""),
        "bytes": result.get("bytes") or 0,
    }


def delete(public_id, resource_type=DEFAULT_RESOURCE_TYPE):
    """Delete an asset. Returns True if it is gone, False otherwise.

    Never raises: deletion runs during user-facing cleanup, and a Cloudinary
    outage must not block removing the database record. A leaked asset is
    recoverable; a stuck UI is not.
    """
    if not public_id or not is_enabled():
        return False

    try:
        cloudinary = _configure()
        import cloudinary.uploader  # noqa: PLC0415

        result = cloudinary.uploader.destroy(
            public_id,
            resource_type=resource_type or DEFAULT_RESOURCE_TYPE,
            invalidate=True,
        )
    except Exception as exc:
        logger.warning("Cloudinary delete failed for %s: %s", public_id, exc)
        return False

    outcome = (result or {}).get("result")
    if outcome not in {"ok", "not found"}:
        logger.warning("Cloudinary delete returned %r for %s", outcome, public_id)
        return False
    return True


# Unambiguous alias for use inside CloudinaryMediaStorage, whose own `delete`
# method would otherwise make the call site hard to read.
delete_asset = delete


class CloudinaryMediaStorage(Storage):
    """Django storage backend backed by Cloudinary.

    Used as the `default` STORAGES backend in production so ordinary
    FileField/ImageField uploads (e.g. SiteSettings.logo) persist instead of
    being written to Vercel's ephemeral disk.

    UploadedDocument does NOT go through this: it needs the Cloudinary
    public_id and resource_type recorded in the database for later deletion,
    so it calls upload()/delete() directly.

    The stored "name" is the Cloudinary public_id, prefixed with its
    resource_type so url() and delete() can round-trip without a database
    lookup (e.g. "image::dubeyai/media/logo_ab12").
    """

    SEPARATOR = "::"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # STORAGES["default"] is resolved once at import time, but
        # CLOUDINARY_ENABLED can be toggled afterwards (most importantly by
        # override_settings in tests). Rather than let the two disagree, every
        # operation re-checks is_enabled() and falls back to local storage —
        # is_enabled() is the single source of truth.
        from django.core.files.storage import FileSystemStorage  # noqa: PLC0415

        self._local = FileSystemStorage()

    def _encode(self, resource_type, public_id):
        return f"{resource_type}{self.SEPARATOR}{public_id}"

    def _decode(self, name):
        if self.SEPARATOR in (name or ""):
            resource_type, public_id = name.split(self.SEPARATOR, 1)
            return resource_type, public_id
        return DEFAULT_RESOURCE_TYPE, name or ""

    def _save(self, name, content):
        if not is_enabled():
            return self._local._save(name, content)
        base_folder = getattr(settings, "CLOUDINARY_FOLDER", "dubeyai")
        asset = upload(content, os.path.basename(name), folder=f"{base_folder}/media")
        return self._encode(asset["resource_type"], asset["public_id"])

    def url(self, name):
        if not is_enabled() or self.SEPARATOR not in (name or ""):
            # Either Cloudinary is off, or this name predates it (a legacy
            # local path) — serve it from MEDIA_URL as before.
            return self._local.url(name)
        resource_type, public_id = self._decode(name)
        if not public_id:
            return ""
        try:
            _configure()
            import cloudinary.utils  # noqa: PLC0415

            return cloudinary.utils.cloudinary_url(
                public_id, resource_type=resource_type, secure=True
            )[0]
        except Exception:
            logger.warning("Could not build Cloudinary URL for %s", public_id)
            return ""

    def delete(self, name):
        if not is_enabled() or self.SEPARATOR not in (name or ""):
            self._local.delete(name)
            return
        resource_type, public_id = self._decode(name)
        delete_asset(public_id, resource_type)

    def exists(self, name):
        if not is_enabled():
            return self._local.exists(name)
        # Cloudinary generates a unique suffix per upload (unique_filename=True),
        # so Django never needs to probe for a name collision.
        return False

    def size(self, name):
        if not is_enabled():
            return self._local.size(name)
        return 0

    def get_valid_name(self, name):
        if not is_enabled():
            return self._local.get_valid_name(name)
        return name

    def get_available_name(self, name, max_length=None):
        if not is_enabled():
            return self._local.get_available_name(name, max_length)
        return name
