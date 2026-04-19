import { forwardRef, useEffect, useImperativeHandle, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  ChevronRight,
  ChevronDown,
  FolderOpen,
  X,
  RotateCcw,
  Save,
} from 'lucide-react';

import { useSettings } from '@/hooks/useSettings';
import { NAV_ITEMS, isNavGroup } from '@/constants/settings';
import type { NavItem, SettingsPageHandle, SettingsPageProps } from '@/types/settings';
import {
  LabeledSelectField,
  MemoryEventsSettingsSection,
  MemoryGeneralSettingsSection,
  MemoryKnowledgeSettingsSection,
  MemoryReflectionSettingsSection,
  MemorySkillsSettingsSection,
  MemoryWorkbenchSettingsSection,
  LLMStatisticsSection,
  RuntimeStatisticsSection,
} from '@/components/settings';
import { DynamicToolsConfig } from '@/components/config-forms/DynamicToolConfig';
import LLMForm from '@/components/config-forms/LLMForm';
import ActionsSection from '@/components/settings/ActionsSection';
import { DesktopUpdateSection } from '@/components/settings/DesktopUpdateSection';
import ExtensionsSection from '@/components/settings/ExtensionsSection';
import { PluginMarketplace } from '@/components/settings/PluginMarketplace';
import TimelineSourcesSection from '@/components/settings/TimelineSourcesSection';
import PersonalityModern from '@/pages/PersonalityModern';
import { skillsApi, type SkillItem } from '@/api/modules/skills';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { cn } from '@/lib/utils';
import { ErrorBoundary } from '@/components/ui/ErrorBoundary';
import { toast } from 'sonner';
import { pickDirectory } from '@/runtime/desktop';
import { getTimelineSourceDisplayName } from '@/utils/timeline-source-copy';

function SettingsSectionShell({
  children,
}: {
  children: React.ReactNode;
}) {
  return <div className="space-y-8">{children}</div>;
}

function SettingsGroup({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-4 pt-4">
      <div className="space-y-1.5">
        <h3 className="text-sm font-semibold tracking-[0.01em] text-foreground">{title}</h3>
        {description ? <p className="max-w-3xl text-xs leading-6 text-muted-foreground">{description}</p> : null}
      </div>
      <div className="space-y-3">{children}</div>
    </section>
  );
}

