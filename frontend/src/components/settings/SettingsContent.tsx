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
  LLMStatisticsSection,
  RuntimeStatisticsSection,
} from '@/components/settings';
import { SettingsControlSection } from '@/components/settings/SettingsControlSection';
import { HooksSection } from '@/components/settings/HooksSection';
import { SettingsConversationSection } from '@/components/settings/SettingsConversationSection';
import { SettingsIntegrationsSection, type SettingsIntegrationsSectionId } from '@/components/settings/SettingsIntegrationsSection';
import { SettingsLlmSection } from '@/components/settings/SettingsLlmSection';
import { SettingsMemorySection, type SettingsMemorySectionId } from '@/components/settings/SettingsMemorySection';
import { EmbeddingPreflightConfirmDialog } from '@/components/settings/EmbeddingPreflightConfirmDialog';
import { SettingsNavigationSidebar } from '@/components/settings/SettingsNavigationSidebar';
import { SettingsPersonalityRuntimeSection } from '@/components/settings/SettingsPersonalityRuntimeSection';
import { SettingsPreferencesSection } from '@/components/settings/SettingsPreferencesSection';
import { SettingsPersonalProfileSection } from '@/components/settings/SettingsPersonalProfileSection';
import { SettingsToolsSection } from '@/components/settings/SettingsToolsSection';
import { MCPServersSection } from '@/components/settings/MCPServersSection';
import { CodeAgentSection } from '@/components/settings/CodeAgentSection';
import TimelineSourcesSection from '@/components/settings/TimelineSourcesSection';
import PersonalityModern from '@/components/personality/PersonalityModern';
import { Button } from '@/components/ui/button';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { cn } from '@/lib/utils';
import { ErrorBoundary } from '@/components/ui/ErrorBoundary';
import {
  buildTimelineAvailableEntries,
  getTimelineCapabilityId,
} from '@/utils/timeline-capabilities';
import { getTimelineSourceDisplayName } from '@/utils/timeline-source-copy';
import { validateLLMCustomProviderReadiness, type LLMValidationIssue } from '@/components/config-forms/llm-form-state';

const ADVANCED_MEMORY_SECTION_IDS = new Set([
  'memoryWorkbench',
  'memoryEvents',
  'memoryKnowledge',
  'memoryReflection',
  'memorySkills',
]);

const MEMORY_SECTION_IDS = new Set<string>([
  'memoryGeneral',
  'memoryWorkbench',
  'memoryEvents',
  'memoryKnowledge',
  'memoryReflection',
  'memorySkills',
]);

const INTEGRATION_SECTION_IDS = new Set<string>([
  'pluginsInstalled',
  'pluginsMarketplace',
  'channels',
]);

const TOOL_SECTION_IDS = new Set<string>([
  'toolsBuiltin',
  'toolsPlugins',
  'toolsSkills',
]);

