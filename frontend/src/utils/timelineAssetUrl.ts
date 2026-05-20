import { getRuntimeConfig } from '@/runtime/config';

/**
 * Resolve a timeline asset_ref (e.g. "photo-library://2026-05-17/IMG.HEIC",
 * "manual-entry-asset://<sha>.jpg") into an absolute URL the browser can
 * <img src> from.
 *
 * IMPORTANT: must return an absolute URL using the runtime's apiBaseUrl,
 * not a relative `/api/...` path. <img>/<video>/etc. tags use the
 * browser's native fetcher, which resolves relative URLs against the
 * page origin — in dev that's Vite (5173), whose proxy is hardcoded to
 * :8000 and misses the desktop backend's dynamic port. axios calls
 * already bypass Vite via apiBaseUrl; this helper closes the gap for
 * everything that goes through the DOM directly.
 *
 * Returns null for empty or unrecognized refs so callers can fall back
 * to the atmospheric-gradient placeholder.
 */
export function resolveTimelineAssetUrl(assetRef: string | null | undefined): string | null {
  if (!assetRef) return null;
  const trimmed = assetRef.trim();
  if (!trimmed) return null;

  // apiBaseUrl is "http://localhost:<port>/api" — strip a trailing slash
  // just in case, then append the per-asset path. The backend gateway
  // accepts any asset scheme; it 404s for unknown ones.
  const base = getRuntimeConfig().apiBaseUrl.replace(/\/+$/, '');
  return `${base}/timeline/asset/${encodeURIComponent(trimmed)}`;
}
