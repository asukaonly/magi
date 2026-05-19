/**
 * Resolve a timeline asset_ref (e.g. "photo-library://2026-05-17/IMG.HEIC")
 * into a URL the browser can <img src> from.
 *
 * Returns null for empty or unrecognized refs so callers can fall back to
 * the atmospheric-gradient placeholder.
 */
export function resolveTimelineAssetUrl(assetRef: string | null | undefined): string | null {
  if (!assetRef) return null;
  const trimmed = assetRef.trim();
  if (!trimmed) return null;

  // The backend gateway accepts any asset scheme; it will 404 for unknown ones.
  return `/api/timeline/asset/${encodeURIComponent(trimmed)}`;
}
