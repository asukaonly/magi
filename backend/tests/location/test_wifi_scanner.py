"""WiFi scanner parser unit tests (no real subprocess invoked)."""

from __future__ import annotations

from magi.location.wifi_scanner import (
    _parse_airport_output,
    _parse_netsh_output,
    _parse_nmcli_output,
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
