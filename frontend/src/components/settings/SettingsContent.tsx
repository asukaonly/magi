import { forwardRef, useImperativeHandle, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import {
  X,
  RotateCcw,
  Save,
} from 'lucide-react';

import { useSettings } from '@/hooks/useSettings';
import { NAV_ITEMS, isNavGroup } from '@/constants/settings';
import type { SettingsPageHandle, SettingsPageProps } from '@/types/settings';
import {
  MemoryEventsSettingsSection,
  MemoryGeneralSettingsSection,
  MemoryKnowledgeSettingsSection,
  MemoryReflectionSettingsSection,
  MemorySkillsSettingsSection,
  MemoryWorkbenchSettingsSection,
  LLMStatisticsSection,
  RuntimeStatisticsSection,
} from '@/components/settings';
import LLMForm from '@/components/config-forms/LLMForm';
import ChannelsSection from '@/components/settings/ChannelsSection';
import { SettingsConversationSection } from '@/components/settings/SettingsConversationSection';
import PluginsSection from '@/components/settings/PluginsSection';
import { PluginMarketplace } from '@/components/settings/PluginMarketplace';
import { SettingsNavigationSidebar } from '@/components/settings/SettingsNavigationSidebar';
import { SettingsPreferencesSection } from '@/components/settings/SettingsPreferencesSection';
import { SettingsGroup, SettingsSectionShell } from '@/components/settings/SettingsSectionPrimitives';
import { SettingsToolsSection } from '@/components/settings/SettingsToolsSection';
import TimelineSourcesSection from '@/components/settings/TimelineSourcesSection';
import { ControlSettingsPanel } from '@/components/control';
import PersonalityModern from '@/pages/PersonalityModern';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { cn } from '@/lib/utils';
import { ErrorBoundary } from '@/components/ui/ErrorBoundary';
import { toast } from 'sonner';
import { getTimelineSourceDisplayName } from '@/utils/timeline-source-copy';

const ADVANCED_MEMORY_SECTION_IDS = new Set([
  'memoryWorkbench',
  'memoryEvents',
  'memoryKnowledge',
  'memoryReflection',
  'memorySkills',
]);

export const SettingsPage = forwardRef<SettingsPageHandle, SettingsPageProps>(({ onRequestClose }, ref) => {
  const { t } = useTranslation('app');

  const {
    loading,
    saving,
    activeSection,
    getGroupExpanded,
    setGroupExpanded,
    handleNavItemClick,
    usesInnerPaneScroll,
    draftConfig,
    patchDraftConfig,
    syncNormalizedLlmConfig,
    draftControlSettings,
    patchDraftControlSettings,
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
    loadPluginsAndSensors,
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
    channelsSelection,
    setChannelsSelection,
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

  const channelContributions = useMemo(() =>
    plugins.flatMap((plugin) =>
      plugin.contributions
        .filter((c) => c.contribution_type === 'channel')
        .map((contribution) => ({ plugin, contribution }))
    ),
    [plugins]
  );

  const quickMode = draftConfig.preferences.user_mode === 'quick';
  const visibleNavItems = useMemo(
    () =>
      NAV_ITEMS.map((item) => {
        if (item.id !== 'memory' || !isNavGroup(item) || !quickMode) {
          return item;
        }
        return {
          ...item,
          children: item.children.filter((child) => !ADVANCED_MEMORY_SECTION_IDS.has(child.id)),
        };
      }),
    [quickMode]
  );
  const effectiveActiveSection = quickMode && ADVANCED_MEMORY_SECTION_IDS.has(activeSection)
    ? 'memoryGeneral'
    : activeSection;

  const handleStateMemoryToggle = (checked: boolean) => {
    patchDraftConfig((draft) => {
      draft.personalitySettings.state_memory_enabled = checked;
      if (!checked) {
        draft.personalitySettings.state_transition_enabled = false;
        draft.personalitySettings.deep_persona_enabled = false;
      }
    });
  };

  const handleStateTransitionToggle = (checked: boolean) => {
    patchDraftConfig((draft) => {
      if (checked) {
        draft.personalitySettings.state_memory_enabled = true;
      }
      draft.personalitySettings.state_transition_enabled = checked;
    });
  };

  const handleDeepPersonaToggle = (checked: boolean) => {
    patchDraftConfig((draft) => {
      if (checked) {
        draft.personalitySettings.state_memory_enabled = true;
      }
      draft.personalitySettings.deep_persona_enabled = checked;
    });
  };

  useImperativeHandle(ref, getHandle, [getHandle]);

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

    switch (effectiveActiveSection) {
      case 'preferences':
        return (
          <SettingsPreferencesSection
            draftConfig={draftConfig}
            draftThemeMode={draftThemeMode}
            patchDraftConfig={patchDraftConfig}
            onThemePreviewChange={handleThemePreviewChange}
            onLanguagePreviewChange={handleLanguagePreviewChange}
          />
        );

      case 'conversation':
        return (
          <SettingsConversationSection
            draftConfig={draftConfig}
            draftControlSettings={draftControlSettings}
            patchDraftConfig={patchDraftConfig}
            patchDraftControlSettings={patchDraftControlSettings}
          />
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

      case 'personalitySelection':
        return <PersonalityModern embedded />;

      case 'personalitySettings':
        return (
          <SettingsSectionShell>
            <SettingsGroup
              title={t('settings.personalitySettings.runtimeTitle')}
              description={t('settings.personalitySettings.runtimeDesc')}
            >
              <div className="rounded-[1.25rem] border border-[hsl(var(--settings-subnav-border)/0.62)] bg-[hsl(var(--settings-shell-elevated)/0.42)] px-4 py-3 text-[13px] leading-6 text-[hsl(var(--foreground)/0.72)]">
                {t('settings.personalitySettings.requestNotice')}
              </div>

              <div className="space-y-3">
                <div className="flex items-start justify-between gap-4 border-b border-[hsl(var(--settings-subnav-border)/0.6)] py-3">
                  <div className="space-y-1">
                    <div className="text-sm font-medium text-foreground">{t('settings.personalitySettings.stateMemoryLabel')}</div>
                    <div className="text-xs leading-6 text-muted-foreground">{t('settings.personalitySettings.stateMemoryDesc')}</div>
                  </div>
                  <Switch
                    aria-label={t('settings.personalitySettings.stateMemoryLabel')}
                    checked={draftConfig.personalitySettings.state_memory_enabled}
                    onCheckedChange={handleStateMemoryToggle}
                  />
                </div>

                <div className="flex items-start justify-between gap-4 border-b border-[hsl(var(--settings-subnav-border)/0.6)] py-3">
                  <div className="space-y-1">
                    <div className="text-sm font-medium text-foreground">{t('settings.personalitySettings.stateTransitionLabel')}</div>
                    <div className="text-xs leading-6 text-muted-foreground">{t('settings.personalitySettings.stateTransitionDesc')}</div>
                  </div>
                  <Switch
                    aria-label={t('settings.personalitySettings.stateTransitionLabel')}
                    checked={draftConfig.personalitySettings.state_transition_enabled}
                    onCheckedChange={handleStateTransitionToggle}
                  />
                </div>

                <div className="flex items-start justify-between gap-4 py-3">
                  <div className="space-y-1">
                    <div className="text-sm font-medium text-foreground">{t('settings.personalitySettings.deepPersonaLabel')}</div>
                    <div className="text-xs leading-6 text-muted-foreground">{t('settings.personalitySettings.deepPersonaDesc')}</div>
                  </div>
                  <Switch
                    aria-label={t('settings.personalitySettings.deepPersonaLabel')}
                    checked={draftConfig.personalitySettings.deep_persona_enabled}
                    onCheckedChange={handleDeepPersonaToggle}
                  />
                </div>
              </div>
            </SettingsGroup>
          </SettingsSectionShell>
        );

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
        return (
          <SettingsToolsSection
            tools={tools}
            toolsLoading={toolsLoading}
            toolsError={toolsError}
            draftToolDrafts={draftToolDrafts}
            selectedSkills={draftConfig.tools.skills || []}
            onToolDraftChange={handleToolDraftChange}
            onToolEnabledChange={handleToolEnabledChange}
            onSelectedSkillsChange={(nextSkills) => patchDraftConfig((draft) => {
              draft.tools.skills = nextSkills;
            })}
          />
        );

      case 'pluginsInstalled':
        return (
          <PluginsSection
            plugins={plugins}
            loading={pluginsLoading}
            drafts={draftPluginDrafts}
            dirty={dirty}
            onFieldChange={handlePluginDraftChange}
            onRescan={async () => {
              await loadPlugins();
              toast.success(t('settings.pluginPackages.feedback.rescanSuccess'));
            }}
            onPluginAction={handlePluginAction}
            processingIds={pluginProcessingIds}
          />
        );

      case 'pluginsMarketplace':
        return (
          <PluginMarketplace
            installedPlugins={plugins}
            onInstallComplete={loadPluginsAndSensors}
          />
        );

      case 'channels':
        return (
          <ChannelsSection
            plugins={plugins}
            drafts={draftPluginDrafts}
            dirty={dirty}
            selectedContributionId={channelsSelection}
            onSelectContribution={setChannelsSelection}
            onFieldChange={handlePluginDraftChange}
            onReloadPlugin={handleReloadActionPlugin}
            onPluginAction={handlePluginAction}
            reloading={reloadingActionPlugins}
          />
        );

      case 'control':
        return (
          <SettingsSectionShell>
            <SettingsGroup
              title={t('settings.control.title')}
              description={t('settings.control.description')}
            >
              {draftControlSettings ? (
                <ControlSettingsPanel
                  value={draftControlSettings}
                  onChange={(next) => patchDraftControlSettings((draft) => {
                    draft.permission_mode = next.permission_mode;
                    draft.plan_approval_required = next.plan_approval_required;
                  })}
                />
              ) : null}
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
        <SettingsNavigationSidebar
          visibleNavItems={visibleNavItems}
          effectiveActiveSection={effectiveActiveSection}
          getGroupExpanded={getGroupExpanded}
          setGroupExpanded={setGroupExpanded}
          handleNavItemClick={handleNavItemClick}
          sortedTimelineStatuses={sortedTimelineStatuses}
          timelineSelection={timelineSelection}
          setTimelineSelection={setTimelineSelection}
          channelContributions={channelContributions}
          channelsSelection={channelsSelection}
          setChannelsSelection={setChannelsSelection}
        />

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
                      : 'h-full overflow-y-auto pl-1 pr-2'
                  )}
                >
                  {renderSectionContent()}
                </div>
              </ErrorBoundary>
            </div>
          </div>
        </main>
      </div>

      {activeSection !== 'personalitySelection' ? (
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
