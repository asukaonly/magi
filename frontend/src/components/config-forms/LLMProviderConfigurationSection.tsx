import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Activity, Check, ChevronDown, Eye, EyeOff, Loader2, Pencil, Plus, RefreshCw, Trash2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import {
  type ApiFormat,
  type LLMConfig,
  type LLMModelMetadataOverride,
  type LLMProvider,
  type LLMProviderConfig,
  type LLMProviderConnectionConfig,
  type LLMProviderRegistry,
  type LLMScenario,
  type TestLLMProviderConnectionResponse,
} from '@/api/modules/config';
import { SelectField } from '@/components/config-forms/fields';
import {
  buildProviderWorkbenchModels,
  cloneModelOverride,
  isModelOverrideEmpty,
} from '@/components/config-forms/llm-provider-workbench-models';
import { LLMProviderModelEditor } from '@/components/config-forms/LLMProviderModelEditor';
import { LLMProviderModelListPane } from '@/components/config-forms/LLMProviderModelListPane';
import { ProviderIcon } from '@/components/config-forms/provider-icons';
import { LLMProviderTestStatus } from '@/components/config-forms/LLMProviderTestStatus';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Switch } from '@/components/ui/switch';
import { cn } from '@/lib/utils';

import { cloneProvider } from './llm-form-state';

interface LLMProviderConfigurationSectionProps {
  registry: LLMProviderRegistry;
  value: LLMConfig;
  activeProviderId: string;
  quickMode?: boolean;
  surface?: 'onboarding' | 'settings';
  showSectionIntro?: boolean;
  scenarioReferences: Record<string, LLMScenario[]>;
  customProviderDefaults?: LLMProviderConfig | null;
  onActiveProviderChange: (providerId: string) => void;
  onProviderChange: (providerId: string, updater: (provider: LLMProviderConfig) => void) => void;
  onSetProvider: (providerId: string, provider: LLMProviderConfig) => void;
  onRemoveProvider: (providerId: string) => void;
  onAddProviderModel: (providerId: string, model: string, kind: 'chat' | 'embedding') => void;
  onRemoveProviderModel: (providerId: string, model: string) => void;
  onProviderDefaultModelChange: (providerId: string, model: string) => void;
  onDiscoverProviderModels: (providerId: string, provider?: LLMProviderConfig) => Promise<string[] | undefined>;
  onResolveDraftProviderPreview: (providerId: string, provider: LLMProviderConfig) => Promise<LLMProviderRegistry | null>;
  providerDiscoveryState: Record<string, { loading: boolean; error: string | null }>;
  onTestProviderConnection: (providerId: string, model: string, provider?: LLMProviderConfig) => void;
  providerTestState: Record<
    string,
    {
      loading: boolean;
      error: string | null;
      result: TestLLMProviderConnectionResponse | null;
    }
  >;
}

type ProviderTemplate = LLMProviderRegistry['providers'][number];
type ServiceName = 'chat' | 'embedding' | 'image_generation' | 'tts';
type VisibleServiceName = Exclude<ServiceName, 'tts'>;
type SecretFieldScope = 'provider' | ServiceName;
type EditorMode = 'add' | 'edit';
type ServiceModelKind = 'chat' | 'embedding' | 'image';

const fieldClassName =
  'h-10 w-full rounded-lg bg-background px-3 text-sm ring-1 ring-inset ring-border/55 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/45';

const SERVICE_NAMES: VisibleServiceName[] = ['chat', 'embedding', 'image_generation'];
const SERVICE_MODEL_KIND: Record<VisibleServiceName, ServiceModelKind> = {
  chat: 'chat',
  embedding: 'embedding',
  image_generation: 'image',
};

const IMAGE_NATIVE_PROTOCOL_OPTIONS = [
  { label: 'OpenAI Images', value: 'openai_images' },
  { label: 'Gemini Predict', value: 'gemini_predict' },
  { label: 'DashScope Multimodal Image', value: 'dashscope_multimodal_image' },
  { label: 'MiniMax Image', value: 'minimax_image' },
  { label: 'Z.ai Images', value: 'zai_images' },
];

const createInstanceId = (providerType: string): string => `${providerType}_${Date.now()}`;

const cloneConnection = (value?: Partial<LLMProviderConnectionConfig>, defaultEnabled = true): LLMProviderConnectionConfig => ({
  enabled: value?.enabled ?? defaultEnabled,
  api_key: value?.api_key || '',
  base_url: value?.base_url || '',
});

