/**
 * Local embedding model management API.
 */
import { apiClient } from '../client';

export interface LocalEmbeddingVariantInfo {
  name: string;
  file: string;
  size_mb: number;
  downloaded: boolean;
}

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
  variants: LocalEmbeddingVariantInfo[];
  default_variant: string | null;
}

export interface DiscoveredModel {
  model_id: string;
  path: string;
  has_onnx: boolean;
  has_tokenizer: boolean;
}

export interface DownloadStatusResponse {
  model_id: string;
  status: 'idle' | 'downloading' | 'completed' | 'failed' | 'not_found';
  progress_pct: number | null;
  error: string | null;
}

export const localEmbeddingApi = {
  async listModels(): Promise<LocalEmbeddingModelInfo[]> {
    const res = await apiClient.get('/local-embedding/models');
    return res.data;
  },

  async downloadModel(modelId: string, variant?: string | null): Promise<void> {
    const params = variant ? { variant } : undefined;
    await apiClient.post(
      `/local-embedding/models/${encodeURIComponent(modelId)}/download`,
      undefined,
      params ? { params } : undefined,
    );
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
