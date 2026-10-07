/**
 * Local embedding model management API.
 */
import { apiClient } from '../client';
import { z } from 'zod';
import { readModelDownloadStatus, type ModelDownloadStatus, type DownloadProgress } from './model-download';
import { validateDownloadProgress } from '../generated/model-download-validators';

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
  download_in_progress: boolean;
  download: DownloadProgress | null;
  variants: LocalEmbeddingVariantInfo[];
  default_variant: string | null;
}

export interface DiscoveredModel {
  dir_name: string;
  path: string;
  has_onnx: boolean;
  has_tokenizer: boolean;
  has_config: boolean;
  dimension: number | null;
}

export type DownloadStatusResponse = ModelDownloadStatus;

const modelSchema = z.object({
  id: z.string(), label: z.string(), repo: z.string(), max_tokens: z.number(), size_mb: z.number(),
  languages: z.array(z.string()), recommended: z.boolean(), description: z.string(), downloaded: z.boolean(),
  download_in_progress: z.boolean(), download: z.custom<DownloadProgress>(validateDownloadProgress).nullable(),
  variants: z.array(z.object({ name: z.string(), file: z.string(), size_mb: z.number(), downloaded: z.boolean() })),
  default_variant: z.string().nullable(), dimension: z.number(), quantized: z.boolean(),
});

export const localEmbeddingApi = {
  async listModels(): Promise<LocalEmbeddingModelInfo[]> {
    const res = await apiClient.get<unknown>('/local-embedding/models');
    return z.array(modelSchema).parse(res.data);
  },

  async downloadModel(modelId: string, variant?: string | null): Promise<ModelDownloadStatus> {
    const params = variant ? { variant } : undefined;
    const response = await apiClient.post<unknown>(
      `/local-embedding/models/${encodeURIComponent(modelId)}/download`,
      undefined,
      params ? { params } : undefined,
    );
    return readModelDownloadStatus(response.data);
  },

  async getDownloadStatus(modelId: string): Promise<DownloadStatusResponse> {
    const res = await apiClient.get<unknown>(`/local-embedding/models/${encodeURIComponent(modelId)}/status`);
    return readModelDownloadStatus(res.data);
  },
  async cancelDownload(modelId: string): Promise<ModelDownloadStatus> {
    const response = await apiClient.post<unknown>(`/local-embedding/models/${encodeURIComponent(modelId)}/download/cancel`);
    return readModelDownloadStatus(response.data);
  },

  async deleteModel(modelId: string): Promise<void> {
    await apiClient.delete(`/local-embedding/models/${encodeURIComponent(modelId)}`);
  },

  async discoverModels(): Promise<DiscoveredModel[]> {
    const res = await apiClient.get<DiscoveredModel[]>('/local-embedding/discovered');
    return res.data;
  },
};
