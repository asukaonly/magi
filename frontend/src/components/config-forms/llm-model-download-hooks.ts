import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { EmbeddingConfig } from '@/api/modules/config';
import { localEmbeddingApi, type DownloadStatusResponse } from '@/api/modules/local-embedding';
import { localRerankerApi } from '@/api/modules/local-reranker';
import { pickDirectory } from '@/runtime/desktop';
import { getErrorMessage } from '@/utils/error-handler';

type ModelLibraryApi<Model> = {
  listModels(): Promise<Model[]>;
  downloadModel(modelId: string, variant?: string | null): Promise<void>;
  deleteModel(modelId: string): Promise<void>;
  getDownloadStatus(modelId: string): Promise<DownloadStatusResponse>;
};

/** Shared lifecycle for the two local model libraries, including serialized polling. */
function useManagedModelLibrary<Model>(api: ModelLibraryApi<Model>, enabled: boolean, downloadFailedMessage: string) {
  const { t } = useTranslation('app');
  const failureMessageRef = useRef(t('common.operationFailed'));
  useEffect(() => { failureMessageRef.current = t('common.operationFailed'); }, [t]);
  const [models, setModels] = useState<Model[]>([]);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const [downloadAccepted, setDownloadAccepted] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const lifetime = useRef(0);
  const listRequest = useRef(0);
  const pendingDownload = useRef(false);
  const pendingDeletes = useRef(new Set<string>());
  useEffect(() => () => { lifetime.current += 1; listRequest.current += 1; }, []);

  const refresh = useCallback(async () => {
    const requestId = ++listRequest.current;
    try {
      const result = await api.listModels();
      if (requestId !== listRequest.current) return;
      setModels(result);
      setError(null);
    } catch (reason) {
      if (requestId === listRequest.current) setError(getErrorMessage(reason) || failureMessageRef.current);
    }
  }, [api]);

  useEffect(() => {
    if (enabled) void refresh();
    return () => { listRequest.current += 1; };
  }, [enabled, refresh]);

  useEffect(() => {
    if (!downloadingId || !downloadAccepted) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const status = await api.getDownloadStatus(downloadingId);
        if (cancelled) return;
        if (status.status === 'completed') {
          pendingDownload.current = false;
          setDownloadingId(null);
          setProgress(null);
          void refresh();
          return;
        }
        if (status.status === 'failed' || status.status === 'not_found' || status.status === 'idle') {
          pendingDownload.current = false;
          setDownloadingId(null);
          setProgress(null);
          setError(status.error || downloadFailedMessage);
          return;
        }
        setProgress(status.progress_pct);
        setError(null);
      } catch (reason) {
        if (cancelled) return;
        setError(getErrorMessage(reason) || failureMessageRef.current);
      }
      if (!cancelled) timer = setTimeout(() => { void poll(); }, 1000);
    };
    timer = setTimeout(() => { void poll(); }, 1000);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [api, downloadAccepted, downloadingId, downloadFailedMessage, refresh]);

  const download = useCallback(async (modelId: string, variant?: string | null) => {
    if (pendingDownload.current) return;
    pendingDownload.current = true;
    const generation = lifetime.current;
    setDownloadAccepted(false);
    setDownloadingId(modelId);
    setProgress(0);
    setError(null);
    try {
      await api.downloadModel(modelId, variant);
      if (generation === lifetime.current) setDownloadAccepted(true);
    } catch (reason) {
      pendingDownload.current = false;
      if (generation !== lifetime.current) return;
      setDownloadingId(null);
      setProgress(null);
      setError(getErrorMessage(reason) || downloadFailedMessage);
    }
  }, [api, downloadFailedMessage]);

  const remove = useCallback(async (modelId: string) => {
    if (pendingDeletes.current.has(modelId) || downloadingId === modelId) return;
    pendingDeletes.current.add(modelId);
    const generation = lifetime.current;
    setError(null);
    try {
      await api.deleteModel(modelId);
      if (generation === lifetime.current) await refresh();
    } catch (reason) {
      if (generation === lifetime.current) setError(getErrorMessage(reason) || failureMessageRef.current);
    } finally {
      pendingDeletes.current.delete(modelId);
    }
  }, [api, downloadingId, refresh]);

  return { models, downloadingId, progress, error, setError, refresh, download, remove };
}

interface UseManagedEmbeddingModelsOptions {
  enabled: boolean;
  modelDirPath?: string | null;
  downloadFailedMessage: string;
  onEmbeddingConfigChange?: (updater: (draft: EmbeddingConfig) => void) => void;
}

export function useManagedEmbeddingModels({ enabled, modelDirPath, downloadFailedMessage, onEmbeddingConfigChange }: UseManagedEmbeddingModelsOptions) {
  const library = useManagedModelLibrary(localEmbeddingApi, enabled, downloadFailedMessage);
  const { t } = useTranslation('app');
  const { setError } = library;
  const pickerGeneration = useRef(0);
  useEffect(() => () => { pickerGeneration.current += 1; }, []);
  const handlePickDirectory = useCallback(async () => {
    const generation = ++pickerGeneration.current;
    try {
      const dir = await pickDirectory(modelDirPath ?? undefined);
      if (generation === pickerGeneration.current && dir && onEmbeddingConfigChange) {
        onEmbeddingConfigChange((draft) => { draft.local.model_dir_path = dir; });
      }
    } catch (reason) {
      if (generation === pickerGeneration.current) setError(getErrorMessage(reason) || t('common.operationFailed'));
    }
  }, [modelDirPath, onEmbeddingConfigChange, setError, t]);
  return {
    presetModels: library.models,
    downloadingModelId: library.downloadingId,
    downloadProgress: library.progress,
    downloadError: library.error,
    refreshPresetModels: library.refresh,
    handleDownloadModel: library.download,
    handleDeleteModel: library.remove,
    handlePickDirectory,
  };
}

export function useManagedRerankerModels({ enabled, downloadFailedMessage }: { enabled: boolean; downloadFailedMessage: string }) {
  const library = useManagedModelLibrary(localRerankerApi, enabled, downloadFailedMessage);
  return {
    rerankerModels: library.models,
    rerankerDownloadingId: library.downloadingId,
    rerankerDownloadProgress: library.progress,
    rerankerDownloadError: library.error,
    refreshRerankerModels: library.refresh,
    handleRerankerDownload: library.download,
    handleRerankerDelete: library.remove,
  };
}
