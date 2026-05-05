export function isInteractionExpired(
  expiresAtMs: number | null | undefined,
  nowMs: number = Date.now(),
): boolean {
  return typeof expiresAtMs === 'number'
    && Number.isFinite(expiresAtMs)
    && expiresAtMs > 0
    && expiresAtMs <= nowMs;
}

export function remainingInteractionSeconds(
  expiresAtMs: number | null | undefined,
  nowMs: number = Date.now(),
): number | null {
  if (typeof expiresAtMs !== 'number' || !Number.isFinite(expiresAtMs) || expiresAtMs <= 0) {
    return null;
  }
  return Math.max(0, Math.ceil((expiresAtMs - nowMs) / 1000));
}
