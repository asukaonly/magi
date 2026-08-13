import { api, unwrapGatewayPayload } from '../client';

const HISTORY_IMPORTER_PREVIEW_TIMEOUT_MS = 75_000;

export type HistoryImportDetectedKind = 'document' | 'chat' | 'mixed';
export type HistoryImportStatus =
  | 'preview_ready'
  | 'running'
  | 'ready'
  | 'completed'
  | 'failed'
  | 'deleted';

export interface HistoryImportParticipant {
  participant_id: string;
  display_name: string;
  is_document_author: boolean;
  message_count: number;
  meaningful_count: number;
  sample: string;
}

export interface HistoryImportRecordPreview {
  source_id: string;
  source_name: string;
  session_id: string;
  session_seq: number;
  speaker_name: string;
  speaker_id: string;
  is_document_author: boolean;
  content: string;
  event_at: number;
  timestamp_confidence: string;
}

export interface HistoryImportSourceSummary {
  source_id: string;
  source_name: string;
  detected_kind: HistoryImportDetectedKind;
  record_count: number;
  meaningful_count: number;
  first_event_at: number;
  last_event_at: number;
  timestamp_confidence: string;
  sample: string;
  included: boolean;
}

export interface HistoryImportSourcePreview {
  source_id: string;
  source_name: string;
  detected_kind: HistoryImportDetectedKind;
  records: HistoryImportRecordPreview[];
  truncated: boolean;
}

export interface HistoryImportWarningSummary {
  total_count: number;
  codes: string[];
  truncated: boolean;
}

export interface HistoryImportJob {
  job_id: string;
  source_type: string;
  importer_plugin_id: string | null;
  importer_id: string | null;
  source_ids: string[];
  included_source_ids: string[];
  detected_kind: HistoryImportDetectedKind;
  status: HistoryImportStatus;
  total_records: number;
  meaningful_records: number;
  quick_target_records: number;
  quick_max_records: number;
  /** Number of source records saved during the bounded first-contact pass. */
  quick_imported_count: number;
  /** Number of selected source records durably saved as original L1 events. */
  imported_count: number;
  /** Number of saved records accepted by the durable L2 queue, not L2 completion. */
  projected_count: number;
  self_participant_ids: string[];
  warning_summary: HistoryImportWarningSummary;
  quick_ready: boolean;
  error_code: string | null;
  created_at: number;
  updated_at: number;
  participants: HistoryImportParticipant[];
  sources: HistoryImportSourceSummary[];
  preview_records: HistoryImportRecordPreview[];
}

export interface HistoryImporterSpec {
  importer_id: string;
  plugin_id: string;
  display_name: string;
  display_name_i18n: Record<string, string>;
  description: string;
  description_i18n: Record<string, string>;
  accepted_extensions: string[];
  participant_identity_scope: 'source' | 'export';
  export_help_url: string | null;
}

export interface HistoryImporterPreviewInput {
  pluginId: string;
  importerId: string;
  paths: string[];
}

export const historyImportsApi = {
  async previewMarkdown(paths: string[]): Promise<HistoryImportJob> {
    const response = await api.post<HistoryImportJob>(
      '/memory/history-imports/markdown/preview',
      { paths },
    );
    return unwrapGatewayPayload(response);
  },

  async listImporters(): Promise<HistoryImporterSpec[]> {
    const response = await api.get<HistoryImporterSpec[]>(
      '/memory/history-imports/importers',
    );
    return unwrapGatewayPayload(response);
  },

  async previewWithImporter(input: HistoryImporterPreviewInput): Promise<HistoryImportJob> {
    const response = await api.post<HistoryImportJob>(
      `/memory/history-imports/importers/${encodeURIComponent(input.pluginId)}/${encodeURIComponent(input.importerId)}/preview`,
      { paths: input.paths },
      { timeout: HISTORY_IMPORTER_PREVIEW_TIMEOUT_MS },
    );
    return unwrapGatewayPayload(response);
  },

  async get(jobId: string): Promise<HistoryImportJob> {
    const response = await api.get<HistoryImportJob>(
      `/memory/history-imports/${encodeURIComponent(jobId)}`,
    );
    return unwrapGatewayPayload(response);
  },

  async list(): Promise<HistoryImportJob[]> {
    const response = await api.get<HistoryImportJob[]>(
      '/memory/history-imports',
    );
    return unwrapGatewayPayload(response);
  },

  async getSourcePreview(
    jobId: string,
    sourceId: string,
  ): Promise<HistoryImportSourcePreview> {
    const response = await api.get<HistoryImportSourcePreview>(
      `/memory/history-imports/${encodeURIComponent(jobId)}/source-preview`,
      { params: { source_id: sourceId } },
    );
    return unwrapGatewayPayload(response);
  },

  async updateSelection(
    jobId: string,
    includedSourceIds: string[],
  ): Promise<HistoryImportJob> {
    const response = await api.patch<HistoryImportJob>(
      `/memory/history-imports/${encodeURIComponent(jobId)}/selection`,
      { included_source_ids: includedSourceIds },
    );
    return unwrapGatewayPayload(response);
  },

  async confirm(
    jobId: string,
    input: {
      confirmPersonalWriting: boolean;
      includedSourceIds: string[];
      selfParticipantIds?: string[];
    },
  ): Promise<HistoryImportJob> {
    const response = await api.post<HistoryImportJob>(
      `/memory/history-imports/${encodeURIComponent(jobId)}/confirm`,
      {
        confirm_personal_writing: input.confirmPersonalWriting,
        included_source_ids: input.includedSourceIds,
        self_participant_ids: input.selfParticipantIds ?? [],
      },
    );
    return unwrapGatewayPayload(response);
  },

  async resume(jobId: string): Promise<HistoryImportJob> {
    const response = await api.post<HistoryImportJob>(
      `/memory/history-imports/${encodeURIComponent(jobId)}/resume`,
    );
    return unwrapGatewayPayload(response);
  },

  async delete(jobId: string): Promise<void> {
    await api.delete(
      `/memory/history-imports/${encodeURIComponent(jobId)}`,
    );
  },
};
