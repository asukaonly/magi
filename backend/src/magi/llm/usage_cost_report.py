"""Present native usage charges in the selected reporting currency."""

import asyncio
import math
import re
import time
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import aiosqlite
import httpx

from ..config import get_config
from ..core.sqlite import sqlite_connection_async

DISPLAY_CURRENCIES = ("CNY", "USD")
RATES_URL = "https://api.frankfurter.dev/v2/rates"


async def _fetch_daily_rates(quote: str, days: set[str]) -> list[tuple[str, str, float, str]]:
    start = date.fromisoformat(min(days)) - timedelta(days=7)
    end = date.fromisoformat(max(days))
    async with httpx.AsyncClient(timeout=4, proxy=get_config().network.proxy_url()) as client:
        response = await client.get(RATES_URL, params={
            "base": "USD", "quotes": quote, "from": start.isoformat(), "to": end.isoformat(),
        })
        response.raise_for_status()
        observations = response.json()
    if not isinstance(observations, list):
        raise ValueError("Invalid exchange rate response")
    rates = {}
    for item in observations:
        if not isinstance(item, dict) or item.get("base") != "USD" or item.get("quote") != quote:
            continue
        value = item.get("rate")
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            continue
        observed = date.fromisoformat(item["date"])
        if start <= observed <= end:
            rates[observed] = value
    selected = []
    for day in sorted(days):
        requested = date.fromisoformat(day)
        for age in range(8):
            observed = requested - timedelta(days=age)
            if observed in rates:
                selected.append((day, quote, rates[observed], observed.isoformat()))
                break
    return selected


class UsageExchangeRates:
    """Pin the first reference rate for a billing day, including across restarts."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = asyncio.Lock()
        self._retry_after: dict[str, float] = {}

    async def get(self, charges: list[aiosqlite.Row]) -> dict[tuple[str, str], float]:
        needed: dict[str, set[str]] = defaultdict(set)
        for row in charges:
            if row["amount"] != 0:
                for currency in {row["currency"], *DISPLAY_CURRENCIES} - {"USD"}:
                    if re.fullmatch(r"[A-Z]{3}", currency):
                        needed[currency].add(row["day"])
        if not needed:
            return {}
        days = set.union(*needed.values())
        async with self._lock, sqlite_connection_async(str(self._path), profile="mixed") as db:
            async def read() -> dict[tuple[str, str], float]:
                rows = await db.execute_fetchall(
                    "SELECT day, currency, rate FROM usage_exchange_rates WHERE day BETWEEN ? AND ?",
                    (min(days), max(days)),
                )
                return {(day, currency): rate for day, currency, rate in rows}

            cached = await read()

            async def fill(quote: str, missing: set[str]) -> list[tuple[str, str, float, str]]:
                if not missing or time.monotonic() < self._retry_after.get(quote, 0):
                    return []
                try:
                    rows = await _fetch_daily_rates(quote, missing)
                except (httpx.HTTPError, ValueError, KeyError, TypeError):
                    rows = []
                if len(rows) < len(missing):
                    self._retry_after[quote] = time.monotonic() + 300
                return rows

            batches = await asyncio.gather(*(
                fill(quote, {day for day in dates if (day, quote) not in cached})
                for quote, dates in needed.items()
            ))
            additions = [row for batch in batches for row in batch]
            if additions:
                await db.executemany(
                    "INSERT INTO usage_exchange_rates(day,currency,rate,reference_day) VALUES(?,?,?,?) "
                    "ON CONFLICT(day,currency) DO NOTHING", additions,
                )
                await db.commit()
                return await read()
            return cached


def attach_display_costs(
    summary: dict[str, Any], charges: list[aiosqlite.Row], rates: dict[tuple[str, str], float],
) -> None:
    """Sum unrounded daily charges. An unavailable rate makes the affected subtotal unknown."""
    subtotals: dict[tuple, dict[str, float | None]] = {}
    for row in charges:
        day, native, amount = row["day"], row["currency"], row["amount"]
        keys = [(), ("day", day), ("provider", row["provider"]),
                ("model", row["provider"], row["model"]), ("kind", row["request_kind"])]
        for target in DISPLAY_CURRENCIES:
            value = amount
            if amount and native != target:
                source_rate = 1.0 if native == "USD" else rates.get((day, native))
                target_rate = 1.0 if target == "USD" else rates.get((day, target))
                value = amount * target_rate / source_rate if source_rate and target_rate else None
            for key in keys:
                bucket = subtotals.setdefault(key, {})
                previous = bucket.get(target, 0.0)
                bucket[target] = previous + value if previous is not None and value is not None else None
    summary["totals"]["display_costs"] = subtotals.get((), {})
    for row in summary["providers"]:
        row["display_costs"] = subtotals.get(("provider", row["provider"]), {})
    for row in summary["models"]:
        row["display_costs"] = subtotals.get(("model", row["provider"], row["model"]), {})
    for row in summary["request_kinds"]:
        row["display_costs"] = subtotals.get(("kind", row["request_kind"]), {})
    summary["daily_display_costs"] = {key[1]: costs for key, costs in subtotals.items() if key[:1] == ("day",)}
