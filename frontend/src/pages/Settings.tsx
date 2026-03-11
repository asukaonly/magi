import React, { useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';
import { useTranslation } from 'react-i18next';
import {
  Download,
  Save,
  Trash2,
  AlertTriangle,
  Settings2,
  Brain,
  User,
  Database,
  Wrench,
  Cpu,
  ChevronRight,
  Sun,
  Moon,
  Monitor,
  BarChart3,
  ScrollText,
  PlugZap,
  Send,
} from 'lucide-react';
import { DynamicToolsConfig } from '@/components/config-forms/DynamicToolConfig';
import LLMForm from '@/components/config-forms/LLMForm';
import { LLMUsageSection } from '@/components/settings/LLMUsageSection';
import ActionsSection from '@/components/settings/ActionsSection';
import ExtensionsSection from '@/components/settings/ExtensionsSection';
import TimelineSourcesSection from '@/components/settings/TimelineSourcesSection';
import { timelineApi, type TimelineSourceStatusItem } from '@/api/modules/timeline';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Switch } from '@/components/ui/switch';
import { Badge } from '@/components/ui/badge';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { SelectField as BaseSelectField } from '@/components/config-forms/fields';
import { configApi, DEFAULT_SYSTEM_CONFIG, SystemConfig } from '../api/modules/config';
import { memoryApi } from '../api/modules/memory';
import { cn } from '@/lib/utils';
import { useThemeStore } from '@/stores';

type SelectOption = { label: string; value: string };

// Navigation items
type NavItem = {
  id: string;
  icon: React.ElementType;
};

const NAV_ITEMS: NavItem[] = [
  { id: 'preferences', icon: Settings2 },
  { id: 'llm', icon: Brain },
  { id: 'usage', icon: BarChart3 },
  { id: 'personality', icon: User },
  { id: 'memory', icon: Database },
  { id: 'timeline', icon: ScrollText },
  { id: 'extensions', icon: PlugZap },
  { id: 'tools', icon: Wrench },
  { id: 'actions', icon: Send },
  { id: 'system', icon: Cpu },
];

// Wrapper for SelectField with label
const LabeledSelectField: React.FC<{
  label: string;
  value: string;
  options: SelectOption[];
  onChange: (value: string) => void;
}> = ({ label, value, options, onChange }) => (
  <label className="space-y-2">
    <span className="text-sm font-medium">{label}</span>
    <BaseSelectField
      value={value}
      onChange={onChange}
      options={options}
      allowEmpty={false}
    />
  </label>
);

const NumberField: React.FC<{
  label: string;
  value: number | undefined;
  min?: number;
  max?: number;
  step?: number;
  onChange: (value: number) => void;
}> = ({ label, value, min, max, step, onChange }) => (
  <label className="space-y-2">
    <span className="text-sm font-medium">{label}</span>
    <input
      className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60"
      type="number"
      min={min}
      max={max}
      step={step}
      value={value ?? ''}
      onChange={(event) => onChange(Number(event.target.value))}
    />
  </label>
);

const serializeConfigWithoutLlm = (config: SystemConfig) => {
  const { llm: _llm, ...rest } = config;
  return JSON.stringify(rest);
};

