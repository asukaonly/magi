from magi.mcp.protocol import (
    encode_message,
    FrameDecoder,
    JsonRpcRequest,
    JsonRpcResponse,
    JsonRpcNotification,
    JsonRpcError,
    parse_message,
)


def test_encode_request_preserves_fields_and_omits_absent_params():
    import json

    for params in [None, {}, {"x": 1, "text": "line\nnext"}]:
        raw = encode_message(JsonRpcRequest(id=1, method="initialize", params=params))
        assert raw.endswith(b"\n") and raw.count(b"\n") == 1
        expected = {"jsonrpc": "2.0", "id": 1, "method": "initialize"}
        if params is not None:
            expected["params"] = params
        assert json.loads(raw) == expected


def test_decoder_reads_full_message_in_chunks():
    dec = FrameDecoder()
    req = JsonRpcRequest(id=1, method="ping", params={})
    raw = encode_message(req)
    dec.feed(raw[:5])
    assert dec.next() is None
    dec.feed(raw[5:])
    out = dec.next()
    assert out is not None
    parsed = parse_message(out)
    assert isinstance(parsed, JsonRpcRequest)
    assert parsed.method == "ping"


def test_decoder_handles_back_to_back_messages():
    dec = FrameDecoder()
    a = encode_message(JsonRpcRequest(id=1, method="a"))
    b = encode_message(JsonRpcRequest(id=2, method="b"))
    dec.feed(a + b)
    m1 = parse_message(dec.next())
    m2 = parse_message(dec.next())
    assert m1.method == "a" and m2.method == "b"
    assert dec.next() is None


def test_decoder_skips_blank_lines_without_losing_next_frame():
    decoder = FrameDecoder()
    decoder.feed(b"\n\n")
    assert decoder.next() is None
    decoder.feed(b'\n{"jsonrpc":"2.0","id":9,"method":"ping","params":{"token":"kept"}}\n\n')
    assert parse_message(decoder.next()) == JsonRpcRequest(
        id=9, method="ping", params={"token": "kept"}
    )
    assert decoder.next() is None


def test_parse_error_response():
    raw = b'{"jsonrpc":"2.0","id":3,"error":{"code":-32601,"message":"not found"}}'
    msg = parse_message(raw)
    assert isinstance(msg, JsonRpcResponse)
    assert msg.error == JsonRpcError(code=-32601, message="not found")


def test_parse_notification():
    raw = b'{"jsonrpc":"2.0","method":"notifications/x","params":{"v":1}}'
    msg = parse_message(raw)
    assert isinstance(msg, JsonRpcNotification)
    assert msg.method == "notifications/x"
    assert msg.params == {"v": 1}


def test_parse_success_response():
    raw = b'{"jsonrpc":"2.0","id":7,"result":{"ok":true}}'
    msg = parse_message(raw)
    assert isinstance(msg, JsonRpcResponse)
    assert msg.result == {"ok": True}
    assert msg.error is None