export const SettingsPage = forwardRef<SettingsPageHandle, SettingsPageProps>(({ onRequestClose }, ref) => {
  const { t } = useTranslation('app');
  const [skills, setSkills] = useState<SkillItem[]>([]);
  const [skillsLoading, setSkillsLoading] = useState(false);
  const [skillsError, setSkillsError] = useState<string | null>(null);
  const [pickingWorkspace, setPickingWorkspace] = useState(false);

  const {
    loading,
    saving,
    activeSection,
    getGroupExpanded,
    setGroupExpanded,
    handleNavItemClick,
    isWideSection,
    usesInnerPaneScroll,
    draftConfig,
    patchDraftConfig,
    syncNormalizedLlmConfig,
    draftThemeMode,
    handleThemePreviewChange,
    handleLanguagePreviewChange,
    updateMemoryToggle,
    plugins,
    pluginsLoading,
    pluginProcessingIds,
    reloadingActionPlugins,
    draftPluginDrafts,
    handlePluginDraftChange,
    handlePluginDraftChanges,
    handlePluginAction,
    handleReloadActionPlugin,
    loadPlugins,
    tools,
    toolsLoading,
    toolsError,
    draftToolDrafts,
    handleToolDraftChange,
    handleToolEnabledChange,
    timelineStatuses,
    timelineStatusesLoading,
    timelineSelection,
    setTimelineSelection,
    fetchTimelineStatuses,
    dirty,
    handleSaveChanges,
    handleDiscardChanges,
    getHandle,
  } = useSettings();

  const sortedTimelineStatuses = useMemo(() => {
    const collator = new Intl.Collator(undefined, {
      numeric: true,
      sensitivity: 'base',
    });

    return [...timelineStatuses].sort((left, right) =>
      collator.compare(getTimelineSourceDisplayName(t, left), getTimelineSourceDisplayName(t, right))
    );
  }, [t, timelineStatuses]);

  const isNavGroupActive = (item: NavItem) => {
    if (!isNavGroup(item)) {
      return activeSection === item.id;
    }
    return item.children!.some((child) => child.id === activeSection);
  };

  useImperativeHandle(ref, getHandle, [getHandle]);

  useEffect(() => {
    if (activeSection !== 'tools') {
      return;
    }

    let cancelled = false;
    const loadSkills = async () => {
      setSkillsLoading(true);
      setSkillsError(null);
      try {
        const data = await skillsApi.list();
        if (!cancelled) {
          setSkills(Array.isArray(data) ? data : []);
        }
      } catch (error: unknown) {
        if (!cancelled) {
          const message = error instanceof Error ? error.message : t('settings.errorUnknown');
          setSkillsError(message);
          setSkills([]);
        }
      } finally {
        if (!cancelled) {
          setSkillsLoading(false);
        }
      }
    };

    void loadSkills();
    return () => {
      cancelled = true;
    };
  }, [activeSection, t]);

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
    const embeddingSelection = draftConfig.llm?.selections?.embedding;
    const hasEmbeddingModel = !!(embeddingSelection?.provider_id && embeddingSelection?.model);
    const defaultChatWorkspacePath = draftConfig.preferences.default_chat_workspace_path;

    const handlePickWorkspace = async () => {
      setPickingWorkspace(true);
      try {
        const selectedPath = await pickDirectory(defaultChatWorkspacePath);
        if (!selectedPath) {
          return;
        }
        patchDraftConfig((draft) => {
          draft.preferences.default_chat_workspace_path = selectedPath;
        });
      } catch (error: unknown) {
        const message = error instanceof Error ? error.message : 'unknown';
        toast.error(t('settings.defaultChatWorkspacePickFailed', { message }));
      } finally {
        setPickingWorkspace(false);
      }
    };

    switch (activeSection) {
      case 'preferences':
        return (
          <SettingsSectionShell>
            <SettingsGroup title={t('settings.fields.language')}>
              <LabeledSelectField
                label=""
                ariaLabel={t('settings.fields.language')}
                value={draftConfig.preferences.language}
                options={[
                  { label: t('language.zhHans', { ns: 'onboarding' }), value: 'zh' },
                  { label: t('language.en', { ns: 'onboarding' }), value: 'en' },
                ]}
                onChange={handleLanguagePreviewChange}
              />
            </SettingsGroup>

            <SettingsGroup
              title={t('settings.fields.theme')}
              description={t('settings.themeDesc')}
            >
              <LabeledSelectField
                label=""
                ariaLabel={t('settings.fields.theme')}
                value={draftThemeMode}
                options={[
                  { label: t('settings.theme.light'), value: 'light' },
                  { label: t('settings.theme.dark'), value: 'dark' },
                  { label: t('settings.theme.system'), value: 'system' },
                ]}
                onChange={(value) => handleThemePreviewChange(value as typeof draftThemeMode)}
              />
            </SettingsGroup>

            <SettingsGroup title={t('settings.fields.windowSettings')}>
              <div className="flex items-center justify-between gap-4">
                <span className="text-sm">{t('settings.closeToTrayLabel')}</span>
                <Switch
                  aria-label={t('settings.closeToTrayLabel')}
                  checked={draftConfig.preferences.close_to_tray_enabled}
                  onCheckedChange={(checked) => patchDraftConfig((draft) => {
                    draft.preferences.close_to_tray_enabled = checked;
                  })}
                />
              </div>
            </SettingsGroup>

            <SettingsGroup title={t('settings.startupSettings')}>
              <div className="space-y-3">
                <div className="flex items-center justify-between gap-4">
                  <span className="text-sm">{t('settings.autoStartLabel')}</span>
                  <Switch
                    aria-label={t('settings.autoStartLabel')}
                    checked={draftConfig.preferences.auto_start_enabled}
                    onCheckedChange={(checked) => patchDraftConfig((draft) => {
                      draft.preferences.auto_start_enabled = checked;
                    })}
                  />
                </div>
                <div className="flex items-center justify-between gap-4">
                  <span className="text-sm">{t('settings.startMinimizedLabel')}</span>
                  <Switch
                    aria-label={t('settings.startMinimizedLabel')}
                    checked={draftConfig.preferences.start_minimized}
                    onCheckedChange={(checked) => patchDraftConfig((draft) => {
                      draft.preferences.start_minimized = checked;
                    })}
                  />
                </div>
              </div>
            </SettingsGroup>

            <SettingsGroup title={t('settings.fields.networkProxy')}>
              <div className="space-y-4">
                <LabeledSelectField
                  label=""
                  ariaLabel={t('settings.fields.networkProxy')}
                  value={draftConfig.network.enabled ? draftConfig.network.proxy_type : 'off'}
                  options={[
                    { label: t('settings.proxyOff'), value: 'off' },
                    { label: 'HTTP', value: 'http' },
                    { label: 'SOCKS5', value: 'socks5' },
                  ]}
                  onChange={(value) => patchDraftConfig((draft) => {
                    if (value === 'off') {
                      draft.network.enabled = false;
                    } else {
                      draft.network.enabled = true;
                      draft.network.proxy_type = value as 'http' | 'socks5';
                    }
                  })}
                />
                {draftConfig.network.enabled && (
                  <div className="grid grid-cols-[1fr_auto] gap-3">
                    <label className="space-y-1.5">
                      <span className="text-xs text-muted-foreground">{t('settings.fields.proxyHost')}</span>
                      <Input
                        aria-label={t('settings.fields.proxyHost')}
                        value={draftConfig.network.host}
                        placeholder="127.0.0.1"
                        onChange={(e) => patchDraftConfig((draft) => {
                          draft.network.host = e.target.value;
                        })}
                      />
                    </label>
                    <label className="space-y-1.5 w-28">
                      <span className="text-xs text-muted-foreground">{t('settings.fields.proxyPort')}</span>
                      <Input
                        type="number"
                        aria-label={t('settings.fields.proxyPort')}
                        value={draftConfig.network.port}
                        min={1}
                        max={65535}
                        placeholder="7890"
                        onChange={(e) => patchDraftConfig((draft) => {
                          const port = parseInt(e.target.value, 10);
                          if (!isNaN(port) && port >= 1 && port <= 65535) {
                            draft.network.port = port;
                          }
                        })}
                      />
                    </label>
                  </div>
                )}
              </div>
            </SettingsGroup>

            <DesktopUpdateSection />
          </SettingsSectionShell>
        );

      case 'conversation':
        return (
          <SettingsSectionShell>
            <SettingsGroup
              title={t('settings.fields.defaultChatWorkspace')}
              description={t('settings.defaultChatWorkspaceDesc')}
            >
              <div className="grid gap-3 border-b border-[hsl(var(--settings-subnav-border)/0.6)] py-3">
                <label className="space-y-2" htmlFor="default-chat-workspace">
                  <Input
                    id="default-chat-workspace"
                    aria-label={t('settings.fields.defaultChatWorkspace')}
                    readOnly
                    value={defaultChatWorkspacePath ?? ''}
                    placeholder={t('settings.defaultChatWorkspacePlaceholder')}
                  />
                </label>
                <div className="flex flex-wrap gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => {
                      void handlePickWorkspace();
                    }}
                    disabled={pickingWorkspace}
                  >
                    <FolderOpen className="mr-2 h-4 w-4" />
                    {t('settings.actions.chooseDirectory')}
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    onClick={() => patchDraftConfig((draft) => {
                      draft.preferences.default_chat_workspace_path = null;
                    })}
                    disabled={!defaultChatWorkspacePath}
                  >
                    <X className="mr-2 h-4 w-4" />
                    {t('settings.actions.clearDirectory')}
                  </Button>
                </div>
              </div>
            </SettingsGroup>

            <SettingsGroup
              title={t('settings.fields.streamingChat')}
              description={t('settings.streamingChatDesc')}
            >
              <div className="flex items-center justify-between border-b border-[hsl(var(--settings-subnav-border)/0.6)] py-3">
                <span className="text-sm">{t('settings.streamingChatLabel')}</span>
                <Switch
                  aria-label={t('settings.fields.streamingChat')}
                  checked={draftConfig.preferences.streaming_chat_enabled}
                  onCheckedChange={(checked) => patchDraftConfig((draft) => {
                    draft.preferences.streaming_chat_enabled = checked;
                  })}
                />
              </div>
            </SettingsGroup>

            <SettingsGroup
              title={t('settings.fields.allowInterjection')}
              description={t('settings.allowInterjectionDesc')}
            >
              <div className="flex items-center justify-between border-b border-[hsl(var(--settings-subnav-border)/0.6)] py-3">
                <span className="text-sm">{t('settings.allowInterjectionLabel')}</span>
                <Switch
                  aria-label={t('settings.fields.allowInterjection')}
                  checked={draftConfig.preferences.allow_interjection}
                  onCheckedChange={(checked) => patchDraftConfig((draft) => {
                    draft.preferences.allow_interjection = checked;
                  })}
                />
              </div>
            </SettingsGroup>
          </SettingsSectionShell>
        );

      case 'llmProviders':
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

      case 'llmModels':
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
                draft.memory.reranker.cross_encoder ??= { enabled: false, managed_model_id: null };
                updater(draft.memory.reranker.cross_encoder);
              })}
            />
          </div>
        );

      case 'personality':
        return <PersonalityModern embedded />;

      case 'statisticsLlm':
        return <LLMStatisticsSection />;

      case 'statisticsRuntime':
        return <RuntimeStatisticsSection />;

      case 'memoryGeneral':
        return (
          <MemoryGeneralSettingsSection
            draftConfig={draftConfig}
            patchDraftConfig={patchDraftConfig}
          />
        );

      case 'memoryWorkbench':
        return (
          <MemoryWorkbenchSettingsSection
            draftConfig={draftConfig}
            patchDraftConfig={patchDraftConfig}
            updateMemoryToggle={updateMemoryToggle}
          />
        );

      case 'memoryEvents':
        return (
          <MemoryEventsSettingsSection
            draftConfig={draftConfig}
            patchDraftConfig={patchDraftConfig}
            updateMemoryToggle={updateMemoryToggle}
            hasEmbeddingModel={hasEmbeddingModel}
          />
        );

      case 'memoryKnowledge':
        return (
          <MemoryKnowledgeSettingsSection
            draftConfig={draftConfig}
            patchDraftConfig={patchDraftConfig}
            updateMemoryToggle={updateMemoryToggle}
            hasEmbeddingModel={hasEmbeddingModel}
          />
        );

      case 'memoryReflection':
        return (
          <MemoryReflectionSettingsSection
            draftConfig={draftConfig}
            patchDraftConfig={patchDraftConfig}
            updateMemoryToggle={updateMemoryToggle}
            hasEmbeddingModel={hasEmbeddingModel}
          />
        );

      case 'memorySkills':
        return (
          <MemorySkillsSettingsSection
            draftConfig={draftConfig}
            patchDraftConfig={patchDraftConfig}
            updateMemoryToggle={updateMemoryToggle}
          />
        );

      case 'timeline':
        return (
          <TimelineSourcesSection
            userMode={draftConfig.preferences.user_mode}
            statuses={sortedTimelineStatuses}
            loadingStatus={timelineStatusesLoading}
            selectedSourceName={timelineSelection}
            pluginDrafts={draftPluginDrafts}
            onSelectSource={setTimelineSelection}
            onRefreshSources={fetchTimelineStatuses}
            onPluginFieldChange={handlePluginDraftChange}
            onPluginFieldsChange={handlePluginDraftChanges}
          />
        );

      case 'tools':
        const selectedSkills = draftConfig.tools.skills || [];
        const skillsEnabled = selectedSkills.length > 0;
        return (
          <div className="space-y-8">
            <DynamicToolsConfig
              tools={tools}
              loading={toolsLoading}
              error={toolsError}
              drafts={draftToolDrafts}
              onUpdateConfig={handleToolDraftChange}
              onUpdateEnabled={handleToolEnabledChange}
            />

            <SettingsGroup
              title={t('tools.skills.label', { ns: 'onboarding' })}
              description={
                skills.length > 0
                  ? t('tools.skills.desc', { ns: 'onboarding', count: skills.length })
                  : t('tools.skills.empty', { ns: 'onboarding' })
              }
            >
              <label className="grid gap-3 border-b border-[hsl(var(--settings-subnav-border)/0.6)] py-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-start">
                <div className="space-y-1">
                  <div className="text-sm font-medium text-foreground">{t('tools.skills.enable', { ns: 'onboarding' })}</div>
                  <div className="text-xs leading-6 text-muted-foreground">
                    {t('tools.skills.emptyHint', { ns: 'onboarding' })}
                  </div>
                </div>
                <div className="flex justify-start sm:justify-end">
                  <Switch
                    checked={skillsEnabled}
                    disabled={skills.length === 0}
                    onCheckedChange={(checked) => patchDraftConfig((draft) => {
                      draft.tools.skills = checked ? skills.map((skill) => skill.name) : [];
                    })}
                  />
                </div>
              </label>

              <div className="max-h-64 overflow-auto">
                {skillsLoading ? (
                  <div className="py-3 text-xs text-muted-foreground">{t('settings.loadingTools')}</div>
                ) : null}

                {!skillsLoading && skillsError ? (
                  <div className="py-3 text-xs text-destructive">{skillsError}</div>
                ) : null}

                {!skillsLoading && !skillsError && skills.length > 0
                  ? skills.map((skill) => {
                      const checked = selectedSkills.includes(skill.name);
                      return (
                        <label
                          key={skill.name}
                          className="flex items-center justify-between gap-3 border-b border-[hsl(var(--settings-subnav-border)/0.6)] py-3 last:border-b-0"
                        >
                          <div className="min-w-0">
                            <div className="truncate text-sm font-medium">{skill.name}</div>
                            <div className="truncate text-xs text-muted-foreground">{skill.description}</div>
                          </div>
                          <Switch
                            checked={checked}
                            onCheckedChange={(nextChecked) => patchDraftConfig((draft) => {
                              const current = new Set(draft.tools.skills || []);
                              if (nextChecked) {
                                current.add(skill.name);
                              } else {
                                current.delete(skill.name);
                              }
                              draft.tools.skills = Array.from(current);
                            })}
                          />
                        </label>
                      );
                    })
                  : null}

                {!skillsLoading && !skillsError && skills.length === 0 ? (
                  <div className="py-3 text-xs text-muted-foreground">{t('tools.skills.emptyHint', { ns: 'onboarding' })}</div>
                ) : null}
              </div>
            </SettingsGroup>
          </div>
        );

      case 'extensionsInstalled':
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

      case 'extensionsMarketplace':
        return (
          <PluginMarketplace
            installedPlugins={plugins}
            onInstallComplete={loadPlugins}
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

      default:
        return null;
    }
  };

  return (
    <div
      data-testid="settings-theme-root"
      className="settings-theme-surface flex h-full min-h-0 flex-col"
    >
      <div className="flex flex-1 min-h-0 overflow-hidden">
        <nav className="flex w-56 shrink-0 flex-col border-r border-[hsl(var(--settings-subnav-border)/0.72)] bg-[hsl(var(--settings-shell)/0.78)]">
          <div className="flex h-16 shrink-0 items-center border-b border-[hsl(var(--settings-subnav-border)/0.68)] bg-[hsl(var(--settings-shell-elevated)/0.94)] px-5 backdrop-blur-sm">
            <p className="text-base font-semibold tracking-[0.01em] text-foreground">
              {t('settings.shellTitle')}
            </p>
          </div>
          <div className="flex-1 space-y-1 overflow-y-auto px-4 py-4">
            {NAV_ITEMS.map((item) => {
              const Icon = item.icon;
              const isActive = isNavGroupActive(item);
              const isExpandable = isNavGroup(item) || item.id === 'timeline';
              const isExpanded = isExpandable ? getGroupExpanded(item.id) : false;
              const ParentChevron = isExpandable && isExpanded ? ChevronDown : ChevronRight;
              return (
                <div key={item.id} className="space-y-1">
                  <button
                    type="button"
                    onClick={() => {
                      if (isExpandable) {
                        handleNavItemClick(item.id, true, isNavGroup(item) ? item.children[0]?.id : item.id);
                      } else {
                        handleNavItemClick(item.id, false);
                      }
                    }}
                    aria-current={isActive ? 'page' : undefined}
                    aria-expanded={isExpandable ? isExpanded : undefined}
                    aria-label={t(`settings.tabs.${item.id}`)}
                    className={cn(
                      'group flex w-full items-center justify-between rounded-md px-3 py-2.5 text-sm',
                      'transition-colors duration-150 ease-out',
                      'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1',
                      isActive
                        ? 'bg-[hsl(var(--settings-nav-active)/0.42)] text-foreground'
                        : 'text-[hsl(var(--settings-nav-foreground))] hover:bg-[hsl(var(--settings-nav-hover))] hover:text-foreground'
                    )}
                  >
                    <div className="flex items-center gap-3">
                      <Icon className={cn(
                        'h-4 w-4 transition-colors',
                        isActive
                          ? 'text-foreground'
                          : 'text-[hsl(var(--settings-nav-foreground))] group-hover:text-foreground'
                      )} />
                      <span className={cn('transition-colors', isActive ? 'font-medium' : 'font-normal')}>
                        {t(`settings.tabs.${item.id}`)}
                      </span>
                    </div>
                    <ParentChevron className={cn(
                      'h-4 w-4 text-[hsl(var(--settings-nav-foreground))] transition-all duration-150',
                      isExpandable
                        ? isExpanded
                          ? 'opacity-100 translate-x-0'
                          : 'opacity-60 -translate-x-0'
                        : isActive
                          ? 'opacity-100 translate-x-0'
                          : 'opacity-0 -translate-x-1 group-hover:opacity-50 group-hover:translate-x-0'
                    )} />
                  </button>

                  {isNavGroup(item) && isExpanded ? (
                    <div className="ml-3 space-y-0.5 border-l border-[hsl(var(--settings-subnav-border)/0.78)] pl-4">
                      {item.children.map((child) => {
                        const isChildActive = activeSection === child.id;
                        return (
                          <button
                            key={child.id}
                            type="button"
                            onClick={() => {
                              setGroupExpanded(item.id, true);
                              handleNavItemClick(child.id, false);
                            }}
                            aria-current={isChildActive ? 'page' : undefined}
                            className={cn(
                              'flex w-full items-center rounded-sm px-2.5 py-1.5 text-[13px] transition-colors duration-150 ease-out focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                              isChildActive
                                ? 'bg-[hsl(var(--settings-shell-elevated)/0.62)] text-foreground font-medium'
                                : 'text-[hsl(var(--settings-nav-foreground))] hover:bg-[hsl(var(--settings-shell-elevated)/0.52)] hover:text-foreground'
                            )}
                          >
                            {t(`settings.tabs.${child.id}`)}
                          </button>
                        );
                      })}
                    </div>
                  ) : null}

                  {item.id === 'timeline' && isActive && isExpanded ? (
                    <div className="ml-3 space-y-0.5 border-l border-[hsl(var(--settings-subnav-border)/0.78)] pl-4">
                      <button
                        type="button"
                        onClick={() => setTimelineSelection(null)}
                        data-testid="timeline-nav-overview"
                        aria-current={timelineSelection === null ? 'page' : undefined}
                        className={cn(
                          'flex w-full items-center rounded-sm px-2.5 py-1.5 text-[13px]',
                          'transition-colors duration-150 ease-out',
                          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                          timelineSelection === null
                            ? 'bg-[hsl(var(--settings-shell-elevated)/0.62)] text-foreground font-medium'
                            : 'text-[hsl(var(--settings-nav-foreground))] hover:bg-[hsl(var(--settings-shell-elevated)/0.52)] hover:text-foreground'
                        )}
                      >
                        {t('settings.timeline.nav.overview')}
                      </button>

                      {sortedTimelineStatuses.map((source) => {
                        const isSelected = timelineSelection === source.source_name;
                        const displayName = getTimelineSourceDisplayName(t, source);
                        return (
                          <button
                            key={source.source_name}
                            type="button"
                            onClick={() => setTimelineSelection(source.source_name)}
                            data-testid={`timeline-nav-source-${source.source_name}`}
                            aria-current={isSelected ? 'page' : undefined}
                            className={cn(
                              'flex w-full items-center gap-2 rounded-sm px-2.5 py-1.5 text-[13px]',
                              'transition-colors duration-150 ease-out',
                              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                              isSelected
                                ? 'bg-[hsl(var(--settings-shell-elevated)/0.62)] text-foreground font-medium'
                                : 'text-[hsl(var(--settings-nav-foreground))] hover:bg-[hsl(var(--settings-shell-elevated)/0.52)] hover:text-foreground'
                            )}
                          >
                            <span className="truncate">{displayName}</span>
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
          <header className="shrink-0 border-b border-[hsl(var(--settings-subnav-border)/0.68)] bg-[hsl(var(--settings-shell-elevated)/0.94)] backdrop-blur-sm">
            <div className="flex h-16 w-full items-center gap-4 px-8">
              <h2 className="text-lg font-semibold tracking-[0.01em] text-foreground">
                {t(`settings.tabs.${activeSection}`)}
              </h2>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                onClick={() => void onRequestClose?.()}
                className="ml-auto h-8 w-8 rounded-md text-[hsl(var(--settings-nav-foreground))] hover:bg-[hsl(var(--settings-nav-hover))] hover:text-foreground"
                aria-label={t('settings.actions.close')}
              >
                <X className="h-4 w-4" />
              </Button>
            </div>
          </header>

          <div className="flex-1 min-h-0 overflow-hidden">
            <div className="h-full w-full px-8 py-8">
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
                  data-testid="settings-section-content"
                  className={cn(
                    'animate-in fade-in-0 slide-in-from-bottom-2 duration-300 ease-out',
                    usesInnerPaneScroll
                      ? 'flex h-full min-h-0 w-full flex-col overflow-hidden'
                      : isWideSection || activeSection === 'preferences'
                        ? 'h-full overflow-y-auto pl-1 pr-2'
                        : 'h-full max-w-3xl overflow-y-auto pl-1 pr-2'
                  )}
                >
                  {renderSectionContent()}
                </div>
              </ErrorBoundary>
            </div>
          </div>
        </main>
      </div>

      {activeSection !== 'personality' ? (
        <footer className="shrink-0 border-t border-[hsl(var(--settings-subnav-border)/0.68)] bg-[hsl(var(--settings-shell-elevated)/0.94)] backdrop-blur-sm">
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
      ) : null}
    </div>
  );
});

SettingsPage.displayName = 'SettingsPage';
