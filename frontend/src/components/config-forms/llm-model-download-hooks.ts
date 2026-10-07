import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { EmbeddingConfig } from '@/api/modules/config';
import { localEmbeddingApi, type DownloadStatusResponse } from '@/api/modules/local-embedding';
import { localRerankerApi } from '@/api/modules/local-reranker';
import { pickCenterDirectory } from '@/runtime/center-files';
import { getErrorMessage } from '@/utils/error-handler';
import type { DownloadProgress, ModelDownloadStatus } from '@/api/modules/model-download';

type ModelLibraryApi<Model> = {
  listModels(): Promise<Model[]>;
  downloadModel(modelId: string, variant?: string | null): Promise<ModelDownloadStatus>;
  cancelDownload(modelId: string): Promise<ModelDownloadStatus>;
  deleteModel(modelId: string): Promise<void>;
  getDownloadStatus(modelId: string): Promise<DownloadStatusResponse>;
};

/** Shared lifecycle for the two local model libraries, including serialized polling. */
function useManagedModelLibrary<Model extends { id: string; download_in_progress: boolean; download: DownloadProgress | null }>(api: ModelLibraryApi<Model>, enabled: boolean, downloadFailedMessage: string) {
  const { t } = useTranslation('app');
  const failureMessageRef = useRef(t('common.operationFailed'));
  useEffect(() => { failureMessageRef.current = t('common.operationFailed'); }, [t]);
  const [models, setModels] = useState<Model[]>([]);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const [downloadAccepted, setDownloadAccepted] = useState(false);
  const [progress, setProgress] = useState<ModelDownloadStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const lifetime = useRef(0);
  const listRequest = useRef(0);
  const pendingDownload = useRef(false);
  const actionGeneration = useRef(0);
  const pendingDeletes = useRef(new Set<string>());
  useEffect(() => () => { lifetime.current += 1; listRequest.current += 1; }, []);

  const refresh = useCallback(async () => {
    const requestId = ++listRequest.current;
    try {
      const result = await api.listModels();
      if (requestId !== listRequest.current) return;
      setModels(result);
      const active = result.find(model => model.download_in_progress);
      if (active && !pendingDownload.current) {
        pendingDownload.current = true;
        setDownloadingId(active.id);
        setDownloadAccepted(true);
      }
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
    if (!enabled || !downloadingId || !downloadAccepted) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      const generation = actionGeneration.current;
      try {
        const status = await api.getDownloadStatus(downloadingId);
        if (cancelled) return;
        if (generation !== actionGeneration.current) {
          timer = setTimeout(() => { void poll(); }, 750);
          return;
        }
        setProgress(status);
        if (status.status === 'completed') {
          pendingDownload.current = false;
          setDownloadingId(null);
          void refresh();
          return;
        }
        if (status.status === 'failed' || status.status === 'not_found' || status.status === 'cancelled') {
          pendingDownload.current = false;
          setDownloadingId(null);
          setError(status.status === 'not_found' ? downloadFailedMessage : null);
          return;
        }
        setError(null);
      } catch (reason) {
        if (cancelled) return;
        setError(getErrorMessage(reason) || failureMessageRef.current);
      }
      if (!cancelled) timer = setTimeout(() => { void poll(); }, 750);
    };
    void poll();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [api, enabled, downloadAccepted, downloadingId, downloadFailedMessage, refresh]);

  const download = useCallback(async (modelId: string, variant?: string | null) => {
    if (pendingDownload.current) return;
    pendingDownload.current = true;
    actionGeneration.current += 1;
    listRequest.current += 1;
    const generation = lifetime.current;
    setDownloadAccepted(false);
    setDownloadingId(modelId);
    setProgress(null);
    setError(null);
    try {
      const status = await api.downloadModel(modelId, variant);
      if (generation === lifetime.current) { setProgress(status); setDownloadAccepted(true); }
    } catch (reason) {
      pendingDownload.current = false;
      if (generation !== lifetime.current) return;
      setDownloadingId(null);
      setProgress(null);
      setError(getErrorMessage(reason) || downloadFailedMessage);
    }
  }, [api, downloadFailedMessage]);

  const cancel = useCallback(async () => {
    if (!downloadingId || !downloadAccepted) return;
    const generation = lifetime.current;
    actionGeneration.current += 1;
    listRequest.current += 1;
    try {
      const status = await api.cancelDownload(downloadingId);
      if (generation !== lifetime.current) return;
      actionGeneration.current += 1;
      setProgress(status);
      setDownloadingId(null);
      setDownloadAccepted(false);
      pendingDownload.current = false;
      setError(null);
    } catch (reason) {
      if (generation === lifetime.current) setError(getErrorMessage(reason) || failureMessageRef.current);
    }
  }, [api, downloadAccepted, downloadingId]);

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

  return { models, downloadingId, progress, error, setError, refresh, download, remove, cancel, canCancel: downloadAccepted };
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
      const dir = await pickCenterDirectory(modelDirPath ?? undefined);
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
    handleCancelDownload: library.cancel,
    canCancelDownload: library.canCancel,
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
    handleRerankerCancel: library.cancel,
    canCancelReranker: library.canCancel,
    handleRerankerDelete: library.remove,
  };
}
