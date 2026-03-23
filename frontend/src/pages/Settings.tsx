import { forwardRef, useEffect, useImperativeHandle, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  ChevronRight,
  ChevronDown,
  Sun,
  Moon,
  Monitor,
  X,
  RotateCcw,
  Save,
} from 'lucide-react';

import { useSettings } from '@/hooks/useSettings';
import { NAV_ITEMS, isNavGroup } from '@/constants/settings';
import type { NavItem, SettingsPageHandle, SettingsPageProps } from '@/types/settings';
import {
  LabeledSelectField,
  NumberField,
  MemoryEventsSettingsSection,
  MemoryGeneralSettingsSection,
  MemoryKnowledgeSettingsSection,
  MemoryReflectionSettingsSection,
  MemorySkillsSettingsSection,
  MemoryWorkbenchSettingsSection,
} from '@/components/settings';
import { DynamicToolsConfig } from '@/components/config-forms/DynamicToolConfig';
import LLMForm from '@/components/config-forms/LLMForm';
import { LLMUsageSection } from '@/components/settings/LLMUsageSection';
import ActionsSection from '@/components/settings/ActionsSection';
import ExtensionsSection from '@/components/settings/ExtensionsSection';
import TimelineSourcesSection from '@/components/settings/TimelineSourcesSection';
import PersonalityModern from '@/pages/PersonalityModern';
import { SystemConfig } from '@/api/modules/config';
import { skillsApi, type SkillItem } from '@/api/modules/skills';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { cn } from '@/lib/utils';
import { ErrorBoundary } from '@/components/ui/ErrorBoundary';
import { toast } from 'sonner';

function SettingsSectionShell({
  description,
  children,
}: {
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-8">
      {description ? <p className="max-w-3xl text-sm leading-7 text-muted-foreground">{description}</p> : null}
      <div className="space-y-8">{children}</div>
    </div>
  );
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
    <section className="space-y-4 border-t border-[hsl(var(--settings-subnav-border)/0.72)] pt-6">
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

    switch (activeSection) {
      case 'preferences':
        return (
          <SettingsSectionShell description={t('settings.preferencesDesc')}>
            <SettingsGroup title={t('settings.fields.language')}>
              <div className="border-b border-[hsl(var(--settings-subnav-border)/0.6)] py-3">
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
            </SettingsGroup>

            <SettingsGroup
              title={t('settings.fields.theme')}
              description={t('settings.themeDesc')}
            >
              <div className="border-b border-[hsl(var(--settings-subnav-border)/0.6)]">
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
                        'flex w-full items-center justify-between border-b border-[hsl(var(--settings-subnav-border)/0.6)] py-3 text-left transition-colors last:border-b-0',
                        isActive
                          ? 'text-foreground'
                          : 'text-[hsl(var(--settings-nav-foreground))] hover:text-foreground'
                      )}
                    >
                      <div className="flex items-center gap-3">
                        <Icon className="h-4 w-4" />
                        <span className="text-sm font-medium">{option.label}</span>
                      </div>
                      <span
                        className={cn(
                          'text-[11px] tracking-[0.08em] transition-opacity',
                          isActive ? 'opacity-100 text-[hsl(var(--settings-nav-active-foreground))]' : 'opacity-0'
                        )}
                      >
                        {t('settings.activeState')}
                      </span>
                    </button>
                  );
                })}
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
        return <PersonalityModern embedded />;

      case 'usage':
        return <LLMUsageSection />;

      case 'memoryGeneral':
        return (
          <MemoryGeneralSettingsSection
            draftConfig={draftConfig}
            patchDraftConfig={patchDraftConfig}
            hasEmbeddingModel={hasEmbeddingModel}
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
          <SettingsSectionShell description={t('settings.systemDesc')}>
            <SettingsGroup title={t('settings.fields.loopStrategy')}>
              <div className="grid gap-6 border-b border-[hsl(var(--settings-subnav-border)/0.6)] py-3 md:grid-cols-2">
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
              </div>
            </SettingsGroup>

            <SettingsGroup title={t('settings.fields.busBackend')}>
              <div className="grid gap-6 border-b border-[hsl(var(--settings-subnav-border)/0.6)] py-3 md:grid-cols-2">
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
              </div>
            </SettingsGroup>

            <SettingsGroup title={t('settings.fields.wsPort')}>
              <div className="grid gap-6 border-b border-[hsl(var(--settings-subnav-border)/0.6)] py-3 md:grid-cols-2">
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
            </SettingsGroup>
          </SettingsSectionShell>
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
                    onClick={() => {
                      if (isNavGroup(item)) {
                        handleNavItemClick(item.id, true, item.children[0]?.id);
                      } else {
                        handleNavItemClick(item.id, false);
                      }
                    }}
                    aria-current={isActive ? 'page' : undefined}
                    aria-expanded={isNavGroup(item) ? isExpanded : undefined}
                    aria-label={t(`settings.tabs.${item.id}`)}
                    className={cn(
                      'group flex w-full items-center justify-between rounded-lg px-3 py-2.5 text-sm font-medium',
                      'transition-all duration-200 ease-out',
                      'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1',
                      isActive
                        ? 'bg-[hsl(var(--settings-nav-active))] text-[hsl(var(--settings-nav-active-foreground))] shadow-sm'
                        : 'text-[hsl(var(--settings-nav-foreground))] hover:bg-[hsl(var(--settings-nav-hover))] hover:text-foreground'
                    )}
                  >
                    <div className="flex items-center gap-3">
                      <Icon className={cn(
                        'h-4 w-4 transition-colors',
                        isActive
                          ? 'text-[hsl(var(--settings-nav-active-foreground))]'
                          : 'text-[hsl(var(--settings-nav-foreground))] group-hover:text-foreground'
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
                    <div className="ml-3 space-y-1 border-l border-[hsl(var(--settings-subnav-border)/0.78)] pl-3">
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
                              'flex w-full items-center rounded-md px-3 py-2 text-sm transition-all duration-150 ease-out focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                              isChildActive
                                ? 'bg-[hsl(var(--settings-shell-elevated)/0.84)] text-foreground font-medium shadow-sm'
                                : 'text-[hsl(var(--settings-nav-foreground))] hover:bg-[hsl(var(--settings-shell-elevated)/0.52)] hover:text-foreground'
                            )}
                          >
                            {t(`settings.tabs.${child.id}`)}
                          </button>
                        );
                      })}
                    </div>
                  ) : null}

                  {item.id === 'timeline' && isActive ? (
                    <div className="ml-3 space-y-1 border-l border-[hsl(var(--settings-subnav-border)/0.78)] pl-3">
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
                            ? 'bg-[hsl(var(--settings-shell-elevated)/0.84)] text-foreground font-medium shadow-sm'
                            : 'text-[hsl(var(--settings-nav-foreground))] hover:bg-[hsl(var(--settings-shell-elevated)/0.52)] hover:text-foreground'
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
                                ? 'bg-[hsl(var(--settings-shell-elevated)/0.84)] text-foreground font-medium shadow-sm'
                                : 'text-[hsl(var(--settings-nav-foreground))] hover:bg-[hsl(var(--settings-shell-elevated)/0.52)] hover:text-foreground'
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
                      : isWideSection
                        ? 'h-full overflow-y-auto pr-1'
                        : 'h-full max-w-3xl overflow-y-auto pr-1'
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
