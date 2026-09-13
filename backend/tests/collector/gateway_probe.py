"""Cross-language probe launched by the real Rust gateway integration test."""
import asyncio
import json
import sys

from magi.collector.transport import CollectorRejected, CollectorTransport


async def probe(settings: dict) -> None:
    transport = CollectorTransport(settings["address"], {})
    try:
        credential = await transport.pair("Transport probe", settings["pairing_token"])
        transport.credential = credential
        info = await transport.request("GET", "/server/info")
        assert info["server_id"] == credential["server_id"]
        # Simulate a gateway restart that invalidates the short-lived access session.
        transport.session = "invalidated-access-session"
        assert (await transport.request("GET", "/server/info"))["server_id"] == info["server_id"]
        body = {"server_id": info["server_id"], "data_epoch": info["maintenance"]["data_epoch"],
                "producer_id": "3007493b-03c1-4d1f-9caf-02371927a35a", "events": [settings["event"]]}
        result = await transport.request("POST", "/delivery/events", body=body)
        assert result["receipts"] == [{"event_id": settings["event"]["event_id"], "status": "accepted", "code": "accepted"}]
        try:
            await transport.request("GET", "/server/clients")
        except CollectorRejected:
            pass
        else:
            raise AssertionError("Collector acquired center administration access")
        print(json.dumps({"client_id": credential["client_id"]}))
    finally:
        await transport.close()


if __name__ == "__main__":
    asyncio.run(probe(json.load(sys.stdin)))
