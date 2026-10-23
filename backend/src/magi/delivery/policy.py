"""Shared delivery retry and lease policy; business stores retain transaction ownership."""
MAX_ATTEMPTS = 5
SEND_TIMEOUT_SECONDS = 30.0
PREPARATION_TIMEOUT_SECONDS = 120.0
LEASE_MS = int((PREPARATION_TIMEOUT_SECONDS + SEND_TIMEOUT_SECONDS + 30) * 1000)
LIFETIME_MS = 86_400_000
UNAVAILABLE_RETRY_MS = 5000


def retry_delay_ms(attempt_count: int) -> int:
    return min(300_000, 1000 * 2 ** min(attempt_count, 8))
