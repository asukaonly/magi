from magi.mcp.prompt import format_resource_block


def test_text_resource_renders_with_attributes_and_body():
    result = {
        "contents": [
            {
                "uri": "file:///docs/readme.md",
                "mimeType": "text/markdown",
                "text": "# Hello\nThis is the content.",
            }
        ]
    }
    block = format_resource_block("docs", result)
    assert "<mcp_resource" in block
    assert 'server_id="docs"' in block
    assert 'uri="file:///docs/readme.md"' in block
    assert 'mimeType="text/markdown"' in block
    assert "# Hello" in block
    assert "This is the content." in block
    assert block.endswith("</mcp_resource>")


def test_multiple_contents_are_concatenated():
    result = {
        "contents": [
            {"uri": "u1", "mimeType": "text/plain", "text": "one"},
            {"uri": "u2", "mimeType": "text/plain", "text": "two"},
        ]
    }
    block = format_resource_block("s", result)
    assert block.count("<mcp_resource") == 2
    assert "one" in block and "two" in block


def test_binary_blob_summarized_not_inlined():
    result = {
        "contents": [
            {
                "uri": "file:///image.png",
                "mimeType": "image/png",
                "blob": "AAAA" * 100,
            }
        ]
    }
    block = format_resource_block("s", result)
    assert "binary content omitted" in block
    assert "AAAA" not in block


def test_attribute_escaping_prevents_injection():
    result = {
        "contents": [
            {
                "uri": 'evil"><script>alert(1)</script>',
                "mimeType": "text/plain",
                "text": "ok",
            }
        ]
    }
    block = format_resource_block("s", result)
    assert "<script>" not in block
    assert "&quot;" in block
    assert "&lt;script&gt;" in block


def test_empty_contents_returns_empty_string():
    assert format_resource_block("s", {}) == ""
    assert format_resource_block("s", {"contents": []}) == ""
