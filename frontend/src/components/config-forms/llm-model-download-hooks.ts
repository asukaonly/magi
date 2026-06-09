import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';

import type { EmbeddingConfig } from '@/api/modules/config';
import type { LocalEmbeddingModelInfo } from '@/api/modules/local-embedding';
import { localEmbeddingApi } from '@/api/modules/local-embedding';
import type { LocalRerankerModelInfo } from '@/api/modules/local-reranker';
import { localRerankerApi } from '@/api/modules/local-reranker';
import { pickDirectory } from '@/runtime/desktop';

interface UseManagedEmbeddingModelsOptions {
  enabled: boolean;
  modelDirPath?: string | null;
  downloadFailedMessage: string;
  onEmbeddingConfigChange?: (updater: (draft: EmbeddingConfig) => void) => void;
}

export function useManagedEmbeddingModels({
  enabled,
  modelDirPath,
  downloadFailedMessage,
  onEmbeddingConfigChange,
}: UseManagedEmbeddingModelsOptions) {
  const [presetModels, setPresetModels] = useState<LocalEmbeddingModelInfo[]>([]);
  const [downloadingModelId, setDownloadingModelId] = useState<string | null>(null);
  const [downloadProgress, setDownloadProgress] = useState<number | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);

  const refreshPresetModels = useCallback(() => {
    localEmbeddingApi.listModels().then(setPresetModels).catch(() => {});
  }, []);

  useEffect(() => {
    if (enabled) {
      refreshPresetModels();
    }
  }, [enabled, refreshPresetModels]);

  useEffect(() => {
    if (!downloadingModelId) {
      return;
    }
    const interval = setInterval(async () => {
      try {
        const status = await localEmbeddingApi.getDownloadStatus(downloadingModelId);
        if (status.status === 'downloading') {
          setDownloadProgress(status.progress_pct ?? null);
        } else if (status.status === 'completed') {
          setDownloadingModelId(null);
          setDownloadProgress(null);
          refreshPresetModels();
        } else if (status.status === 'failed') {
          setDownloadingModelId(null);
          setDownloadProgress(null);
          setDownloadError(status.error ?? downloadFailedMessage);
          toast.error(status.error ?? downloadFailedMessage);
        }
      } catch {
        // Ignore polling errors.
      }
    }, 1000);
    return () => clearInterval(interval);
  }, [downloadFailedMessage, downloadingModelId, refreshPresetModels]);

  const handleDownloadModel = useCallback(async (modelId: string, variant?: string | null) => {
    setDownloadingModelId(modelId);
    setDownloadProgress(0);
    setDownloadError(null);
    try {
      await localEmbeddingApi.downloadModel(modelId, variant);
    } catch {
      setDownloadingModelId(null);
      setDownloadProgress(null);
    }
  }, []);

  const handleDeleteModel = useCallback(async (modelId: string) => {
    try {
      await localEmbeddingApi.deleteModel(modelId);
      refreshPresetModels();
    } catch {
      // Ignore delete errors.
    }
  }, [refreshPresetModels]);

  const handlePickDirectory = useCallback(async () => {
    const dir = await pickDirectory(modelDirPath ?? undefined);
    if (dir && onEmbeddingConfigChange) {
      onEmbeddingConfigChange((embeddingConfig) => {
        embeddingConfig.local.model_dir_path = dir;
      });
    }
  }, [modelDirPath, onEmbeddingConfigChange]);

  return {
    presetModels,
    downloadingModelId,
    downloadProgress,
    downloadError,
    handleDownloadModel,
    handleDeleteModel,
    handlePickDirectory,
  };
}

interface UseManagedRerankerModelsOptions {
  enabled: boolean;
  downloadFailedMessage: string;
}

export function useManagedRerankerModels({
  enabled,
  downloadFailedMessage,
}: UseManagedRerankerModelsOptions) {
  const [rerankerModels, setRerankerModels] = useState<LocalRerankerModelInfo[]>([]);
  const [rerankerDownloadingId, setRerankerDownloadingId] = useState<string | null>(null);
  const [rerankerDownloadProgress, setRerankerDownloadProgress] = useState<number | null>(null);
  const [rerankerDownloadError, setRerankerDownloadError] = useState<string | null>(null);

  const refreshRerankerModels = useCallback(() => {
    localRerankerApi.listModels().then(setRerankerModels).catch(() => {});
  }, []);

  useEffect(() => {
    if (enabled) {
      refreshRerankerModels();
    }
  }, [enabled, refreshRerankerModels]);

  useEffect(() => {
    if (!rerankerDownloadingId) {
      return;
    }
    const interval = setInterval(async () => {
      try {
        const status = await localRerankerApi.getDownloadStatus(rerankerDownloadingId);
        if (status.status === 'downloading') {
          setRerankerDownloadProgress(status.progress_pct ?? null);
        } else if (status.status === 'completed') {
          setRerankerDownloadingId(null);
          setRerankerDownloadProgress(null);
          refreshRerankerModels();
        } else if (status.status === 'failed') {
          setRerankerDownloadingId(null);
          setRerankerDownloadProgress(null);
          setRerankerDownloadError(status.error ?? downloadFailedMessage);
          toast.error(status.error ?? downloadFailedMessage);
        }
      } catch {
        // Ignore polling errors.
      }
    }, 1000);
    return () => clearInterval(interval);
  }, [downloadFailedMessage, refreshRerankerModels, rerankerDownloadingId]);

  const handleRerankerDownload = useCallback(async (modelId: string) => {
    setRerankerDownloadingId(modelId);
    setRerankerDownloadProgress(0);
    setRerankerDownloadError(null);
    try {
      await localRerankerApi.downloadModel(modelId);
    } catch {
      setRerankerDownloadingId(null);
      setRerankerDownloadProgress(null);
    }
  }, []);

  const handleRerankerDelete = useCallback(async (modelId: string) => {
    try {
      await localRerankerApi.deleteModel(modelId);
      refreshRerankerModels();
    } catch {
      // Ignore delete errors.
    }
  }, [refreshRerankerModels]);

  return {
    rerankerModels,
    rerankerDownloadingId,
    rerankerDownloadProgress,
    rerankerDownloadError,
    handleRerankerDownload,
    handleRerankerDelete,
  };
}