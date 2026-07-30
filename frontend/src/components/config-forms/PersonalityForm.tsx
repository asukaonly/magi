import React, { useEffect, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { ArrowLeft, ChevronRight, PencilLine, Sparkles } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { ProtectedImage } from '@/components/media/ProtectedImage';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';
import { FormContext, SimpleForm as Form } from '../onboarding/simple-form';
import PersonalityDetailEditor from '@/components/PersonalityDetailEditor';
import type { LLMConfig } from '../../api/modules/config';
import {
  personasApi,
  DEFAULT_PERSONALITY_CONFIG,
  PERSONA_GENERATION_STAGE_IDS,
  selectDefaultSeedPreview,
  type PersonalityConfig,
  type PersonaGenerationStage,
  type PersonaGenerationStageId,
  type SeedPreview,
} from '../../api/modules/personas';

interface PersonalityFormProps {
  quickMode?: boolean;
  language?: 'zh' | 'en';
}

// Group display order
const GROUP_ORDER = ['magi', 'general'];
const buildPendingGenerationStages = (): PersonaGenerationStage[] =>
  PERSONA_GENERATION_STAGE_IDS.map((stageId) => ({ stage_id: stageId, status: 'pending' }));

const getGenerationStageKey = (stages: PersonaGenerationStage[]): PersonaGenerationStageId => {
  const running = stages.find((stage) => stage.status === 'running');
  const pending = stages.find((stage) => stage.status === 'pending');
  const active = running || pending || stages[stages.length - 1];
  return PERSONA_GENERATION_STAGE_IDS.includes(active?.stage_id as PersonaGenerationStageId)
    ? (active.stage_id as PersonaGenerationStageId)
    : PERSONA_GENERATION_STAGE_IDS[0];
};

const getGenerationProgress = (stages: PersonaGenerationStage[], generating: boolean): number => {
  if (!generating || stages.length === 0) return 0;
  const completedCount = stages.filter((stage) => stage.status === 'completed').length;
  const failedCount = stages.filter((stage) => stage.status === 'failed').length;
  if (completedCount + failedCount >= stages.length) {
    return 100;
  }
  return Math.round((completedCount / stages.length) * 100);
};

const mergeConfig = (incoming: Partial<PersonalityConfig>): PersonalityConfig => {
  const next = structuredClone(DEFAULT_PERSONALITY_CONFIG);
  next.name = incoming.name || next.name;
  next.avatar = incoming.avatar || next.avatar;
  next.description = incoming.description || next.description;
  next.appearance_prompt = incoming.appearance_prompt || next.appearance_prompt;
  next.identity_core = { ...next.identity_core, ...(incoming.identity_core || {}) };
  next.idiolect = { ...next.idiolect, ...(incoming.idiolect || {}) };
  next.registers = { ...next.registers, ...(incoming.registers || {}) };
  next.quiet_hours = incoming.quiet_hours ?? next.quiet_hours;
  next.signature_triggers = incoming.signature_triggers ?? next.signature_triggers;
  next.persona_layers = incoming.persona_layers ?? next.persona_layers;
  next.dynamic_state_rules = incoming.dynamic_state_rules ?? next.dynamic_state_rules;
  next.milestone_conditions = incoming.milestone_conditions ?? next.milestone_conditions;
  next.interim_lines = incoming.interim_lines ?? next.interim_lines;
  next.bootstrap = incoming.bootstrap ?? next.bootstrap;
  return next;
};

export const PersonalityForm: React.FC<PersonalityFormProps> = ({ quickMode = false, language = 'zh' }) => {
  const { t } = useTranslation('onboarding');
  const formContext = React.useContext(FormContext);
  const formInstance = formContext?.instance;
  const [presets, setPresets] = useState<SeedPreview[]>([]);
  const [generating, setGenerating] = useState(false);
  const [generationStages, setGenerationStages] = useState<PersonaGenerationStage[]>(buildPendingGenerationStages);
  const [oneLiner, setOneLiner] = useState('');
  const [viewMode, setViewMode] = useState<'selection' | 'focus'>('selection');
  const [showDetails, setShowDetails] = useState(false);
  const [uploadingAvatar, setUploadingAvatar] = useState(false);
  const [expandedCardId, setExpandedCardId] = useState<string | null>(null);
  const [config, setConfig] = useState<PersonalityConfig>(DEFAULT_PERSONALITY_CONFIG);
  const [loadingConfig, setLoadingConfig] = useState(false);
  const [configLoaded, setConfigLoaded] = useState(false); // Track if config has been loaded
  const [brokenAvatarKeys, setBrokenAvatarKeys] = useState<Record<string, boolean>>({});
  const [defaultPresetResolved, setDefaultPresetResolved] = useState(false);

  useEffect(() => {
    const loadPresets = async () => {
      try {
        const response = await personasApi.seedPreviews(language);
        setPresets(response.data || []);
      } catch (error) {
        setPresets([]);
      }
    };
    void loadPresets();
  }, [language]);

  useEffect(() => {
    if (defaultPresetResolved || !formInstance || presets.length === 0) {
      return;
    }

    const currentPersonality = formInstance.getFieldValue(['personality']) as PersonalityConfig | undefined;
    const currentName = currentPersonality?.name;
    const isBlankSelection = !currentName || currentName === 'AI Assistant';

    if (!isBlankSelection) {
      setDefaultPresetResolved(true);
      return;
    }

    const defaultPreset = selectDefaultSeedPreview(presets);
    if (!defaultPreset) {
      return;
    }

    let cancelled = false;
    const applyDefaultPreset = async () => {
      setLoadingConfig(true);
      setConfigLoaded(false);
      try {
        const result = await personasApi.getPresetConfig(defaultPreset.seed_slug, language);
        if (cancelled) return;
        const data = (result.data || {}) as Partial<PersonalityConfig>;
        const mergedConfig = mergeConfig(data);
        setConfig(mergedConfig);
        formInstance.setFieldValue(['personality'], mergedConfig);
        formInstance.setFieldValue(['personalitySeedSlug'], defaultPreset.seed_slug);
      } catch {
        if (cancelled) return;
        const fallbackConfig = mergeConfig({
          name: defaultPreset.name,
          description: defaultPreset.description,
          avatar: defaultPreset.avatar,
        } as Partial<PersonalityConfig>);
        setConfig(fallbackConfig);
        formInstance.setFieldValue(['personality'], fallbackConfig);
        formInstance.setFieldValue(['personalitySeedSlug'], defaultPreset.seed_slug);
      } finally {
        if (!cancelled) {
          setLoadingConfig(false);
          setConfigLoaded(true);
          setDefaultPresetResolved(true);
        }
      }
    };

    void applyDefaultPreset();
    return () => {
      cancelled = true;
    };
  }, [defaultPresetResolved, formInstance, language, presets]);

  const avatarFor = (item: SeedPreview): string => {
    const map: Record<string, string> = {
      assistant: '🤖',
      analyst: '🧠',
      teacher: '🧑‍🏫',
      coder: '💻',
      writer: '✍️',
      default: '✨',
    };
    return map[item.seed_slug] || item.name.trim().charAt(0).toUpperCase() || '✨';
  };

  const patch = (fn: (draft: PersonalityConfig) => void) => {
    setConfig((prev) => {
      const next = structuredClone(prev);
      fn(next);
      return next;
    });
  };

  const markAvatarBroken = (key: string) => {
    setBrokenAvatarKeys((prev) => ({ ...prev, [key]: true }));
  };

  const resetAvatarBroken = (key: string) => {
    setBrokenAvatarKeys((prev) => {
      if (!prev[key]) return prev;
      const next = { ...prev };
      delete next[key];
      return next;
    });
  };

  const resolveAvatarUrl = (avatar?: string): string => personasApi.getAvatarUrl(avatar || '');
  const avatarLabel = (avatar?: string): string => (avatar || '').split('/').pop() || '';

  const handleAvatarUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    setUploadingAvatar(true);
    try {
      const response = await personasApi.uploadAvatar(file);
      const avatarValue = response.data?.url || response.data?.filename;
      if (!avatarValue) return;
      patch((d) => {
        d.avatar = avatarValue;
      });
      resetAvatarBroken(`focus:${avatarValue}`);
    } finally {
      setUploadingAvatar(false);
      event.target.value = '';
    }
  };

  const handleSelectPreset = async (
    item: SeedPreview,
    setFieldValue: (name: any, value: any) => void
  ) => {
    setViewMode('focus');
    setShowDetails(false);
    setLoadingConfig(true);
    setConfigLoaded(false);

    try {
      // Fetch full config from preset API using seed_slug
      const result = await personasApi.getPresetConfig(item.seed_slug, language);
      const data = (result.data || {}) as Partial<PersonalityConfig>;
      const mergedConfig = mergeConfig(data);
      setConfig(mergedConfig);
      setFieldValue(['personality'], mergedConfig);
      setFieldValue(['personalitySeedSlug'], item.seed_slug);
    } catch {
      setConfig(DEFAULT_PERSONALITY_CONFIG);
      setFieldValue(['personality'], DEFAULT_PERSONALITY_CONFIG);
      setFieldValue(['personalitySeedSlug'], null);
    } finally {
      setLoadingConfig(false);
      setConfigLoaded(true);
    }
  };

  const handleSelectCustom = (setFieldValue: (name: any, value: any) => void) => {
    setViewMode('focus');
    setShowDetails(false);
    setConfig(DEFAULT_PERSONALITY_CONFIG);
    setConfigLoaded(true);
    setFieldValue(['personality'], DEFAULT_PERSONALITY_CONFIG);
    setFieldValue(['personalitySeedSlug'], null);
    setOneLiner('');
  };

  const handleGenerate = async (
    setFieldValue: (name: any, value: any) => void,
    getFieldValue: (name: any) => any,
  ) => {
    if (!oneLiner.trim()) return;
    setGenerating(true);
    setGenerationStages(buildPendingGenerationStages());
    try {
      const llmOverride = getFieldValue(['llm']) as LLMConfig | undefined;
      const generated = await personasApi.generateWithProgress({
        description: oneLiner.trim(),
        target_language: language === 'zh' ? 'Chinese' : 'English',
        current_config: config,
        llm_override: llmOverride,
      }, (snapshot) => {
        setGenerationStages(snapshot.stages?.length ? snapshot.stages : buildPendingGenerationStages());
      });
      const data = (generated.data || {}) as Partial<PersonalityConfig>;
      const mergedConfig = mergeConfig(data);
      setConfig(mergedConfig);
      setFieldValue(['personality'], mergedConfig);
      setFieldValue(['personalitySeedSlug'], null);
    } catch (error: any) {
      toast.error(error?.message || t('personality.generateFailed'));
    } finally {
      setGenerating(false);
    }
  };

  const generationStageKey = getGenerationStageKey(generationStages);
  const generationProgress = getGenerationProgress(generationStages, generating);

  return (
    <>
      <Form.Item label={t('personality.presetLabel')}>
        <Form.Item noStyle shouldUpdate>
          {({
            getFieldValue,
            setFieldValue,
          }: {
            getFieldValue: (name: any) => any;
            setFieldValue: (name: any, value: any) => void;
          }) => {
            const personalityValue = getFieldValue(['personality']);
            const selectedPreset = personalityValue?.name;
            const isCustomSelected = !selectedPreset || selectedPreset === 'AI Assistant';
            const showCustomSection = viewMode === 'focus';
            const focusedPreset = presets.find((item) => item.name === selectedPreset);
            const focusTitle = isCustomSelected && !focusedPreset
              ? t('personality.blankCardTitle')
              : config.name || selectedPreset;
            const focusAvatar = config.avatar || focusedPreset?.avatar || '';
            const focusSubtitle = isCustomSelected && !focusedPreset
              ? t('personality.blankCardDesc')
              : config.description || focusedPreset?.description || '';
            const focusDescription = isCustomSelected
              ? t('personality.blankCardDesc')
              : config.identity_core.identity_statement || focusedPreset?.description || '';

            // Group by backend group field
            const groupedPersonalities = GROUP_ORDER.reduce((acc, group) => {
              const items = presets.filter((p) => p.group === group);
              if (items.length > 0) {
                acc.push({ group, items });
              }
              return acc;
            }, [] as Array<{ group: string; items: SeedPreview[] }>);

            const renderPersonalityCard = (item: SeedPreview) => {
              const active = selectedPreset === item.name;
              const expanded = expandedCardId === item.seed_slug;
              return (
                <div key={item.seed_slug} className="relative">
                  <div
                    onClick={() => void handleSelectPreset(item, setFieldValue)}
                    className={cn(
                      'group cursor-pointer rounded-2xl border bg-card p-5 text-left transition',
                      active
                        ? 'border-primary/60 bg-primary/10 ring-1 ring-primary/20'
                        : 'border-border hover:border-primary/30 hover:bg-muted/50'
                    )}
                  >
                    <div className="flex items-center gap-3">
                      <div className="flex h-12 w-12 shrink-0 items-center justify-center overflow-hidden rounded-full border border-border/50 bg-neutral-200 text-xl dark:bg-neutral-700">
                        {item.avatar && !brokenAvatarKeys[`list:${item.seed_slug}:${item.avatar}`] ? (
                          <ProtectedImage
                            src={resolveAvatarUrl(item.avatar)}
                            alt={item.name}
                            eager
                            className="h-full w-full object-cover"
                            onError={() => markAvatarBroken(`list:${item.seed_slug}:${item.avatar}`)}
                            onProtectedAccessError={() => markAvatarBroken(`list:${item.seed_slug}:${item.avatar}`)}
                          />
                        ) : (
                          avatarFor(item)
                        )}
                      </div>
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-base font-semibold">{item.name}</p>
                        {item.description ? <p className="truncate text-sm text-muted-foreground">{item.description}</p> : null}
                      </div>
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          setExpandedCardId(expanded ? null : item.seed_slug);
                        }}
                        className={cn(
                          'pointer-events-auto shrink-0 rounded p-1 transition-colors hover:bg-muted',
                          expanded && 'bg-muted'
                        )}
                      >
                        <ChevronRight
                          className={cn(
                            'h-4 w-4 text-muted-foreground transition-transform duration-200',
                            expanded && 'rotate-90'
                          )}
                        />
                      </button>
                    </div>
                    <p className="mt-2 line-clamp-2 text-sm text-muted-foreground">{item.description}</p>
                  </div>

                  <AnimatePresence initial={false}>
                    {expanded && (
                      <motion.div
                        initial={{ height: 0, opacity: 0 }}
                        animate={{ height: 'auto', opacity: 1 }}
                        exit={{ height: 0, opacity: 0 }}
                        transition={{ duration: 0.2, ease: 'easeOut' }}
                        className="overflow-hidden"
                      >
                        <div className="mt-1 rounded-xl border border-border/70 bg-muted/30 p-3 text-xs text-muted-foreground">
                          <p className="line-clamp-4">{item.description}</p>
                        </div>
                      </motion.div>
                    )}
                  </AnimatePresence>
                </div>
              );
            };

            return (
              <div className="space-y-6">
                <AnimatePresence mode="wait" initial={false}>
                  {viewMode === 'selection' ? (
                    <motion.div
                      key="personality-selection"
                      initial={{ opacity: 0, y: 16 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0, y: -12 }}
                      transition={{ duration: 0.22, ease: 'easeOut' }}
                      className="space-y-6"
                    >
                      {/* Dynamic group sections */}
                      {groupedPersonalities.map(({ group, items }) => (
                        <div key={group}>
                          <h3 className={cn(
                            'mb-3 text-sm font-semibold',
                            group === 'magi' ? 'text-primary' : 'text-muted-foreground'
                          )}>
                            {t(`personality.groups.${group}`, { defaultValue: group })}
                          </h3>
                          <div className={cn(
                            'grid gap-4',
                            group === 'magi' ? 'md:grid-cols-3' : 'md:grid-cols-2 xl:grid-cols-3'
                          )}>
                            {items.map(renderPersonalityCard)}
                          </div>
                        </div>
                      ))}

                      {/* Custom personality */}
                      <div>
                        <h3 className="mb-3 text-sm font-semibold text-muted-foreground">{t('personality.groups.custom')}</h3>
                        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                          <button
                            type="button"
                            onClick={() => handleSelectCustom(setFieldValue)}
                            className={cn(
                              'group relative min-h-[168px] overflow-hidden rounded-2xl border border-dashed bg-card p-5 text-left transition',
                              isCustomSelected
                                ? 'border-primary/60 bg-primary/10 ring-1 ring-primary/20'
                                : 'border-border hover:border-primary/30 hover:bg-muted/50'
                            )}
                          >
                                    <div className="mb-3 flex items-center gap-3">
                              <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full border border-primary/20 bg-primary/10 text-base">
                                <Sparkles className="h-5 w-5 text-primary" />
                              </div>
                              <div className="min-w-0">
                                <p className="truncate text-base font-semibold">{t('personality.blankCardTitle')}</p>
                                <p className="truncate text-sm text-muted-foreground">{t('personality.blankCardTag')}</p>
                              </div>
                            </div>
                            <p className="line-clamp-3 text-sm text-muted-foreground">{t('personality.blankCardDesc')}</p>
                          </button>
                        </div>
                      </div>
                    </motion.div>
                  ) : (
                    <motion.div
                      key="personality-focus"
                      initial={{ opacity: 0, y: 10, scale: 0.99 }}
                      animate={{ opacity: 1, y: 0, scale: 1 }}
                      exit={{ opacity: 0, y: -8 }}
                      transition={{ duration: 0.24, ease: 'easeOut' }}
                      className="mx-auto w-full max-w-5xl space-y-4"
                    >
                      <div className="relative overflow-hidden rounded-2xl border border-primary/20 bg-card p-5">
                            <AnimatePresence initial={false}>
                          {!showDetails && (
                            <motion.div
                              initial={{ height: 0, opacity: 0 }}
                              animate={{ height: 'auto', opacity: 1 }}
                              exit={{ height: 0, opacity: 0 }}
                              className="overflow-hidden"
                            >
                              <div className="flex flex-wrap items-start gap-4">
                                <div className="flex h-16 w-16 shrink-0 items-center justify-center overflow-hidden rounded-full border border-border/50 bg-neutral-200 text-2xl dark:bg-neutral-700">
                                  {isCustomSelected ? (
                                    <Sparkles className="h-7 w-7 text-primary" />
                                  ) : focusAvatar && !brokenAvatarKeys[`focus:${focusAvatar}`] ? (
                                    <ProtectedImage
                                      src={resolveAvatarUrl(focusAvatar)}
                                      alt={focusTitle}
                                      eager
                                      className="h-full w-full rounded-full object-cover"
                                      onError={() => markAvatarBroken(`focus:${focusAvatar}`)}
                                      onProtectedAccessError={() => markAvatarBroken(`focus:${focusAvatar}`)}
                                    />
                                  ) : focusedPreset ? (
                                    avatarFor(focusedPreset)
                                  ) : (
                                    '✨'
                                  )}
                                </div>
                                <div className="min-w-0 flex-1">
                                  <div className="mb-2 flex items-center gap-2">
                                    <span className="rounded-full border border-primary/30 bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">
                                      {selectedPreset}
                                    </span>
                                  </div>
                                  <p className="text-xl font-semibold tracking-wide">{focusTitle}</p>
                                  {focusSubtitle ? <p className="mt-1 text-sm text-muted-foreground">{focusSubtitle}</p> : null}
                                  <p className="mt-3 line-clamp-3 text-sm text-muted-foreground">{focusDescription}</p>
                                </div>
                              </div>
                            </motion.div>
                          )}
                        </AnimatePresence>
                        <div className={cn('flex flex-wrap items-center gap-2', !showDetails && 'mt-4')}>
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            onClick={() => {
                              setViewMode('selection');
                              setShowDetails(false);
                            }}
                          >
                            <ArrowLeft className="h-4 w-4" />
                            {t('personality.actions.backToCards')}
                          </Button>
                          <Button type="button" size="sm" onClick={() => setShowDetails((prev) => !prev)}>
                            <PencilLine className="h-4 w-4" />
                            {showDetails ? t('personality.actions.hideDetails') : t('personality.actions.editDetails')}
                          </Button>
                        </div>
                      </div>

                      {isCustomSelected && (
                        <motion.div
                          initial={{ height: 0, opacity: 0 }}
                          animate={{ height: 'auto', opacity: 1 }}
                          exit={{ height: 0, opacity: 0 }}
                          className="overflow-hidden"
                        >
                          <div className="rounded-xl border border-border bg-muted/20 p-3">
                            <div className="mb-2 flex items-center gap-2 text-sm font-medium">
                              <Sparkles className="h-4 w-4 text-primary" />
                              {t('personality.oneLinerLabel')}
                            </div>
                            <div className="flex flex-col gap-2 md:flex-row">
                              <Input
                                value={oneLiner}
                                onChange={(event) => setOneLiner(event.target.value)}
                                placeholder={t('personality.oneLinerPlaceholder')}
                                className="flex-1"
                              />
                              <Button
                                type="button"
                                disabled={generating}
                                onClick={() => void handleGenerate(setFieldValue, getFieldValue)}
                              >
                                {generating ? t('personality.generating') : t('personality.generateAction')}
                              </Button>
                            </div>
                            {generating ? (
                              <div className="mt-2 space-y-1.5 rounded-lg border border-border/60 bg-background/70 px-3 py-2">
                                <div className="flex items-center justify-between gap-3 text-xs text-muted-foreground">
                                  <span>{t(`personality.generationStages.${generationStageKey}`)}</span>
                                  <span>{generationProgress}%</span>
                                </div>
                                <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                                  <div
                                    className="h-full rounded-full bg-primary transition-all duration-500"
                                    style={{ width: `${generationProgress}%` }}
                                  />
                                </div>
                              </div>
                            ) : null}
                          </div>
                        </motion.div>
                      )}

                      <AnimatePresence initial={false}>
                        {showCustomSection && showDetails && (
                          <motion.div
                            initial={{ height: 0, opacity: 0 }}
                            animate={{ height: 'auto', opacity: 1 }}
                            exit={{ height: 0, opacity: 0 }}
                            transition={{ duration: 0.2, ease: 'easeOut' }}
                            className="overflow-hidden rounded-xl border border-border bg-background"
                          >
                            {loadingConfig || !configLoaded ? (
                              <div className="flex items-center justify-center p-8">
                                <div className="h-5 w-5 animate-spin rounded-full border-2 border-primary border-t-transparent" />
                              </div>
                            ) : (
                              <div className="p-2.5">
                                <PersonalityDetailEditor
                                  config={config}
                                  patch={patch}
                                  t={t}
                                  onAvatarUpload={(e) => void handleAvatarUpload(e)}
                                  uploadingAvatar={uploadingAvatar}
                                  avatarFilename={avatarLabel(config.avatar)}
                                />
                              </div>
                            )}
                          </motion.div>
                        )}
                      </AnimatePresence>
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
            );
          }}
        </Form.Item>
      </Form.Item>

      {quickMode ? null : null}
    </>
  );
};

export default PersonalityForm;