const createProviderFromTemplate = (
  template: ProviderTemplate | null,
  customProviderDefaults: LLMProviderConfig | null | undefined,
  customDisplayName: string
): LLMProviderConfig => {
  if (!template) {
    const customDefaults = customProviderDefaults ? cloneProvider(customProviderDefaults) : undefined;
    return cloneProvider({
      enabled: true,
      provider_type: 'custom',
      display_name: customDefaults?.display_name || customDisplayName,
      api_key: customDefaults?.api_key || '',
      base_url: customDefaults?.base_url || '',
      services: {
        chat: cloneConnection(customDefaults?.services?.chat, true),
        embedding: cloneConnection(customDefaults?.services?.embedding, false),
        image_generation: {
          ...cloneConnection(customDefaults?.services?.image_generation, false),
          timeout: customDefaults?.services?.image_generation?.timeout ?? 180,
          native_protocol: customDefaults?.services?.image_generation?.native_protocol ?? null,
        },
        tts: {
          ...cloneConnection(customDefaults?.services?.tts, false),
          model: customDefaults?.services?.tts?.model || '',
          voice: customDefaults?.services?.tts?.voice || '',
          response_format: customDefaults?.services?.tts?.response_format || '',
        },
      },
      api_format: customDefaults?.api_format || 'openai',
      custom_models: customDefaults?.custom_models || [],
      custom_default_model: customDefaults?.custom_default_model || '',
      model_metadata_overrides: customDefaults?.model_metadata_overrides || {},
    });
  }

  const providerType = (template.provider_type || template.id) as LLMProvider;
  return cloneProvider({
    enabled: true,
    provider_type: providerType,
    display_name: template.display_name || template.id,
    api_key: '',
    base_url: template.default_base_url || '',
    services: {
      chat: { enabled: true, api_key: '', base_url: '' },
      embedding: {
        enabled: Boolean(template.resolved_embedding_models?.length),
        api_key: '',
        base_url: '',
      },
      image_generation: {
        enabled: Boolean(template.resolved_image_generation_models?.length),
        api_key: '',
        base_url: '',
        timeout: 180,
        native_protocol: null,
      },
      tts: {
        enabled: false,
        api_key: '',
        base_url: '',
        model: '',
        voice: '',
        response_format: '',
      },
    },
    api_format: template.api_format,
    custom_models: [],
    custom_default_model: '',
    model_metadata_overrides: {},
  });
};

