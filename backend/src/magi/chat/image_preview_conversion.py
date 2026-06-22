"""Image preview conversion helpers for chat attachments."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Protocol


class HeicPreviewConverter(Protocol):
    """Converts HEIC/HEIF image bytes into browser-friendly JPEG preview bytes."""

    def convert_heic_to_jpeg(self, *, content: bytes, original_name: str) -> bytes:
        """Return JPEG bytes for the provided HEIC/HEIF image."""


class PillowHeicPreviewConverter:
    """HEIC/HEIF preview converter backed by Pillow and pillow-heif."""

    def convert_heic_to_jpeg(self, *, content: bytes, original_name: str) -> bytes:
        try:
            import pillow_heif
            from PIL import Image, ImageOps
        except ImportError as exc:
            raise RuntimeError("HEIC image conversion requires Pillow and pillow-heif.") from exc

        try:
            pillow_heif.register_heif_opener()
            with Image.open(BytesIO(content)) as image:
                image.load()
                image = ImageOps.exif_transpose(image)
                icc_profile = image.info.get("icc_profile")
                image = _prepare_for_jpeg(image)
                output = BytesIO()
                save_kwargs: dict[str, object] = {
                    "format": "JPEG",
                    "quality": 95,
                    "subsampling": 0,
                    "optimize": True,
                }
                if icc_profile:
                    save_kwargs["icc_profile"] = icc_profile
                image.save(output, **save_kwargs)
                return output.getvalue()
        except Exception as exc:
            display_name = Path(str(original_name or "attachment")).name or "attachment"
            raise RuntimeError(f"HEIC image conversion failed for {display_name}.") from exc


def _prepare_for_jpeg(image: object) -> object:
    mode = str(getattr(image, "mode", "") or "")
    if mode == "RGB":
        return image
    bands = set(getattr(image, "getbands")())
    if "A" in bands:
        from PIL import Image

        background = Image.new("RGB", getattr(image, "size"), (255, 255, 255))
        background.paste(image, mask=getattr(image, "getchannel")("A"))
        return background
    return getattr(image, "convert")("RGB")
