/**
 * Local cross-encoder reranker model management API.
 */
import { apiClient } from '../client';
import { z } from 'zod';
import { readModelDownloadStatus, type ModelDownloadStatus, type DownloadProgress } from './model-download';
import { validateDownloadProgress } from '../generated/model-download-validators';

export interface LocalRerankerVariantInfo {
  name: string;
  file: string;
  size_mb: number;
  downloaded: boolean;
}

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
  download: DownloadProgress | null;
  variants: LocalRerankerVariantInfo[];
  default_variant: string | null;
}

export type RerankerDownloadStatusResponse = ModelDownloadStatus;

const modelSchema = z.object({
  id: z.string(), label: z.string(), repo: z.string(), max_tokens: z.number(), size_mb: z.number(),
  languages: z.array(z.string()), recommended: z.boolean(), description: z.string(), downloaded: z.boolean(),
  download_in_progress: z.boolean(), download: z.custom<DownloadProgress>(validateDownloadProgress).nullable(),
  variants: z.array(z.object({ name: z.string(), file: z.string(), size_mb: z.number(), downloaded: z.boolean() })),
  default_variant: z.string().nullable(),
});

export const localRerankerApi = {
  async listModels(): Promise<LocalRerankerModelInfo[]> {
    const res = await apiClient.get<unknown>('/local-reranker/models');
    return z.array(modelSchema).parse(res.data);
  },

  async downloadModel(modelId: string, variant?: string | null): Promise<ModelDownloadStatus> {
    const config = variant ? { params: { variant } } : undefined;
    const response = await apiClient.post<unknown>(
      `/local-reranker/models/${encodeURIComponent(modelId)}/download`,
      undefined,
      config,
    );
    return readModelDownloadStatus(response.data);
  },

  async getDownloadStatus(modelId: string): Promise<RerankerDownloadStatusResponse> {
    const res = await apiClient.get<unknown>(`/local-reranker/models/${encodeURIComponent(modelId)}/status`);
    return readModelDownloadStatus(res.data);
  },
  async cancelDownload(modelId: string): Promise<ModelDownloadStatus> {
    const response = await apiClient.post<unknown>(`/local-reranker/models/${encodeURIComponent(modelId)}/download/cancel`);
    return readModelDownloadStatus(response.data);
  },

  async deleteModel(modelId: string): Promise<void> {
    await apiClient.delete(`/local-reranker/models/${encodeURIComponent(modelId)}`);
  },
};
