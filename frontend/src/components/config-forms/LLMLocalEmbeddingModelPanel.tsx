import { AlertTriangle, Check, Download, FolderOpen, Loader2, Trash2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import type { EmbeddingConfig } from '@/api/modules/config';
import type { LocalEmbeddingModelInfo } from '@/api/modules/local-embedding';
import { SelectField } from '@/components/config-forms/fields';
import { Button } from '@/components/ui/button';

interface LLMLocalEmbeddingModelPanelProps {
  embeddingConfig: EmbeddingConfig;
  onEmbeddingConfigChange: (updater: (draft: EmbeddingConfig) => void) => void;
  inputClassName: string;
  presetModels: LocalEmbeddingModelInfo[];
  downloadingModelId: string | null;
  downloadProgress: number | null;
  downloadError: string | null;
  onDownloadModel: (modelId: string) => void;
  onDeleteModel: (modelId: string) => void;
  onPickDirectory: () => void;
}

export function LLMLocalEmbeddingModelPanel({
  embeddingConfig,
  onEmbeddingConfigChange,
  inputClassName,
  presetModels,
  downloadingModelId,
  downloadProgress,
  downloadError,
  onDownloadModel,
  onDeleteModel,
  onPickDirectory,
}: LLMLocalEmbeddingModelPanelProps) {
  const { t: tApp } = useTranslation('app');

  return (
    <div className="space-y-3">
      <label className="space-y-2">
        <span className="text-sm font-medium">{tApp('settings.memory.fields.embedding_local_model_source.label')}</span>
        <SelectField
          className="w-full"
          triggerClassName={inputClassName}
          value={embeddingConfig.local.model_source}
          allowEmpty={false}
          options={[
            { label: tApp('settings.memory.options.embedding_local_model_source.managed'), value: 'managed' },
            { label: tApp('settings.memory.options.embedding_local_model_source.external'), value: 'external' },
          ]}
          onChange={(value) => onEmbeddingConfigChange((embeddingConfig) => {
            embeddingConfig.local.model_source = value as typeof embeddingConfig.local.model_source;
          })}
        />
      </label>

      {embeddingConfig.local.model_source === 'managed' ? (
        <>
          <label className="space-y-2">
            <span className="text-sm font-medium">{tApp('settings.memory.fields.embedding_local_managed_model_id.label')}</span>
            <SelectField
              className="w-full"
              triggerClassName={inputClassName}
              value={embeddingConfig.local.managed_model_id ?? ''}
              allowEmpty={false}
              placeholder={tApp('settings.memory.fields.embedding_local_managed_model_id.placeholder')}
              options={presetModels.map((model) => ({
                label: `${model.label}${model.recommended ? ` (${tApp('settings.memory.fields.embedding_local_download.recommended')})` : ''} — ${model.dimension}d, ${model.size_mb}MB`,
                value: model.id,
              }))}
              onChange={(value) => onEmbeddingConfigChange((embeddingConfig) => {
                embeddingConfig.local.managed_model_id = value || null;
              })}
            />
          </label>

          {embeddingConfig.local.managed_model_id ? (() => {
            const selectedModel = presetModels.find((model) => model.id === embeddingConfig.local.managed_model_id);
            if (!selectedModel) return null;
            const isDownloading = downloadingModelId === selectedModel.id;
            return (
              <>
                <div className="flex items-center gap-2">
                  {selectedModel.downloaded ? (
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="text-destructive hover:text-destructive"
                      onClick={() => onDeleteModel(selectedModel.id)}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                      {tApp('settings.memory.fields.embedding_local_download.delete')}
                    </Button>
                  ) : isDownloading ? (
                    <Button type="button" variant="outline" size="sm" disabled>
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      {tApp('settings.memory.fields.embedding_local_download.downloading')}
                      {downloadProgress !== null ? ` ${Math.round(downloadProgress)}%` : ''}
                    </Button>
                  ) : (
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => onDownloadModel(selectedModel.id)}
                    >
                      <Download className="h-3.5 w-3.5" />
                      {tApp('settings.memory.fields.embedding_local_download.download')}
                    </Button>
                  )}
                  {selectedModel.downloaded && (
                    <span className="flex items-center gap-1 text-xs text-emerald-600 dark:text-emerald-400">
                      <Check className="h-3.5 w-3.5" />
                      {tApp('settings.memory.fields.embedding_local_download.downloaded')}
                    </span>
                  )}
                </div>
                {downloadError && !isDownloading && !selectedModel.downloaded && (
                  <p className="mt-1 flex items-center gap-1 text-xs text-destructive">
                    <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
                    {downloadError}
                  </p>
                )}
              </>
            );
          })() : null}
        </>
      ) : (
        <div className="space-y-2">
          <span className="text-sm font-medium">{tApp('settings.memory.fields.embedding_local_model_dir_path.label')}</span>
          <div className="flex gap-2">
            <input
              aria-label={tApp('settings.memory.fields.embedding_local_model_dir_path.label')}
              className={inputClassName}
              value={embeddingConfig.local.model_dir_path ?? ''}
              readOnly
              placeholder={tApp('settings.memory.fields.embedding_local_model_dir_path.placeholder')}
            />
            <Button
              type="button"
              variant="outline"
              className="h-11 shrink-0"
              onClick={onPickDirectory}
            >
              <FolderOpen className="h-4 w-4" />
            </Button>
          </div>
        </div>
      )}

      <label className="space-y-2">
        <span className="text-sm font-medium">{tApp('settings.memory.fields.embedding_local_idle_timeout.label')}</span>
        <input
          aria-label={tApp('settings.memory.fields.embedding_local_idle_timeout.label')}
          className={inputClassName}
          type="number"
          min={1}
          step={1}
          value={String(Math.round(embeddingConfig.local.idle_timeout_seconds / 60))}
          onChange={(event) => {
            const nextValue = event.target.value.trim();
            onEmbeddingConfigChange((embeddingConfig) => {
              embeddingConfig.local.idle_timeout_seconds = nextValue ? Number(nextValue) * 60 : 1800;
            });
          }}
        />
      </label>

      <p className="text-xs leading-5 text-muted-foreground">
        {tApp('settings.memory.fields.embedding_local_managed_cache_path.description')}
      </p>
    </div>
  );
}