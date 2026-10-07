import { AlertTriangle, Check, Download, Trash2 } from 'lucide-react';
import { ModelDownloadProgress } from '@/components/settings/ModelDownloadProgress';
import type { ModelDownloadStatus } from '@/api/modules/model-download';
import { useTranslation } from 'react-i18next';

import type { CrossEncoderConfig } from '@/api/modules/config';
import type { LocalRerankerModelInfo } from '@/api/modules/local-reranker';
import { SelectField } from '@/components/config-forms/fields';
import { Button } from '@/components/ui/button';

interface LLMRerankerModelPanelProps {
  crossEncoderConfig?: CrossEncoderConfig;
  onCrossEncoderConfigChange?: (updater: (draft: CrossEncoderConfig) => void) => void;
  inputClassName: string;
  onRefreshModels: () => void;
  rerankerModels: LocalRerankerModelInfo[];
  rerankerDownloadingId: string | null;
  rerankerDownloadProgress: ModelDownloadStatus | null;
  onRerankerCancel: () => void;
  canCancelReranker: boolean;
  rerankerDownloadError: string | null;
  onRerankerDownload: (modelId: string) => void;
  onRerankerDelete: (modelId: string) => void;
}

export function LLMRerankerModelPanel({
  crossEncoderConfig,
  onCrossEncoderConfigChange,
  inputClassName,
  onRefreshModels,
  rerankerModels,
  rerankerDownloadingId,
  rerankerDownloadProgress,
  onRerankerCancel,
  canCancelReranker,
  rerankerDownloadError,
  onRerankerDownload,
  onRerankerDelete,
}: LLMRerankerModelPanelProps) {
  const { t: tApp } = useTranslation('app');
  const rerankerMode = crossEncoderConfig?.enabled ? 'local' : 'off';

  if (!crossEncoderConfig || !onCrossEncoderConfigChange) {
    return (
      <p className="text-sm text-muted-foreground">
        {tApp('settings.memory.fields.reranker_not_available')}
      </p>
    );
  }

  return (
    <div className="space-y-3">
      {rerankerDownloadError ? <div role="alert" className="space-y-2 text-xs text-destructive">
        <p className="flex items-center gap-1"><AlertTriangle className="h-3.5 w-3.5" />{rerankerDownloadError}</p>
        <Button type="button" variant="outline" size="sm" onClick={onRefreshModels}>{tApp('common.retryRefresh')}</Button>
      </div> : null}
      <label className="flex flex-col gap-2">
        <span className="text-sm font-medium">{tApp('settings.memory.fields.reranker_mode.label')}</span>
        <SelectField
          className="w-full"
          triggerClassName={inputClassName}
          value={rerankerMode}
          allowEmpty={false}
          options={[
            { label: tApp('settings.options.off'), value: 'off' },
            { label: tApp('settings.options.local'), value: 'local' },
          ]}
          onChange={(value) => onCrossEncoderConfigChange((crossEncoderConfig) => {
            crossEncoderConfig.enabled = value === 'local';
          })}
        />
      </label>

      {rerankerMode === 'local' ? (
        <>
          <label className="flex flex-col gap-2">
            <span className="text-sm font-medium">{tApp('settings.memory.fields.reranker_model.label')}</span>
            <SelectField
              className="w-full"
              triggerClassName={inputClassName}
              value={crossEncoderConfig.managed_model_id ?? ''}
              allowEmpty={false}
              placeholder={tApp('settings.memory.fields.reranker_model.placeholder')}
              options={rerankerModels.map((model) => ({
                label: `${model.label}${model.recommended ? ` (${tApp('settings.memory.fields.reranker_download.recommended')})` : ''} — ${model.size_mb}MB, ${model.languages.join('/')}`,
                value: model.id,
              }))}
              onChange={(value) => onCrossEncoderConfigChange((crossEncoderConfig) => {
                crossEncoderConfig.managed_model_id = value || null;
              })}
            />
          </label>

          {crossEncoderConfig.managed_model_id ? (() => {
            const selectedModel = rerankerModels.find((model) => model.id === crossEncoderConfig.managed_model_id);
            if (!selectedModel) return null;
            const isDownloading = rerankerDownloadingId === selectedModel.id;
            const transfer = rerankerDownloadProgress?.model_id === selectedModel.id ? rerankerDownloadProgress.download : selectedModel.download;
            return (
              <>
                <div className="flex items-center gap-2">
                  {isDownloading ? (
                    <Button type="button" variant="outline" size="sm" disabled={!canCancelReranker} onClick={onRerankerCancel}>{tApp('modelDownload.cancel')}</Button>
                  ) : selectedModel.downloaded ? (
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="text-destructive hover:text-destructive"
                      onClick={() => onRerankerDelete(selectedModel.id)}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                      {tApp('settings.memory.fields.reranker_download.delete')}
                    </Button>
                  ) : (
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => onRerankerDownload(selectedModel.id)}
                    >
                      <Download className="h-3.5 w-3.5" />
                      {tApp(transfer?.phase === 'failed' || transfer?.phase === 'cancelled' ? 'modelDownload.resume' : 'settings.memory.fields.reranker_download.download')}
                    </Button>
                  )}
                  {selectedModel.downloaded && !isDownloading && (
                    <span className="flex items-center gap-1 text-xs text-emerald-600 dark:text-emerald-400">
                      <Check className="h-3.5 w-3.5" />
                      {tApp('settings.memory.fields.reranker_download.downloaded')}
                    </span>
                  )}
                </div>
                <ModelDownloadProgress progress={transfer} active={isDownloading} />

                {selectedModel.description && (
                  <p className="text-xs leading-5 text-muted-foreground">{selectedModel.description}</p>
                )}
              </>
            );
          })() : null}
        </>
      ) : null}
    </div>
  );
}
