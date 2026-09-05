import { api, apiClient } from '../client';
import { type LifecycleWire, parseHistoryImportJob, parseHistoryImportAppend, parseHistoryImporters, parseHistoryImportList, parseHistorySourcePreview } from '../lifecycle-contract';
import { ApiContractError } from '../config-contract';

const HISTORY_IMPORTER_PREVIEW_TIMEOUT_MS = 75_000;

export type HistoryImportJob = LifecycleWire<'HistoryImportJobResponse'>;
export type HistoryImportParticipant = LifecycleWire<'HistoryImportParticipantResponse'>;
export type HistoryImportRecordPreview = LifecycleWire<'HistoryImportRecordPreviewResponse'>;
export type HistoryImportSourceSummary = LifecycleWire<'HistoryImportSourceSummaryResponse'>;
export type HistoryImportSourcePreview = LifecycleWire<'HistoryImportSourcePreviewResponse'>;
export type HistoryImportWarningSummary = LifecycleWire<'HistoryImportWarningSummaryResponse'>;
export type HistoryImporterSpec = LifecycleWire<'HistoryImporterResponse'>;
export type HistoryImportAppendResult = LifecycleWire<'HistoryImportAppendResponse'>;
export type HistoryImportDetectedKind = HistoryImportJob['detected_kind'];
export type HistoryImportStatus = HistoryImportJob['status'];

export interface HistoryImporterPreviewInput {
  pluginId: string;
  importerId: string;
  paths: string[];
}

export const historyImportsApi = {
  async previewMarkdown(paths: string[]): Promise<HistoryImportJob> {
    const response = await api.post<unknown>(
      '/memory/history-imports/markdown/preview',
      { paths },
    );
    return parseHistoryImportJob(response);
  },

  async appendMarkdown(jobId: string, paths: string[]): Promise<HistoryImportAppendResult> {
    const response = await api.post<unknown>(
      `/memory/history-imports/${encodeURIComponent(jobId)}/markdown/append`,
      { paths },
    );
    return parseHistoryImportAppend(response, jobId);
  },

  async listImporters(): Promise<HistoryImporterSpec[]> {
    const response = await api.get<unknown>(
      '/memory/history-imports/importers',
    );
    return parseHistoryImporters(response);
  },

  async previewWithImporter(input: HistoryImporterPreviewInput): Promise<HistoryImportJob> {
    const response = await api.post<unknown>(
      `/memory/history-imports/importers/${encodeURIComponent(input.pluginId)}/${encodeURIComponent(input.importerId)}/preview`,
      { paths: input.paths },
      { timeout: HISTORY_IMPORTER_PREVIEW_TIMEOUT_MS },
    );
    return parseHistoryImportJob(response);
  },

  async get(jobId: string): Promise<HistoryImportJob> {
    const response = await api.get<unknown>(
      `/memory/history-imports/${encodeURIComponent(jobId)}`,
    );
    return parseHistoryImportJob(response, jobId);
  },

  async list(): Promise<HistoryImportJob[]> {
    const response = await api.get<unknown>(
      '/memory/history-imports',
    );
    return parseHistoryImportList(response);
  },

  async getSourcePreview(
    jobId: string,
    sourceId: string,
    signal?: AbortSignal,
  ): Promise<HistoryImportSourcePreview> {
    const response = await api.get<unknown>(
      `/memory/history-imports/${encodeURIComponent(jobId)}/source-preview`,
      { params: { source_id: sourceId }, signal },
    );
    return parseHistorySourcePreview(response, sourceId);
  },

  async updateSelection(
    jobId: string,
    includedSourceIds: string[],
  ): Promise<HistoryImportJob> {
    const response = await api.patch<unknown>(
      `/memory/history-imports/${encodeURIComponent(jobId)}/selection`,
      { included_source_ids: includedSourceIds },
    );
    return parseHistoryImportJob(response, jobId);
  },

  async confirm(
    jobId: string,
    input: {
      confirmPersonalWriting: boolean;
      includedSourceIds: string[];
      selfParticipantIds?: string[];
    },
  ): Promise<HistoryImportJob> {
    const response = await api.post<unknown>(
      `/memory/history-imports/${encodeURIComponent(jobId)}/confirm`,
      {
        confirm_personal_writing: input.confirmPersonalWriting,
        included_source_ids: input.includedSourceIds,
        self_participant_ids: input.selfParticipantIds ?? [],
      },
    );
    return parseHistoryImportJob(response, jobId);
  },

  async resume(jobId: string): Promise<HistoryImportJob> {
    const response = await api.post<unknown>(
      `/memory/history-imports/${encodeURIComponent(jobId)}/resume`,
    );
    return parseHistoryImportJob(response, jobId);
  },

  async delete(jobId: string): Promise<void> {
    const response = await apiClient.delete<unknown>(
      `/memory/history-imports/${encodeURIComponent(jobId)}`,
    );
    if (response.status !== 204) throw new ApiContractError('Import deletion was not confirmed');
  },
};
