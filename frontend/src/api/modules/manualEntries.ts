import { api, unwrapGatewayPayload } from '../client';

/** Valence labels matching MoodCalendar's color palette. */
export type MoodValence = 'warm' | 'bright' | 'neutral' | 'cool' | 'tense';

export interface ManualEntry {
  entry_id: string;
  created_at: number;
  event_at: number;
  kind: 'quick' | 'rich';
  body: string;
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
}

export interface ListManualEntriesOptions {
  timeStart: number;
  timeEnd: number;
  includeDeleted?: boolean;
  limit?: number;
}

export interface ManualEntryCreate {
  body: string;
  /** Unix seconds; defaults to now server-side when undefined. */
  event_at?: number;
  mood?: MoodValence | null;
  location_label?: string | null;
  location_lat?: number | null;
  location_lng?: number | null;
  attachment_refs?: string[];
}

export interface ManualEntryUpdate {
  body?: string;
  event_at?: number;
  /** Empty string clears the mood server-side; undefined leaves untouched. */
  mood?: MoodValence | '' | null;
  attachment_refs?: string[];
  user_pinned?: boolean;
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

  async create(body: ManualEntryCreate): Promise<ManualEntry> {
    const response = await api.post<ManualEntry>(`/memory/manual-entries`, body);
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
   * Upload a single image and get back a content-addressed asset_ref.
   * Pass the ref to `create()` / `update()` via `attachment_refs`.
   */
  async uploadAsset(file: File): Promise<AssetUploadResponse> {
    const formData = new FormData();
    formData.append('file', file);
    const response = await api.post<AssetUploadResponse>(
      `/memory/manual-entries/assets`,
      formData,
      { headers: { 'Content-Type': 'multipart/form-data' } },
    );
    return unwrapGatewayPayload(response);
  },
};
