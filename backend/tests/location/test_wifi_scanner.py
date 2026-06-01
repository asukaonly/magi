"""WiFi scanner parser unit tests (no real subprocess invoked)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from magi.location import wifi_scanner
from magi.location.wifi_scanner import (
    _parse_airport_output,
    _parse_netsh_output,
    _parse_nmcli_output,
    scan_wifi,
)


def test_parse_airport_output():
    sample = (
        "                            SSID BSSID             RSSI CHANNEL HT CC SECURITY\n"
        "                    HomeNetwork aa:bb:cc:11:22:33 -42  6       N -- WPA2(PSK/AES/AES)\n"
        "                       Cafe-WiFi 11:22:33:dd:ee:ff -68  11      N CN WPA2(PSK/AES/AES)\n"
    )
    aps = _parse_airport_output(sample)
    bssids = [ap.bssid for ap in aps]
    assert bssids == ["aa:bb:cc:11:22:33", "11:22:33:dd:ee:ff"]
    assert aps[0].signal_dbm == -42
    assert aps[1].signal_dbm == -68


def test_parse_netsh_output():
    sample = (
        "SSID 1 : HomeNetwork\n"
        "    Network type            : Infrastructure\n"
        "    Authentication          : WPA2-Personal\n"
        "    BSSID 1                 : aa:bb:cc:11:22:33\n"
        "         Signal             : 84%\n"
        "         Radio type         : 802.11n\n"
        "    BSSID 2                 : 11:22:33:dd:ee:ff\n"
        "         Signal             : 50%\n"
    )
    aps = _parse_netsh_output(sample)
    assert len(aps) == 2
    assert aps[0].bssid == "aa:bb:cc:11:22:33"
    # 84% → -100 + 42 = -58 dBm
    assert aps[0].signal_dbm == -58
    # 50% → -75 dBm
    assert aps[1].signal_dbm == -75


def test_parse_nmcli_output():
    sample = (
        "aa\\:bb\\:cc\\:11\\:22\\:33:80\n"
        "11\\:22\\:33\\:dd\\:ee\\:ff:40\n"
    )
    aps = _parse_nmcli_output(sample)
    assert len(aps) == 2
    assert aps[0].bssid == "aa:bb:cc:11:22:33"
    assert aps[0].signal_dbm == -60   # 80% → -60
    assert aps[1].signal_dbm == -80   # 40% → -80


def test_parse_handles_empty_input():
    assert _parse_airport_output("") == []
    assert _parse_netsh_output("") == []
    assert _parse_nmcli_output("") == []


@pytest.mark.asyncio
async def test_scan_wifi_marks_macos_unavailable_when_airport_missing(monkeypatch):
    """macOS 15 removed the airport binary entirely. The scanner must
    return [] gracefully + cache the unavailable state so it stops
    logging the same warning every 10 minutes."""
    monkeypatch.setattr(wifi_scanner.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(wifi_scanner.os.path, "exists", lambda p: False)
    # Clear cache (other tests may have populated it)
    wifi_scanner._PLATFORMS_KNOWN_UNAVAILABLE.clear()

    first = await scan_wifi()
    assert first == []
    assert "Darwin" in wifi_scanner._PLATFORMS_KNOWN_UNAVAILABLE

    # Subsequent calls return [] without re-running the (mocked) os.path.exists
    with patch.object(wifi_scanner.os.path, "exists") as exists_mock:
        second = await scan_wifi()
        assert second == []
        # short-circuit hit — exists_mock should not have been called
        exists_mock.assert_not_called()

    # Cleanup so this test doesn't leak state into others
    wifi_scanner._PLATFORMS_KNOWN_UNAVAILABLE.clear()


@pytest.mark.asyncio
async def test_scan_wifi_short_circuits_for_cached_unavailable_platform(monkeypatch):
    """Even without a missing-binary path, if the platform is pre-marked
    unavailable (e.g. by an earlier subprocess crash), scan_wifi returns
    [] without trying again."""
    monkeypatch.setattr(wifi_scanner.platform, "system", lambda: "Darwin")
    wifi_scanner._PLATFORMS_KNOWN_UNAVAILABLE.add("Darwin")
    try:
        result = await scan_wifi()
        assert result == []
    finally:
        wifi_scanner._PLATFORMS_KNOWN_UNAVAILABLE.clear()
