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

export interface HistoryImportJob {
  job_id: string;
  source_type: string;
  source_files: string[];
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
  participants: HistoryImportParticipant[];
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

  async confirm(
    jobId: string,
    input: {
      selfParticipants: string[];
      confirmPersonalWriting: boolean;
    },
  ): Promise<HistoryImportJob> {
    const response = await api.post<HistoryImportJob>(
      `/memory/history-imports/${encodeURIComponent(jobId)}/confirm`,
      {
        self_participants: input.selfParticipants,
        confirm_personal_writing: input.confirmPersonalWriting,
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
