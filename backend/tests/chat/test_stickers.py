"""Sticker ownership, file validation and independent asset lifetimes."""

import io
from pathlib import Path

from PIL import Image
import pytest

from magi.chat.asset_gc import ChatAssetGC
from magi.chat.attachment_ingestion import LocalChatAttachmentIngestionService
from magi.chat.stickers import ChatStickerLibrary, MAX_STICKER_BYTES
from magi.core.chat_assets.mutations import run_chat_asset_mutation
from magi.utils.runtime import RuntimePaths


def picture(format: str = "PNG") -> bytes:
    buffer = io.BytesIO()
    first = Image.new("RGB", (2, 2), "red")
    if format == "GIF":
        first.save(buffer, format=format, save_all=True,
                   append_images=[Image.new("RGB", (2, 2), "blue")], duration=100, loop=0)
    else:
        first.save(buffer, format=format)
    return buffer.getvalue()


async def source(paths: RuntimePaths, content: bytes, extension: str = "png") -> dict:
    return await run_chat_asset_mutation(
        LocalChatAttachmentIngestionService(runtime_paths=paths).ingest_attachment,
        session_id="source", turn_id="source_turn", original_name=f"smile.{extension}",
        mime_type=f"image/{extension}", content=content,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("format", ["PNG", "JPEG", "WEBP", "GIF"])
async def test_saved_image_outlives_source_and_sent_image_outlives_library(tmp_path, format):
    paths = RuntimePaths(base_dir=tmp_path)
    library = ChatStickerLibrary(paths)
    content = picture(format)
    original = await source(paths, content, format.lower())
    sticker = await run_chat_asset_mutation(
        library.save, user_id="u1", session_id="source", attachment=original, name="开心",
    )
    same = await run_chat_asset_mutation(
        library.save, user_id="u1", session_id="source", attachment=original, name="开心猫",
    )
    assert same["sticker_id"] == sticker["sticker_id"]
    assert library.catalog("u1") == [same]
    assert library.catalog("u2") == []
    with pytest.raises(ValueError, match="not in this user's library"):
        await run_chat_asset_mutation(library.prepare_attachment, user_id="u2", session_id="s", turn_id="t",
                                      sticker_id=sticker["sticker_id"])
    gc = ChatAssetGC(runtime_paths=paths)
    await run_chat_asset_mutation(gc.delete_session_assets, "source")
    assert not Path(original["storage_path"]).exists()
    attachment, metadata = await run_chat_asset_mutation(
        library.prepare_attachment, user_id="u1", session_id="target", turn_id="target_turn",
        sticker_id=sticker["sticker_id"],
    )
    assert metadata == same
    sent = Path(attachment["storage_path"])
    assert sent.read_bytes() == content
    assert attachment["mime_type"] == f"image/{format.lower()}"
    if format == "GIF":
        with Image.open(sent) as image:
            assert image.n_frames == 2
    await run_chat_asset_mutation(library.remove, user_id="u1", sticker_id=sticker["sticker_id"])
    assert library.catalog("u1") == []
    assert sent.read_bytes() == content


@pytest.mark.asyncio
async def test_library_survives_orphan_sweep_but_full_clear_removes_it(tmp_path):
    paths = RuntimePaths(base_dir=tmp_path)
    library = ChatStickerLibrary(paths)
    original = await source(paths, picture())
    sticker = await run_chat_asset_mutation(
        library.save, user_id="u1", session_id="source", attachment=original, name="开心",
    )
    gc = ChatAssetGC(runtime_paths=paths)
    # Force old, unowned session roots through the ordinary orphan sweep.
    gc._active_asset_scopes = lambda: (set(), set(), {})
    await run_chat_asset_mutation(gc.sweep_orphan_assets, orphan_grace_hours=0)
    assert library.catalog("u1") == [sticker]
    await run_chat_asset_mutation(gc.clear_all_assets)
    assert library.catalog("u1") == []
    assert not list(paths.chat_stickers_dir.rglob("*.png"))


@pytest.mark.asyncio
@pytest.mark.parametrize("content", [b"not an image", b"x" * (MAX_STICKER_BYTES + 1)])
async def test_save_rejects_invalid_or_oversized_images(tmp_path, content):
    paths = RuntimePaths(base_dir=tmp_path)
    original = await source(paths, content)
    library = ChatStickerLibrary(paths)
    with pytest.raises(ValueError):
        await run_chat_asset_mutation(library.save, user_id="u", session_id="source",
                                      attachment=original, name="bad")
    assert library.catalog("u") == []


@pytest.mark.asyncio
async def test_save_rejects_attachment_from_another_session(tmp_path):
    paths = RuntimePaths(base_dir=tmp_path)
    original = await source(paths, picture())
    with pytest.raises(ValueError, match="unavailable"):
        await run_chat_asset_mutation(ChatStickerLibrary(paths).save, user_id="u", session_id="different",
                                      attachment=original, name="no")


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ["index", "image", "root"])
async def test_retargeted_library_paths_cannot_be_read(tmp_path, target):
    paths = RuntimePaths(base_dir=tmp_path / "home")
    library = ChatStickerLibrary(paths)
    original = await source(paths, picture())
    sticker = await run_chat_asset_mutation(library.save, user_id="u", session_id="source",
                                           attachment=original, name="happy")
    root = next(paths.chat_stickers_dir.iterdir())
    if target == "root":
        moved = tmp_path / "moved"
        root.rename(moved)
        root.symlink_to(moved, target_is_directory=True)
    else:
        path = root / ("index.json" if target == "index" else f"{sticker['sticker_id']}.png")
        moved = tmp_path / "private"
        path.rename(moved)
        path.symlink_to(moved)
    with pytest.raises(ValueError, match="retargeted|outside chat resources"):
        await run_chat_asset_mutation(library.prepare_attachment, user_id="u", session_id="s", turn_id="t",
                                      sticker_id=sticker["sticker_id"])
