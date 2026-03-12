import React, {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useState,
} from 'react';
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
  ChevronDown,
  Sun,
  Moon,
  Monitor,
  BarChart3,
  ScrollText,
  PlugZap,
  Send,
  X,
  RotateCcw,
} from 'lucide-react';
import { DynamicToolsConfig } from '@/components/config-forms/DynamicToolConfig';
import LLMForm from '@/components/config-forms/LLMForm';
import { LLMUsageSection } from '@/components/settings/LLMUsageSection';
import ActionsSection from '@/components/settings/ActionsSection';
import ExtensionsSection from '@/components/settings/ExtensionsSection';
import TimelineSourcesSection from '@/components/settings/TimelineSourcesSection';
import { timelineApi, type TimelineSourceStatusItem } from '@/api/modules/timeline';
import {
  buildPluginFieldValueMap,
  pluginsApi,
  type PluginPackageState,
} from '@/api/modules/plugins';
import { toolsApi, type ToolConfig } from '@/api/modules/tools';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Switch } from '@/components/ui/switch';
import { Badge } from '@/components/ui/badge';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { SelectField as BaseSelectField } from '@/components/config-forms/fields';
import { configApi, DEFAULT_SYSTEM_CONFIG, SystemConfig, type LanguageCode } from '../api/modules/config';
import { memoryApi } from '../api/modules/memory';
import { cn } from '@/lib/utils';
import { useThemeStore, type ThemeMode } from '@/stores';
import i18n from '@/i18n';
import { ErrorBoundary } from '@/components/ui/ErrorBoundary';

type SelectOption = { label: string; value: string };

type NavLeaf = {
  id: string;
  icon: React.ElementType;
  children?: never;
};

type NavGroup = {
  id: string;
  icon: React.ElementType;
  children: Array<{ id: string }>;
};

type NavItem = NavLeaf | NavGroup;

const NAV_ITEMS: NavItem[] = [
  { id: 'preferences', icon: Settings2 },
  { id: 'llm', icon: Brain, children: [{ id: 'llmProviders' }, { id: 'llmModels' }] },
  { id: 'usage', icon: BarChart3 },
  { id: 'personality', icon: User },
  { id: 'memory', icon: Database },
  { id: 'timeline', icon: ScrollText },
  { id: 'extensions', icon: PlugZap },
  { id: 'tools', icon: Wrench },
  { id: 'actions', icon: Send },
  { id: 'system', icon: Cpu },
];

const isNavGroup = (item: NavItem): item is NavGroup => Array.isArray((item as NavGroup).children);

const LANGUAGE_STORAGE_KEY = 'magi_language';

const toI18nLanguage = (language: LanguageCode) => (language === 'zh' ? 'zh-CN' : 'en');

const persistLanguageSelection = (language: LanguageCode) => {
  const nextLanguage = toI18nLanguage(language);
  localStorage.setItem(LANGUAGE_STORAGE_KEY, language);
  document.documentElement.lang = nextLanguage;
};

const previewLanguageSelection = async (language: LanguageCode) => {
  const nextLanguage = toI18nLanguage(language);
  document.documentElement.lang = nextLanguage;
  await i18n.changeLanguage(nextLanguage);
};

const serialize = (value: unknown) => JSON.stringify(value);

const collectPluginSurfaceFields = (plugin: PluginPackageState, surfaces: string[]) =>
  plugin.contributions
    .flatMap((contribution) => contribution.fields)
    .filter((field) => surfaces.includes(field.surface));

const buildPluginDraftSnapshotFromPackages = (plugins: PluginPackageState[]) =>
  Object.fromEntries(
    plugins.map((plugin) => [
      plugin.manifest.plugin_id,
      buildPluginFieldValueMap(collectPluginSurfaceFields(plugin, ['extensions', 'actions']), plugin.current_settings),
    ])
  );

const buildPluginDraftSnapshotFromTimeline = (statuses: TimelineSourceStatusItem[]) =>
  statuses.reduce<Record<string, Record<string, any>>>((acc, source) => {
    const current = acc[source.plugin_id] || {};
    for (const field of source.fields) {
      current[field.key] = source.current_settings[field.key] ?? field.default;
    }
    const activationFlow = source.activation_flow;
    if (activationFlow) {
      current[activationFlow.enabled_key] =
        source.current_settings[activationFlow.enabled_key] ?? source.enabled;
      current[activationFlow.configured_key] =
        source.current_settings[activationFlow.configured_key] ?? false;
      for (const field of activationFlow.fields) {
        current[field.key] = source.current_settings[field.key] ?? field.default;
      }
    }
    acc[source.plugin_id] = current;
    return acc;
  }, {});

const mergeDraftMaps = (
  current: Record<string, Record<string, any>>,
  incoming: Record<string, Record<string, any>>,
  { preserveExisting }: { preserveExisting: boolean }
) => {
  const next = structuredClone(current);
  for (const [pluginId, values] of Object.entries(incoming)) {
    next[pluginId] = next[pluginId] || {};
    for (const [key, value] of Object.entries(values)) {
      if (preserveExisting && key in next[pluginId]) {
        continue;
      }
      next[pluginId][key] = value;
    }
  }
  return next;
};

