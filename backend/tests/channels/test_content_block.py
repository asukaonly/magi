from magi_plugin_sdk.conversation import ContentBlock


def test_content_block_text_construction():
    b = ContentBlock(kind="text", text="hi", metadata={})
    assert b.kind == "text"
    assert b.text == "hi"
    assert b.metadata == {}


def test_content_block_is_frozen():
    import pytest
    b = ContentBlock(kind="text", text="hi", metadata={})
    with pytest.raises(Exception):  # FrozenInstanceError or AttributeError
        b.text = "no"


def test_content_block_metadata_defaults_to_empty_dict():
    b = ContentBlock(kind="text", text="hi")
    assert b.metadata == {}


def test_content_block_roundtrip_to_from_dict():
    b = ContentBlock(kind="text", text="hello", metadata={"x": 1})
    d = b.to_dict()
    assert d == {"kind": "text", "text": "hello", "metadata": {"x": 1}}
    b2 = ContentBlock.from_dict(d)
    assert b2 == b


def test_content_block_from_dict_handles_missing_metadata():
    b = ContentBlock.from_dict({"kind": "text", "text": "hi"})
    assert b.metadata == {}
