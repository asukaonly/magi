import { api, unwrapGatewayPayload } from '../client';

export type HistoryImportDetectedKind = 'chat' | 'document' | 'mixed';
export type HistoryImportStatus =
  | 'preview_ready'
  | 'running'
  | 'ready'
  | 'completed'
  | 'failed'
  | 'deleted';

export interface HistoryImportParticipant {
  name: string;
  is_document_author: boolean;
  message_count: number;
  meaningful_count: number;
  sample: string;
}

export interface HistoryImportRecordPreview {
  source_name: string;
  session_id: string;
  session_seq: number;
  speaker_name: string;
  is_document_author: boolean;
  content: string;
  event_at: number;
  timestamp_confidence: string;
}

export interface HistoryImportSourceSummary {
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

export interface HistoryImportJob {
  job_id: string;
  source_type: string;
  source_files: string[];
  included_files: string[];
  detected_kind: HistoryImportDetectedKind;
  status: HistoryImportStatus;
  total_records: number;
  meaningful_records: number;
  quick_target_records: number;
  quick_max_records: number;
  quick_imported_count: number;
  imported_count: number;
  projected_count: number;
  self_participants: string[];
  warnings: string[];
  quick_ready: boolean;
  error_code: string | null;
  created_at: number;
  updated_at: number;
  participants: HistoryImportParticipant[];
  sources: HistoryImportSourceSummary[];
  preview_records: HistoryImportRecordPreview[];
}

export const historyImportsApi = {
  async previewMarkdown(paths: string[]): Promise<HistoryImportJob> {
    const response = await api.post<HistoryImportJob>(
      '/memory/history-imports/markdown/preview',
      { paths },
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

  async updateSelection(
    jobId: string,
    includedFiles: string[],
  ): Promise<HistoryImportJob> {
    const response = await api.patch<HistoryImportJob>(
      `/memory/history-imports/${encodeURIComponent(jobId)}/selection`,
      { included_files: includedFiles },
    );
    return unwrapGatewayPayload(response);
  },

  async confirm(
    jobId: string,
    input: {
      selfParticipants: string[];
      confirmPersonalWriting: boolean;
      includedFiles: string[];
    },
  ): Promise<HistoryImportJob> {
    const response = await api.post<HistoryImportJob>(
      `/memory/history-imports/${encodeURIComponent(jobId)}/confirm`,
      {
        self_participants: input.selfParticipants,
        confirm_personal_writing: input.confirmPersonalWriting,
        included_files: input.includedFiles,
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
