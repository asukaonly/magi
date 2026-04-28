import React, { useEffect, useMemo, useState } from 'react';
import { Plus } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { LLMProviderChatModelFields } from '@/components/config-forms/LLMProviderChatModelFields';
import { LLMProviderConnectionFields } from '@/components/config-forms/LLMProviderConnectionFields';
import { LLMProviderDetailHeader } from '@/components/config-forms/LLMProviderDetailHeader';
import { LLMProviderEmbeddingModelFields } from '@/components/config-forms/LLMProviderEmbeddingModelFields';
import { LLMProviderImageModelFields } from '@/components/config-forms/LLMProviderImageModelFields';
import { LLMProviderListPane } from '@/components/config-forms/LLMProviderListPane';
import { LLMProviderModelEditorHeader, type LLMProviderModelEditorKind } from '@/components/config-forms/LLMProviderModelEditorHeader';
import { LLMProviderModelListPane } from '@/components/config-forms/LLMProviderModelListPane';
import { LLMProviderModelToolbar, type LLMProviderModelKind } from '@/components/config-forms/LLMProviderModelToolbar';
import { LLMProviderTestStatus } from '@/components/config-forms/LLMProviderTestStatus';
import {
  type LLMModelMetadataOverride,
  type LLMConfig,
  type LLMProviderConfig,
  type LLMProviderRegistry,
  type LLMScenario,
  type TestLLMProviderConnectionResponse,
} from '@/api/modules/config';
import { cn } from '@/lib/utils';
import {
  buildProviderWorkbenchModels,
  cloneModelOverride,
  isModelOverrideEmpty,
  type ProviderWorkbenchModelItem,
} from '@/components/config-forms/llm-provider-workbench-models';

interface LLMProviderConfigurationSectionProps {
  registry: LLMProviderRegistry;
  value: LLMConfig;
  activeProviderId: string;
  quickMode?: boolean;
  surface?: 'onboarding' | 'settings';
  showSectionIntro?: boolean;
  scenarioReferences: Record<string, LLMScenario[]>;
  onActiveProviderChange: (providerId: string) => void;
  onProviderChange: (providerId: string, updater: (provider: LLMProviderConfig) => void) => void;
  onAddCustomProvider: () => void;
  onRemoveCustomProvider: (providerId: string) => void;
  onAddProviderModel: (providerId: string, model: string, kind: 'chat' | 'embedding' | 'image') => void;
  onRemoveProviderModel: (providerId: string, model: string) => void;
  onProviderDefaultModelChange: (providerId: string, model: string) => void;
  onDiscoverProviderModels: (providerId: string) => void;
  providerDiscoveryState: Record<string, { loading: boolean; error: string | null }>;
  onTestProviderConnection: (providerId: string, model: string) => void;
  providerTestState: Record<
    string,
    {
      loading: boolean;
      error: string | null;
      result: TestLLMProviderConnectionResponse | null;
    }
  >;
}

const fieldClassName =
  'h-11 w-full rounded-xl bg-background px-3 text-sm ring-1 ring-inset ring-border/55 shadow-[0_1px_2px_rgba(15,23,42,0.04)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/45';

