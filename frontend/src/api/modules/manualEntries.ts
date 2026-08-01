import { api, unwrapGatewayPayload } from '../client';

/** Valence labels matching MoodCalendar's color palette. */
export type MoodValence = 'warm' | 'bright' | 'neutral' | 'cool' | 'tense';

/** Ambient weather snapshot resolved against Open-Meteo at the entry's
 *  event_at + nearest location sample. `code` is a WMO weather code
 *  (see WMO_EMOJI). Null on the entry when the fetcher couldn't resolve
 *  coords or reach the API — render the chip conditionally. */
export interface ManualEntryWeather {
  code: number;
  temp_c: number;
  fetched_at: number;
}

export interface ManualEntry {
  entry_id: string;
  created_at: number;
  event_at: number;
  kind: 'quick' | 'rich';
  body: string;
  /** ProseMirror JSON document for the rich-text editor (Phase B-2).
   *  Null means render `body` as plain text. Keep both in sync on save:
   *  the canonical text projection in `body` is what L1 / search /
   *  diary LLM read, while `body_doc` preserves formatting fidelity. */
  body_doc: Record<string, unknown> | null;
  mood: MoodValence | null;
  location_label: string | null;
  location_lat: number | null;
  location_lng: number | null;
  /** List of ``manual-entry-asset://<sha>.<ext>`` refs. Resolved via the
   *  existing /api/timeline/asset/{ref:path} route. */
  attachments: string[];
  exclude_from_llm: boolean;
  user_pinned: boolean;
  deleted_at: number | null;
  l1_event_id: string | null;
  weather: ManualEntryWeather | null;
}

/** WMO weather code → emoji. Mirrored from the backend WMO_CATEGORY
 *  table; keep both sides in sync when adding codes. Codes outside the
 *  table fall back to the rendering caller (which can decide to drop
 *  the chip rather than show a generic ❓). */
export const WMO_EMOJI: Record<number, string> = {
  0: '☀️',
  1: '🌤️',
  2: '⛅',
  3: '☁️',
  45: '🌫️',
  48: '🌫️',
  51: '🌦️',
  53: '🌦️',
  55: '🌦️',
  56: '🌦️',
  57: '🌦️',
  61: '🌧️',
  63: '🌧️',
  65: '🌧️',
  66: '🌧️',
  67: '🌧️',
  71: '🌨️',
  73: '🌨️',
  75: '🌨️',
  77: '🌨️',
  80: '🌧️',
  81: '🌧️',
  82: '🌧️',
  85: '🌨️',
  86: '🌨️',
  95: '⛈️',
  96: '⛈️',
  99: '⛈️',
};

export function weatherEmoji(code: number | null | undefined): string | null {
  if (code == null) return null;
  return WMO_EMOJI[code] ?? null;
}

export interface ListManualEntriesOptions {
  timeStart: number;
  timeEnd: number;
  includeDeleted?: boolean;
  limit?: number;
}

export interface ManualEntryCreate {
  /** Stable client-owned identity. Reuse it when retrying the same draft. */
  entry_id: string;
  body: string;
  /** Optional ProseMirror JSON; if set, the entry round-trips with
   *  formatting preserved. Both fields are derived from the same
   *  editor state on save (plain text via editor.getText(), JSON via
   *  editor.getJSON()). */
  body_doc?: Record<string, unknown> | null;
  /** Unix seconds; defaults to now server-side when undefined. */
  event_at?: number;
  mood?: MoodValence | null;
  location_label?: string | null;
  location_lat?: number | null;
  location_lng?: number | null;
  attachment_refs?: string[];
}

export interface ManualEntryCreateResult extends ManualEntry {
  /** Whether recall-ready memory is linked or will be completed in the background. */
  memory_status: 'ready' | 'pending';
}

export interface ManualEntryUpdate {
  body?: string;
  body_doc?: Record<string, unknown> | null;
  /** Explicit flag to clear body_doc — JSON docs don't have a natural
   *  empty form, so we can't reuse the empty-string-clears convention. */
  clear_body_doc?: boolean;
  event_at?: number;
  /** Empty string clears the mood server-side; undefined leaves untouched. */
  mood?: MoodValence | '' | null;
  attachment_refs?: string[];
  user_pinned?: boolean;
  /** Empty string clears the location label server-side; undefined leaves
   *  untouched. Same empty-string-clears convention as mood. */
  location_label?: string | null;
}

export interface AssetUploadResponse {
  asset_ref: string;
  content_type: string;
  byte_size: number;
}

export const manualEntriesApi = {
  async list({
    timeStart, timeEnd, includeDeleted = false, limit = 500,
  }: ListManualEntriesOptions): Promise<ManualEntry[]> {
    const response = await api.get<{ items: ManualEntry[] }>(
      `/memory/manual-entries`,
      {
        params: {
          time_start: timeStart,
          time_end: timeEnd,
          include_deleted: includeDeleted,
          limit,
        },
      },
    );
    const data = unwrapGatewayPayload(response);
    return data.items || [];
  },

  async create(body: ManualEntryCreate): Promise<ManualEntryCreateResult> {
    const response = await api.post<ManualEntryCreateResult>(
      `/memory/manual-entries`,
      body,
    );
    return unwrapGatewayPayload(response);
  },

  async update(entryId: string, patch: ManualEntryUpdate): Promise<ManualEntry> {
    const response = await api.patch<ManualEntry>(
      `/memory/manual-entries/${encodeURIComponent(entryId)}`,
      patch,
    );
    return unwrapGatewayPayload(response);
  },

  async remove(entryId: string): Promise<void> {
    await api.delete(`/memory/manual-entries/${encodeURIComponent(entryId)}`);
  },

  /**
   * Clear the auto-resolved weather snapshot. Idempotent — safe to call
   * even when the entry has no weather attached. Returns the updated
   * entry (with `weather: null`).
   */
  async clearWeather(entryId: string): Promise<ManualEntry> {
    const response = await api.delete<ManualEntry>(
      `/memory/manual-entries/${encodeURIComponent(entryId)}/weather`,
    );
    return unwrapGatewayPayload(response);
  },

  /**
   * Upload a single image and get back a content-addressed asset_ref.
   * Pass the ref to `create()` / `update()` via `attachment_refs`.
   */
  async uploadAsset(
    file: File,
    options: { signal?: AbortSignal } = {},
  ): Promise<AssetUploadResponse> {
    const formData = new FormData();
    formData.append('file', file);
    const response = await api.post<AssetUploadResponse>(
      `/memory/manual-entries/assets`,
      formData,
      {
        headers: { 'Content-Type': 'multipart/form-data' },
        signal: options.signal,
      },
    );
    return unwrapGatewayPayload(response);
  },
};
