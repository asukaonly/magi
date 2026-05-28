import type { SystemConfig } from '@/api/modules/config';
import LLMForm from '@/components/config-forms/LLMForm';

interface SettingsLlmSectionProps {
  view: 'providers' | 'models';
  draftConfig: SystemConfig;
  patchDraftConfig: (updater: (draft: SystemConfig) => void) => void;
  syncNormalizedLlmConfig: (nextLlmConfig: SystemConfig['llm']) => void;
}

export function SettingsLlmSection({
  view,
  draftConfig,
  patchDraftConfig,
  syncNormalizedLlmConfig,
}: SettingsLlmSectionProps) {
  if (view === 'providers') {
    return (
      <div className="h-full min-h-0">
        <LLMForm
          quickMode={false}
          view="providers"
          surface="settings"
          showSectionIntro={false}
          value={draftConfig.llm}
          onAutoNormalize={syncNormalizedLlmConfig}
          onChange={(next) => patchDraftConfig((draft) => {
            draft.llm = next;
          })}
        />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <LLMForm
        quickMode={false}
        view="models"
        surface="settings"
        showSectionIntro={false}
        value={draftConfig.llm}
        onAutoNormalize={syncNormalizedLlmConfig}
        onChange={(next) => patchDraftConfig((draft) => {
          draft.llm = next;
        })}
        embeddingConfig={draftConfig.memory.embedding}
        onEmbeddingConfigChange={(updater) => patchDraftConfig((draft) => {
          updater(draft.memory.embedding);
        })}
        crossEncoderConfig={draftConfig.memory.reranker?.cross_encoder}
        onCrossEncoderConfigChange={(updater) => patchDraftConfig((draft) => {
          draft.memory.reranker.cross_encoder ??= { enabled: false, managed_model_id: null, variant: null };
          updater(draft.memory.reranker.cross_encoder);
        })}
      />
    </div>
  );
}