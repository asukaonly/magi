import { api } from '../client';

export interface ModelDownloadStatus {
  model: string;
  status: 'not_downloaded' | 'downloading' | 'ready';
  progress: number;
  message?: string;
  updated_at: number;
}

export const memoryApi = {
  downloadModel: (model: string) =>
    api.post<ModelDownloadStatus>('/memory/models/download', { model }),
  getModelStatus: (model: string) =>
    api.get<ModelDownloadStatus>(`/memory/models/download/${encodeURIComponent(model)}/status`),
  listModels: () =>
    api.get<{ models: string[] }>('/memory/models'),
};

export default memoryApi;
