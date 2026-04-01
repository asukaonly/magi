/**
 * Local embedding model management API.
 */
import { apiClient } from '../client';

export interface LocalEmbeddingModelInfo {
  id: string;
  label: string;
  repo: string;
  dimension: number;
  max_tokens: number;
  size_mb: number;
  quantized: boolean;
  languages: string[];
  recommended: boolean;
  description: string;
  downloaded: boolean;
}

export interface DiscoveredModel {
  model_id: string;
  path: string;
  has_onnx: boolean;
  has_tokenizer: boolean;
}

export interface DownloadStatusResponse {
  model_id: string;
  status: 'idle' | 'downloading' | 'completed' | 'failed';
  progress: number | null;
  error: string | null;
}

export const localEmbeddingApi = {
  async listModels(): Promise<LocalEmbeddingModelInfo[]> {
    const res = await apiClient.get('/local-embedding/models');
    return res.data;
  },

  async downloadModel(modelId: string): Promise<void> {
    await apiClient.post(`/local-embedding/models/${encodeURIComponent(modelId)}/download`);
  },

  async getDownloadStatus(modelId: string): Promise<DownloadStatusResponse> {
    const res = await apiClient.get(`/local-embedding/models/${encodeURIComponent(modelId)}/status`);
    return res.data;
  },

  async deleteModel(modelId: string): Promise<void> {
    await apiClient.delete(`/local-embedding/models/${encodeURIComponent(modelId)}`);
  },

  async discoverModels(): Promise<DiscoveredModel[]> {
    const res = await apiClient.get('/local-embedding/discovered');
    return res.data;
  },
};
