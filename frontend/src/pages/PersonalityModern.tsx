import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';
import { useTranslation } from 'react-i18next';
import {
  Check,
  Loader2,
  Plus,
  RefreshCw,
  Sparkles,
  Trash2,
  UserRound,
} from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import GuidedConfigFrame from '@/components/config-forms/GuidedConfigFrame';
import { cn } from '@/lib/utils';
import {
  personalityApi,
  DEFAULT_PERSONALITY_CONFIG,
  type PersonalityConfig,
  type PersonalityDiff,
  type StateTransitionProtocolItem,
} from '../api';

interface PersonalityInfo {
  name: string;
  displayName: string;
  subtitle?: string;
}

const CONFIDENCE_OPTIONS = ['Extremely High', 'High', 'Medium', 'Low'];

const sectionCardClass =
  'border-violet-500/18 bg-background/92 shadow-[0_16px_40px_-28px_rgba(124,58,237,0.45)] backdrop-blur';

const parseLines = (value: string): string[] =>
  value
    .split('\n')
    .map((item) => item.trim())
    .filter(Boolean);

const toLines = (items: string[]): string => items.join('\n');

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

const PersonalityModern: React.FC = () => {
  const { t } = useTranslation('app');
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [switching, setSwitching] = useState(false);
  const [currentName, setCurrentName] = useState('default');
  const [selectedName, setSelectedName] = useState('default');
  const [config, setConfig] = useState<PersonalityConfig>(DEFAULT_PERSONALITY_CONFIG);
  const [list, setList] = useState<PersonalityInfo[]>([
    { name: 'default', displayName: 'default', subtitle: 'System Default' },
  ]);
  const [prompt, setPrompt] = useState('');
  const [targetLanguage, setTargetLanguage] = useState('Auto');
  const [diffs, setDiffs] = useState<PersonalityDiff[]>([]);

  const patch = (fn: (draft: PersonalityConfig) => void) => {
    setConfig((prev) => {
      const next = structuredClone(prev);
      fn(next);
      return next;
    });
  };

  const loadList = useCallback(async () => {
    try {
      const result = await personalityApi.list();
      const names = ((result.data as any)?.personalities || ['default']) as string[];
      const items: PersonalityInfo[] = [];
      for (const name of names) {
        try {
          const detail = await personalityApi.get(name);
          const basicProfile = (detail.data as any)?.persona_entity?.basic_profile;
          items.push({
            name,
            displayName: basicProfile?.name || name,
            subtitle: basicProfile?.occupation,
          });
        } catch {
          items.push({ name, displayName: name });
        }
      }
      setList(items.length ? items : [{ name: 'default', displayName: 'default' }]);
    } catch {
      setList([{ name: 'default', displayName: 'default' }]);
    }
  }, []);

  const loadCurrent = useCallback(async () => {
    try {
      const result = await personalityApi.getCurrent();
      const current = (result.data as any)?.current || 'default';
      setCurrentName(current);
      setSelectedName(current);
      return current;
    } catch {
      setCurrentName('default');
      setSelectedName('default');
      return 'default';
    }
  }, []);

  const loadOne = useCallback(async (name: string) => {
    setLoading(true);
    try {
      const result = await personalityApi.get(name);
      const data = (result.data || {}) as Partial<PersonalityConfig>;
      setConfig(mergeConfig(data));
    } catch {
      toast.error(t('personality.loadFailed'));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    const init = async () => {
      const current = await loadCurrent();
      await loadList();
      await loadOne(current);
    };
    void init();
  }, [loadCurrent, loadList, loadOne]);

  const switchPersonality = async () => {
    if (selectedName === currentName) return;
    setSwitching(true);
    try {
      const response = await personalityApi.compare(currentName, selectedName);
      const nextDiffs = ((response.data as any)?.diffs || []) as PersonalityDiff[];
      setDiffs(nextDiffs);
      const ok = window.confirm(t('personality.switchConfirm', { from: currentName, to: selectedName }));
      if (!ok) return;
      await personalityApi.setCurrent(selectedName);
      setCurrentName(selectedName);
      await loadOne(selectedName);
      toast.success(t('personality.switchSuccess', { name: selectedName }));
    } catch {
      toast.error(t('personality.switchFailed'));
    } finally {
      setSwitching(false);
    }
  };

  const save = async () => {
    setSaving(true);
    try {
      if (currentName === 'default' || currentName !== config.persona_entity.basic_profile.name) {
        await personalityApi.updateWithAIName(config);
      } else {
        await personalityApi.update(currentName, config);
      }
      toast.success(t('personality.saveSuccess'));
      await loadList();
      await loadCurrent();
    } catch {
      toast.error(t('personality.saveFailed'));
    } finally {
      setSaving(false);
    }
  };

  const generate = async () => {
    if (!prompt.trim()) {
      toast.warning(t('personality.generatePromptRequired'));
      return;
    }
    setGenerating(true);
    try {
      const response = await personalityApi.generate({ description: prompt, target_language: targetLanguage });
      const data = (response.data || {}) as Partial<PersonalityConfig>;
      setConfig(mergeConfig(data));
      setPrompt('');
      toast.success(t('personality.generateSuccess'));
    } catch {
      toast.error(t('personality.generateFailed'));
    } finally {
      setGenerating(false);
    }
  };

  const createPersonality = () => {
    const name = window.prompt(t('personality.newNamePrompt'));
    if (!name) return;
    void personalityApi
      .updateWithAIName({
        ...DEFAULT_PERSONALITY_CONFIG,
        persona_entity: {
          ...DEFAULT_PERSONALITY_CONFIG.persona_entity,
          basic_profile: {
            ...DEFAULT_PERSONALITY_CONFIG.persona_entity.basic_profile,
            name,
          },
        },
      })
      .then(async () => {
        await loadList();
      });
  };

  const deletePersonality = () => {
    if (selectedName === 'default') return;
    if (!window.confirm(t('personality.deleteConfirm', { name: selectedName }))) return;
    void personalityApi.delete(selectedName).then(async () => {
      setDiffs([]);
      await loadList();
      const current = await loadCurrent();
      await loadOne(current);
    });
  };

  const selectedInfo = useMemo(
    () => list.find((item) => item.name === selectedName),
    [list, selectedName]
  );
  const diffPreview = useMemo(() => diffs.slice(0, 8), [diffs]);

  return (
    <div className="mx-auto h-full w-full max-w-6xl">
      <GuidedConfigFrame
        className="min-h-full"
        layoutClassName="min-h-[calc(88vh-4rem)]"
        sidebarClassName="lg:w-72"
        sidebar={(
          <div className="space-y-5">
            <div className="space-y-2">
              <p className="text-xs font-semibold uppercase tracking-[0.24em] text-violet-700/80">
                {t('settings.tabs.personality')}
              </p>
              <div>
                <h1 className="text-2xl font-semibold tracking-tight text-foreground">
                  {t('personality.title')}
                </h1>
                <p className="mt-1 text-sm leading-6 text-muted-foreground">
                  {t('settings.personalityDesc')}
                </p>
              </div>
            </div>

            <div className="rounded-2xl border border-violet-500/20 bg-background/70 p-4 shadow-[0_12px_30px_-24px_rgba(124,58,237,0.65)] backdrop-blur">
              <div className="mb-3 flex items-start justify-between gap-3">
                <div className="flex items-center gap-3">
                  <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-violet-500/12 text-violet-700">
                    <UserRound className="h-5 w-5" />
                  </div>
                  <div className="min-w-0">
                    <p className="text-xs font-medium uppercase tracking-[0.18em] text-violet-700/75">
                      {t('personality.current')}
                    </p>
                    <p className="truncate text-base font-semibold text-foreground">
                      {selectedInfo?.displayName || selectedName}
                    </p>
                  </div>
                </div>
                <Badge variant="secondary" className="border border-violet-500/20 bg-violet-500/10 text-violet-700">
                  {currentName}
                </Badge>
              </div>
              {selectedInfo?.subtitle ? (
                <p className="text-sm text-muted-foreground">{selectedInfo.subtitle}</p>
              ) : null}
            </div>

            <div className="space-y-2">
              <label className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                {t('personality.current')}
              </label>
              <select
                className="h-11 w-full rounded-2xl border border-violet-500/18 bg-background/90 px-4 text-sm shadow-sm outline-none transition focus:border-violet-500/55"
                value={selectedName}
                onChange={(event) => {
                  const nextName = event.target.value;
                  setSelectedName(nextName);
                  setDiffs([]);
                  void loadOne(nextName);
                }}
              >
                {list.map((item) => (
                  <option key={item.name} value={item.name}>
                    {item.displayName}{item.subtitle ? ` (${item.subtitle})` : ''}
                  </option>
                ))}
              </select>
            </div>

            <div className="grid gap-2">
              {selectedName !== currentName ? (
                <Button onClick={switchPersonality} disabled={switching} className="justify-start rounded-2xl">
                  <Check className="mr-2 h-4 w-4" />
                  {switching ? t('personality.switching') : t('personality.switch')}
                </Button>
              ) : null}
              <Button
                variant="outline"
                onClick={() => {
                  setDiffs([]);
                  void loadOne(selectedName);
                }}
                className="justify-start rounded-2xl border-violet-500/18 bg-background/80"
              >
                <RefreshCw className="mr-2 h-4 w-4" />
                {t('personality.reload')}
              </Button>
              <Button
                variant="outline"
                onClick={createPersonality}
                className="justify-start rounded-2xl border-violet-500/18 bg-background/80"
              >
                <Plus className="mr-2 h-4 w-4" />
                {t('personality.create')}
              </Button>
              <Button
                variant="outline"
                onClick={deletePersonality}
                disabled={selectedName === 'default'}
                className="justify-start rounded-2xl border-destructive/35 bg-background/80 text-destructive hover:bg-destructive/10 hover:text-destructive"
              >
                <Trash2 className="mr-2 h-4 w-4" />
                {t('personality.delete')}
              </Button>
            </div>

            {diffPreview.length > 0 ? (
              <div className="rounded-2xl border border-violet-500/16 bg-background/60 p-4">
                <p className="mb-3 text-sm font-semibold text-foreground">{t('personality.diffPreview')}</p>
                <div className="space-y-2 text-xs leading-5 text-muted-foreground">
                  {diffPreview.map((item) => (
                    <div key={item.field} className="rounded-xl border border-border/60 bg-muted/25 px-3 py-2">
                      <div className="font-medium text-foreground">{item.field_label}</div>
                      <div>
                        <span className="text-red-600">{String(item.old_value)}</span>
                        {' -> '}
                        <span className="text-emerald-600">{String(item.new_value)}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
          </div>
        )}
        footer={(
          <div className="flex justify-end">
            <Button onClick={save} disabled={saving || loading} size="lg" className="rounded-2xl px-6">
              <Check className="mr-2 h-4 w-4" />
              {saving ? t('personality.saving') : t('personality.save')}
            </Button>
          </div>
        )}
      >
        <div className="space-y-5">
          <div className="relative overflow-hidden rounded-[24px] border border-violet-500/28 bg-[radial-gradient(110%_140%_at_0%_0%,rgba(124,58,237,0.16)_0%,rgba(124,58,237,0.08)_28%,transparent_60%),linear-gradient(135deg,rgba(255,255,255,0.05),rgba(255,255,255,0.01))] p-5 shadow-[0_18px_48px_-26px_rgba(124,58,237,0.55)]">
            <div className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-violet-300 to-transparent" />
            <div className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
              <div className="max-w-2xl">
                <p className="text-xs font-semibold uppercase tracking-[0.22em] text-violet-700/80">
                  {t('personality.current')}
                </p>
                <h2 className="mt-2 text-2xl font-semibold tracking-tight text-foreground">
                  {config.persona_entity.basic_profile.name || selectedInfo?.displayName || t('personality.title')}
                </h2>
                <p className="mt-2 text-sm leading-6 text-muted-foreground">
                  {config.persona_entity.basic_profile.description || selectedInfo?.subtitle || t('settings.personalityDesc')}
                </p>
              </div>

              <div className="w-full max-w-2xl space-y-3">
                <div className="flex items-center gap-2 text-sm font-medium text-foreground">
                  <Sparkles className="h-4 w-4 text-violet-600" />
                  {t('personality.generate')}
                </div>
                <div className="flex flex-col gap-2 xl:flex-row">
                  <Input
                    value={prompt}
                    onChange={(event) => setPrompt(event.target.value)}
                    placeholder={t('personality.generatePlaceholder')}
                    className="h-11 rounded-2xl border-violet-500/20 bg-background/90"
                  />
                  <select
                    className="h-11 rounded-2xl border border-violet-500/20 bg-background/90 px-4 text-sm outline-none transition focus:border-violet-500/55"
                    value={targetLanguage}
                    onChange={(event) => setTargetLanguage(event.target.value)}
                  >
                    <option value="Auto">{t('personality.languages.auto')}</option>
                    <option value="Chinese">{t('personality.languages.chinese')}</option>
                    <option value="English">{t('personality.languages.english')}</option>
                    <option value="Japanese">{t('personality.languages.japanese')}</option>
                  </select>
                  <Button onClick={generate} disabled={generating} className="h-11 rounded-2xl px-5">
                    <Sparkles className="mr-2 h-4 w-4" />
                    {t('personality.generate')}
                  </Button>
                </div>
              </div>
            </div>
          </div>

          {loading ? (
            <div className="flex min-h-[360px] items-center justify-center rounded-[24px] border border-violet-500/18 bg-background/70">
              <Loader2 className="h-6 w-6 animate-spin text-violet-600" />
            </div>
          ) : (
            <>
              <Card className={sectionCardClass}>
                <CardHeader>
                  <CardTitle>{t('personality.sections.basicInfo')}</CardTitle>
                </CardHeader>
                <CardContent className="grid gap-4 md:grid-cols-3">
                  <label className="space-y-2">
                    <span className="text-sm font-medium">{t('personality.fields.name')}</span>
                    <Input
                      className="rounded-xl border-violet-500/18"
                      value={config.persona_entity.basic_profile.name}
                      onChange={(event) => patch((d) => { d.persona_entity.basic_profile.name = event.target.value; })}
                    />
                  </label>
                  <label className="space-y-2">
                    <span className="text-sm font-medium">{t('personality.fields.age')}</span>
                    <Input
                      className="rounded-xl border-violet-500/18"
                      value={config.persona_entity.basic_profile.age}
                      onChange={(event) => patch((d) => { d.persona_entity.basic_profile.age = event.target.value; })}
                    />
                  </label>
                  <label className="space-y-2">
                    <span className="text-sm font-medium">{t('personality.fields.gender')}</span>
                    <Input
                      className="rounded-xl border-violet-500/18"
                      value={config.persona_entity.basic_profile.gender}
                      onChange={(event) => patch((d) => { d.persona_entity.basic_profile.gender = event.target.value; })}
                    />
                  </label>
                  <label className="space-y-2 md:col-span-3">
                    <span className="text-sm font-medium">{t('personality.fields.occupation')}</span>
                    <Input
                      className="rounded-xl border-violet-500/18"
                      value={config.persona_entity.basic_profile.occupation}
                      onChange={(event) => patch((d) => { d.persona_entity.basic_profile.occupation = event.target.value; })}
                    />
                  </label>
                  <label className="space-y-2 md:col-span-3">
                    <span className="text-sm font-medium">{t('personality.fields.coreBackground')}</span>
                    <Textarea
                      rows={6}
                      className="rounded-xl border-violet-500/18"
                      value={config.persona_entity.basic_profile.core_background}
                      onChange={(event) => patch((d) => { d.persona_entity.basic_profile.core_background = event.target.value; })}
                    />
                  </label>
                </CardContent>
              </Card>

              <Card className={sectionCardClass}>
                <CardHeader>
                  <CardTitle>{t('personality.sections.psychologicalTraits')}</CardTitle>
                </CardHeader>
                <CardContent className="grid gap-4 md:grid-cols-2">
                  <label className="space-y-2">
                    <span className="text-sm font-medium">{t('personality.fields.communicationTone')}</span>
                    <Input
                      className="rounded-xl border-violet-500/18"
                      value={config.persona_entity.psychological_traits.communication_tone}
                      onChange={(event) => patch((d) => { d.persona_entity.psychological_traits.communication_tone = event.target.value; })}
                    />
                  </label>
                  <label className="space-y-2">
                    <span className="text-sm font-medium">{t('personality.fields.confidenceLevel')}</span>
                    <select
                      className="h-10 w-full rounded-xl border border-violet-500/18 bg-background px-3 text-sm outline-none transition focus:border-violet-500/55"
                      value={config.persona_entity.psychological_traits.confidence_level}
                      onChange={(event) => patch((d) => { d.persona_entity.psychological_traits.confidence_level = event.target.value; })}
                    >
                      {CONFIDENCE_OPTIONS.map((item) => <option key={item} value={item}>{item}</option>)}
                    </select>
                  </label>
                  <label className="space-y-2 md:col-span-2">
                    <span className="text-sm font-medium">{t('personality.fields.empathyThreshold')}</span>
                    <Input
                      className="rounded-xl border-violet-500/18"
                      value={config.persona_entity.psychological_traits.empathy_threshold}
                      onChange={(event) => patch((d) => { d.persona_entity.psychological_traits.empathy_threshold = event.target.value; })}
                    />
                  </label>
                  <label className="space-y-2 md:col-span-2">
                    <span className="text-sm font-medium">{t('personality.fields.highFrequencyKeywords')}</span>
                    <Input
                      className="rounded-xl border-violet-500/18"
                      value={config.persona_entity.psychological_traits.high_frequency_keywords.join(', ')}
                      onChange={(event) => patch((d) => {
                        d.persona_entity.psychological_traits.high_frequency_keywords = event.target.value
                          .split(',')
                          .map((item) => item.trim())
                          .filter(Boolean);
                      })}
                    />
                  </label>
                </CardContent>
              </Card>

              <div className="grid gap-5 xl:grid-cols-2">
                <Card className={sectionCardClass}>
                  <CardHeader>
                    <CardTitle>{t('personality.sections.socialResponses')}</CardTitle>
                  </CardHeader>
                  <CardContent className="grid gap-4">
                    <label className="space-y-2">
                      <span className="text-sm font-medium">{t('personality.fields.praiseReaction')}</span>
                      <Input
                        className="rounded-xl border-violet-500/18"
                        value={config.persona_entity.social_responses.praise_reaction}
                        onChange={(event) => patch((d) => { d.persona_entity.social_responses.praise_reaction = event.target.value; })}
                      />
                    </label>
                    <label className="space-y-2">
                      <span className="text-sm font-medium">{t('personality.fields.criticismReaction')}</span>
                      <Input
                        className="rounded-xl border-violet-500/18"
                        value={config.persona_entity.social_responses.criticism_reaction}
                        onChange={(event) => patch((d) => { d.persona_entity.social_responses.criticism_reaction = event.target.value; })}
                      />
                    </label>
                    <label className="space-y-2">
                      <span className="text-sm font-medium">{t('personality.fields.obedienceStrategy')}</span>
                      <Textarea
                        rows={4}
                        className="rounded-xl border-violet-500/18"
                        value={config.persona_entity.social_responses.obedience_strategy}
                        onChange={(event) => patch((d) => { d.persona_entity.social_responses.obedience_strategy = event.target.value; })}
                      />
                    </label>
                  </CardContent>
                </Card>

                <Card className={sectionCardClass}>
                  <CardHeader>
                    <CardTitle>{t('personality.sections.behavioralStrategies')}</CardTitle>
                  </CardHeader>
                  <CardContent className="grid gap-4">
                    <label className="space-y-2">
                      <span className="text-sm font-medium">{t('personality.fields.errorHandling')}</span>
                      <Textarea
                        rows={4}
                        className="rounded-xl border-violet-500/18"
                        value={config.persona_entity.behavioral_strategies.error_handling}
                        onChange={(event) => patch((d) => { d.persona_entity.behavioral_strategies.error_handling = event.target.value; })}
                      />
                    </label>
                    <label className="space-y-2">
                      <span className="text-sm font-medium">{t('personality.fields.refusalStyle')}</span>
                      <Textarea
                        rows={4}
                        className="rounded-xl border-violet-500/18"
                        value={config.persona_entity.behavioral_strategies.refusal_style}
                        onChange={(event) => patch((d) => { d.persona_entity.behavioral_strategies.refusal_style = event.target.value; })}
                      />
                    </label>
                  </CardContent>
                </Card>
              </div>

              <Card className={sectionCardClass}>
                <CardHeader>
                  <CardTitle>{t('personality.sections.cachedPhrases')}</CardTitle>
                </CardHeader>
                <CardContent className="grid gap-4 md:grid-cols-2">
                  <label className="space-y-2">
                    <span className="text-sm font-medium">{t('personality.fields.onInit')}</span>
                    <Textarea
                      rows={3}
                      className="rounded-xl border-violet-500/18"
                      value={toLines(config.cached_phrases.on_init)}
                      onChange={(event) => patch((d) => { d.cached_phrases.on_init = parseLines(event.target.value); })}
                    />
                  </label>
                  <label className="space-y-2">
                    <span className="text-sm font-medium">{t('personality.fields.onWake')}</span>
                    <Textarea
                      rows={3}
                      className="rounded-xl border-violet-500/18"
                      value={toLines(config.cached_phrases.on_wake)}
                      onChange={(event) => patch((d) => { d.cached_phrases.on_wake = parseLines(event.target.value); })}
                    />
                  </label>
                  <label className="space-y-2">
                    <span className="text-sm font-medium">{t('personality.fields.onError')}</span>
                    <Textarea
                      rows={3}
                      className="rounded-xl border-violet-500/18"
                      value={toLines(config.cached_phrases.on_error_generic)}
                      onChange={(event) => patch((d) => { d.cached_phrases.on_error_generic = parseLines(event.target.value); })}
                    />
                  </label>
                  <label className="space-y-2">
                    <span className="text-sm font-medium">{t('personality.fields.onSuccess')}</span>
                    <Textarea
                      rows={3}
                      className="rounded-xl border-violet-500/18"
                      value={toLines(config.cached_phrases.on_success)}
                      onChange={(event) => patch((d) => { d.cached_phrases.on_success = parseLines(event.target.value); })}
                    />
                  </label>
                  <label className="space-y-2 md:col-span-2">
                    <span className="text-sm font-medium">{t('personality.fields.onSwitchAttempt')}</span>
                    <Textarea
                      rows={3}
                      className="rounded-xl border-violet-500/18"
                      value={toLines(config.cached_phrases.on_switch_attempt)}
                      onChange={(event) => patch((d) => { d.cached_phrases.on_switch_attempt = parseLines(event.target.value); })}
                    />
                  </label>
                </CardContent>
              </Card>

              <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
                <Card className={sectionCardClass}>
                  <CardHeader>
                    <CardTitle>{t('personality.sections.appearance')}</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <label className="space-y-2">
                      <span className="text-sm font-medium">{t('personality.fields.appearancePrompt')}</span>
                      <Textarea
                        rows={8}
                        className="rounded-xl border-violet-500/18"
                        value={config.appearance_prompt}
                        onChange={(event) => patch((d) => { d.appearance_prompt = event.target.value; })}
                      />
                    </label>
                  </CardContent>
                </Card>

                <Card className={sectionCardClass}>
                  <CardHeader>
                    <CardTitle>{t('personality.sections.stateTransitionProtocol')}</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    {config.state_transition_protocol.map((item, index) => (
                      <div
                        key={`${index}-${item.target_state_name}`}
                        className={cn(
                          'rounded-2xl border border-violet-500/16 bg-muted/15 p-4',
                          config.state_transition_protocol.length > 1 && 'shadow-[0_8px_24px_-20px_rgba(124,58,237,0.55)]'
                        )}
                      >
                        <div className="mb-3 text-sm font-medium">{t('personality.fields.stateTransitionItem', { index: index + 1 })}</div>
                        <div className="grid gap-3">
                          <label className="space-y-1.5">
                            <span className="text-xs text-muted-foreground">{t('personality.fields.triggerCondition')}</span>
                            <Input
                              className="rounded-xl border-violet-500/18"
                              value={item.trigger_condition}
                              onChange={(event) => patch((d) => {
                                d.state_transition_protocol[index] = normalizeTransition({
                                  ...d.state_transition_protocol[index],
                                  trigger_condition: event.target.value,
                                });
                              })}
                            />
                          </label>
                          <label className="space-y-1.5">
                            <span className="text-xs text-muted-foreground">{t('personality.fields.targetStateName')}</span>
                            <Input
                              className="rounded-xl border-violet-500/18"
                              value={item.target_state_name}
                              onChange={(event) => patch((d) => {
                                d.state_transition_protocol[index] = normalizeTransition({
                                  ...d.state_transition_protocol[index],
                                  target_state_name: event.target.value,
                                });
                              })}
                            />
                          </label>
                          <label className="space-y-1.5">
                            <span className="text-xs text-muted-foreground">{t('personality.fields.behaviorShift')}</span>
                            <Textarea
                              rows={3}
                              className="rounded-xl border-violet-500/18"
                              value={item.behavior_shift}
                              onChange={(event) => patch((d) => {
                                d.state_transition_protocol[index] = normalizeTransition({
                                  ...d.state_transition_protocol[index],
                                  behavior_shift: event.target.value,
                                });
                              })}
                            />
                          </label>
                          <div className="flex justify-end">
                            <Button
                              variant="outline"
                              onClick={() => patch((d) => {
                                if (d.state_transition_protocol.length === 1) return;
                                d.state_transition_protocol.splice(index, 1);
                              })}
                              disabled={config.state_transition_protocol.length === 1}
                              className="rounded-xl border-violet-500/18 bg-background/85"
                            >
                              {t('personality.actions.removeTransition')}
                            </Button>
                          </div>
                        </div>
                      </div>
                    ))}

                    <Button
                      variant="outline"
                      onClick={() => patch((d) => {
                        d.state_transition_protocol.push(normalizeTransition({}));
                      })}
                      className="rounded-xl border-violet-500/18 bg-background/85"
                    >
                      {t('personality.actions.addTransition')}
                    </Button>
                  </CardContent>
                </Card>
              </div>
            </>
          )}
        </div>
      </GuidedConfigFrame>
    </div>
  );
};

export default PersonalityModern;