export const SettingsPage: React.FC = () => {
  const { t, i18n } = useTranslation('app');
  const themeMode = useThemeStore((state) => state.mode);
  const setThemeMode = useThemeStore((state) => state.setMode);
  const [config, setConfig] = useState<SystemConfig>(DEFAULT_SYSTEM_CONFIG);
  const [llmDraft, setLlmDraft] = useState(DEFAULT_SYSTEM_CONFIG.llm);
  const [loading, setLoading] = useState(true);
  const [savingLlm, setSavingLlm] = useState(false);
  const [activeSection, setActiveSection] = useState('preferences');
  const [downloadModel, setDownloadModel] = useState('bge-m3');
  const [downloadProgress, setDownloadProgress] = useState(0);
  const [downloadStatus, setDownloadStatus] = useState<'not_downloaded' | 'downloading' | 'ready'>('not_downloaded');
  const [installedModels, setInstalledModels] = useState<string[]>([]);
  const [showClearConfirm, setShowClearConfirm] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [timelineStatuses, setTimelineStatuses] = useState<TimelineSourceStatusItem[]>([]);
  const [timelineStatusesLoading, setTimelineStatusesLoading] = useState(false);
  const [timelineSelection, setTimelineSelection] = useState<string | null>(null);
  const hasLoadedConfigRef = useRef(false);
  const lastSavedNonLlmSnapshotRef = useRef(serializeConfigWithoutLlm(DEFAULT_SYSTEM_CONFIG));
  const autoSaveRequestIdRef = useRef(0);

  useEffect(() => {
    void fetchConfig();
    void fetchInstalledModels();
    void fetchTimelineStatuses();
  }, []);

  const patchConfig = (updater: (draft: SystemConfig) => void) => {
    setConfig((prev) => {
      const next = structuredClone(prev);
      updater(next);
      return next;
    });
  };

  const fetchConfig = async () => {
    setLoading(true);
    try {
      const response = await configApi.get();
      const nextConfig = response.data || DEFAULT_SYSTEM_CONFIG;
      setConfig(nextConfig);
      setLlmDraft(nextConfig.llm);
      lastSavedNonLlmSnapshotRef.current = serializeConfigWithoutLlm(nextConfig);
      hasLoadedConfigRef.current = true;
    } catch (error: any) {
      toast.error(t('settings.loadFailed', { message: error?.message || 'unknown' }));
    } finally {
      setLoading(false);
    }
  };

  const fetchInstalledModels = async () => {
    try {
      const response = await memoryApi.listModels();
      setInstalledModels(response.data?.models || []);
    } catch {
      setInstalledModels([]);
    }
  };

  const fetchTimelineStatuses = async () => {
    setTimelineStatusesLoading(true);
    try {
      const response = await timelineApi.getSourceStatus();
      setTimelineStatuses(response.sources || []);
    } catch (error: any) {
      toast.error(t('settings.timeline.errors.statusLoadFailed', { message: error?.message || 'unknown' }));
      setTimelineStatuses([]);
    } finally {
      setTimelineStatusesLoading(false);
    }
  };

  useEffect(() => {
    if (timelineSelection && !timelineStatuses.some((source) => source.source_name === timelineSelection)) {
      setTimelineSelection(null);
    }
  }, [timelineSelection, timelineStatuses]);

  useEffect(() => {
    if (activeSection !== 'timeline') {
      return;
    }
    const timer = window.setInterval(() => {
      void fetchTimelineStatuses();
    }, 4000);
    return () => {
      window.clearInterval(timer);
    };
  }, [activeSection]);

  const handleSaveLlm = async () => {
    try {
      setSavingLlm(true);
      await configApi.update({
        ...config,
        llm: llmDraft,
      });
      setConfig((prev) => ({
        ...prev,
        llm: llmDraft,
      }));
      toast.success(t('settings.saveSuccess'));
    } catch (error: any) {
      toast.error(t('settings.saveFailed', { message: error?.message || 'unknown' }));
    } finally {
      setSavingLlm(false);
    }
  };

  useEffect(() => {
    if (!hasLoadedConfigRef.current || loading) {
      return;
    }

    const snapshot = serializeConfigWithoutLlm(config);
    if (snapshot === lastSavedNonLlmSnapshotRef.current) {
      return;
    }

    const requestId = ++autoSaveRequestIdRef.current;
    const timer = window.setTimeout(async () => {
      try {
        await configApi.update(config);
        if (requestId === autoSaveRequestIdRef.current) {
          lastSavedNonLlmSnapshotRef.current = snapshot;
        }
      } catch (error: any) {
        toast.error(t('settings.saveFailed', { message: error?.message || 'unknown' }));
      }
    }, 600);

    return () => {
      window.clearTimeout(timer);
    };
  }, [config, loading, t]);

  const llmDirty = JSON.stringify(llmDraft) !== JSON.stringify(config.llm);

  const startDownload = async () => {
    try {
      const response = await memoryApi.downloadModel(downloadModel);
      setDownloadProgress(response.data?.progress || 0);
      setDownloadStatus(response.data?.status || 'not_downloaded');
    } catch (error: any) {
      toast.error(error?.message || t('settings.downloadStartFailed'));
      return;
    }

    const timer = window.setInterval(async () => {
      try {
        const status = await memoryApi.getModelStatus(downloadModel);
        setDownloadProgress(status.data?.progress || 0);
        setDownloadStatus(status.data?.status || 'not_downloaded');
        if (status.data?.status === 'ready') {
          window.clearInterval(timer);
          toast.success(t('settings.modelReady'));
          await fetchInstalledModels();
        }
      } catch {
        window.clearInterval(timer);
      }
    }, 800);
  };

  const handleClearMemory = async () => {
    setClearing(true);
    try {
      const response = await memoryApi.clearAll();
      // API client already unwraps res.data, so check response.success directly
      if (response.success) {
        const results = response.results;
        const totalCleared = Object.values(results).reduce(
          (sum: number, r: any) => sum + (r.cleared ? r.count : 0),
          0
        );
        toast.success(t('settings.memoryCleared', { count: totalCleared }));
        if (response.warnings && response.warnings.length > 0) {
          response.warnings.forEach((w) => console.warn(w));
        }
        // Notify Chat page to refresh sessions and history
        window.dispatchEvent(new CustomEvent('magi-memory-cleared'));
      }
    } catch (error: any) {
      toast.error(error?.message || t('settings.memoryClearFailed'));
    } finally {
      setClearing(false);
      setShowClearConfirm(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <div className="flex items-center gap-2 text-muted-foreground">
          <LoadingSpinner />
          <span className="text-sm">{t('settings.loadingConfig')}</span>
        </div>
      </div>
    );
  }

  // Render section content
  const renderSectionContent = () => {
    switch (activeSection) {
      case 'preferences':
        return (
          <div className="space-y-6">
            <div>
              <h2 className="text-xl font-semibold">{t('settings.tabs.preferences')}</h2>
              <p className="text-sm text-muted-foreground">{t('settings.preferencesDesc')}</p>
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              <LabeledSelectField
                label={t('settings.fields.language')}
                value={config.preferences.language}
                options={[
                  { label: t('language.zhHans', { ns: 'onboarding' }), value: 'zh' },
                  { label: t('language.en', { ns: 'onboarding' }), value: 'en' },
                ]}
                onChange={(value) => {
                  patchConfig((draft) => {
                    draft.preferences.language = value as SystemConfig['preferences']['language'];
                  });
                  i18n.changeLanguage(value);
                }}
              />
            </div>

            {/* Theme selector */}
            <div className="space-y-3">
              <h3 className="text-sm font-medium">{t('settings.fields.theme')}</h3>
              <div className="flex gap-3">
                {([
                  { value: 'light', icon: Sun, label: t('settings.theme.light') },
                  { value: 'dark', icon: Moon, label: t('settings.theme.dark') },
                  { value: 'system', icon: Monitor, label: t('settings.theme.system') },
                ] as const).map((option) => {
                  const Icon = option.icon;
                  const isActive = themeMode === option.value;
                  return (
                    <button
                      key={option.value}
                      type="button"
                      onClick={() => setThemeMode(option.value)}
                      aria-pressed={isActive}
                      aria-label={option.label}
                      className={cn(
                        'flex flex-1 flex-col items-center gap-2 rounded-xl border-2 p-4 transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50',
                        isActive
                          ? 'border-primary bg-primary/10 text-primary'
                          : 'border-border hover:border-border/80 hover:bg-muted/50'
                      )}
                    >
                      <Icon className="h-5 w-5" />
                      <span className="text-sm font-medium">{option.label}</span>
                    </button>
                  );
                })}
              </div>
              <p className="text-xs text-muted-foreground">{t('settings.themeDesc')}</p>
            </div>
          </div>
        );

      case 'llm':
        return (
          <div className="space-y-6">
            <div>
              <h2 className="text-xl font-semibold">{t('settings.tabs.llm')}</h2>
              <p className="text-sm text-muted-foreground">{t('settings.llmDesc')}</p>
            </div>
            <LLMForm
              quickMode={false}
              value={llmDraft}
              showAdvancedByDefault
              onChange={setLlmDraft}
            />
            <div className="flex items-center justify-between rounded-2xl border border-border/60 bg-muted/20 px-4 py-3">
              <p className="text-sm text-muted-foreground">{t('settings.llmSaveHint')}</p>
              <Button size="sm" onClick={handleSaveLlm} disabled={!llmDirty || savingLlm}>
                <Save className="mr-2 h-4 w-4" />
                {savingLlm ? t('settings.saving') : t('settings.saveLLM')}
              </Button>
            </div>
          </div>
        );

      case 'personality':
        return (
          <div className="space-y-6">
            <div>
              <h2 className="text-xl font-semibold">{t('settings.tabs.personality')}</h2>
              <p className="text-sm text-muted-foreground">{t('settings.personalityDesc')}</p>
            </div>
            <div className="overflow-hidden rounded-3xl border border-primary/20 bg-muted/30 p-5">
              <div className="mb-3 flex items-center justify-between gap-3">
                <div>
                  <h3 className="font-medium text-primary">{t('settings.fields.currentPersonality')}</h3>
                  <p className="text-sm text-muted-foreground">{config.personality?.persona_entity?.basic_profile?.name || 'Default'}</p>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  className="rounded-xl"
                  onClick={() => window.location.href = '/personality'}
                >
                  {t('settings.actions.configure')}
                </Button>
              </div>
              <p className="text-xs leading-6 text-muted-foreground">
                {config.personality?.persona_entity?.basic_profile?.occupation || ''}
              </p>
            </div>
          </div>
        );

      case 'usage':
        return <LLMUsageSection />;

      case 'memory':
        return (
          <div className="space-y-6">
            <div>
              <h2 className="text-xl font-semibold">{t('settings.tabs.memory')}</h2>
              <p className="text-sm text-muted-foreground">{t('settings.memoryDesc')}</p>
            </div>

            {/* Clear memory card */}
            <Card className="border-destructive/50">
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-base text-destructive">
                  <Trash2 className="h-4 w-4" />
                  {t('settings.fields.clearMemory')}
                </CardTitle>
                <CardDescription>
                  {t('settings.fields.clearMemoryDesc')}
                </CardDescription>
              </CardHeader>
              <CardContent>
                <Button
                  variant="destructive"
                  onClick={() => setShowClearConfirm(true)}
                >
                  <Trash2 className="mr-2 h-4 w-4" />
                  {t('settings.actions.clearMemory')}
                </Button>
              </CardContent>
            </Card>

            {/* Memory layers */}
            <div className="space-y-3">
              <h3 className="font-medium">{t('settings.fields.memoryLayers')}</h3>
              <div className="grid gap-3 md:grid-cols-2">
                {(['L1', 'L2', 'L3', 'L4', 'L5'] as const).map((layer) => (
                  <label
                    key={layer}
                    className="flex items-center justify-between rounded-md border p-3"
                  >
                    <span className="text-sm font-medium">{t(`settings.fields.${layer.toLowerCase()}Enabled`)}</span>
                    <Switch
                      checked={config.memory_layers[layer].enabled}
                      onCheckedChange={(checked) => patchConfig((draft) => {
                        draft.memory_layers[layer].enabled = checked;
                      })}
                    />
                  </label>
                ))}
              </div>
            </div>

            {/* Model download */}
            <Card>
              <CardHeader>
                <CardTitle className="text-base">{t('settings.fields.l3ModelDownload')}</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <LabeledSelectField
                  label={t('settings.fields.model')}
                  value={downloadModel}
                  options={[
                    { label: 'bge-m3', value: 'bge-m3' },
                    { label: 'nomic-embed-text', value: 'nomic-embed-text' },
                    { label: 'text-embedding-3-large', value: 'text-embedding-3-large' },
                  ]}
                  onChange={setDownloadModel}
                />
                <Button variant="outline" onClick={startDownload}>
                  <Download className="mr-2 h-4 w-4" />
                  {t('settings.fields.downloadModel')}
                </Button>
                <div className="space-y-1">
                  <div className="h-2 overflow-hidden rounded-full bg-muted">
                    <div className="h-full bg-primary transition-all" style={{ width: `${downloadProgress}%` }} />
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {downloadStatus} · {downloadProgress}%
                  </div>
                </div>
                <div className="flex flex-wrap gap-2">
                  <span className="text-sm text-muted-foreground">{t('settings.fields.installedModels')}</span>
                  {installedModels.length > 0 ? installedModels.map((model) => (
                    <Badge key={model} variant="secondary">{model}</Badge>
                  )) : <Badge variant="outline">{t('settings.fields.none')}</Badge>}
                </div>
              </CardContent>
            </Card>
          </div>
        );

      case 'timeline':
        return (
          <TimelineSourcesSection
            value={config.timeline}
            userMode={config.preferences.user_mode}
            statuses={timelineStatuses}
            loadingStatus={timelineStatusesLoading}
            selectedSourceName={timelineSelection}
            onSelectSource={setTimelineSelection}
            onRefreshSources={fetchTimelineStatuses}
            onChange={(updater) => patchConfig((draft) => {
              updater(draft.timeline);
            })}
          />
        );

      case 'tools':
        return (
          <div className="space-y-6">
            <div>
              <h2 className="text-xl font-semibold">{t('settings.tabs.tools')}</h2>
              <p className="text-sm text-muted-foreground">{t('settings.toolsDesc')}</p>
            </div>
            <DynamicToolsConfig />
          </div>
        );

      case 'extensions':
        return <ExtensionsSection />;

      case 'actions':
        return <ActionsSection />;

      case 'system':
        return (
          <div className="space-y-6">
            <div>
              <h2 className="text-xl font-semibold">{t('settings.tabs.system')}</h2>
              <p className="text-sm text-muted-foreground">{t('settings.systemDesc')}</p>
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              <LabeledSelectField
                label={t('settings.fields.loopStrategy')}
                value={config.loop.strategy}
                options={[
                  { label: 'STEP', value: 'step' },
                  { label: 'WAVE', value: 'wave' },
                  { label: 'CONTINUOUS', value: 'continuous' },
                ]}
                onChange={(value) => patchConfig((draft) => {
                  draft.loop.strategy = value as SystemConfig['loop']['strategy'];
                })}
              />
              <NumberField
                label={t('settings.fields.loopInterval')}
                value={config.loop.interval}
                min={0.1}
                max={60}
                step={0.1}
                onChange={(value) => patchConfig((draft) => {
                  draft.loop.interval = value;
                })}
              />
              <LabeledSelectField
                label={t('settings.fields.busBackend')}
                value={config.message_bus.backend}
                options={[
                  { label: 'memory', value: 'memory' },
                  { label: 'sqlite', value: 'sqlite' },
                  { label: 'redis', value: 'redis' },
                ]}
                onChange={(value) => patchConfig((draft) => {
                  draft.message_bus.backend = value as SystemConfig['message_bus']['backend'];
                })}
              />
              <NumberField
                label={t('settings.fields.busQueueSize')}
                value={config.message_bus.max_size}
                min={100}
                max={50000}
                onChange={(value) => patchConfig((draft) => {
                  draft.message_bus.max_size = value;
                })}
              />
              <NumberField
                label={t('settings.fields.wsPort')}
                value={config.websocket.port}
                min={1024}
                max={65535}
                onChange={(value) => patchConfig((draft) => {
                  draft.websocket.port = value;
                })}
              />
              <LabeledSelectField
                label={t('settings.fields.logLevel')}
                value={config.log.level}
                options={[
                  { label: 'DEBUG', value: 'DEBUG' },
                  { label: 'INFO', value: 'INFO' },
                  { label: 'WARNING', value: 'WARNING' },
                  { label: 'ERROR', value: 'ERROR' },
                ]}
                onChange={(value) => patchConfig((draft) => {
                  draft.log.level = value as SystemConfig['log']['level'];
                })}
              />
            </div>
          </div>
        );

      default:
        return null;
    }
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* Header */}
      <div className="shrink-0 border-b bg-background/95 px-6 py-4 backdrop-blur">
        <div>
          <h1 className="text-xl font-semibold">{t('settings.title')}</h1>
          <p className="text-sm text-muted-foreground">{t('settings.subtitle')}</p>
        </div>
      </div>

      {/* Main content */}
      <div className="flex flex-1 min-h-0 overflow-hidden">
        {/* Left navigation */}
        <nav className="shrink-0 w-52 border-r bg-muted/30 p-3">
          <div className="space-y-1">
            {NAV_ITEMS.map((item) => {
              const Icon = item.icon;
              const isActive = activeSection === item.id;
              return (
                <div key={item.id} className="space-y-1">
                  <button
                    onClick={() => {
                      setActiveSection(item.id);
                      if (item.id === 'timeline') {
                        setTimelineSelection(null);
                        void fetchTimelineStatuses();
                      }
                    }}
                    aria-current={isActive ? 'page' : undefined}
                    aria-label={t(`settings.tabs.${item.id}`)}
                    className={cn(
                      'flex w-full items-center justify-between rounded-lg px-3 py-2.5 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40',
                      isActive
                        ? 'bg-primary text-primary-foreground'
                        : 'text-muted-foreground hover:bg-muted hover:text-foreground'
                    )}
                  >
                    <div className="flex items-center gap-2.5">
                      <Icon className="h-4 w-4" />
                      <span>{t(`settings.tabs.${item.id}`)}</span>
                    </div>
                    {isActive && <ChevronRight className="h-4 w-4" />}
                  </button>

                  {item.id === 'timeline' && isActive ? (
                    <div className="space-y-1 pl-3">
                      <button
                        type="button"
                        onClick={() => setTimelineSelection(null)}
                        data-testid="timeline-nav-overview"
                        aria-current={timelineSelection === null ? 'page' : undefined}
                        className={cn(
                          'flex w-full items-center rounded-lg px-3 py-2 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40',
                          timelineSelection === null
                            ? 'bg-background text-foreground shadow-sm'
                            : 'text-muted-foreground hover:bg-background/70 hover:text-foreground'
                        )}
                      >
                        {t('settings.timeline.nav.overview')}
                      </button>

                      {timelineStatuses.map((source) => {
                        const isSelected = timelineSelection === source.source_name;
                        return (
                          <button
                            key={source.source_name}
                            type="button"
                            onClick={() => setTimelineSelection(source.source_name)}
                            data-testid={`timeline-nav-source-${source.source_name}`}
                            aria-current={isSelected ? 'page' : undefined}
                            className={cn(
                              'flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40',
                              isSelected
                                ? 'bg-background text-foreground shadow-sm'
                                : 'text-muted-foreground hover:bg-background/70 hover:text-foreground'
                            )}
                          >
                            <span className="truncate">{source.display_name}</span>
                            {source.last_error ? (
                              <span className="ml-auto h-2 w-2 rounded-full bg-destructive" aria-hidden="true" />
                            ) : null}
                          </button>
                        );
                      })}
                    </div>
                  ) : null}
                </div>
              );
            })}
          </div>
        </nav>

        {/* Right content */}
        <main className="flex-1 overflow-y-auto p-6">
          {renderSectionContent()}
        </main>
      </div>

      {/* Confirm dialog */}
      {showClearConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <Card className="mx-4 max-w-md">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-destructive">
                <AlertTriangle className="h-5 w-5" />
                {t('settings.clearConfirm.title')}
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="rounded-md border border-destructive/50 bg-destructive/10 p-4 text-sm">
                <p className="font-medium text-destructive">{t('settings.clearConfirm.warning')}</p>
                <ul className="mt-2 list-inside list-disc space-y-1 text-destructive/80">
                  <li>{t('settings.clearConfirm.l1')}</li>
                  <li>{t('settings.clearConfirm.l2')}</li>
                  <li>{t('settings.clearConfirm.l3')}</li>
                  <li>{t('settings.clearConfirm.l4')}</li>
                  <li>{t('settings.clearConfirm.l5')}</li>
                  <li>{t('settings.clearConfirm.chatContext')}</li>
                </ul>
                <p className="mt-3 font-semibold text-destructive">
                  {t('settings.clearConfirm.irreversible')}
                </p>
              </div>
              <div className="flex justify-end gap-2">
                <Button
                  variant="outline"
                  onClick={() => setShowClearConfirm(false)}
                  disabled={clearing}
                >
                  {t('settings.clearConfirm.cancel')}
                </Button>
                <Button
                  variant="destructive"
                  onClick={handleClearMemory}
                  disabled={clearing}
                >
                  {clearing ? t('settings.clearConfirm.clearing') : t('settings.clearConfirm.confirm')}
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
};