export const LLMProviderConfigurationSection: React.FC<LLMProviderConfigurationSectionProps> = ({
  registry,
  value,
  activeProviderId,
  quickMode = false,
  surface = 'onboarding',
  showSectionIntro = true,
  scenarioReferences,
  onActiveProviderChange,
  onProviderChange,
  onAddCustomProvider,
  onRemoveCustomProvider,
  onAddProviderModel,
  onRemoveProviderModel,
  onProviderDefaultModelChange,
  onDiscoverProviderModels,
  providerDiscoveryState,
  onTestProviderConnection,
  providerTestState,
}) => {
  const { t } = useTranslation('onboarding');
  const [modelDraft, setModelDraft] = useState('');
  const [modelDraftKind, setModelDraftKind] = useState<LLMProviderModelKind>('chat');
  const [selectedModelId, setSelectedModelId] = useState('');
  const [providerTestModels, setProviderTestModels] = useState<Record<string, string>>({});
  const [showApiKey, setShowApiKey] = useState(false);
  const isSettingsSurface = surface === 'settings';

  const customProviderIds = Object.entries(value.providers)
    .filter(([, provider]) => provider.provider_type === 'custom')
    .map(([providerId]) => providerId);
  const providerOrder = [
    ...registry.providers.map((provider) => provider.id),
    ...customProviderIds.filter((providerId) => !registry.providers.some((provider) => provider.id === providerId)),
  ];
  const providerItems = useMemo(
    () =>
      providerOrder
        .map((providerId, index) => ({ providerId, provider: value.providers[providerId], index }))
        .filter((item): item is { providerId: string; provider: LLMProviderConfig; index: number } => Boolean(item.provider))
        .sort((left, right) => {
          if (left.provider.enabled === right.provider.enabled) {
            return left.index - right.index;
          }
          return left.provider.enabled ? -1 : 1;
        }),
    [providerOrder, value.providers]
  );

  const activeProvider = value.providers[activeProviderId] || value.providers[providerOrder[0]];
  const activeProviderMeta =
    activeProvider?.provider_type === 'custom'
      ? undefined
      : registry.providers.find((provider) => provider.id === activeProvider?.provider_type);
  const activeReferences = scenarioReferences[activeProviderId] || [];
  const activeDiscoveryState = providerDiscoveryState[activeProviderId] || { loading: false, error: null };
  const activeTestState = providerTestState[activeProviderId] || { loading: false, error: null, result: null };
  const activeWorkbenchModels = useMemo(
    () => buildProviderWorkbenchModels(registry, activeProviderId, activeProvider),
    [activeProvider, activeProviderId, registry]
  );
  const filteredWorkbenchModels = useMemo(
    () => activeWorkbenchModels.filter((model) => model.kinds.includes(modelDraftKind)),
    [activeWorkbenchModels, modelDraftKind]
  );
  const activeTestableModels = useMemo(
    () =>
      activeWorkbenchModels.filter(
        (model) => model.kinds.includes('chat') && !model.capabilities.embedding && !model.capabilities.image_output
      ),
    [activeWorkbenchModels]
  );
  const activeWorkbenchModel =
    filteredWorkbenchModels.find((model) => model.id === selectedModelId) || filteredWorkbenchModels[0];
  const resolveDefaultTestModel = (providerId: string, models: ProviderWorkbenchModelItem[]): string => {
    if (!models.length) {
      return '';
    }

    const testableModelIds = new Set(models.map((model) => model.id));
    const referencedSelection = Object.values(value.selections).find(
      (selection) => selection.provider_id === providerId && testableModelIds.has(selection.model)
    );

    return referencedSelection?.model || models[0]?.id || '';
  };
  const activeSelectedTestModel = providerTestModels[activeProviderId];
  const resolvedActiveTestModel =
    activeSelectedTestModel && activeTestableModels.some((model) => model.id === activeSelectedTestModel)
      ? activeSelectedTestModel
      : resolveDefaultTestModel(activeProviderId, activeTestableModels);
  const activeModelOverride =
    activeWorkbenchModel && activeProvider?.model_metadata_overrides
      ? activeProvider.model_metadata_overrides[activeWorkbenchModel.id]
      : undefined;
  const workbenchColumnsClassName = quickMode
    ? 'xl:grid-cols-[220px_minmax(0,1fr)]'
    : 'xl:grid-cols-[240px_minmax(0,1fr)]';
  const settingsWorkbenchColumnsClassName = quickMode
    ? 'xl:grid-cols-[250px_minmax(0,1fr)]'
    : 'xl:grid-cols-[280px_minmax(0,1fr)]';

  useEffect(() => {
    setModelDraft('');
    setModelDraftKind('chat');
    setSelectedModelId('');
    setShowApiKey(false);
  }, [activeProviderId]);

  useEffect(() => {
    if (!filteredWorkbenchModels.length) {
      if (selectedModelId) {
        setSelectedModelId('');
      }
      return;
    }

    if (!filteredWorkbenchModels.some((model) => model.id === selectedModelId)) {
      setSelectedModelId(filteredWorkbenchModels[0].id);
    }
  }, [filteredWorkbenchModels, selectedModelId]);

  useEffect(() => {
    if (!activeProviderId) {
      return;
    }

    if (!activeTestableModels.length) {
      if (providerTestModels[activeProviderId]) {
        setProviderTestModels((prev) => ({
          ...prev,
          [activeProviderId]: '',
        }));
      }
      return;
    }

    const nextModel = resolveDefaultTestModel(activeProviderId, activeTestableModels);
    if (nextModel && providerTestModels[activeProviderId] !== nextModel && !activeSelectedTestModel) {
      setProviderTestModels((prev) => ({
        ...prev,
        [activeProviderId]: nextModel,
      }));
    }
  }, [activeProviderId, activeSelectedTestModel, activeTestableModels, providerTestModels, value.selections]);

  const updateModelOverride = (modelId: string, updater: (draft: LLMModelMetadataOverride) => void) => {
    onProviderChange(activeProviderId, (provider) => {
      const overrides = { ...(provider.model_metadata_overrides || {}) };
      const nextOverride = cloneModelOverride(overrides[modelId]);
      updater(nextOverride);
      if (isModelOverrideEmpty(nextOverride)) {
        delete overrides[modelId];
      } else {
        overrides[modelId] = nextOverride;
      }
      provider.model_metadata_overrides = overrides;
    });
  };

  return (
    <section
      data-testid="llm-provider-configuration-section"
      className={cn(
        'flex min-h-0 flex-1 flex-col space-y-4',
        isSettingsSurface && 'space-y-0'
      )}
    >
      {showSectionIntro ? (
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="space-y-1.5">
            <h3 className="text-lg font-semibold text-foreground sm:text-xl">{t('llm.providerConfiguration.title')}</h3>
            <p className="max-w-2xl text-sm leading-6 text-muted-foreground">{t('llm.providerConfiguration.desc')}</p>
          </div>
          <button
            type="button"
            onClick={onAddCustomProvider}
            className="inline-flex items-center gap-2 self-start rounded-xl bg-muted px-3.5 py-2.5 text-sm font-medium text-foreground transition hover:bg-accent"
          >
            <Plus className="h-4 w-4" />
            <span>{t('llm.actions.addCustomProvider')}</span>
          </button>
        </div>
      ) : null}

      <div
        data-testid="llm-provider-workbench"
        className={cn(
          'grid min-h-0 flex-1 gap-4 overflow-hidden rounded-[28px] bg-muted/35 p-3 sm:p-4',
          workbenchColumnsClassName,
          'md:min-h-[440px] xl:items-stretch',
          isSettingsSurface &&
            cn(
              'h-full gap-0 rounded-none bg-transparent p-0 sm:p-0 md:h-full',
              settingsWorkbenchColumnsClassName
            )
        )}
      >
        <LLMProviderListPane
          registry={registry}
          providerItems={providerItems}
          activeProviderId={activeProviderId}
          isSettingsSurface={isSettingsSurface}
          onActiveProviderChange={onActiveProviderChange}
          onAddCustomProvider={onAddCustomProvider}
        />

        {activeProvider ? (
          <div
            data-testid="llm-provider-detail-pane"
            className={cn(
              'min-h-0 overflow-y-auto rounded-[24px] bg-background/72 p-5 sm:p-6',
              isSettingsSurface &&
                'bg-transparent p-0 pl-6'
            )}
          >
            <div className={cn('space-y-6', isSettingsSurface && 'space-y-5')}>
              <LLMProviderDetailHeader
                providerId={activeProviderId}
                provider={activeProvider}
                providerMeta={activeProviderMeta}
                references={activeReferences}
                surface={surface}
                isSettingsSurface={isSettingsSurface}
                isTesting={activeTestState.loading}
                testableModels={activeTestableModels}
                selectedTestModelId={resolvedActiveTestModel}
                onProviderChange={onProviderChange}
                onRemoveCustomProvider={onRemoveCustomProvider}
                onSelectedTestModelChange={(providerId, modelId) =>
                  setProviderTestModels((prev) => ({
                    ...prev,
                    [providerId]: modelId,
                  }))
                }
                onTestProviderConnection={onTestProviderConnection}
              />

              <LLMProviderTestStatus error={activeTestState.error} result={activeTestState.result} />

              <div className="grid gap-4">
                <LLMProviderConnectionFields
                  registry={registry}
                  providerId={activeProviderId}
                  provider={activeProvider}
                  providerMeta={activeProviderMeta}
                  isSettingsSurface={isSettingsSurface}
                  showApiKey={showApiKey}
                  onShowApiKeyChange={setShowApiKey}
                  onProviderChange={onProviderChange}
                  onProviderDefaultModelChange={onProviderDefaultModelChange}
                />

                <div
                  className={cn(
                    'space-y-4 pt-1',
                    isSettingsSurface && 'border-t border-[hsl(var(--settings-subnav-border)/0.72)] pt-5'
                  )}
                >
                  <div className="text-sm font-medium text-foreground">{t('llm.providerConfiguration.availableModels')}</div>

                  <LLMProviderModelToolbar
                    providerId={activeProviderId}
                    isCustomProvider={activeProvider.provider_type === 'custom'}
                    isSettingsSurface={isSettingsSurface}
                    modelDraft={modelDraft}
                    modelDraftKind={modelDraftKind}
                    discoveryLoading={activeDiscoveryState.loading}
                    onModelDraftChange={setModelDraft}
                    onModelDraftKindChange={setModelDraftKind}
                    onAddProviderModel={onAddProviderModel}
                    onDiscoverProviderModels={onDiscoverProviderModels}
                  />

                  {activeDiscoveryState.error ? (
                    <p className="text-sm text-destructive">{activeDiscoveryState.error}</p>
                  ) : null}

                  <div
                    className={cn(
                      'grid gap-4',
                      !isSettingsSurface && 'xl:grid-cols-[220px_minmax(0,1fr)]',
                      isSettingsSurface && 'xl:grid-cols-[240px_minmax(0,1fr)]'
                    )}
                  >
                    <LLMProviderModelListPane
                      models={filteredWorkbenchModels}
                      activeModelId={activeWorkbenchModel?.id}
                      isSettingsSurface={isSettingsSurface}
                      onSelectedModelChange={setSelectedModelId}
                    />

                    <div
                      data-testid="llm-provider-model-editor"
                      className={cn(
                        'space-y-4 rounded-[18px] bg-muted/25 p-4',
                        isSettingsSurface && 'rounded-lg bg-[hsl(var(--settings-shell-elevated)/0.22)]'
                      )}
                    >
                      {activeWorkbenchModel ? (() => {
                        const activeKind: LLMProviderModelEditorKind =
                          activeWorkbenchModel.kinds.includes('image') &&
                          !activeWorkbenchModel.kinds.includes('chat') &&
                          !activeWorkbenchModel.kinds.includes('embedding')
                            ? 'image'
                            : activeWorkbenchModel.kinds.includes('embedding') &&
                              !activeWorkbenchModel.kinds.includes('chat')
                            ? 'embedding'
                            : 'chat';
                        return (
                          <>
                            <LLMProviderModelEditorHeader
                              providerId={activeProviderId}
                              model={activeWorkbenchModel}
                              activeKind={activeKind}
                              onProviderChange={onProviderChange}
                              onRemoveProviderModel={onRemoveProviderModel}
                            />

                            <div className="grid gap-4">
                              <label className="space-y-2">
                                <span className="text-sm font-medium">{t('llm.fields.displayName')}</span>
                                <input
                                  aria-label={t('llm.fields.displayName')}
                                  className={cn(fieldClassName, isSettingsSurface && 'rounded-lg')}
                                  value={activeModelOverride?.label ?? activeWorkbenchModel.label}
                                  onChange={(event) =>
                                    updateModelOverride(activeWorkbenchModel.id, (draft) => {
                                      draft.label = event.target.value.trim() || undefined;
                                    })
                                  }
                                />
                              </label>
                            </div>

                            {activeKind === 'chat' ? (
                              <LLMProviderChatModelFields
                                model={activeWorkbenchModel}
                                modelOverride={activeModelOverride}
                                isSettingsSurface={isSettingsSurface}
                                onModelOverrideChange={updateModelOverride}
                              />
                            ) : activeKind === 'embedding' ? (
                              <LLMProviderEmbeddingModelFields
                                model={activeWorkbenchModel}
                                modelOverride={activeModelOverride}
                                isSettingsSurface={isSettingsSurface}
                                onModelOverrideChange={updateModelOverride}
                              />
                            ) : (
                              <LLMProviderImageModelFields />
                            )}
                          </>
                        );
                      })() : (
                        <div className="rounded-lg bg-background/80 px-3 py-3 text-sm text-muted-foreground">
                          {t('llm.providerConfiguration.noModelSelected')}
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        ) : null}
      </div>
    </section>
  );
};
