import { api } from '../client';

export interface ModelDownloadStatus {
  model: string;
  status: 'not_downloaded' | 'downloading' | 'ready';
  progress: number;
  message?: string;
  updated_at: number;
}

export interface ClearMemoryResult {
  cleared: boolean;
  count: number;
}

export interface ClearMemoryResponse {
  success: boolean;
  results: {
    l1_raw: ClearMemoryResult;
    l2_relations: ClearMemoryResult;
    l3_embeddings: ClearMemoryResult;
    l4_summaries: ClearMemoryResult;
    l5_capabilities: ClearMemoryResult;
    chat_context: ClearMemoryResult;
  };
  warnings?: string[];
}

export const memoryApi = {
  downloadModel: (model: string) =>
    api.post<ModelDownloadStatus>('/memory/models/download', { model }),
  getModelStatus: (model: string) =>
    api.get<ModelDownloadStatus>(`/memory/models/download/${encodeURIComponent(model)}/status`),
  listModels: () =>
    api.get<{ models: string[] }>('/memory/models'),
  clearAll: () =>
    api.delete<ClearMemoryResponse>('/memory/clear'),
};

export default memoryApi;