const buildToolDraftSnapshot = (tools: ToolConfig[]) =>
  Object.fromEntries(
    tools.map((tool) => [
      tool.name,
      {
        enabled: tool.enabled,
        values: structuredClone(tool.current_values || {}),
      },
    ])
  );

const diffFlatMaps = (saved: Record<string, any>, draft: Record<string, any>) => {
  const keys = new Set([...Object.keys(saved), ...Object.keys(draft)]);
  const updates: Record<string, any> = {};
  for (const key of keys) {
    if (serialize(saved[key] ?? null) !== serialize(draft[key] ?? null)) {
      updates[key] = draft[key];
    }
  }
  return updates;
};

const LabeledSelectField: React.FC<{
  label: string;
  value: string;
  options: SelectOption[];
  onChange: (value: string) => void;
}> = ({ label, value, options, onChange }) => (
  <label className="space-y-2">
    <span className="text-sm font-medium">{label}</span>
    <BaseSelectField value={value} onChange={onChange} options={options} allowEmpty={false} />
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

export interface SettingsPageHandle {
  hasUnsavedChanges: () => boolean;
  discardChanges: () => Promise<void>;
}

interface SettingsPageProps {
  onRequestClose?: () => void;
}

export const SettingsPage = forwardRef<SettingsPageHandle, SettingsPageProps>(({ onRequestClose }, ref) => {
  const { t } = useTranslation('app');
  const themeMode = useThemeStore((state) => state.mode);
  const setThemeMode = useThemeStore((state) => state.setMode);
  const [savedConfig, setSavedConfig] = useState<SystemConfig>(DEFAULT_SYSTEM_CONFIG);
  const [draftConfig, setDraftConfig] = useState<SystemConfig>(DEFAULT_SYSTEM_CONFIG);
  const [savedThemeMode, setSavedThemeMode] = useState<ThemeMode>(themeMode);
  const [draftThemeMode, setDraftThemeMode] = useState<ThemeMode>(themeMode);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [activeSection, setActiveSection] = useState('preferences');
  const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>({
    llm: false,
  });
  const [downloadModel, setDownloadModel] = useState('bge-m3');
  const [downloadProgress, setDownloadProgress] = useState(0);
  const [downloadStatus, setDownloadStatus] = useState<'not_downloaded' | 'downloading' | 'ready'>('not_downloaded');
  const [installedModels, setInstalledModels] = useState<string[]>([]);
  const [showClearConfirm, setShowClearConfirm] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [timelineStatuses, setTimelineStatuses] = useState<TimelineSourceStatusItem[]>([]);
  const [timelineStatusesLoading, setTimelineStatusesLoading] = useState(false);
  const [timelineSelection, setTimelineSelection] = useState<string | null>(null);
  const [plugins, setPlugins] = useState<PluginPackageState[]>([]);
  const [pluginsLoading, setPluginsLoading] = useState(false);
  const [pluginProcessingIds, setPluginProcessingIds] = useState<Record<string, string>>({});
  const [savedPluginDrafts, setSavedPluginDrafts] = useState<Record<string, Record<string, any>>>({});
  const [draftPluginDrafts, setDraftPluginDrafts] = useState<Record<string, Record<string, any>>>({});
  const [tools, setTools] = useState<ToolConfig[]>([]);
  const [toolsLoading, setToolsLoading] = useState(false);
  const [toolsError, setToolsError] = useState<string | null>(null);
  const [savedToolDrafts, setSavedToolDrafts] = useState<Record<string, { enabled: boolean; values: Record<string, any> }>>({});
  const [draftToolDrafts, setDraftToolDrafts] = useState<Record<string, { enabled: boolean; values: Record<string, any> }>>({});
  const [reloadingActionPlugins, setReloadingActionPlugins] = useState<Record<string, boolean>>({});

  const isNavGroupActive = (item: NavItem) => {
    if (!isNavGroup(item)) {
      return activeSection === item.id;
    }
    return item.children.some((child) => child.id === activeSection);
  };
  const isWideSection = activeSection === 'llmProviders' || activeSection === 'llmModels';

  const getGroupExpanded = (groupId: string) => expandedGroups[groupId] ?? false;

  const setGroupExpanded = (groupId: string, expanded: boolean) => {
    setExpandedGroups((prev) => ({ ...prev, [groupId]: expanded }));
  };

  const handleSectionSelect = (sectionId: string) => {
    setActiveSection(sectionId);
    if (sectionId === 'timeline') {
      setTimelineSelection(null);
      void fetchTimelineStatuses();
    }
  };

  const handleNavItemClick = (item: NavItem) => {
    if (isNavGroup(item)) {
      const isExpanded = getGroupExpanded(item.id);
      if (isExpanded) {
        setGroupExpanded(item.id, false);
        return;
      }
      setGroupExpanded(item.id, true);
      handleSectionSelect(item.children[0]?.id || item.id);
      return;
    }
    handleSectionSelect(item.id);
  };

  const patchDraftConfig = (updater: (draft: SystemConfig) => void) => {
    setDraftConfig((prev) => {
      const next = structuredClone(prev);
      updater(next);
      return next;
    });
  };

  const loadPlugins = async ({ silent = false }: { silent?: boolean } = {}) => {
    if (!silent) {
      setPluginsLoading(true);
    }
    try {
      const response = await pluginsApi.list();
      const nextPlugins = response.plugins || [];
      const nextSnapshot = buildPluginDraftSnapshotFromPackages(nextPlugins);
      setPlugins(nextPlugins);
      setSavedPluginDrafts((prev) => mergeDraftMaps(prev, nextSnapshot, { preserveExisting: false }));
      setDraftPluginDrafts((prev) => mergeDraftMaps(prev, nextSnapshot, { preserveExisting: true }));
    } catch (error: any) {
      toast.error(t('settings.extensions.errors.loadFailed', { message: error?.message || 'unknown' }));
    } finally {
      if (!silent) {
        setPluginsLoading(false);
      }
    }
  };

  const loadTools = async ({ silent = false }: { silent?: boolean } = {}) => {
    if (!silent) {
      setToolsLoading(true);
      setToolsError(null);
    }
    try {
      const response = await toolsApi.listWithConfig();
      const nextTools = response.tools || [];
      const nextDrafts = buildToolDraftSnapshot(nextTools);
      setTools(nextTools);
      setSavedToolDrafts(nextDrafts);
      setDraftToolDrafts((prev) => {
        if (Object.keys(prev).length === 0) {
          return nextDrafts;
        }
        const merged = structuredClone(prev);
        for (const [toolName, snapshot] of Object.entries(nextDrafts)) {
          merged[toolName] = {
            enabled: merged[toolName]?.enabled ?? snapshot.enabled,
            values: {
              ...snapshot.values,
              ...(merged[toolName]?.values || {}),
            },
          };
        }
        return merged;
      });
    } catch (error: any) {
      const message = error?.message || t('settings.errorUnknown');
      setToolsError(t('settings.loadToolsFailed', { message }));
      toast.error(t('settings.loadToolsFailed', { message }));
    } finally {
      if (!silent) {
        setToolsLoading(false);
      }
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
      const nextStatuses = response.sources || [];
      const nextSnapshot = buildPluginDraftSnapshotFromTimeline(nextStatuses);
      setTimelineStatuses(nextStatuses);
      setSavedPluginDrafts((prev) => mergeDraftMaps(prev, nextSnapshot, { preserveExisting: false }));
      setDraftPluginDrafts((prev) => mergeDraftMaps(prev, nextSnapshot, { preserveExisting: true }));
    } catch (error: any) {
      toast.error(t('settings.timeline.errors.statusLoadFailed', { message: error?.message || 'unknown' }));
      setTimelineStatuses([]);
    } finally {
      setTimelineStatusesLoading(false);
    }
  };

  const fetchConfig = async () => {
    setLoading(true);
    try {
      const response = await configApi.get();
      const nextConfig = response.data || DEFAULT_SYSTEM_CONFIG;
      setSavedConfig(nextConfig);
      setDraftConfig(structuredClone(nextConfig));
      setSavedThemeMode(themeMode);
      setDraftThemeMode(themeMode);
    } catch (error: any) {
      toast.error(t('settings.loadFailed', { message: error?.message || 'unknown' }));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void Promise.all([
      fetchConfig(),
      fetchInstalledModels(),
      fetchTimelineStatuses(),
      loadPlugins(),
      loadTools(),
    ]);
  }, []);

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
    return () => window.clearInterval(timer);
  }, [activeSection]);

  const configDirty = serialize(savedConfig) !== serialize(draftConfig);
  const pluginsDirty = serialize(savedPluginDrafts) !== serialize(draftPluginDrafts);
  const toolsDirty = serialize(savedToolDrafts) !== serialize(draftToolDrafts);
  const themeDirty = savedThemeMode !== draftThemeMode;
  const dirty = configDirty || pluginsDirty || toolsDirty || themeDirty;

  const handleThemePreviewChange = (mode: ThemeMode) => {
    setDraftThemeMode(mode);
    setThemeMode(mode, { persist: false });
  };

  const handleLanguagePreviewChange = (value: string) => {
    const nextLanguage = value as LanguageCode;
    patchDraftConfig((draft) => {
      draft.preferences.language = nextLanguage;
    });
    void previewLanguageSelection(nextLanguage);
  };

  const handlePluginDraftChange = (pluginId: string, key: string, value: any) => {
    setDraftPluginDrafts((prev) => ({
      ...prev,
      [pluginId]: {
        ...(prev[pluginId] || {}),
        [key]: value,
      },
    }));
  };

  const handlePluginDraftChanges = (pluginId: string, updates: Record<string, any>) => {
    setDraftPluginDrafts((prev) => ({
      ...prev,
      [pluginId]: {
        ...(prev[pluginId] || {}),
        ...updates,
      },
    }));
  };

  const handleToolDraftChange = (toolName: string, path: string, value: any) => {
    setDraftToolDrafts((prev) => ({
      ...prev,
      [toolName]: {
        enabled: prev[toolName]?.enabled ?? tools.find((tool) => tool.name === toolName)?.enabled ?? true,
        values: {
          ...(prev[toolName]?.values || {}),
          [path]: value,
        },
      },
    }));
  };

  const handleToolEnabledChange = (toolName: string, enabled: boolean) => {
    setDraftToolDrafts((prev) => ({
      ...prev,
      [toolName]: {
        enabled,
        values: {
          ...(prev[toolName]?.values || tools.find((tool) => tool.name === toolName)?.current_values || {}),
        },
      },
    }));
  };

  const handlePluginAction = async (pluginId: string, action: 'enable' | 'disable' | 'reload') => {
    setPluginProcessingIds((prev) => ({ ...prev, [pluginId]: action }));
    try {
      const next =
        action === 'enable'
          ? await pluginsApi.enable(pluginId)
          : action === 'disable'
            ? await pluginsApi.disable(pluginId)
            : await pluginsApi.reload(pluginId);
      const nextSnapshot = buildPluginDraftSnapshotFromPackages([next]);
      setPlugins((prev) => prev.map((item) => (item.manifest.plugin_id === next.manifest.plugin_id ? next : item)));
      setSavedPluginDrafts((prev) => mergeDraftMaps(prev, nextSnapshot, { preserveExisting: false }));
      setDraftPluginDrafts((prev) => mergeDraftMaps(prev, nextSnapshot, { preserveExisting: false }));
      toast.success(t(`settings.extensions.feedback.${action}Success`, { name: next.manifest.name }));
      await fetchTimelineStatuses();
    } catch (error: any) {
      toast.error(t('settings.extensions.errors.actionFailed', { message: error?.message || 'unknown' }));
    } finally {
      setPluginProcessingIds((prev) => {
        const next = { ...prev };
        delete next[pluginId];
        return next;
      });
    }
  };

  const handleReloadActionPlugin = async (pluginId: string) => {
    setReloadingActionPlugins((prev) => ({ ...prev, [pluginId]: true }));
    try {
      const next = await pluginsApi.reload(pluginId);
      const nextSnapshot = buildPluginDraftSnapshotFromPackages([next]);
      setPlugins((prev) => prev.map((item) => (item.manifest.plugin_id === next.manifest.plugin_id ? next : item)));
      setSavedPluginDrafts((prev) => mergeDraftMaps(prev, nextSnapshot, { preserveExisting: false }));
      setDraftPluginDrafts((prev) => mergeDraftMaps(prev, nextSnapshot, { preserveExisting: false }));
      toast.success(t('settings.actionsConfig.feedback.reloadSuccess', { name: next.manifest.name }));
      await fetchTimelineStatuses();
    } catch (error: any) {
      toast.error(t('settings.actionsConfig.errors.reloadFailed', { message: error?.message || 'unknown' }));
    } finally {
      setReloadingActionPlugins((prev) => ({ ...prev, [pluginId]: false }));
    }
  };

  const handleSaveChanges = async () => {
    setSaving(true);
    try {
      if (configDirty) {
        await configApi.update(draftConfig);
        setSavedConfig(structuredClone(draftConfig));
      }

      for (const tool of tools) {
        const savedSnapshot = savedToolDrafts[tool.name] ?? { enabled: tool.enabled, values: tool.current_values };
        const draftSnapshot = draftToolDrafts[tool.name] ?? savedSnapshot;
        const updates = diffFlatMaps(savedSnapshot.values || {}, draftSnapshot.values || {});
        const enabledChanged = savedSnapshot.enabled !== draftSnapshot.enabled;
        if (Object.keys(updates).length === 0 && !enabledChanged) {
          continue;
        }
        await toolsApi.updateToolConfig(tool.name, {
          updates,
          enabled: enabledChanged ? draftSnapshot.enabled : undefined,
        });
      }

      for (const plugin of plugins) {
        const pluginId = plugin.manifest.plugin_id;
        const savedValues = savedPluginDrafts[pluginId] || {};
        const draftValues = draftPluginDrafts[pluginId] || {};
        const updates = diffFlatMaps(savedValues, draftValues);
        if (Object.keys(updates).length === 0) {
          continue;
        }
        await pluginsApi.updateSettings(pluginId, updates);
      }

      if (themeDirty) {
        setThemeMode(draftThemeMode, { persist: true });
        setSavedThemeMode(draftThemeMode);
      }
      persistLanguageSelection(draftConfig.preferences.language);

      await Promise.all([
        fetchTimelineStatuses(),
        loadPlugins({ silent: true }),
        loadTools({ silent: true }),
      ]);

      setSavedPluginDrafts(structuredClone(draftPluginDrafts));
      setSavedToolDrafts(structuredClone(draftToolDrafts));
      toast.success(t('settings.saveSuccess'));
    } catch (error: any) {
      toast.error(t('settings.saveFailed', { message: error?.message || 'unknown' }));
    } finally {
      setSaving(false);
    }
  };

  const handleDiscardChanges = async () => {
    setDraftConfig(structuredClone(savedConfig));
    setDraftPluginDrafts(structuredClone(savedPluginDrafts));
    setDraftToolDrafts(structuredClone(savedToolDrafts));
    setDraftThemeMode(savedThemeMode);
    setThemeMode(savedThemeMode, { persist: true });
    await previewLanguageSelection(savedConfig.preferences.language);
  };

  useImperativeHandle(ref, () => ({
    hasUnsavedChanges: () => dirty,
    discardChanges: handleDiscardChanges,
  }), [dirty, savedConfig, savedPluginDrafts, savedThemeMode, savedToolDrafts]);

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
      if (response.success) {
        const totalCleared = Object.values(response.results).reduce(
          (sum: number, result: any) => sum + (result.cleared ? result.count : 0),
          0
        );
        toast.success(t('settings.memoryCleared', { count: totalCleared }));
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

  const renderSectionContent = () => {
    switch (activeSection) {
      case 'preferences':
        return (
          <div className="space-y-6">
            <div className="grid gap-4 md:grid-cols-2">
              <LabeledSelectField
                label={t('settings.fields.language')}
                value={draftConfig.preferences.language}
                options={[
                  { label: t('language.zhHans', { ns: 'onboarding' }), value: 'zh' },
                  { label: t('language.en', { ns: 'onboarding' }), value: 'en' },
                ]}
                onChange={handleLanguagePreviewChange}
              />
            </div>

            <div className="space-y-3">
              <h3 className="text-sm font-medium">{t('settings.fields.theme')}</h3>
              <div className="flex gap-3">
                {([
                  { value: 'light', icon: Sun, label: t('settings.theme.light') },
                  { value: 'dark', icon: Moon, label: t('settings.theme.dark') },
                  { value: 'system', icon: Monitor, label: t('settings.theme.system') },
                ] as const).map((option) => {
                  const Icon = option.icon;
                  const isActive = draftThemeMode === option.value;
                  return (
                    <button
                      key={option.value}
                      type="button"
                      onClick={() => handleThemePreviewChange(option.value)}
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

      case 'llmProviders':
        return (
          <div className="space-y-4">
            <LLMForm
              quickMode={false}
              view="providers"
              surface="settings"
              showSectionIntro={false}
              value={draftConfig.llm}
              showAdvancedByDefault
              onChange={(next) => patchDraftConfig((draft) => {
                draft.llm = next;
              })}
            />
          </div>
        );

      case 'llmModels':
        return (
          <div className="space-y-4">
            <LLMForm
              quickMode={false}
              view="models"
              surface="settings"
              showSectionIntro={false}
              value={draftConfig.llm}
              showAdvancedByDefault
              onChange={(next) => patchDraftConfig((draft) => {
                draft.llm = next;
              })}
            />
          </div>
        );

      case 'personality':
        return (
          <div className="space-y-6">
            <div className="overflow-hidden rounded-3xl border border-primary/20 bg-muted/30 p-5">
              <div className="mb-3 flex items-center justify-between gap-3">
                <div>
                  <h3 className="font-medium text-primary">{t('settings.fields.currentPersonality')}</h3>
                  <p className="text-sm text-muted-foreground">
                    {draftConfig.personality?.persona_entity?.basic_profile?.name || 'Default'}
                  </p>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  className="rounded-xl"
                  onClick={() => {
                    window.location.href = '/personality';
                  }}
                >
                  {t('settings.actions.configure')}
                </Button>
              </div>
              <p className="text-xs leading-6 text-muted-foreground">
                {draftConfig.personality?.persona_entity?.basic_profile?.occupation || ''}
              </p>
            </div>
          </div>
        );

      case 'usage':
        return <LLMUsageSection />;

      case 'memory':
        return (
          <div className="space-y-8">
            {/* Danger Zone */}
            <Card className="border-destructive/40 bg-destructive/5">
              <CardHeader className="pb-3">
                <CardTitle className="flex items-center gap-2 text-sm font-medium text-destructive">
                  <Trash2 className="h-4 w-4" />
                  {t('settings.fields.clearMemory')}
                </CardTitle>
                <CardDescription className="text-xs">
                  {t('settings.fields.clearMemoryDesc')}
                </CardDescription>
              </CardHeader>
              <CardContent>
                <Button
                  variant="destructive"
                  size="sm"
                  onClick={() => setShowClearConfirm(true)}
                >
                  <Trash2 className="mr-1.5 h-4 w-4" />
                  {t('settings.actions.clearMemory')}
                </Button>
              </CardContent>
            </Card>

            {/* Memory Layers */}
            <div className="space-y-4">
              <div>
                <h3 className="text-sm font-medium">{t('settings.fields.memoryLayers')}</h3>
                <p className="mt-1 text-xs text-muted-foreground">
                  {t('settings.fields.memoryLayersDesc')}
                </p>
              </div>
              <div className="grid gap-2.5 sm:grid-cols-2">
                {(['L1', 'L2', 'L3', 'L4', 'L5'] as const).map((layer) => (
                  <label
                    key={layer}
                    className={cn(
                      'group flex items-center justify-between rounded-lg border px-4 py-3',
                      'transition-colors duration-150',
                      'hover:border-border/80 hover:bg-muted/30',
                      'cursor-pointer'
                    )}
                  >
                    <div className="flex items-center gap-3">
                      <span className="text-xs font-semibold tabular-nums text-muted-foreground">
                        {layer}
                      </span>
                      <span className="text-sm font-medium">
                        {t(`settings.fields.${layer.toLowerCase()}Enabled`)}
                      </span>
                    </div>
                    <Switch
                      checked={draftConfig.memory_layers[layer].enabled}
                      onCheckedChange={(checked) =>
                        patchDraftConfig((draft) => {
                          draft.memory_layers[layer].enabled = checked;
                        })
                      }
                    />
                  </label>
                ))}
              </div>
            </div>

            {/* Model Download */}
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-medium">
                  {t('settings.fields.l3ModelDownload')}
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
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
                <Button variant="outline" size="sm" onClick={startDownload}>
                  <Download className="mr-1.5 h-4 w-4" />
                  {t('settings.fields.downloadModel')}
                </Button>

                {/* Progress */}
                <div className="space-y-2">
                  <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                    <div
                      className="h-full rounded-full bg-primary transition-all duration-300 ease-out"
                      style={{ width: `${downloadProgress}%` }}
                    />
                  </div>
                  <div className="flex items-center justify-between text-xs text-muted-foreground">
                    <span className="capitalize">{downloadStatus}</span>
                    <span className="tabular-nums">{downloadProgress}%</span>
                  </div>
                </div>

                {/* Installed Models */}
                <div className="flex flex-wrap items-center gap-2 pt-2">
                  <span className="text-xs text-muted-foreground">
                    {t('settings.fields.installedModels')}:
                  </span>
                  {installedModels.length > 0 ? (
                    installedModels.map((model) => (
                      <Badge key={model} variant="secondary" className="text-xs">
                        {model}
                      </Badge>
                    ))
                  ) : (
                    <Badge variant="outline" className="text-xs">
                      {t('settings.fields.none')}
                    </Badge>
                  )}
                </div>
              </CardContent>
            </Card>
          </div>
        );

      case 'timeline':
        return (
          <TimelineSourcesSection
            value={draftConfig.timeline}
            userMode={draftConfig.preferences.user_mode}
            statuses={timelineStatuses}
            loadingStatus={timelineStatusesLoading}
            selectedSourceName={timelineSelection}
            pluginDrafts={draftPluginDrafts}
            onSelectSource={setTimelineSelection}
            onRefreshSources={fetchTimelineStatuses}
            onChange={(updater) => patchDraftConfig((draft) => {
              updater(draft.timeline);
            })}
            onPluginFieldChange={handlePluginDraftChange}
            onPluginFieldsChange={handlePluginDraftChanges}
          />
        );

      case 'tools':
        return (
          <div className="space-y-6">
            <DynamicToolsConfig
              tools={tools}
              loading={toolsLoading}
              error={toolsError}
              drafts={draftToolDrafts}
              onUpdateConfig={handleToolDraftChange}
              onUpdateEnabled={handleToolEnabledChange}
            />
          </div>
        );

      case 'extensions':
        return (
          <ExtensionsSection
            plugins={plugins}
            loading={pluginsLoading}
            drafts={draftPluginDrafts}
            dirty={dirty}
            onFieldChange={handlePluginDraftChange}
            onRescan={async () => {
              await loadPlugins();
              toast.success(t('settings.extensions.feedback.rescanSuccess'));
            }}
            onPluginAction={handlePluginAction}
            processingIds={pluginProcessingIds}
          />
        );

      case 'actions':
        return (
          <ActionsSection
            plugins={plugins}
            drafts={draftPluginDrafts}
            dirty={dirty}
            onFieldChange={handlePluginDraftChange}
            onReloadPlugin={handleReloadActionPlugin}
            reloading={reloadingActionPlugins}
          />
        );

      case 'system':
        return (
          <div className="grid gap-4 md:grid-cols-2">
            <LabeledSelectField
              label={t('settings.fields.loopStrategy')}
              value={draftConfig.loop.strategy}
              options={[
                { label: 'STEP', value: 'step' },
                { label: 'WAVE', value: 'wave' },
                { label: 'CONTINUOUS', value: 'continuous' },
              ]}
              onChange={(value) => patchDraftConfig((draft) => {
                draft.loop.strategy = value as SystemConfig['loop']['strategy'];
              })}
            />
            <NumberField
              label={t('settings.fields.loopInterval')}
              value={draftConfig.loop.interval}
              min={0.1}
              max={60}
              step={0.1}
              onChange={(value) => patchDraftConfig((draft) => {
                draft.loop.interval = value;
              })}
            />
            <LabeledSelectField
              label={t('settings.fields.busBackend')}
              value={draftConfig.message_bus.backend}
              options={[
                { label: 'memory', value: 'memory' },
                { label: 'sqlite', value: 'sqlite' },
                { label: 'redis', value: 'redis' },
              ]}
              onChange={(value) => patchDraftConfig((draft) => {
                draft.message_bus.backend = value as SystemConfig['message_bus']['backend'];
              })}
            />
            <NumberField
              label={t('settings.fields.busQueueSize')}
              value={draftConfig.message_bus.max_size}
              min={100}
              max={50000}
              onChange={(value) => patchDraftConfig((draft) => {
                draft.message_bus.max_size = value;
              })}
            />
            <NumberField
              label={t('settings.fields.wsPort')}
              value={draftConfig.websocket.port}
              min={1024}
              max={65535}
              onChange={(value) => patchDraftConfig((draft) => {
                draft.websocket.port = value;
              })}
            />
            <LabeledSelectField
              label={t('settings.fields.logLevel')}
              value={draftConfig.log.level}
              options={[
                { label: 'DEBUG', value: 'DEBUG' },
                { label: 'INFO', value: 'INFO' },
                { label: 'WARNING', value: 'WARNING' },
                { label: 'ERROR', value: 'ERROR' },
              ]}
              onChange={(value) => patchDraftConfig((draft) => {
                draft.log.level = value as SystemConfig['log']['level'];
              })}
            />
          </div>
        );

      default:
        return null;
    }
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex flex-1 min-h-0 overflow-hidden">
        <nav className="flex w-56 shrink-0 flex-col border-r border-border/50 bg-muted/40">
          <div className="flex h-16 shrink-0 items-center border-b border-border/60 bg-background/95 px-5 backdrop-blur-sm">
            <p className="text-base font-semibold tracking-[0.01em] text-foreground">
              {t('settings.shellTitle')}
            </p>
          </div>
          <div className="flex-1 space-y-1.5 overflow-y-auto px-4 py-4">
            {NAV_ITEMS.map((item) => {
              const Icon = item.icon;
              const isActive = isNavGroupActive(item);
              const isExpanded = isNavGroup(item) ? getGroupExpanded(item.id) : false;
              const ParentChevron = isNavGroup(item) && isExpanded ? ChevronDown : ChevronRight;
              return (
                <div key={item.id} className="space-y-1.5">
                  <button
                    type="button"
                    onClick={() => handleNavItemClick(item)}
                    aria-current={isActive ? 'page' : undefined}
                    aria-expanded={isNavGroup(item) ? isExpanded : undefined}
                    aria-label={t(`settings.tabs.${item.id}`)}
                    className={cn(
                      'group flex w-full items-center justify-between rounded-lg px-3 py-2.5 text-sm font-medium',
                      'transition-all duration-200 ease-out',
                      'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1',
                      isActive
                        ? 'bg-primary text-primary-foreground shadow-sm'
                        : 'text-muted-foreground hover:bg-muted/80 hover:text-foreground'
                    )}
                  >
                    <div className="flex items-center gap-3">
                      <Icon className={cn(
                        'h-4 w-4 transition-colors',
                        isActive ? 'text-primary-foreground' : 'text-muted-foreground group-hover:text-foreground'
                      )} />
                      <span className="transition-colors">{t(`settings.tabs.${item.id}`)}</span>
                    </div>
                    <ParentChevron className={cn(
                      'h-4 w-4 transition-all duration-200',
                      isNavGroup(item)
                        ? isExpanded
                          ? 'opacity-100 translate-x-0'
                          : 'opacity-60 -translate-x-0'
                        : isActive
                          ? 'opacity-100 translate-x-0'
                          : 'opacity-0 -translate-x-1 group-hover:opacity-50 group-hover:translate-x-0'
                    )} />
                  </button>

                  {isNavGroup(item) && isExpanded ? (
                    <div className="ml-3 space-y-1 border-l border-border/50 pl-3">
                      {item.children.map((child) => {
                        const isChildActive = activeSection === child.id;
                        return (
                          <button
                            key={child.id}
                            type="button"
                            onClick={() => {
                              setGroupExpanded(item.id, true);
                              handleSectionSelect(child.id);
                            }}
                            aria-current={isChildActive ? 'page' : undefined}
                            className={cn(
                              'flex w-full items-center rounded-md px-3 py-2 text-sm transition-all duration-150 ease-out focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                              isChildActive
                                ? 'bg-background/80 text-foreground font-medium shadow-sm'
                                : 'text-muted-foreground hover:bg-background/50 hover:text-foreground'
                            )}
                          >
                            {t(`settings.tabs.${child.id}`)}
                          </button>
                        );
                      })}
                    </div>
                  ) : null}

                  {item.id === 'timeline' && isActive ? (
                    <div className="ml-3 space-y-1 border-l border-border/50 pl-3">
                      <button
                        type="button"
                        onClick={() => setTimelineSelection(null)}
                        data-testid="timeline-nav-overview"
                        aria-current={timelineSelection === null ? 'page' : undefined}
                        className={cn(
                          'flex w-full items-center rounded-md px-3 py-2 text-sm',
                          'transition-all duration-150 ease-out',
                          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                          timelineSelection === null
                            ? 'bg-background/80 text-foreground font-medium shadow-sm'
                            : 'text-muted-foreground hover:bg-background/50 hover:text-foreground'
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
                              'flex w-full items-center gap-2 rounded-md px-3 py-2 text-sm',
                              'transition-all duration-150 ease-out',
                              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                              isSelected
                                ? 'bg-background/80 text-foreground font-medium shadow-sm'
                                : 'text-muted-foreground hover:bg-background/50 hover:text-foreground'
                            )}
                          >
                            <span className="truncate">{source.display_name}</span>
                            {source.last_error ? (
                              <span className="ml-auto h-1.5 w-1.5 rounded-full bg-destructive" aria-hidden="true" />
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

        <main className="flex min-h-0 flex-1 flex-col">
          <header className="shrink-0 border-b border-border/60 bg-background/95 backdrop-blur-sm">
            <div className="flex h-16 w-full items-center gap-4 px-12">
              <h2 className="text-lg font-semibold tracking-[0.01em] text-foreground">
                {t(`settings.tabs.${activeSection}`)}
              </h2>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                onClick={() => void onRequestClose?.()}
                className="ml-auto h-8 w-8 rounded-md text-muted-foreground hover:bg-muted hover:text-foreground"
                aria-label={t('settings.actions.close')}
              >
                <X className="h-4 w-4" />
              </Button>
            </div>
          </header>

          <div className="flex-1 overflow-y-auto">
            <div className="w-full px-12 py-8">
              <ErrorBoundary
                fallback={
                  <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-4">
                    <p className="text-sm text-destructive">
                      {t('settings.sectionError', { defaultValue: 'This section encountered an error. Please try refreshing.' })}
                    </p>
                    <Button
                      variant="outline"
                      size="sm"
                      className="mt-3"
                      onClick={() => window.location.reload()}
                    >
                      {t('settings.refresh', { defaultValue: 'Refresh' })}
                    </Button>
                  </div>
                }
              >
                <div
                  key={activeSection}
                  className={cn(
                    'animate-in fade-in-0 slide-in-from-bottom-2 duration-300 ease-out',
                    isWideSection ? 'w-full' : 'max-w-3xl'
                  )}
                >
                  {renderSectionContent()}
                </div>
              </ErrorBoundary>
            </div>
          </div>
        </main>
      </div>

      <footer className="shrink-0 border-t border-border/60 bg-background/95 backdrop-blur-sm">
        <div className="flex flex-wrap items-center justify-between gap-4 px-8 py-4">
          <p className={cn(
            'text-sm transition-colors duration-200',
            dirty ? 'text-primary font-medium' : 'text-muted-foreground'
          )}>
            {dirty ? t('settings.pendingChanges') : t('settings.allChangesSaved')}
          </p>
          <div className="flex flex-wrap items-center gap-2.5">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => void handleDiscardChanges()}
              disabled={!dirty || saving}
              className="disabled:opacity-40"
            >
              <RotateCcw className="mr-1.5 h-4 w-4" />
              {t('settings.actions.discard')}
            </Button>
            <Button
              type="button"
              size="sm"
              onClick={() => void handleSaveChanges()}
              disabled={!dirty || saving}
              className={cn(
                'transition-all duration-200',
                dirty && 'animate-in pulse duration-300'
              )}
            >
              <Save className="mr-1.5 h-4 w-4" />
              {saving ? t('settings.saving') : t('settings.actions.save')}
            </Button>
          </div>
        </div>
      </footer>

      {showClearConfirm ? (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="clear-confirm-title"
          aria-describedby="clear-confirm-desc"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
          onKeyDown={(e) => {
            if (e.key === 'Escape' && !clearing) {
              setShowClearConfirm(false);
            }
          }}
        >
          <Card className="mx-4 max-w-md">
            <CardHeader>
              <CardTitle id="clear-confirm-title" className="flex items-center gap-2 text-destructive">
                <AlertTriangle className="h-5 w-5" aria-hidden="true" />
                {t('settings.clearConfirm.title')}
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div id="clear-confirm-desc" className="rounded-md border border-destructive/50 bg-destructive/10 p-4 text-sm">
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
                <Button variant="outline" onClick={() => setShowClearConfirm(false)} disabled={clearing}>
                  {t('settings.clearConfirm.cancel')}
                </Button>
                <Button variant="destructive" onClick={handleClearMemory} disabled={clearing}>
                  {clearing ? t('settings.clearConfirm.clearing') : t('settings.clearConfirm.confirm')}
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      ) : null}
    </div>
  );
});

SettingsPage.displayName = 'SettingsPage';