export const SettingsPage = forwardRef<SettingsPageHandle, SettingsPageProps>(({ onRequestClose }, ref) => {
  const { t, i18n } = useTranslation('app');

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
    handleLanguageDraftChange,
    updateMemoryToggle,
    plugins,
    pluginsLoading,
    pluginRegistryEntries,
    pluginProcessingIds,
    reloadingActionPlugins,
    draftPluginDrafts,
    handlePluginDraftChange,
    handlePluginDraftChanges,
    applyPersistedPluginSettings,
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
    embeddingPreflightPrompt,
    confirmEmbeddingPreflight,
    cancelEmbeddingPreflight,
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

  const timelineAvailableEntries = useMemo(() => {
    const installedPluginIds = new Set(plugins.map((plugin) => plugin.manifest.plugin_id));
    for (const source of timelineStatuses) {
      installedPluginIds.add(source.plugin_id);
    }
    return buildTimelineAvailableEntries(
      pluginRegistryEntries,
      installedPluginIds,
      i18n?.language ?? 'zh-CN'
    ).filter((entry) =>
      timelineStatuses.some((source) => getTimelineCapabilityId(source) === entry.capabilityId)
    );
  }, [i18n?.language, pluginRegistryEntries, plugins, timelineStatuses]);

  const channelContributions = useMemo(() =>
    plugins.flatMap((plugin) =>
      plugin.contributions
        .filter((c) => c.contribution_type === 'channel')
        .map((contribution) => ({ plugin, contribution }))
    ),
    [plugins]
  );

  const quickMode = draftConfig.preferences.user_mode === 'quick';
  const llmValidationIssues = useMemo(
    () => validateLLMCustomProviderReadiness(draftConfig.llm),
    [draftConfig.llm]
  );
  const formatLlmValidationIssue = (issue: LLMValidationIssue): string => {
    const serviceLabel = t(`settings.llmValidation.services.${issue.serviceName}`);
    if (issue.code === 'customScenarioModelMissing' && issue.scenario && issue.model) {
      return t('settings.llmValidation.customScenarioModelMissing', {
        provider: issue.providerName,
        scenario: t(`settings.llmValidation.scenarios.${issue.scenario}`),
        model: issue.model,
        service: serviceLabel,
      });
    }
    return t('settings.llmValidation.customServiceModelRequired', {
      provider: issue.providerName,
      service: serviceLabel,
    });
  };
  const llmValidationMessage = llmValidationIssues[0]
    ? formatLlmValidationIssue(llmValidationIssues[0])
    : null;
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
  const showSettingsFooter = !['personalitySelection', 'personalProfile'].includes(effectiveActiveSection);
  const browsePluginMarketplace = () => {
    setGroupExpanded('plugins', true);
    handleNavItemClick('pluginsMarketplace', false);
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
    const hasCrossEncoderModel = !!(draftConfig.memory.reranker?.cross_encoder?.managed_model_id);

    switch (effectiveActiveSection) {
      case 'preferences':
        return (
          <SettingsPreferencesSection
            draftConfig={draftConfig}
            draftThemeMode={draftThemeMode}
            patchDraftConfig={patchDraftConfig}
            onThemePreviewChange={handleThemePreviewChange}
            onLanguageDraftChange={handleLanguageDraftChange}
          />
        );

      case 'personalProfile':
        return <SettingsPersonalProfileSection />;

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
          <SettingsLlmSection
            view="providers"
            draftConfig={draftConfig}
            patchDraftConfig={patchDraftConfig}
            syncNormalizedLlmConfig={syncNormalizedLlmConfig}
          />
        );

      case 'llmModels':
        return (
          <SettingsLlmSection
            view="models"
            draftConfig={draftConfig}
            patchDraftConfig={patchDraftConfig}
            syncNormalizedLlmConfig={syncNormalizedLlmConfig}
          />
        );

      case 'personalitySelection':
        return <PersonalityModern embedded />;

      case 'personalitySettings':
        return (
          <SettingsPersonalityRuntimeSection
            draftConfig={draftConfig}
            patchDraftConfig={patchDraftConfig}
          />
        );

      case 'statisticsLlm':
        return <LLMStatisticsSection />;

      case 'statisticsRuntime':
        return <RuntimeStatisticsSection />;

      case 'memoryGeneral':
      case 'memoryWorkbench':
      case 'memoryEvents':
      case 'memoryKnowledge':
      case 'memoryReflection':
      case 'memorySkills':
        if (!MEMORY_SECTION_IDS.has(effectiveActiveSection)) {
          return null;
        }
        return (
          <SettingsMemorySection
            section={effectiveActiveSection as SettingsMemorySectionId}
            draftConfig={draftConfig}
            patchDraftConfig={patchDraftConfig}
            updateMemoryToggle={updateMemoryToggle}
            hasEmbeddingModel={hasEmbeddingModel}
            hasCrossEncoderModel={hasCrossEncoderModel}
          />
        );

      case 'timeline':
        return (
          <TimelineSourcesSection
            userMode={draftConfig.preferences.user_mode}
            statuses={sortedTimelineStatuses}
            availableEntries={timelineAvailableEntries}
            loadingStatus={timelineStatusesLoading}
            selectedSourceName={timelineSelection}
            pluginDrafts={draftPluginDrafts}
            onSelectSource={setTimelineSelection}
            onRefreshSources={fetchTimelineStatuses}
            onPluginInstalled={loadPluginsAndSensors}
            onBrowseMarketplace={browsePluginMarketplace}
            onPluginFieldChange={handlePluginDraftChange}
            onPluginFieldsChange={handlePluginDraftChanges}
          />
        );

      case 'mcpServers':
        return <MCPServersSection />;

      case 'codeAgent':
        return <CodeAgentSection />;

      case 'toolsBuiltin':
      case 'toolsPlugins':
      case 'toolsSkills':
        if (!TOOL_SECTION_IDS.has(effectiveActiveSection)) {
          return null;
        }
        return (
          <SettingsToolsSection
            view={effectiveActiveSection === 'toolsPlugins' ? 'plugins' : effectiveActiveSection === 'toolsSkills' ? 'skills' : 'builtin'}
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
      case 'pluginsMarketplace':
      case 'channels':
        if (!INTEGRATION_SECTION_IDS.has(effectiveActiveSection)) {
          return null;
        }
        return (
          <SettingsIntegrationsSection
            section={effectiveActiveSection as SettingsIntegrationsSectionId}
            plugins={plugins}
            pluginsLoading={pluginsLoading}
            draftPluginDrafts={draftPluginDrafts}
            dirty={dirty}
            pluginProcessingIds={pluginProcessingIds}
            reloadingActionPlugins={reloadingActionPlugins}
            channelsSelection={channelsSelection}
            setChannelsSelection={setChannelsSelection}
            handlePluginDraftChange={handlePluginDraftChange}
            applyPersistedPluginSettings={applyPersistedPluginSettings}
            handlePluginAction={handlePluginAction}
            handleReloadActionPlugin={handleReloadActionPlugin}
            loadPlugins={loadPlugins}
            loadPluginsAndSensors={loadPluginsAndSensors}
            onBrowseMarketplace={browsePluginMarketplace}
          />
        );

      case 'control':
        return (
          <SettingsControlSection
            draftControlSettings={draftControlSettings}
            patchDraftControlSettings={patchDraftControlSettings}
          />
        );

      case 'hooks':
        return <HooksSection />;

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

        <main className="flex min-h-0 min-w-0 flex-1 flex-col">
          <header className="shrink-0 bg-[hsl(var(--settings-shell-elevated)/0.64)] shadow-[inset_0_-1px_0_hsl(var(--settings-subnav-border)/0.2)] backdrop-blur-sm">
            <div data-testid="settings-main-header" className="flex h-16 w-full items-center gap-4 px-5">
              <h2 className="text-base font-bold leading-6 text-foreground">
                {t(`settings.tabs.${effectiveActiveSection}`)}
              </h2>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                onClick={() => void onRequestClose?.()}
                className="ml-auto h-8 w-8 rounded-md text-[hsl(var(--settings-nav-foreground))] transition-colors duration-200 hover:bg-[hsl(var(--settings-nav-hover)/0.72)] hover:text-foreground"
                aria-label={t('settings.actions.close')}
              >
                <X className="h-4 w-4" />
              </Button>
            </div>
          </header>

          <div className="flex-1 min-h-0 min-w-0 overflow-hidden">
            <div className="h-full w-full min-w-0 px-5 py-5">
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
                    'animate-in fade-in-0 slide-in-from-bottom-2 duration-300 ease-out min-w-0',
                    usesInnerPaneScroll
                      ? 'flex h-full min-h-0 w-full flex-col overflow-hidden'
                      : 'h-full overflow-y-auto px-1 pr-5'
                  )}
                >
                  {renderSectionContent()}
                </div>
              </ErrorBoundary>
            </div>
          </div>
        </main>
      </div>

      {showSettingsFooter ? (
        <footer className="shrink-0 bg-[hsl(var(--settings-shell-elevated)/0.72)] shadow-[inset_0_1px_0_hsl(var(--settings-subnav-border)/0.18)] backdrop-blur-sm">
          <div data-testid="settings-main-footer" className="flex flex-wrap items-center justify-between gap-4 px-5 py-4">
            <p className={cn(
              'text-sm leading-6 transition-colors duration-200',
              llmValidationMessage ? 'font-medium text-amber-700 dark:text-amber-300' : dirty ? 'text-primary font-medium' : 'text-muted-foreground'
            )}>
              {llmValidationMessage || (dirty ? t('settings.pendingChanges') : t('settings.allChangesSaved'))}
            </p>
            <div className="flex flex-wrap items-center gap-2.5">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => void handleDiscardChanges()}
                disabled={!dirty || saving}
                className="h-9 rounded-lg border-transparent bg-[hsl(var(--settings-shell-elevated)/0.5)] px-4 text-muted-foreground shadow-[inset_0_0_0_1px_hsl(var(--settings-subnav-border)/0.22)] transition-[background-color,box-shadow,color] duration-200 hover:bg-[hsl(var(--settings-nav-hover)/0.72)] hover:text-foreground disabled:opacity-40"
              >
                <RotateCcw className="mr-1.5 h-4 w-4" />
                {t('settings.actions.discard')}
              </Button>
              <Button
                type="button"
                size="sm"
                onClick={() => void handleSaveChanges()}
                disabled={!dirty || saving || llmValidationIssues.length > 0}
                className={cn(
                  'h-9 rounded-lg px-4 transition-all duration-200 shadow-[0_8px_18px_hsl(var(--primary)/0.11)] hover:shadow-[0_10px_22px_hsl(var(--primary)/0.15)]',
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

      <EmbeddingPreflightConfirmDialog
        prompt={embeddingPreflightPrompt}
        onCancel={cancelEmbeddingPreflight}
        onConfirm={confirmEmbeddingPreflight}
      />
    </div>
  );
});

SettingsPage.displayName = 'SettingsPage';
