import { AlertTriangle, Check, Download, Loader2, Trash2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import type { CrossEncoderConfig } from '@/api/modules/config';
import type { LocalRerankerModelInfo } from '@/api/modules/local-reranker';
import { SelectField } from '@/components/config-forms/fields';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';

interface LLMRerankerModelPanelProps {
  crossEncoderConfig?: CrossEncoderConfig;
  onCrossEncoderConfigChange?: (updater: (draft: CrossEncoderConfig) => void) => void;
  inputClassName: string;
  rerankerModels: LocalRerankerModelInfo[];
  rerankerDownloadingId: string | null;
  rerankerDownloadProgress: number | null;
  rerankerDownloadError: string | null;
  onRerankerDownload: (modelId: string) => void;
  onRerankerDelete: (modelId: string) => void;
}

export function LLMRerankerModelPanel({
  crossEncoderConfig,
  onCrossEncoderConfigChange,
  inputClassName,
  rerankerModels,
  rerankerDownloadingId,
  rerankerDownloadProgress,
  rerankerDownloadError,
  onRerankerDownload,
  onRerankerDelete,
}: LLMRerankerModelPanelProps) {
  const { t: tApp } = useTranslation('app');

  if (!crossEncoderConfig || !onCrossEncoderConfigChange) {
    return (
      <p className="text-sm text-muted-foreground">
        {tApp('settings.memory.fields.reranker_not_available')}
      </p>
    );
  }

  return (
    <div className="space-y-3">
      <label className="flex items-center justify-between gap-3">
        <span className="text-sm font-medium">{tApp('settings.memory.fields.reranker_enabled.label')}</span>
        <Switch
          checked={crossEncoderConfig.enabled}
          onCheckedChange={(checked) => onCrossEncoderConfigChange((crossEncoderConfig) => {
            crossEncoderConfig.enabled = checked;
          })}
        />
      </label>

      {crossEncoderConfig.enabled ? (
        <>
          <label className="space-y-2">
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
            return (
              <>
                <div className="flex items-center gap-2">
                  {selectedModel.downloaded ? (
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
                  ) : isDownloading ? (
                    <Button type="button" variant="outline" size="sm" disabled>
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      {tApp('settings.memory.fields.reranker_download.downloading')}
                      {rerankerDownloadProgress !== null ? ` ${Math.round(rerankerDownloadProgress)}%` : ''}
                    </Button>
                  ) : (
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => onRerankerDownload(selectedModel.id)}
                    >
                      <Download className="h-3.5 w-3.5" />
                      {tApp('settings.memory.fields.reranker_download.download')}
                    </Button>
                  )}
                  {selectedModel.downloaded && (
                    <span className="flex items-center gap-1 text-xs text-emerald-600 dark:text-emerald-400">
                      <Check className="h-3.5 w-3.5" />
                      {tApp('settings.memory.fields.reranker_download.downloaded')}
                    </span>
                  )}
                </div>
                {rerankerDownloadError && !isDownloading && !selectedModel.downloaded && (
                  <p className="mt-1 flex items-center gap-1 text-xs text-destructive">
                    <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
                    {rerankerDownloadError}
                  </p>
                )}
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