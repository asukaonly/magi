/**
 * Local cross-encoder reranker model management API.
 */
import { apiClient } from '../client';

export interface LocalRerankerModelInfo {
  id: string;
  label: string;
  repo: string;
  max_tokens: number;
  size_mb: number;
  languages: string[];
  recommended: boolean;
  description: string;
  downloaded: boolean;
  download_in_progress: boolean;
  download_progress_pct: number | null;
}

export interface RerankerDownloadStatusResponse {
  model_id: string;
  status: 'idle' | 'downloading' | 'completed' | 'failed' | 'not_found';
  progress_pct: number | null;
  error: string | null;
}

export const localRerankerApi = {
  async listModels(): Promise<LocalRerankerModelInfo[]> {
    const res = await apiClient.get('/local-reranker/models');
    return res.data;
  },

  async downloadModel(modelId: string): Promise<void> {
    await apiClient.post(`/local-reranker/models/${encodeURIComponent(modelId)}/download`);
  },

  async getDownloadStatus(modelId: string): Promise<RerankerDownloadStatusResponse> {
    const res = await apiClient.get(`/local-reranker/models/${encodeURIComponent(modelId)}/status`);
    return res.data;
  },

  async deleteModel(modelId: string): Promise<void> {
    await apiClient.delete(`/local-reranker/models/${encodeURIComponent(modelId)}`);
  },
};
