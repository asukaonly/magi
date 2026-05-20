"""Platform-specific WiFi scanners + the Mozilla Location Service client.

The scanner enumerates nearby WiFi APs (BSSID + signal strength) by
shelling out to a platform command. Mozilla Location Service then turns
that list into a single (lat, lng) coordinate.

Limitations to expect:
  - macOS 14+ tightened CoreWLAN scan permissions; ``airport -s`` is
    deprecated but still works without sudo for read-only scans.
  - Windows ``netsh wlan show networks mode=bssid`` works for
    unprivileged users but requires the WLAN service to be running.
  - On a desktop with no WiFi adapter (and many Windows towers), scans
    return empty. The resolver gracefully falls through to IPGeo.

Any failure (missing binary, no adapter, parser unable to find BSSIDs)
returns an empty list — the caller treats "no samples" as "nothing
contributed" and the scheduler's backoff kicks in.
"""

from __future__ import annotations

import asyncio
import platform
import re
from dataclasses import dataclass
from typing import Optional

import httpx

from ..core.logger import get_logger

logger = get_logger("magi.location.wifi_scanner")


@dataclass(slots=True)
class WiFiAP:
    """A single WiFi access point observation."""

    bssid: str
    signal_dbm: int


@dataclass(slots=True)
class WiFiLocationFix:
    """Mozilla Location Service result for a list of BSSIDs."""

    lat: float
    lng: float
    accuracy_m: float
    ap_count: int


_BSSID_RE = re.compile(r"\b([0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5})\b")


async def scan_wifi() -> list[WiFiAP]:
    """Run the platform's WiFi-scan command and parse out BSSIDs.

    Returns an empty list on any failure — caller treats that as
    "no samples this round" without raising.
    """
    system = platform.system()
    try:
        if system == "Darwin":
            return await _scan_macos()
        if system == "Windows":
            return await _scan_windows()
        if system == "Linux":
            return await _scan_linux()
    except Exception as exc:
        logger.warning("WiFi scan failed", platform=system, error=str(exc))
    return []


async def _scan_macos() -> list[WiFiAP]:
    """macOS: airport -s. Deprecated but the only no-sudo path on 14+."""
    airport_path = "/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport"
    proc = await asyncio.create_subprocess_exec(
        airport_path, "-s",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=8.0)
    text = stdout.decode("utf-8", errors="replace")
    return _parse_airport_output(text)


def _parse_airport_output(text: str) -> list[WiFiAP]:
    """Parse the columnar ``airport -s`` output.

    Sample line (whitespace-separated, BSSID + RSSI columns):
       MySSID    aa:bb:cc:dd:ee:ff  -65   1   N -- WPA2(PSK/AES/AES) ...
    """
    results: list[WiFiAP] = []
    for line in text.splitlines():
        bssid_match = _BSSID_RE.search(line)
        if not bssid_match:
            continue
        # Signal column is right after BSSID — first negative integer.
        signal_match = re.search(r"\s(-\d{2,3})\s", line)
        signal = int(signal_match.group(1)) if signal_match else -85
        results.append(WiFiAP(bssid=bssid_match.group(1).lower(), signal_dbm=signal))
    return results


async def _scan_windows() -> list[WiFiAP]:
    """Windows: netsh wlan show networks mode=bssid."""
    proc = await asyncio.create_subprocess_exec(
        "netsh", "wlan", "show", "networks", "mode=bssid",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)
    text = stdout.decode("utf-8", errors="replace")
    return _parse_netsh_output(text)


def _parse_netsh_output(text: str) -> list[WiFiAP]:
    """Parse ``netsh`` output. BSSID + Signal % lines come in pairs."""
    results: list[WiFiAP] = []
    current_bssid: Optional[str] = None
    for raw in text.splitlines():
        line = raw.strip()
        m = _BSSID_RE.search(line)
        if m and line.startswith("BSSID"):
            current_bssid = m.group(1).lower()
            continue
        if current_bssid and line.startswith("Signal"):
            pct_match = re.search(r"(\d+)\s*%", line)
            if pct_match:
                # Convert percentage to dBm (rough): 100% ≈ -50dBm, 0% ≈ -100dBm.
                pct = int(pct_match.group(1))
                signal_dbm = -100 + (pct // 2)
                results.append(WiFiAP(bssid=current_bssid, signal_dbm=signal_dbm))
            current_bssid = None
    return results


async def _scan_linux() -> list[WiFiAP]:
    """Linux: try nmcli first, fall back to iw."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "nmcli", "-t", "-f", "BSSID,SIGNAL", "dev", "wifi", "list",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=8.0)
        return _parse_nmcli_output(stdout.decode("utf-8", errors="replace"))
    except FileNotFoundError:
        return []


def _parse_nmcli_output(text: str) -> list[WiFiAP]:
    """nmcli -t output is BSSID:SIGNAL per line, signal is 0-100.

    With ``-t`` (terse), nmcli escapes embedded colons in the BSSID with
    backslashes — e.g. ``aa\\:bb\\:cc\\:11\\:22\\:33:80``. Strip the
    backslashes before matching so the standard BSSID regex finds the MAC.
    """
    results: list[WiFiAP] = []
    for line in text.splitlines():
        unescaped = line.replace("\\:", ":")
        bssid_match = _BSSID_RE.search(unescaped)
        if not bssid_match:
            continue
        sig_match = re.search(r":(\d+)$", unescaped)
        if not sig_match:
            continue
        pct = int(sig_match.group(1))
        signal_dbm = -100 + (pct // 2)
        results.append(WiFiAP(bssid=bssid_match.group(1).lower(), signal_dbm=signal_dbm))
    return results


# ─── Mozilla Location Service ────────────────────────────────────────

MOZILLA_GEOLOCATE_URL = "https://location.services.mozilla.com/v1/geolocate?key=test"
MOZILLA_TIMEOUT = 8.0
# Mozilla requires at least 2 APs for a useful fix; submitting 1 gets you
# an LAC fallback that's basically the IP-geo answer.
MIN_APS_FOR_LOOKUP = 2


async def mozilla_locate(aps: list[WiFiAP]) -> Optional[WiFiLocationFix]:
    """Resolve a list of BSSIDs to (lat, lng) via Mozilla Location Service.

    Returns ``None`` on insufficient APs or network failure.
    """
    if len(aps) < MIN_APS_FOR_LOOKUP:
        return None

    payload = {
        "wifiAccessPoints": [
            {"macAddress": ap.bssid, "signalStrength": ap.signal_dbm}
            for ap in aps
        ]
    }
    try:
        async with httpx.AsyncClient(timeout=MOZILLA_TIMEOUT) as client:
            response = await client.post(MOZILLA_GEOLOCATE_URL, json=payload)
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        logger.warning("Mozilla geolocate failed", error=str(exc))
        return None

    if not isinstance(data, dict):
        return None
    location = data.get("location") or {}
    try:
        lat = float(location.get("lat"))
        lng = float(location.get("lng"))
    except (TypeError, ValueError):
        return None
    accuracy = float(data.get("accuracy") or 0.0)
    return WiFiLocationFix(
        lat=lat, lng=lng, accuracy_m=accuracy, ap_count=len(aps),
    )