export const LLMProviderConfigurationSection: React.FC<LLMProviderConfigurationSectionProps> = ({
  registry,
  value,
  activeProviderId,
  surface = 'onboarding',
  showSectionIntro = true,
  scenarioReferences,
  customProviderDefaults,
  onActiveProviderChange,
  onProviderChange,
  onSetProvider,
  onRemoveProvider,
  onDiscoverProviderModels,
  onResolveDraftProviderPreview,
  providerDiscoveryState,
  onTestProviderConnection,
  providerTestState,
}) => {
  const { t } = useTranslation('onboarding');
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editorMode, setEditorMode] = useState<EditorMode>('add');
  const [editingProviderId, setEditingProviderId] = useState('');
  const [selectedTemplateId, setSelectedTemplateId] = useState('');
  const [draftProvider, setDraftProvider] = useState<LLMProviderConfig | null>(null);
  const [showApiKeys, setShowApiKeys] = useState<Record<SecretFieldScope, boolean>>({
    provider: false,
    chat: false,
    embedding: false,
    image_generation: false,
    tts: false,
  });
  const [expandedServices, setExpandedServices] = useState<Record<VisibleServiceName, boolean>>({
    chat: false,
    embedding: false,
    image_generation: false,
  });
  const [serviceModelDrafts, setServiceModelDrafts] = useState<Record<VisibleServiceName, string>>({
    chat: '',
    embedding: '',
    image_generation: '',
  });
  const [selectedServiceModels, setSelectedServiceModels] = useState<Record<VisibleServiceName, string>>({
    chat: '',
    embedding: '',
    image_generation: '',
  });
  const [testPopoverService, setTestPopoverService] = useState<VisibleServiceName | null>(null);
  const [testModelByService, setTestModelByService] = useState<Record<VisibleServiceName, string>>({
    chat: '',
    embedding: '',
    image_generation: '',
  });
  const [draftPreviewRegistry, setDraftPreviewRegistry] = useState<LLMProviderRegistry | null>(null);
  const draftPreviewRequestRef = useRef(0);
  const testPopoverRootRef = useRef<HTMLDivElement | null>(null);
  const isSettingsSurface = surface === 'settings';

  const providerTemplates = useMemo(
    () =>
      registry.providers.filter(
        (provider) => provider.source !== 'custom' && provider.id === (provider.provider_type || provider.id)
      ),
    [registry.providers]
  );

  const providerItems = useMemo(
    () =>
      Object.entries(value.providers).sort(([, left], [, right]) => {
        if (left.enabled === right.enabled) {
          return (left.display_name || left.provider_type).localeCompare(right.display_name || right.provider_type);
        }
        return left.enabled ? -1 : 1;
      }),
    [value.providers]
  );

  const draftProviderId = editorMode === 'edit' && editingProviderId
    ? editingProviderId
    : (draftProvider?.provider_type === 'custom' ? 'custom' : draftProvider?.provider_type || selectedTemplateId || 'custom');
  const draftPreviewProviderId = editorMode === 'edit' && editingProviderId
    ? editingProviderId
    : `__draft_preview__${draftProvider?.provider_type || selectedTemplateId || 'custom'}`;
  const draftRegistry = draftPreviewRegistry || registry;
  const resolvedDraftProviderId = draftPreviewRegistry ? draftPreviewProviderId : draftProviderId;
  const activeProviderMeta = draftProvider?.provider_type === 'custom'
    ? undefined
    : draftRegistry.providers.find((provider) => provider.id === resolvedDraftProviderId)
      || draftRegistry.providers.find((provider) => provider.id === draftProvider?.provider_type);
  const draftWorkbenchModels = useMemo(
    () => (draftProvider ? buildProviderWorkbenchModels(draftRegistry, resolvedDraftProviderId, draftProvider) : []),
    [draftProvider, draftRegistry, resolvedDraftProviderId]
  );
  const serviceModelsByName = useMemo(
    () => ({
      chat: draftWorkbenchModels.filter(
        (model) => model.kinds.includes('chat') && !model.capabilities.embedding && !model.capabilities.image_output
      ),
      embedding: draftWorkbenchModels.filter((model) => model.kinds.includes('embedding')),
      image_generation: draftWorkbenchModels.filter((model) => model.kinds.includes('image')),
    }),
    [draftWorkbenchModels]
  );
  const draftTestState = providerTestState[draftProviderId] || { loading: false, error: null, result: null };
  const draftDiscoveryState = providerDiscoveryState[draftProviderId] || { loading: false, error: null };

  const resetEditorState = () => {
    setShowApiKeys({ provider: false, chat: false, embedding: false, image_generation: false, tts: false });
    setExpandedServices({ chat: false, embedding: false, image_generation: false });
    setServiceModelDrafts({ chat: '', embedding: '', image_generation: '' });
    setSelectedServiceModels({ chat: '', embedding: '', image_generation: '' });
    setTestModelByService({ chat: '', embedding: '', image_generation: '' });
    setTestPopoverService(null);
  };

  useEffect(() => {
    if (!dialogOpen || !draftProvider) {
      draftPreviewRequestRef.current += 1;
      setDraftPreviewRegistry(null);
      return;
    }

    const requestId = draftPreviewRequestRef.current + 1;
    draftPreviewRequestRef.current = requestId;
    setDraftPreviewRegistry(null);

    const timeoutId = window.setTimeout(() => {
      void (async () => {
        try {
          const previewRegistry = await onResolveDraftProviderPreview(draftPreviewProviderId, draftProvider);
          if (draftPreviewRequestRef.current !== requestId) {
            return;
          }
          setDraftPreviewRegistry(previewRegistry);
        } catch {
          if (draftPreviewRequestRef.current !== requestId) {
            return;
          }
          setDraftPreviewRegistry(null);
        }
      })();
    }, 120);

    return () => {
      window.clearTimeout(timeoutId);
    };
  }, [dialogOpen, draftPreviewProviderId, draftProvider, onResolveDraftProviderPreview]);

  useEffect(() => {
    if (!testPopoverService) return;

    const handleMouseDown = (event: MouseEvent) => {
      const target = event.target as Node | null;
      if (!target) return;
      if (testPopoverRootRef.current?.contains(target)) return;
      if (target instanceof Element && target.closest('[data-select-field-menu]')) return;
      setTestPopoverService(null);
    };

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setTestPopoverService(null);
      }
    };

    document.addEventListener('mousedown', handleMouseDown);
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('mousedown', handleMouseDown);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [testPopoverService]);

  const openAddDialog = () => {
    const firstTemplate = providerTemplates[0] || null;
    const nextTemplateId = firstTemplate?.id || 'custom';
    setEditorMode('add');
    setEditingProviderId('');
    setSelectedTemplateId(nextTemplateId);
    setDraftProvider(createProviderFromTemplate(firstTemplate, customProviderDefaults, t('llm.customProviderDefaultName')));
    resetEditorState();
    setDialogOpen(true);
  };

  const openEditDialog = (providerId: string) => {
    const provider = value.providers[providerId];
    if (!provider) return;
    setEditorMode('edit');
    setEditingProviderId(providerId);
    setSelectedTemplateId(provider.provider_type);
    setDraftProvider(cloneProvider(provider));
    resetEditorState();
    setDialogOpen(true);
  };

  const handleTemplateChange = (templateId: string) => {
    setSelectedTemplateId(templateId);
    const template = templateId === 'custom' ? null : providerTemplates.find((provider) => provider.id === templateId) || null;
    setDraftProvider(createProviderFromTemplate(template, customProviderDefaults, t('llm.customProviderDefaultName')));
    resetEditorState();
  };

  const updateDraftProvider = (updater: (provider: LLMProviderConfig) => void) => {
    setDraftProvider((current) => {
      const next = cloneProvider(current || undefined);
      updater(next);
      return next;
    });
  };

  const updateDraftService = (serviceName: ServiceName, updater: (service: any) => void) => {
    updateDraftProvider((provider) => {
      updater(provider.services[serviceName]);
    });
  };

  const updateDraftModelOverride = (modelId: string, updater: (draft: LLMModelMetadataOverride) => void) => {
    updateDraftProvider((provider) => {
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

  const removeDraftProviderModel = (modelId: string) => {
    updateDraftProvider((provider) => {
      provider.custom_models = (provider.custom_models || []).filter((item) => item !== modelId);
      if (provider.custom_default_model === modelId) {
        provider.custom_default_model = provider.custom_models[0] || '';
      }
      const overrides = { ...(provider.model_metadata_overrides || {}) };
      delete overrides[modelId];
      provider.model_metadata_overrides = overrides;
    });
  };

  const addDraftProviderModel = (serviceName: VisibleServiceName) => {
    if (serviceName === 'image_generation') return;
    const modelId = serviceModelDrafts[serviceName].trim();
    if (!modelId) return;

    updateDraftProvider((provider) => {
      if (serviceName === 'embedding') {
        const overrides = { ...(provider.model_metadata_overrides || {}) };
        overrides[modelId] = {
          ...(overrides[modelId] || {}),
          capabilities: {
            ...(overrides[modelId]?.capabilities || {}),
            embedding: true,
          },
        };
        provider.model_metadata_overrides = overrides;
      } else {
        provider.custom_models = Array.from(new Set([...(provider.custom_models || []), modelId]));
        provider.custom_default_model = provider.custom_default_model || modelId;
      }
    });
    setSelectedServiceModels((current) => ({ ...current, [serviceName]: modelId }));
    setServiceModelDrafts((current) => ({ ...current, [serviceName]: '' }));
  };

  const saveDraftProvider = () => {
    if (!draftProvider) return;
    const providerId = editorMode === 'edit' && editingProviderId
      ? editingProviderId
      : createInstanceId(draftProvider.provider_type || 'custom');
    onSetProvider(providerId, draftProvider);
    onActiveProviderChange(providerId);
    setDialogOpen(false);
  };

  const removeProvider = (providerId: string) => {
    onRemoveProvider(providerId);
    if (activeProviderId === providerId) {
      const nextId = Object.keys(value.providers).find((candidate) => candidate !== providerId) || '';
      onActiveProviderChange(nextId);
    }
  };

  const handleDiscoverDraftModels = async (serviceName: VisibleServiceName) => {
    if (!draftProvider || serviceName === 'image_generation') return;
    const nextModels = await onDiscoverProviderModels(draftProviderId, draftProvider);
    if (!nextModels?.length) return;
    updateDraftProvider((provider) => {
      if (serviceName === 'embedding') {
        const overrides = { ...(provider.model_metadata_overrides || {}) };
        for (const modelId of nextModels) {
          overrides[modelId] = {
            ...(overrides[modelId] || {}),
            capabilities: {
              ...(overrides[modelId]?.capabilities || {}),
              embedding: true,
            },
          };
        }
        provider.model_metadata_overrides = overrides;
        return;
      }

      provider.custom_models = Array.from(new Set(nextModels));
      provider.custom_default_model = provider.custom_default_model || provider.custom_models[0] || '';
    });
    setSelectedServiceModels((current) => ({ ...current, [serviceName]: nextModels[0] || '' }));
  };

  const renderSecretField = ({
    scope,
    value,
    onChange,
    ariaLabel,
    placeholder,
  }: {
    scope: SecretFieldScope;
    value: string;
    onChange: (value: string) => void;
    ariaLabel: string;
    placeholder?: string;
  }) => {
    const visible = showApiKeys[scope];
    return (
      <div className="relative">
        <input
          aria-label={ariaLabel}
          className={cn(fieldClassName, 'pr-10')}
          type={visible ? 'text' : 'password'}
          placeholder={placeholder}
          value={value}
          onChange={(event) => onChange(event.target.value)}
        />
        <button
          type="button"
          aria-label={visible ? t('llm.providerConfiguration.hideKey') : t('llm.providerConfiguration.showKey')}
          className="absolute right-2 top-1/2 inline-flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded-md text-muted-foreground transition hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/45"
          onClick={() => setShowApiKeys((current) => ({ ...current, [scope]: !current[scope] }))}
        >
          {visible ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
        </button>
      </div>
    );
  };

  const renderServiceFields = (serviceName: VisibleServiceName) => {
    if (!draftProvider) return null;
    const service = draftProvider.services[serviceName];
    const serviceLabel = t(`llm.providerConfiguration.serviceLabels.${serviceName}`);
    const serviceDesc = t(`llm.providerConfiguration.serviceDescriptions.${serviceName}`);
    const expanded = expandedServices[serviceName];
    const serviceModels = serviceModelsByName[serviceName];
    const selectedModelId = selectedServiceModels[serviceName] && serviceModels.some((model) => model.id === selectedServiceModels[serviceName])
      ? selectedServiceModels[serviceName]
      : serviceModels[0]?.id || '';
    const selectedModel = serviceModels.find((model) => model.id === selectedModelId);
    const canManageModels = serviceName !== 'image_generation';
    const canTestService = serviceName === 'chat' && service.enabled && serviceModels.length > 0;
    const selectedTestModel = testModelByService[serviceName] && serviceModels.some((model) => model.id === testModelByService[serviceName])
      ? testModelByService[serviceName]
      : serviceModels[0]?.id || '';
    const serviceModelKind = SERVICE_MODEL_KIND[serviceName];

    return (
      <div key={serviceName} className="overflow-visible rounded-lg border border-border/70 bg-background/80">
        <div
          className="flex items-center justify-between gap-3 px-4 py-3"
          role="button"
          tabIndex={0}
          onClick={() => setExpandedServices((current) => ({ ...current, [serviceName]: !current[serviceName] }))}
          onKeyDown={(event) => {
            if (event.key === 'Enter' || event.key === ' ') {
              event.preventDefault();
              setExpandedServices((current) => ({ ...current, [serviceName]: !current[serviceName] }));
            }
          }}
        >
          <div className="min-w-0">
            <div className="text-sm font-semibold text-foreground">{serviceLabel}</div>
            {expanded ? <p className="mt-1 text-xs leading-5 text-muted-foreground">{serviceDesc}</p> : null}
          </div>
          <div className="flex shrink-0 items-center gap-2" onClick={(event) => event.stopPropagation()}>
            {expanded ? (
              <div ref={testPopoverService === serviceName ? testPopoverRootRef : undefined} className="relative">
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  aria-label={t('llm.actions.testConnection')}
                  title={t('llm.actions.testConnection')}
                  className={cn(
                    'h-8 w-8 rounded-md border border-border/65 bg-background/70 p-0 text-muted-foreground shadow-none hover:bg-muted hover:text-foreground',
                    testPopoverService === serviceName && 'bg-muted text-foreground'
                  )}
                  disabled={!canTestService}
                  onClick={() => setTestPopoverService((current) => current === serviceName ? null : serviceName)}
                >
                  <Activity className="h-4 w-4" />
                </Button>

                {testPopoverService === serviceName ? (
                  <div className="absolute right-0 top-full z-50 mt-2 w-[min(320px,calc(100vw-3rem))] space-y-3 rounded-lg border border-border bg-background p-3 shadow-[0_18px_42px_rgba(15,23,42,0.18)]">
                    <div className="text-sm font-medium text-foreground">{t('llm.providerConfiguration.testTitle')}</div>
                    <label className="block space-y-2">
                      <span className="text-sm font-medium">{t('llm.providerConfiguration.testModelLabel')}</span>
                      <SelectField
                        value={selectedTestModel}
                        disabled={!serviceModels.length}
                        placeholder={t('llm.providerConfiguration.testModelEmpty')}
                        options={serviceModels.map((model) => ({ label: model.label, value: model.id }))}
                        onChange={(nextModel) => setTestModelByService((current) => ({ ...current, [serviceName]: nextModel }))}
                      />
                    </label>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="w-full gap-2"
                      disabled={!selectedTestModel || draftTestState.loading}
                      onClick={() => {
                        onTestProviderConnection(draftProviderId, selectedTestModel, draftProvider);
                      }}
                    >
                      {draftTestState.loading ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                      <span>{t('llm.actions.testConnection')}</span>
                    </Button>
                    <LLMProviderTestStatus error={draftTestState.error} result={draftTestState.result} />
                  </div>
                ) : null}
              </div>
            ) : null}
            <Switch
              aria-label={serviceLabel}
              checked={Boolean(service.enabled)}
              onCheckedChange={(checked) => updateDraftService(serviceName, (draft) => { draft.enabled = checked; })}
            />
            <ChevronDown className={cn('h-4 w-4 text-muted-foreground transition', expanded && 'rotate-180')} />
          </div>
        </div>

        {expanded ? (
          <div className="space-y-4 border-t border-border/70 px-4 py-4">
            <div className="grid gap-3 md:grid-cols-2">
              <label className="space-y-2">
                <span className="text-sm font-medium">{t('llm.fields.apiKey')}</span>
                {renderSecretField({
                  scope: serviceName,
                  ariaLabel: `${serviceLabel} ${t('llm.fields.apiKey')}`,
                  placeholder: t('llm.providerConfiguration.inheritApiKeyPlaceholder'),
                  value: service.api_key || '',
                  onChange: (nextValue) => updateDraftService(serviceName, (draft) => { draft.api_key = nextValue; }),
                })}
              </label>
              <label className="space-y-2">
                <span className="text-sm font-medium">{t('llm.fields.baseUrl')}</span>
                <input
                  aria-label={`${serviceLabel} ${t('llm.fields.baseUrl')}`}
                  className={fieldClassName}
                  placeholder={t('llm.providerConfiguration.inheritBaseUrlPlaceholder')}
                  value={service.base_url || ''}
                  onChange={(event) => updateDraftService(serviceName, (draft) => { draft.base_url = event.target.value; })}
                />
              </label>

              {serviceName === 'image_generation' ? (
                <>
                  <label className="space-y-2">
                    <span className="text-sm font-medium">{t('llm.imageGenerationConnection.timeout')}</span>
                    <input
                      aria-label={t('llm.imageGenerationConnection.timeout')}
                      className={fieldClassName}
                      type="number"
                      min={1}
                      value={draftProvider.services.image_generation.timeout ?? 180}
                      onChange={(event) => {
                        const timeout = Number(event.target.value);
                        updateDraftService('image_generation', (draft) => {
                          draft.timeout = Number.isFinite(timeout) && timeout > 0 ? Math.floor(timeout) : 180;
                        });
                      }}
                    />
                  </label>
                  <label className="space-y-2">
                    <span className="text-sm font-medium">{t('llm.providerConfiguration.nativeProtocol')}</span>
                    <SelectField
                      value={draftProvider.services.image_generation.native_protocol || ''}
                      allowEmpty
                      placeholder={t('llm.providerConfiguration.modelDefaultProtocol')}
                      options={IMAGE_NATIVE_PROTOCOL_OPTIONS}
                      onChange={(nextValue) => updateDraftService('image_generation', (draft) => {
                        draft.native_protocol = nextValue || null;
                      })}
                    />
                  </label>
                </>
              ) : null}
            </div>

            <div className="space-y-3 rounded-lg bg-muted/25 p-3">
              <div className="flex flex-col gap-2 lg:flex-row lg:items-end">
                <label className="min-w-0 flex-1 space-y-2">
                  <span className="text-sm font-medium">{t(`llm.modelKinds.${serviceModelKind}`)}</span>
                  <input
                    aria-label={`${serviceLabel} ${t('llm.fields.modelManualEntry')}`}
                    className={fieldClassName}
                    disabled={!canManageModels}
                    placeholder={canManageModels ? t('llm.fields.modelManualEntryPlaceholder') : t('llm.providerConfiguration.imageModelsManaged')}
                    value={serviceModelDrafts[serviceName]}
                    onChange={(event) => setServiceModelDrafts((current) => ({ ...current, [serviceName]: event.target.value }))}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter') {
                        event.preventDefault();
                        addDraftProviderModel(serviceName);
                      }
                    }}
                  />
                </label>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={!canManageModels || !serviceModelDrafts[serviceName].trim()}
                  onClick={() => addDraftProviderModel(serviceName)}
                >
                  {t('llm.actions.addModel')}
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="gap-2"
                  disabled={!canManageModels || draftDiscoveryState.loading}
                  onClick={() => void handleDiscoverDraftModels(serviceName)}
                >
                  {draftDiscoveryState.loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                  <span>{t('llm.actions.fetchModels')}</span>
                </Button>
              </div>
              {draftDiscoveryState.error ? (
                <p className="text-sm text-destructive">{draftDiscoveryState.error}</p>
              ) : null}

              <div className="grid gap-3 lg:grid-cols-[minmax(220px,280px)_minmax(0,1fr)]">
                <LLMProviderModelListPane
                  models={serviceModels}
                  activeModelId={selectedModelId}
                  isSettingsSurface={isSettingsSurface}
                  onSelectedModelChange={(modelId) => setSelectedServiceModels((current) => ({ ...current, [serviceName]: modelId }))}
                />
                <LLMProviderModelEditor
                  providerId={draftProviderId}
                  model={selectedModel}
                  modelOverride={selectedModel ? draftProvider.model_metadata_overrides?.[selectedModel.id] : undefined}
                  isSettingsSurface={isSettingsSurface}
                  onProviderChange={(_providerId, updater) => updateDraftProvider(updater)}
                  onRemoveProviderModel={(_providerId, modelId) => removeDraftProviderModel(modelId)}
                  onModelOverrideChange={updateDraftModelOverride}
                />
              </div>
            </div>
          </div>
        ) : null}
      </div>
    );
  };

  return (
    <section
      data-testid="llm-provider-configuration-section"
      className={cn('flex min-h-0 flex-1 flex-col space-y-4', isSettingsSurface && 'space-y-5')}
    >
      {showSectionIntro ? (
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="space-y-1.5">
            <h3 className="text-lg font-semibold text-foreground sm:text-xl">{t('llm.providerConfiguration.title')}</h3>
            <p className="max-w-2xl text-sm leading-6 text-muted-foreground">{t('llm.providerConfiguration.desc')}</p>
          </div>
          <Button type="button" onClick={openAddDialog} className="gap-2 self-start">
            <Plus className="h-4 w-4" />
            <span>{t('llm.providerConfiguration.addProvider')}</span>
          </Button>
        </div>
      ) : null}

      {!showSectionIntro && providerItems.length > 0 ? (
        <div className="flex justify-end">
          <Button type="button" onClick={openAddDialog} className="gap-2">
            <Plus className="h-4 w-4" />
            <span>{t('llm.providerConfiguration.addProvider')}</span>
          </Button>
        </div>
      ) : null}

      <div data-testid="llm-provider-list-pane" className="min-h-0 flex-1 space-y-3 overflow-y-auto">
        {providerItems.length === 0 ? (
          <div className="flex min-h-[260px] flex-col items-center justify-center rounded-lg border border-dashed border-border/80 bg-muted/25 px-6 text-center">
            <div className="text-base font-semibold text-foreground">{t('llm.providerConfiguration.emptyTitle')}</div>
            <p className="mt-2 max-w-md text-sm leading-6 text-muted-foreground">{t('llm.providerConfiguration.emptyDesc')}</p>
            <Button type="button" onClick={openAddDialog} className="mt-5 gap-2">
              <Plus className="h-4 w-4" />
              <span>{t('llm.providerConfiguration.addProvider')}</span>
            </Button>
          </div>
        ) : (
          providerItems.map(([providerId, provider]) => {
            const providerMeta = provider.provider_type === 'custom'
              ? undefined
              : registry.providers.find((item) => item.id === provider.provider_type);
            const references = scenarioReferences[providerId] || [];
            const serviceLabels = SERVICE_NAMES
              .filter((serviceName) => provider.services[serviceName]?.enabled)
              .map((serviceName) => t(`llm.providerConfiguration.serviceLabels.${serviceName}`));
            return (
              <div
                key={providerId}
                data-testid={`llm-provider-row-${providerId}`}
                className={cn(
                  'flex flex-col gap-4 rounded-lg border border-border/70 bg-background/80 p-4 transition sm:flex-row sm:items-center sm:justify-between',
                  providerId === activeProviderId && 'border-primary/45 bg-primary/5'
                )}
              >
                <button
                  type="button"
                  className="flex min-w-0 flex-1 items-start gap-3 text-left"
                  onClick={() => onActiveProviderChange(providerId)}
                >
                  <ProviderIcon
                    providerId={provider.provider_type}
                    iconName={providerMeta?.icon || (provider.provider_type === 'custom' ? 'custom' : undefined)}
                    displayName={provider.display_name || providerMeta?.display_name || providerId}
                  />
                  <span className="min-w-0 space-y-1">
                    <span className="block truncate text-sm font-semibold text-foreground">
                      {provider.display_name || providerMeta?.display_name || providerId}
                    </span>
                    <span className="block text-xs text-muted-foreground">
                      {provider.provider_type === 'custom'
                        ? t('llm.providerConfiguration.providerKinds.custom')
                        : providerMeta?.display_name || provider.provider_type}
                    </span>
                    <span className="flex flex-wrap gap-1.5 pt-1">
                      {serviceLabels.map((label) => (
                        <span key={label} className="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">
                          {label}
                        </span>
                      ))}
                    </span>
                    {references.length > 0 ? (
                      <span className="block text-xs leading-5 text-muted-foreground">
                        {t('llm.providerConfiguration.referencedBy')}: {references.map((scenario) => t(`llm.scenarios.${scenario}.title`)).join(' / ')}
                      </span>
                    ) : null}
                  </span>
                </button>
                <div className="flex shrink-0 flex-wrap items-center gap-2 sm:justify-end">
                  <div className="inline-flex items-center gap-2 rounded-md bg-muted/55 px-3 py-2 text-sm">
                    <span className="text-muted-foreground">{t('llm.fields.enabled')}</span>
                    <Switch
                      aria-label={t('llm.fields.enabled')}
                      checked={provider.enabled}
                      onCheckedChange={(checked) => onProviderChange(providerId, (draft) => { draft.enabled = checked; })}
                    />
                  </div>
                  <Button type="button" variant="outline" size="sm" className="gap-2" onClick={() => openEditDialog(providerId)}>
                    <Pencil className="h-4 w-4" />
                    <span>{t('llm.providerConfiguration.editProvider')}</span>
                  </Button>
                  <Button type="button" variant="ghost" size="sm" className="gap-2 text-destructive" onClick={() => removeProvider(providerId)}>
                    <Trash2 className="h-4 w-4" />
                    <span>{t('llm.providerConfiguration.deleteProvider')}</span>
                  </Button>
                </div>
              </div>
            );
          })
        )}
      </div>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-h-[88vh] max-w-4xl overflow-hidden p-0">
          <DialogHeader>
            <DialogTitle>
              {editorMode === 'add'
                ? t('llm.providerConfiguration.addProvider')
                : t('llm.providerConfiguration.editProvider')}
            </DialogTitle>
            <DialogDescription>{t('llm.providerConfiguration.editorDesc')}</DialogDescription>
          </DialogHeader>

          <div className="max-h-[68vh] space-y-5 overflow-y-auto px-6 pb-6">
            {editorMode === 'add' ? (
              <div className="space-y-3">
                <div className="text-sm font-semibold text-foreground">{t('llm.providerConfiguration.providerTemplate')}</div>
                <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                  {providerTemplates.map((provider) => (
                    <button
                      key={provider.id}
                      type="button"
                      onClick={() => handleTemplateChange(provider.id)}
                      className={cn(
                        'flex items-center gap-3 rounded-lg border border-border/70 p-3 text-left transition hover:bg-muted/45',
                        selectedTemplateId === provider.id && 'border-primary/55 bg-primary/6'
                      )}
                    >
                      <ProviderIcon providerId={provider.provider_type || provider.id} iconName={provider.icon} displayName={provider.display_name || provider.id} />
                      <span className="min-w-0 flex-1 truncate text-sm font-medium">{provider.display_name || provider.id}</span>
                      {selectedTemplateId === provider.id ? <Check className="h-4 w-4 text-primary" /> : null}
                    </button>
                  ))}
                  <button
                    type="button"
                    onClick={() => handleTemplateChange('custom')}
                    className={cn(
                      'flex items-center gap-3 rounded-lg border border-border/70 p-3 text-left transition hover:bg-muted/45',
                      selectedTemplateId === 'custom' && 'border-primary/55 bg-primary/6'
                    )}
                  >
                    <ProviderIcon providerId="custom" iconName="custom" displayName={t('llm.providerConfiguration.providerKinds.custom')} />
                    <span className="min-w-0 flex-1 truncate text-sm font-medium">{t('llm.providerConfiguration.providerKinds.custom')}</span>
                    {selectedTemplateId === 'custom' ? <Check className="h-4 w-4 text-primary" /> : null}
                  </button>
                </div>
              </div>
            ) : null}

            {draftProvider ? (
              <>
                <div className="space-y-3">
                  <div className="grid gap-3 md:grid-cols-2">
                    <label className="space-y-2">
                      <span className="text-sm font-medium">{t('llm.fields.displayName')}</span>
                      <input
                        aria-label={t('llm.fields.displayName')}
                        className={fieldClassName}
                        value={draftProvider.display_name || ''}
                        onChange={(event) => updateDraftProvider((provider) => { provider.display_name = event.target.value; })}
                      />
                    </label>
                    {draftProvider.provider_type === 'custom' ? (
                      <label className="space-y-2">
                        <span className="text-sm font-medium">{t('llm.fields.apiFormat')}</span>
                        <SelectField
                          value={draftProvider.api_format || 'openai'}
                          allowEmpty={false}
                          options={(registry.custom_provider.fields?.api_format?.options || ['openai', 'anthropic']).map((option) => ({
                            label: t(`llm.apiFormatOptions.${option}`),
                            value: option,
                          }))}
                          onChange={(nextValue) => updateDraftProvider((provider) => { provider.api_format = nextValue as ApiFormat; })}
                        />
                      </label>
                    ) : null}
                  </div>
                  <div className="grid gap-3 md:grid-cols-2">
                    <label className="space-y-2">
                      <span className="text-sm font-medium">{t('llm.fields.apiKey')}</span>
                      {renderSecretField({
                        scope: 'provider',
                        ariaLabel: t('llm.fields.apiKey'),
                        value: draftProvider.api_key || '',
                        onChange: (nextValue) => updateDraftProvider((provider) => { provider.api_key = nextValue; }),
                      })}
                    </label>
                    <label className="space-y-2">
                      <span className="text-sm font-medium">{t('llm.fields.baseUrl')}</span>
                      <input
                        aria-label={t('llm.fields.baseUrl')}
                        className={fieldClassName}
                        placeholder={activeProviderMeta?.default_base_url || ''}
                        value={draftProvider.base_url || ''}
                        onChange={(event) => updateDraftProvider((provider) => { provider.base_url = event.target.value; })}
                      />
                    </label>
                  </div>
                  <p className="text-xs leading-5 text-muted-foreground">
                    {t('llm.providerConfiguration.providerConnectionHint')}
                  </p>
                </div>

                <div className="space-y-3">
                  <div className="text-sm font-semibold text-foreground">{t('llm.providerConfiguration.servicesTitle')}</div>
                  {SERVICE_NAMES.map(renderServiceFields)}
                </div>
              </>
            ) : null}
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setDialogOpen(false)}>
              {t('common.cancel')}
            </Button>
            <Button type="button" onClick={saveDraftProvider}>
              {t('llm.providerConfiguration.saveProvider')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
};
