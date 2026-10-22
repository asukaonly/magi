"""Canonical image reference and upload format contract."""

# Content-Type → file extension. The keys are what we accept on upload;
# anything else gets a 415 at the route layer.
ACCEPTED_CONTENT_TYPES: dict[str, str] = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/gif": "gif",
    "image/webp": "webp",
}

# Content types we explicitly recognize but don't yet support — produces
# a clearer error message than a generic "not allowed".
KNOWN_UNSUPPORTED_CONTENT_TYPES: dict[str, str] = {
    "image/heic": "HEIC 暂不支持，请先转换为 JPG 或 PNG。",
    "image/heif": "HEIF 暂不支持，请先转换为 JPG 或 PNG。",
}

# Reverse map for content-type lookup on serve.
EXT_TO_CONTENT_TYPE: dict[str, str] = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
}

ASSET_SCHEME = "manual-entry-asset"
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
