import React, { useEffect, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { ArrowLeft, ChevronRight, PencilLine, Plus, Sparkles, Trash2, Upload } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';
import { SimpleForm as Form } from '../onboarding/simple-form';
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from '@/components/ui/collapsible';
import { AutoResizeTextarea } from '@/components/ui/auto-resize-textarea';
import {
  DEFAULT_PERSONALITY_CONFIG,
  personalityApi,
  personalitiesApi,
  PersonalityPreset,
  PersonalityConfig,
  type StateTransitionProtocolItem,
} from '../../api';

interface PersonalityFormProps {
  quickMode?: boolean;
  language?: 'zh' | 'en';
}

// 分组显示顺序
const GROUP_ORDER = ['magi', 'general'];

type CachedPhraseKey = 'on_init' | 'on_wake' | 'on_error_generic' | 'on_success' | 'on_switch_attempt';

const normalizePhraseList = (items: string[] = []): string[] => (items.length > 0 ? items : ['']);

const normalizeTransition = (item: Partial<StateTransitionProtocolItem>): StateTransitionProtocolItem => ({
  trigger_type: item.trigger_type || '',
  trigger_condition: item.trigger_condition || '',
  target_state_name: item.target_state_name || '',
  behavior_shift: item.behavior_shift || '',
});

const mergeConfig = (incoming: Partial<PersonalityConfig>): PersonalityConfig => {
  const next = structuredClone(DEFAULT_PERSONALITY_CONFIG);
  next.persona_entity.basic_profile = {
    ...next.persona_entity.basic_profile,
    ...(incoming.persona_entity?.basic_profile || {}),
  };
  next.persona_entity.psychological_traits = {
    ...next.persona_entity.psychological_traits,
    ...(incoming.persona_entity?.psychological_traits || {}),
  };
  next.persona_entity.social_responses = {
    ...next.persona_entity.social_responses,
    ...(incoming.persona_entity?.social_responses || {}),
  };
  next.persona_entity.behavioral_strategies = {
    ...next.persona_entity.behavioral_strategies,
    ...(incoming.persona_entity?.behavioral_strategies || {}),
  };
  next.cached_phrases = {
    ...next.cached_phrases,
    ...(incoming.cached_phrases || {}),
  };
  next.appearance_prompt = incoming.appearance_prompt || next.appearance_prompt;
  const transitions = incoming.state_transition_protocol || next.state_transition_protocol;
  next.state_transition_protocol = transitions.length > 0 ? transitions.map(normalizeTransition) : [normalizeTransition({})];
  return next;
};

export const PersonalityForm: React.FC<PersonalityFormProps> = ({ quickMode = false, language = 'zh' }) => {
  const { t } = useTranslation('onboarding');
  const [presets, setPresets] = useState<PersonalityPreset[]>([]);
  const [generating, setGenerating] = useState(false);
  const [oneLiner, setOneLiner] = useState('');
  const [viewMode, setViewMode] = useState<'selection' | 'focus'>('selection');
  const [showDetails, setShowDetails] = useState(false);
  const [uploadingAvatar, setUploadingAvatar] = useState(false);
  const [expandedCardId, setExpandedCardId] = useState<string | null>(null);
  const [config, setConfig] = useState<PersonalityConfig>(DEFAULT_PERSONALITY_CONFIG);
  const [loadingConfig, setLoadingConfig] = useState(false);
  const [configLoaded, setConfigLoaded] = useState(false); // Track if config has been loaded
  const [brokenAvatarKeys, setBrokenAvatarKeys] = useState<Record<string, boolean>>({});

  useEffect(() => {
    const loadPresets = async () => {
      try {
        const response = await personalitiesApi.list(language);
        setPresets(response.data || []);
      } catch (error) {
        setPresets([]);
      }
    };
    void loadPresets();
  }, [language]);

  const avatarFor = (item: PersonalityPreset): string => {
    const map: Record<string, string> = {
      assistant: '🤖',
      analyst: '🧠',
      teacher: '🧑‍🏫',
      coder: '💻',
      writer: '✍️',
      default: '✨',
    };
    return map[item.id] || item.name.trim().charAt(0).toUpperCase() || '✨';
  };

  const patch = (fn: (draft: PersonalityConfig) => void) => {
    setConfig((prev) => {
      const next = structuredClone(prev);
      fn(next);
      return next;
    });
  };

  const updatePhraseItem = (key: CachedPhraseKey, index: number, value: string) => {
    patch((d) => {
      const next = normalizePhraseList(d.cached_phrases[key]);
      next[index] = value;
      d.cached_phrases[key] = next;
    });
  };

  const addPhraseItem = (key: CachedPhraseKey) => {
    patch((d) => {
      const next = normalizePhraseList(d.cached_phrases[key]);
      next.push('');
      d.cached_phrases[key] = next;
    });
  };

  const removePhraseItem = (key: CachedPhraseKey, index: number) => {
    patch((d) => {
      const next = normalizePhraseList(d.cached_phrases[key]);
      if (next.length <= 1) {
        next[0] = '';
        d.cached_phrases[key] = next;
        return;
      }
      next.splice(index, 1);
      d.cached_phrases[key] = next;
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

  const resolveAvatarUrl = (avatar?: string): string => personalitiesApi.getAvatarUrl(avatar || '');

  const handleAvatarUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    setUploadingAvatar(true);
    try {
      const response = await personalitiesApi.uploadAvatar(file);
      const filename = response.data?.filename;
      if (!filename) return;
      patch((d) => {
        d.persona_entity.basic_profile.avatar = filename;
      });
      resetAvatarBroken(`focus:${filename}`);
    } finally {
      setUploadingAvatar(false);
      event.target.value = '';
    }
  };

  const handleSelectPreset = async (
    item: PersonalityPreset,
    setFieldValue: (name: any, value: any) => void
  ) => {
    setViewMode('focus');
    setShowDetails(false);
    // 先设置加载状态，然后设置选中状态
    setLoadingConfig(true);
    setConfigLoaded(false);

    try {
      // 从预设 API 获取完整配置
      const result = await personalitiesApi.get(item.id, language);
      const data = (result.data || {}) as Partial<PersonalityConfig>;
      const mergedConfig = mergeConfig(data);
      setConfig(mergedConfig);
      // 将完整的人格配置设置到表单
      setFieldValue(['personality'], mergedConfig);
    } catch {
      setConfig(DEFAULT_PERSONALITY_CONFIG);
      setFieldValue(['personality'], DEFAULT_PERSONALITY_CONFIG);
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
    // 将默认人格配置设置到表单
    setFieldValue(['personality'], DEFAULT_PERSONALITY_CONFIG);
    setOneLiner('');
  };

  const handleGenerate = async (setFieldValue: (name: any, value: any) => void) => {
    if (!oneLiner.trim()) return;
    setGenerating(true);
    try {
      const generated = await personalityApi.generate({
        description: oneLiner.trim(),
        target_language: language === 'zh' ? 'Chinese' : 'English',
      });
      const data = (generated.data || {}) as Partial<PersonalityConfig>;
      const mergedConfig = mergeConfig(data);
      setConfig(mergedConfig);
      // 将完整的人格配置设置到表单
      setFieldValue(['personality'], mergedConfig);
    } catch {
      // Ignore generate errors
    } finally {
      setGenerating(false);
    }
  };

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
            const selectedPreset = personalityValue?.persona_entity?.basic_profile?.name;
            const isCustomSelected = !selectedPreset || selectedPreset === 'AI Assistant';
            const showCustomSection = viewMode === 'focus';
            const focusedPreset = presets.find((item) => item.name === selectedPreset);
            const focusTitle = isCustomSelected && !focusedPreset
              ? t('personality.blankCardTitle')
              : config.persona_entity.basic_profile.name || selectedPreset;
            const focusAvatar = config.persona_entity.basic_profile.avatar || focusedPreset?.avatar || '';
            const focusSubtitle = isCustomSelected && !focusedPreset
              ? t('personality.blankCardDesc')
              : config.persona_entity.basic_profile.description || focusedPreset?.description || '';
            const focusDescription = isCustomSelected
              ? t('personality.blankCardDesc')
              : config.persona_entity.basic_profile.core_background || focusedPreset?.prompt || focusedPreset?.description || '';

            // 按后端返回的 group 字段分组
            const groupedPersonalities = GROUP_ORDER.reduce((acc, group) => {
              const items = presets.filter((p) => p.group === group);
              if (items.length > 0) {
                acc.push({ group, items });
              }
              return acc;
            }, [] as Array<{ group: string; items: PersonalityPreset[] }>);

            const renderPersonalityCard = (item: PersonalityPreset) => {
              const active = selectedPreset === item.name;
              const expanded = expandedCardId === item.id;
              return (
                <div key={item.id} className="relative">
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
                      <div className="flex h-12 w-12 shrink-0 items-center justify-center overflow-hidden rounded-full border border-primary/20 bg-primary/10 text-xl">
                        {item.avatar && !brokenAvatarKeys[`list:${item.id}:${item.avatar}`] ? (
                          <img
                            src={resolveAvatarUrl(item.avatar)}
                            alt={item.name}
                            className="h-full w-full object-cover"
                            onError={() => markAvatarBroken(`list:${item.id}:${item.avatar}`)}
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
                          setExpandedCardId(expanded ? null : item.id);
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
                    <p className="mt-2 line-clamp-2 text-sm text-muted-foreground">{item.prompt || item.description}</p>
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
                          <p className="line-clamp-4">{item.prompt || item.description}</p>
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
                      {/* 动态分组显示 */}
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

                      {/* 自定义人格 */}
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
                                <div className="flex h-16 w-16 shrink-0 items-center justify-center rounded-full bg-primary/10 text-2xl">
                                  {isCustomSelected ? (
                                    <Sparkles className="h-7 w-7 text-primary" />
                                  ) : focusAvatar && !brokenAvatarKeys[`focus:${focusAvatar}`] ? (
                                    <img
                                      src={resolveAvatarUrl(focusAvatar)}
                                      alt={focusTitle}
                                      className="h-full w-full rounded-full object-cover"
                                      onError={() => markAvatarBroken(`focus:${focusAvatar}`)}
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
                                onClick={() => void handleGenerate(setFieldValue)}
                              >
                                {generating ? t('personality.generating') : t('personality.generateAction')}
                              </Button>
                            </div>
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
                              <div className="max-h-[50vh] overflow-y-auto p-2.5">
                                <div className="space-y-0.5 pr-1">
                        {/* Basic Profile */}
                        <Collapsible
                          className="space-y-1"
                          defaultOpen
                        >
                          <CollapsibleTrigger className="rounded-md px-2 py-1.5 text-sm font-medium hover:bg-muted">
                            {t('personality.sections.basicProfile')}
                          </CollapsibleTrigger>
                          <CollapsibleContent className="pt-2">
                            <div className="grid gap-3 md:grid-cols-3">
                              <label className="space-y-1.5">
                                <span className="text-xs font-medium text-muted-foreground">{t('personality.fields.name')}</span>
                                <Input
                                  value={config.persona_entity.basic_profile.name}
                                  onChange={(e) => patch((d) => { d.persona_entity.basic_profile.name = e.target.value; })}
                                />
                              </label>
                              <label className="space-y-1.5">
                                <span className="text-xs font-medium text-muted-foreground">{t('personality.fields.age')}</span>
                                <Input
                                  value={config.persona_entity.basic_profile.age}
                                  onChange={(e) => patch((d) => { d.persona_entity.basic_profile.age = e.target.value; })}
                                />
                              </label>
                              <label className="space-y-1.5">
                                <span className="text-xs font-medium text-muted-foreground">{t('personality.fields.gender')}</span>
                                <Input
                                  value={config.persona_entity.basic_profile.gender}
                                  onChange={(e) => patch((d) => { d.persona_entity.basic_profile.gender = e.target.value; })}
                                />
                              </label>
                              <label className="space-y-1.5 md:col-span-3">
                                <span className="text-xs font-medium text-muted-foreground">{t('personality.fields.description')}</span>
                                <Input
                                  value={config.persona_entity.basic_profile.description}
                                  onChange={(e) => patch((d) => { d.persona_entity.basic_profile.description = e.target.value; })}
                                />
                              </label>
                              <label className="space-y-1.5 md:col-span-3">
                                <span className="text-xs font-medium text-muted-foreground">{t('personality.fields.avatar')}</span>
                                <div className="flex flex-wrap items-center gap-2">
                                  <input
                                    id="personality-avatar-upload"
                                    type="file"
                                    accept="image/png,image/jpeg,image/webp"
                                    className="hidden"
                                    onChange={(e) => void handleAvatarUpload(e)}
                                  />
                                  <Button
                                    type="button"
                                    variant="outline"
                                    size="sm"
                                    disabled={uploadingAvatar}
                                    onClick={() => {
                                      const node = document.getElementById('personality-avatar-upload') as HTMLInputElement | null;
                                      node?.click();
                                    }}
                                  >
                                    <Upload className="h-4 w-4" />
                                    {uploadingAvatar ? t('personality.actions.uploadingAvatar') : t('personality.actions.uploadAvatar')}
                                  </Button>
                                  {config.persona_entity.basic_profile.avatar ? (
                                    <span className="text-xs text-muted-foreground">{config.persona_entity.basic_profile.avatar}</span>
                                  ) : (
                                    <span className="text-xs text-muted-foreground">{t('personality.noAvatar')}</span>
                                  )}
                                </div>
                              </label>
                              <label className="space-y-1.5 md:col-span-3">
                                <span className="text-xs font-medium text-muted-foreground">{t('personality.fields.occupation')}</span>
                                <Input
                                  value={config.persona_entity.basic_profile.occupation}
                                  onChange={(e) => patch((d) => { d.persona_entity.basic_profile.occupation = e.target.value; })}
                                />
                              </label>
                              <label className="space-y-1.5 md:col-span-3">
                                <span className="text-xs font-medium text-muted-foreground">{t('personality.fields.coreBackground')}</span>
                                <AutoResizeTextarea
                                  value={config.persona_entity.basic_profile.core_background}
                                  minHeight={120}
                                  className="w-full"
                                  onChange={(e) => patch((d) => { d.persona_entity.basic_profile.core_background = e.target.value; })}
                                />
                              </label>
                            </div>
                          </CollapsibleContent>
                        </Collapsible>

                        {/* Psychological Traits */}
                        <Collapsible
                          className="space-y-1"
                          defaultOpen
                        >
                          <CollapsibleTrigger className="rounded-md px-2 py-1.5 text-sm font-medium hover:bg-muted">
                            {t('personality.sections.psychologicalTraits')}
                          </CollapsibleTrigger>
                          <CollapsibleContent className="pt-2">
                            <div className="grid gap-3 md:grid-cols-2">
                              <label className="space-y-1.5">
                                <span className="text-xs font-medium text-muted-foreground">{t('personality.fields.communicationTone')}</span>
                                <Input
                                  value={config.persona_entity.psychological_traits.communication_tone}
                                  onChange={(e) => patch((d) => { d.persona_entity.psychological_traits.communication_tone = e.target.value; })}
                                />
                              </label>
                              <label className="space-y-1.5">
                                <span className="text-xs font-medium text-muted-foreground">{t('personality.fields.confidenceLevel')}</span>
                                <Input
                                  value={config.persona_entity.psychological_traits.confidence_level}
                                  onChange={(e) => patch((d) => { d.persona_entity.psychological_traits.confidence_level = e.target.value; })}
                                />
                              </label>
                              <label className="space-y-1.5">
                                <span className="text-xs font-medium text-muted-foreground">{t('personality.fields.empathyThreshold')}</span>
                                <Input
                                  value={config.persona_entity.psychological_traits.empathy_threshold}
                                  onChange={(e) => patch((d) => { d.persona_entity.psychological_traits.empathy_threshold = e.target.value; })}
                                />
                              </label>
                              <label className="space-y-1.5">
                                <span className="text-xs font-medium text-muted-foreground">{t('personality.fields.highFrequencyKeywords')}</span>
                                <Input
                                  value={config.persona_entity.psychological_traits.high_frequency_keywords.join(', ')}
                                  onChange={(e) => patch((d) => {
                                    d.persona_entity.psychological_traits.high_frequency_keywords = e.target.value
                                      .split(',')
                                      .map((s) => s.trim())
                                      .filter(Boolean);
                                  })}
                                />
                              </label>
                            </div>
                          </CollapsibleContent>
                        </Collapsible>

                        {/* Social Responses */}
                        <Collapsible className="space-y-1">
                          <CollapsibleTrigger className="rounded-md px-2 py-1.5 text-sm font-medium hover:bg-muted">
                            {t('personality.sections.socialResponses')}
                          </CollapsibleTrigger>
                          <CollapsibleContent className="pt-2">
                            <div className="grid gap-3 md:grid-cols-2">
                              <label className="space-y-1.5">
                                <span className="text-xs font-medium text-muted-foreground">{t('personality.fields.praiseReaction')}</span>
                                <Input
                                  value={config.persona_entity.social_responses.praise_reaction}
                                  onChange={(e) => patch((d) => { d.persona_entity.social_responses.praise_reaction = e.target.value; })}
                                />
                              </label>
                              <label className="space-y-1.5">
                                <span className="text-xs font-medium text-muted-foreground">{t('personality.fields.criticismReaction')}</span>
                                <Input
                                  value={config.persona_entity.social_responses.criticism_reaction}
                                  onChange={(e) => patch((d) => { d.persona_entity.social_responses.criticism_reaction = e.target.value; })}
                                />
                              </label>
                              <label className="space-y-1.5 md:col-span-2">
                                <span className="text-xs font-medium text-muted-foreground">{t('personality.fields.obedienceStrategy')}</span>
                                <AutoResizeTextarea
                                  value={config.persona_entity.social_responses.obedience_strategy}
                                  onChange={(e) => patch((d) => { d.persona_entity.social_responses.obedience_strategy = e.target.value; })}
                                />
                              </label>
                            </div>
                          </CollapsibleContent>
                        </Collapsible>

                        {/* Behavioral Strategies */}
                        <Collapsible className="space-y-1">
                          <CollapsibleTrigger className="rounded-md px-2 py-1.5 text-sm font-medium hover:bg-muted">
                            {t('personality.sections.behavioralStrategies')}
                          </CollapsibleTrigger>
                          <CollapsibleContent className="pt-2">
                            <div className="grid gap-3">
                              <label className="space-y-1.5">
                                <span className="text-xs font-medium text-muted-foreground">{t('personality.fields.errorHandling')}</span>
                                <AutoResizeTextarea
                                  value={config.persona_entity.behavioral_strategies.error_handling}
                                  onChange={(e) => patch((d) => { d.persona_entity.behavioral_strategies.error_handling = e.target.value; })}
                                />
                              </label>
                              <label className="space-y-1.5">
                                <span className="text-xs font-medium text-muted-foreground">{t('personality.fields.refusalStyle')}</span>
                                <AutoResizeTextarea
                                  value={config.persona_entity.behavioral_strategies.refusal_style}
                                  onChange={(e) => patch((d) => { d.persona_entity.behavioral_strategies.refusal_style = e.target.value; })}
                                />
                              </label>
                            </div>
                          </CollapsibleContent>
                        </Collapsible>

                        {/* Cached Phrases */}
                        <Collapsible className="space-y-1">
                          <CollapsibleTrigger className="rounded-md px-2 py-1.5 text-sm font-medium hover:bg-muted">
                            {t('personality.sections.cachedPhrases')}
                          </CollapsibleTrigger>
                          <CollapsibleContent className="pt-2">
                            <p className="mb-2 text-xs text-muted-foreground">{t('personality.arrayHint')}</p>
                            <div className="grid gap-3 md:grid-cols-2">
                              {[
                                { key: 'on_init', label: t('personality.fields.onInit') },
                                { key: 'on_wake', label: t('personality.fields.onWake') },
                                { key: 'on_error_generic', label: t('personality.fields.onError') },
                                { key: 'on_success', label: t('personality.fields.onSuccess') },
                                { key: 'on_switch_attempt', label: t('personality.fields.onSwitchAttempt'), full: true },
                              ].map((field) => {
                                const values = normalizePhraseList(config.cached_phrases[field.key as CachedPhraseKey]);
                                return (
                                  <div key={field.key} className={cn('space-y-2', field.full && 'md:col-span-2')}>
                                    <div className="flex items-center justify-between">
                                      <span className="text-xs font-medium text-muted-foreground">{field.label}</span>
                                      <Button
                                        type="button"
                                        variant="outline"
                                        size="sm"
                                        onClick={() => addPhraseItem(field.key as CachedPhraseKey)}
                                      >
                                        <Plus className="h-3.5 w-3.5" />
                                        {t('personality.actions.addItem')}
                                      </Button>
                                    </div>
                                    <div className="space-y-2 rounded-md border border-border/60 bg-muted/10 p-2">
                                      {values.map((value, index) => (
                                        <div key={`${field.key}-${index}`} className="flex items-start gap-2">
                                          <AutoResizeTextarea
                                            value={value}
                                            minHeight={56}
                                            className="w-full"
                                            onChange={(e) => updatePhraseItem(field.key as CachedPhraseKey, index, e.target.value)}
                                          />
                                          <Button
                                            type="button"
                                            variant="outline"
                                            size="icon"
                                            onClick={() => removePhraseItem(field.key as CachedPhraseKey, index)}
                                            disabled={values.length <= 1}
                                            aria-label={t('personality.actions.removeItem')}
                                          >
                                            <Trash2 className="h-4 w-4" />
                                          </Button>
                                        </div>
                                      ))}
                                    </div>
                                  </div>
                                );
                              })}
                            </div>
                          </CollapsibleContent>
                        </Collapsible>

                        {/* Appearance Prompt */}
                        <Collapsible className="space-y-1">
                          <CollapsibleTrigger className="rounded-md px-2 py-1.5 text-sm font-medium hover:bg-muted">
                            {t('personality.sections.appearance')}
                          </CollapsibleTrigger>
                          <CollapsibleContent className="pt-2">
                            <label className="space-y-1.5">
                              <span className="text-xs font-medium text-muted-foreground">{t('personality.fields.appearancePrompt')}</span>
                              <AutoResizeTextarea
                                value={config.appearance_prompt}
                                onChange={(e) => patch((d) => { d.appearance_prompt = e.target.value; })}
                              />
                            </label>
                          </CollapsibleContent>
                        </Collapsible>

                        {/* State Transition Protocol */}
                        <Collapsible className="space-y-1">
                          <CollapsibleTrigger className="rounded-md px-2 py-1.5 text-sm font-medium hover:bg-muted">
                            {t('personality.sections.stateTransitionProtocol')}
                          </CollapsibleTrigger>
                          <CollapsibleContent className="pt-2">
                            <div className="space-y-3">
                              {config.state_transition_protocol.map((item, index) => (
                                <div key={index} className="rounded-md border border-border/70 p-2">
                                  <div className="grid gap-2">
                                    <label className="space-y-1">
                                      <span className="text-xs text-muted-foreground">{t('personality.fields.triggerCondition')}</span>
                                      <Input
                                        value={item.trigger_condition}
                                        onChange={(e) => patch((d) => {
                                          d.state_transition_protocol[index] = normalizeTransition({
                                            ...d.state_transition_protocol[index],
                                            trigger_condition: e.target.value,
                                          });
                                        })}
                                      />
                                    </label>
                                    <label className="space-y-1">
                                      <span className="text-xs text-muted-foreground">{t('personality.fields.targetStateName')}</span>
                                      <Input
                                        value={item.target_state_name}
                                        onChange={(e) => patch((d) => {
                                          d.state_transition_protocol[index] = normalizeTransition({
                                            ...d.state_transition_protocol[index],
                                            target_state_name: e.target.value,
                                          });
                                        })}
                                      />
                                    </label>
                                    <label className="space-y-1">
                                      <span className="text-xs text-muted-foreground">{t('personality.fields.behaviorShift')}</span>
                                      <AutoResizeTextarea
                                        value={item.behavior_shift}
                                        minHeight={96}
                                        className="w-full"
                                        onChange={(e) => patch((d) => {
                                          d.state_transition_protocol[index] = normalizeTransition({
                                            ...d.state_transition_protocol[index],
                                            behavior_shift: e.target.value,
                                          });
                                        })}
                                      />
                                    </label>
                                  </div>
                                </div>
                              ))}
                              <Button
                                type="button"
                                variant="outline"
                                size="sm"
                                onClick={() => patch((d) => {
                                  d.state_transition_protocol.push(normalizeTransition({}));
                                })}
                              >
                                {t('personality.actions.addTransition')}
                              </Button>
                            </div>
                          </CollapsibleContent>
                        </Collapsible>
                                </div>
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
