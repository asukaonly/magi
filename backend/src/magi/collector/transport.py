"""Scoped collector authentication and network delivery with explicit result validation."""
from __future__ import annotations

import json
import time
from urllib.parse import urlsplit
from uuid import UUID

import httpx

from .queue import CollectorQueue


class CollectorRejected(RuntimeError):
    """Authorization or generation changed; human recovery is required."""


def validate_address(address: str) -> str:
    parsed = urlsplit(address)
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Magi address must not contain credentials, query parameters or fragments")
    if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}):
        raise ValueError("Use HTTPS, or HTTP only for a loopback address")
    if not parsed.hostname or parsed.path.rstrip("/") not in {"", "/api"}:
        raise ValueError("Expected a Magi server address")
    return address.rstrip("/").removesuffix("/api") + "/api"


class CollectorTransport:
    def __init__(self, address: str, credential: dict[str, str]) -> None:
        self.client = httpx.AsyncClient(base_url=validate_address(address), timeout=20, follow_redirects=False, trust_env=False)
        self.credential = credential
        self.session = ""
        self.expires_at = 0.0

    async def request(self, method: str, path: str, *, body: object = None, token: str | None = None) -> dict:
        if token is None:
            if self.expires_at <= time.time() + 30:
                session = await self.request("POST", "/server/session", token=self.credential["client_credential"])
                if session.get("server_id") != self.credential["server_id"] or session.get("client_id") != self.credential["client_id"]:
                    raise CollectorRejected("Collector server or device identity changed")
                if not isinstance(session.get("access_token"), str) or not session["access_token"] or type(session.get("expires_at_ms")) is not int:
                    raise ValueError("Invalid collector access session")
                self.session = session["access_token"]
                self.expires_at = session["expires_at_ms"] / 1000
            token = self.session
        response = await self.client.request(method, path, json=body, headers={"Authorization": f"Bearer {token}"})
        if response.status_code in {401, 403}:
            self.expires_at = 0
            raise CollectorRejected("Collector authorization expired or was revoked; check the device grant")
        response.raise_for_status()
        value = response.json()
        if not isinstance(value, dict):
            raise ValueError("Invalid collector response")
        if "success" in value:
            if value["success"] is not True or not isinstance(value.get("data"), dict):
                raise ValueError("Invalid collector response envelope")
            value = value["data"]
        return value

    async def scope(self, connection_id: str, plugin_version: str, plugin_id: str, *, claim: bool = False) -> dict[str, str]:
        info = await self.request("GET", "/server/info")
        if info.get("server_id") != self.credential["server_id"] or info.get("protocol_version") != 2:
            raise CollectorRejected("Collector server identity or protocol changed")
        maintenance = info.get("maintenance")
        if not isinstance(maintenance, dict) or not isinstance(maintenance.get("data_epoch"), str):
            raise ValueError("Server did not supply a collection generation")
        value = await self.request("POST" if claim else "GET", f"/delivery/collector/{connection_id}",
                                   body={"plugin_id": plugin_id, "plugin_version": plugin_version} if claim else None)
        keys = ("connection_id", "connection_epoch", "plugin_id", "plugin_version", "source_type")
        if not all(isinstance(value.get(key), str) and value[key] for key in keys):
            raise ValueError("Invalid source scope response")
        if value["connection_id"] != connection_id or value["plugin_version"] != plugin_version or value["plugin_id"] != plugin_id:
            raise CollectorRejected("Collector connection or plugin version changed")
        if value.get("claimed_by") != self.credential["client_id"]:
            raise CollectorRejected("Collector no longer owns this source; check collection settings on the center")
        UUID(value["connection_epoch"])
        UUID(maintenance["data_epoch"])
        return {**{key: value[key] for key in keys}, "data_epoch": maintenance["data_epoch"], "server_id": info["server_id"]}

    async def deliver(self, queue: CollectorQueue, scope: dict[str, str]) -> bool:
        row = queue.head()
        if row is None:
            return False
        event = json.loads(row["event"])
        batch = {"server_id": scope["server_id"], "data_epoch": scope["data_epoch"],
                 "producer_id": queue.state()["producer"], "events": [event]}
        try:
            result = await self.request("POST", "/delivery/events", body=batch)
            if result.get("server_id") != scope["server_id"] or result.get("data_epoch") != scope["data_epoch"]:
                raise CollectorRejected("Collector data generation changed")
            receipts = result.get("receipts")
            if not isinstance(receipts, list) or len(receipts) != 1 or not isinstance(receipts[0], dict) or receipts[0].get("event_id") != event["event_id"]:
                raise ValueError("Delivery receipt identity mismatch")
            receipt = receipts[0]
            if receipt.get("status") == "accepted" and receipt.get("code") == "accepted":
                queue.acknowledge(row["sequence"])
                return True
            if receipt.get("status") not in {"retry", "rejected"}:
                raise ValueError("Invalid delivery receipt status")
            code = receipt.get("code")
            safe_codes = {"inbox_full", "receipt_capacity", "processor_unavailable", "storage_unavailable", "connection_unavailable", "connection_epoch_changed", "handler_unavailable", "sequence_conflict"}
            queue.fail(row["sequence"], code if code in safe_codes else "delivery_rejected", terminal=receipt["status"] == "rejected")
            if code == "connection_epoch_changed":
                raise CollectorRejected("Source content was cleared; old observations remain quarantined")
        except CollectorRejected:
            raise
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            queue.fail(row["sequence"], "transport_unavailable")
        return False

    async def close(self) -> None:
        await self.client.aclose()
