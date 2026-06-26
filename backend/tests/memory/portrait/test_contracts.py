from magi.memory.portrait.contracts import RawMemorySnippet


def test_raw_memory_snippet_kind_required():
    s = RawMemorySnippet(
        id="mem_1",
        kind="reflection",
        layer="L3",
        statement="对失败者有同理心",
        confidence=0.7,
    )
    assert s.kind == "reflection"
    assert s.layer == "L3"
