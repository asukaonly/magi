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
  ExpandableMemoryLayerCard,
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
    expandedMemoryLayers,
    setExpandedMemoryLayers,
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

      case 'memory': {
        // Check if embedding model is configured
        const embeddingSelection = draftConfig.llm?.selections?.embedding;
        const hasEmbeddingModel = !!(embeddingSelection?.provider_id && embeddingSelection?.model);

        return (
          <div className="space-y-6">
            {/* L0 Working Context */}
            <ExpandableMemoryLayerCard
              layerKey="l0"
              label={t('settings.memory.fields.enable_l0.label')}
              description={t('settings.memory.fields.enable_l0.description')}
              checked={draftConfig.memory.enable_l0}
              expanded={expandedMemoryLayers.has('l0')}
              onToggle={(checked) => updateMemoryToggle('enable_l0', checked)}
              onExpand={(expanded) => {
                setExpandedMemoryLayers((prev) => {
                  const next = new Set(prev);
                  if (expanded) {
                    next.add('l0');
                  } else {
                    next.delete('l0');
                  }
                  return next;
                });
              }}
            >
              <div className="space-y-4">
                <NumberField
                  label={t('settings.memory.fields.l0_checkpoint_interval_seconds.label')}
                  value={draftConfig.memory.l0_checkpoint_interval_seconds ?? 60}
                  min={1}
                  onChange={(value) => patchDraftConfig((draft) => {
                    draft.memory.l0_checkpoint_interval_seconds = value;
                  })}
                />
                <label className="flex items-start justify-between gap-4 rounded-lg border border-border/40 bg-background/50 px-3 py-2.5">
                  <div className="space-y-0.5">
                    <div className="text-xs font-medium">{t('settings.memory.fields.runtime_replay_include_l0_only.label')}</div>
                    <div className="text-[11px] leading-4 text-muted-foreground">{t('settings.memory.fields.runtime_replay_include_l0_only.description')}</div>
                  </div>
                  <Switch
                    checked={draftConfig.memory.runtime_replay_include_l0_only ?? false}
                    onCheckedChange={(checked) => patchDraftConfig((draft) => {
                      draft.memory.runtime_replay_include_l0_only = checked;
                    })}
                    aria-label={t('settings.memory.fields.runtime_replay_include_l0_only.label')}
                  />
                </label>
              </div>
            </ExpandableMemoryLayerCard>

            {/* L1 Event Memory */}
            <ExpandableMemoryLayerCard
              layerKey="l1"
              label={t('settings.memory.fields.enable_l1.label')}
              description={t('settings.memory.fields.enable_l1.description')}
              checked={draftConfig.memory.enable_l1}
              expanded={expandedMemoryLayers.has('l1')}
              onToggle={(checked) => updateMemoryToggle('enable_l1', checked)}
              onExpand={(expanded) => {
                setExpandedMemoryLayers((prev) => {
                  const next = new Set(prev);
                  if (expanded) {
                    next.add('l1');
                  } else {
                    next.delete('l1');
                  }
                  return next;
                });
              }}
            >
              <div className="space-y-4">
                <NumberField
                  label={t('settings.memory.fields.retention_days.label')}
                  value={draftConfig.memory.retention_days ?? 30}
                  min={1}
                  onChange={(value) => patchDraftConfig((draft) => {
                    draft.memory.retention_days = value;
                  })}
                />
                <label className="flex items-start justify-between gap-4 rounded-lg border border-border/40 bg-background/50 px-3 py-2.5">
                  <div className="space-y-0.5">
                    <div className="text-xs font-medium">{t('settings.memory.fields.enable_t1_importance.label')}</div>
                    <div className="text-[11px] leading-4 text-muted-foreground">{t('settings.memory.fields.enable_t1_importance.description')}</div>
                  </div>
                  <Switch
                    checked={draftConfig.memory.enable_t1_importance ?? false}
                    onCheckedChange={(checked) => patchDraftConfig((draft) => {
                      draft.memory.enable_t1_importance = checked;
                    })}
                    aria-label={t('settings.memory.fields.enable_t1_importance.label')}
                  />
                </label>

                <label className={cn(
                  "flex items-start justify-between gap-4 rounded-lg border border-border/40 bg-background/50 px-3 py-2.5",
                  !hasEmbeddingModel && "opacity-50"
                )}>
                  <div className="space-y-0.5">
                    <div className="text-xs font-medium">{t('settings.memory.fields.enable_l1_vectorization.label')}</div>
                    <div className="text-[11px] leading-4 text-muted-foreground">
                      {hasEmbeddingModel
                        ? t('settings.memory.fields.enable_l1_vectorization.description')
                        : t('settings.memory.fields.enable_l1_vectorization.description_disabled')}
                    </div>
                  </div>
                  <Switch
                    checked={draftConfig.memory.enable_l1_vectorization ?? false}
                    disabled={!hasEmbeddingModel}
                    onCheckedChange={(checked) => patchDraftConfig((draft) => {
                      draft.memory.enable_l1_vectorization = checked;
                    })}
                    aria-label={t('settings.memory.fields.enable_l1_vectorization.label')}
                  />
                </label>
              </div>
            </ExpandableMemoryLayerCard>

            {/* L2 Cognition Graph */}
            <ExpandableMemoryLayerCard
              layerKey="l2"
              label={t('settings.memory.fields.enable_l2.label')}
              description={t('settings.memory.fields.enable_l2.description')}
              checked={draftConfig.memory.enable_l1 && draftConfig.memory.enable_l2}
              disabled={!draftConfig.memory.enable_l1}
              expanded={expandedMemoryLayers.has('l2')}
              onToggle={(checked) => updateMemoryToggle('enable_l2', checked)}
              onExpand={(expanded) => {
                setExpandedMemoryLayers((prev) => {
                  const next = new Set(prev);
                  if (expanded) {
                    next.add('l2');
                  } else {
                    next.delete('l2');
                  }
                  return next;
                });
              }}
            >
              <label className="flex items-start justify-between gap-4 rounded-lg border border-border/40 bg-background/50 px-3 py-2.5">
                <div className="space-y-0.5">
                  <div className="text-xs font-medium">{t('settings.memory.fields.enable_l2_llm_extraction.label')}</div>
                  <div className="text-[11px] leading-4 text-muted-foreground">{t('settings.memory.fields.enable_l2_llm_extraction.description')}</div>
                </div>
                <Switch
                  checked={draftConfig.memory.enable_l2_llm_extraction ?? false}
                  disabled={!draftConfig.memory.enable_l2}
                  onCheckedChange={(checked) => patchDraftConfig((draft) => {
                    draft.memory.enable_l2_llm_extraction = checked;
                  })}
                  aria-label={t('settings.memory.fields.enable_l2_llm_extraction.label')}
                />
              </label>
            </ExpandableMemoryLayerCard>

            {/* L3 Reflection */}
            <ExpandableMemoryLayerCard
              layerKey="l3"
              label={t('settings.memory.fields.enable_l3.label')}
              description={t('settings.memory.fields.enable_l3.description')}
              checked={draftConfig.memory.enable_l1 && draftConfig.memory.enable_l3}
              disabled={!draftConfig.memory.enable_l1}
              expanded={expandedMemoryLayers.has('l3')}
              onToggle={(checked) => updateMemoryToggle('enable_l3', checked)}
              onExpand={(expanded) => {
                setExpandedMemoryLayers((prev) => {
                  const next = new Set(prev);
                  if (expanded) {
                    next.add('l3');
                  } else {
                    next.delete('l3');
                  }
                  return next;
                });
              }}
            >
              <div className="space-y-3">
                <label className="flex items-start justify-between gap-4 rounded-lg border border-border/40 bg-background/50 px-3 py-2.5">
                  <div className="space-y-0.5">
                    <div className="text-xs font-medium">{t('settings.memory.fields.enable_l3_llm_summary.label')}</div>
                    <div className="text-[11px] leading-4 text-muted-foreground">{t('settings.memory.fields.enable_l3_llm_summary.description')}</div>
                  </div>
                  <Switch
                    checked={draftConfig.memory.enable_l3_llm_summary ?? false}
                    disabled={!draftConfig.memory.enable_l3}
                    onCheckedChange={(checked) => patchDraftConfig((draft) => {
                      draft.memory.enable_l3_llm_summary = checked;
                    })}
                    aria-label={t('settings.memory.fields.enable_l3_llm_summary.label')}
                  />
                </label>

                <label className={cn(
                  "flex items-start justify-between gap-4 rounded-lg border border-border/40 bg-background/50 px-3 py-2.5",
                  !hasEmbeddingModel && "opacity-50"
                )}>
                  <div className="space-y-0.5">
                    <div className="text-xs font-medium">{t('settings.memory.fields.enable_l3_vectorization.label')}</div>
                    <div className="text-[11px] leading-4 text-muted-foreground">
                      {hasEmbeddingModel
                        ? t('settings.memory.fields.enable_l3_vectorization.description')
                        : t('settings.memory.fields.enable_l3_vectorization.description_disabled')}
                    </div>
                  </div>
                  <Switch
                    checked={draftConfig.memory.enable_l3_vectorization ?? false}
                    disabled={!draftConfig.memory.enable_l3 || !hasEmbeddingModel}
                    onCheckedChange={(checked) => patchDraftConfig((draft) => {
                      draft.memory.enable_l3_vectorization = checked;
                    })}
                    aria-label={t('settings.memory.fields.enable_l3_vectorization.label')}
                  />
                </label>
              </div>
            </ExpandableMemoryLayerCard>

            {/* L4 Procedural Memory */}
            <ExpandableMemoryLayerCard
              layerKey="l4"
              label={t('settings.memory.fields.enable_l4.label')}
              description={t('settings.memory.fields.enable_l4.description')}
              checked={draftConfig.memory.enable_l1 && draftConfig.memory.enable_l4}
              disabled={!draftConfig.memory.enable_l1}
              expanded={expandedMemoryLayers.has('l4')}
              onToggle={(checked) => updateMemoryToggle('enable_l4', checked)}
              onExpand={(expanded) => {
                setExpandedMemoryLayers((prev) => {
                  const next = new Set(prev);
                  if (expanded) {
                    next.add('l4');
                  } else {
                    next.delete('l4');
                  }
                  return next;
                });
              }}
            >
              <label className="flex items-start justify-between gap-4 rounded-lg border border-border/40 bg-background/50 px-3 py-2.5">
                <div className="space-y-0.5">
                  <div className="text-xs font-medium">{t('settings.memory.fields.enable_l4_skill_extraction.label')}</div>
                  <div className="text-[11px] leading-4 text-muted-foreground">{t('settings.memory.fields.enable_l4_skill_extraction.description')}</div>
                </div>
                <Switch
                  checked={draftConfig.memory.enable_l4_skill_extraction ?? false}
                  disabled={!draftConfig.memory.enable_l4}
                  onCheckedChange={(checked) => patchDraftConfig((draft) => {
                    draft.memory.enable_l4_skill_extraction = checked;
                  })}
                  aria-label={t('settings.memory.fields.enable_l4_skill_extraction.label')}
                />
              </label>
            </ExpandableMemoryLayerCard>

            {!draftConfig.memory.enable_l1 ? (
              <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
                <div className="font-medium">{t('settings.memory.form.l1DependencyTitle')}</div>
                <div className="mt-1 text-amber-800">{t('settings.memory.form.l1DependencyDescription')}</div>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="mt-3"
                  onClick={() => updateMemoryToggle('enable_l1', true)}
                >
                  {t('settings.memory.form.restoreL1')}
                </Button>
              </div>
            ) : null}
          </div>
        );
      }

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
          <div className="space-y-6">
            <DynamicToolsConfig
              tools={tools}
              loading={toolsLoading}
              error={toolsError}
              drafts={draftToolDrafts}
              onUpdateConfig={handleToolDraftChange}
              onUpdateEnabled={handleToolEnabledChange}
            />

            <div className="overflow-hidden rounded-2xl border border-border/70 bg-background/80">
              <div className="border-b border-border/60 px-4 py-3">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <h3 className="text-sm font-semibold">{t('tools.skills.label', { ns: 'onboarding' })}</h3>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {skills.length > 0
                        ? t('tools.skills.desc', { ns: 'onboarding', count: skills.length })
                        : t('tools.skills.empty', { ns: 'onboarding' })}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-muted-foreground">{t('tools.skills.enable', { ns: 'onboarding' })}</span>
                    <Switch
                      checked={skillsEnabled}
                      disabled={skills.length === 0}
                      onCheckedChange={(checked) => patchDraftConfig((draft) => {
                        draft.tools.skills = checked ? skills.map((skill) => skill.name) : [];
                      })}
                    />
                  </div>
                </div>
              </div>

              <div className="max-h-64 space-y-2 overflow-auto p-4">
                {skillsLoading ? (
                  <div className="text-xs text-muted-foreground">{t('settings.loadingTools')}</div>
                ) : null}

                {!skillsLoading && skillsError ? (
                  <div className="text-xs text-destructive">{skillsError}</div>
                ) : null}

                {!skillsLoading && !skillsError && skills.length > 0
                  ? skills.map((skill) => {
                      const checked = selectedSkills.includes(skill.name);
                      return (
                        <label
                          key={skill.name}
                          className="flex items-center justify-between gap-3 rounded-lg border border-border/50 bg-background/60 px-3 py-2"
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
                  <div className="text-xs text-muted-foreground">{t('tools.skills.emptyHint', { ns: 'onboarding' })}</div>
                ) : null}
              </div>
            </div>
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
                              handleNavItemClick(child.id, false);
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
            <div className="flex h-16 w-full items-center gap-4 px-8">
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
      ) : null}
    </div>
  );
});

SettingsPage.displayName = 'SettingsPage';
