import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';
import { useTranslation } from 'react-i18next';
import { Check, Plus, RefreshCw, Sparkles, Trash2 } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
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

  const diffPreview = useMemo(() => diffs.slice(0, 8), [diffs]);

  return (
    <div className="mx-auto max-w-6xl space-y-4 p-6">
      <Card>
        <CardHeader>
          <CardTitle>{t('personality.title')}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm text-muted-foreground">{t('personality.current')}</span>
            <Badge>{currentName}</Badge>
            <select
              className="h-10 min-w-[220px] rounded-md border border-input bg-background px-3 text-sm"
              value={selectedName}
              onChange={(event) => {
                setSelectedName(event.target.value);
                void loadOne(event.target.value);
              }}
            >
              {list.map((item) => (
                <option key={item.name} value={item.name}>
                  {item.displayName}{item.subtitle ? ` (${item.subtitle})` : ''}
                </option>
              ))}
            </select>
            {selectedName !== currentName && (
              <Button onClick={switchPersonality} disabled={switching}>
                <Check className="mr-2 h-4 w-4" />
                {switching ? t('personality.switching') : t('personality.switch')}
              </Button>
            )}
            <Button variant="outline" onClick={() => void loadOne(selectedName)}><RefreshCw className="mr-2 h-4 w-4" />{t('personality.reload')}</Button>
            <Button variant="outline" onClick={() => {
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
                .then(loadList);
            }}><Plus className="mr-2 h-4 w-4" />{t('personality.create')}</Button>
            <Button variant="destructive" onClick={() => {
              if (selectedName === 'default') return;
              if (window.confirm(t('personality.deleteConfirm', { name: selectedName }))) void personalityApi.delete(selectedName).then(loadList);
            }}><Trash2 className="mr-2 h-4 w-4" />{t('personality.delete')}</Button>
          </div>

          <div className="flex gap-2">
            <Input value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder={t('personality.generatePlaceholder')} />
            <select
              className="h-10 rounded-md border border-input bg-background px-3 text-sm"
              value={targetLanguage}
              onChange={(event) => setTargetLanguage(event.target.value)}
            >
              <option value="Auto">{t('personality.languages.auto')}</option>
              <option value="Chinese">{t('personality.languages.chinese')}</option>
              <option value="English">{t('personality.languages.english')}</option>
              <option value="Japanese">{t('personality.languages.japanese')}</option>
            </select>
            <Button onClick={generate} disabled={generating}><Sparkles className="mr-2 h-4 w-4" />{t('personality.generate')}</Button>
          </div>

          {diffPreview.length > 0 && (
            <div className="rounded-md border p-3">
              <div className="mb-2 text-sm font-medium">{t('personality.diffPreview')}</div>
              <div className="space-y-1 text-xs text-muted-foreground">
                {diffPreview.map((item) => (
                  <div key={item.field}>
                    {item.field_label}: <span className="text-red-600">{String(item.old_value)}</span> {'->'}{' '}
                    <span className="text-emerald-600">{String(item.new_value)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>{t('personality.sections.basicInfo')}</CardTitle></CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-3">
          <label className="space-y-2">
            <span className="text-sm font-medium">{t('personality.fields.name')}</span>
            <Input value={config.persona_entity.basic_profile.name} onChange={(event) => patch((d) => { d.persona_entity.basic_profile.name = event.target.value; })} />
          </label>
          <label className="space-y-2">
            <span className="text-sm font-medium">{t('personality.fields.age')}</span>
            <Input value={config.persona_entity.basic_profile.age} onChange={(event) => patch((d) => { d.persona_entity.basic_profile.age = event.target.value; })} />
          </label>
          <label className="space-y-2">
            <span className="text-sm font-medium">{t('personality.fields.gender')}</span>
            <Input value={config.persona_entity.basic_profile.gender} onChange={(event) => patch((d) => { d.persona_entity.basic_profile.gender = event.target.value; })} />
          </label>
          <label className="space-y-2 md:col-span-3">
            <span className="text-sm font-medium">{t('personality.fields.occupation')}</span>
            <Input value={config.persona_entity.basic_profile.occupation} onChange={(event) => patch((d) => { d.persona_entity.basic_profile.occupation = event.target.value; })} />
          </label>
          <label className="space-y-2 md:col-span-3">
            <span className="text-sm font-medium">{t('personality.fields.coreBackground')}</span>
            <Textarea
              rows={6}
              value={config.persona_entity.basic_profile.core_background}
              onChange={(event) => patch((d) => { d.persona_entity.basic_profile.core_background = event.target.value; })}
            />
          </label>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>{t('personality.sections.psychologicalTraits')}</CardTitle></CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-2">
          <label className="space-y-2">
            <span className="text-sm font-medium">{t('personality.fields.communicationTone')}</span>
            <Input
              value={config.persona_entity.psychological_traits.communication_tone}
              onChange={(event) => patch((d) => { d.persona_entity.psychological_traits.communication_tone = event.target.value; })}
            />
          </label>
          <label className="space-y-2">
            <span className="text-sm font-medium">{t('personality.fields.confidenceLevel')}</span>
            <select
              className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
              value={config.persona_entity.psychological_traits.confidence_level}
              onChange={(event) => patch((d) => { d.persona_entity.psychological_traits.confidence_level = event.target.value; })}
            >
              {CONFIDENCE_OPTIONS.map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
          </label>
          <label className="space-y-2 md:col-span-2">
            <span className="text-sm font-medium">{t('personality.fields.empathyThreshold')}</span>
            <Input
              value={config.persona_entity.psychological_traits.empathy_threshold}
              onChange={(event) => patch((d) => { d.persona_entity.psychological_traits.empathy_threshold = event.target.value; })}
            />
          </label>
          <label className="space-y-2 md:col-span-2">
            <span className="text-sm font-medium">{t('personality.fields.highFrequencyKeywords')}</span>
            <Input
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

      <Card>
        <CardHeader><CardTitle>{t('personality.sections.socialResponses')}</CardTitle></CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-2">
          <label className="space-y-2">
            <span className="text-sm font-medium">{t('personality.fields.praiseReaction')}</span>
            <Input
              value={config.persona_entity.social_responses.praise_reaction}
              onChange={(event) => patch((d) => { d.persona_entity.social_responses.praise_reaction = event.target.value; })}
            />
          </label>
          <label className="space-y-2">
            <span className="text-sm font-medium">{t('personality.fields.criticismReaction')}</span>
            <Input
              value={config.persona_entity.social_responses.criticism_reaction}
              onChange={(event) => patch((d) => { d.persona_entity.social_responses.criticism_reaction = event.target.value; })}
            />
          </label>
          <label className="space-y-2 md:col-span-2">
            <span className="text-sm font-medium">{t('personality.fields.obedienceStrategy')}</span>
            <Textarea
              rows={3}
              value={config.persona_entity.social_responses.obedience_strategy}
              onChange={(event) => patch((d) => { d.persona_entity.social_responses.obedience_strategy = event.target.value; })}
            />
          </label>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>{t('personality.sections.behavioralStrategies')}</CardTitle></CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-1">
          <label className="space-y-2">
            <span className="text-sm font-medium">{t('personality.fields.errorHandling')}</span>
            <Textarea
              rows={3}
              value={config.persona_entity.behavioral_strategies.error_handling}
              onChange={(event) => patch((d) => { d.persona_entity.behavioral_strategies.error_handling = event.target.value; })}
            />
          </label>
          <label className="space-y-2">
            <span className="text-sm font-medium">{t('personality.fields.refusalStyle')}</span>
            <Textarea
              rows={3}
              value={config.persona_entity.behavioral_strategies.refusal_style}
              onChange={(event) => patch((d) => { d.persona_entity.behavioral_strategies.refusal_style = event.target.value; })}
            />
          </label>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>{t('personality.sections.cachedPhrases')}</CardTitle></CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-2">
          <label className="space-y-2">
            <span className="text-sm font-medium">{t('personality.fields.onInit')}</span>
            <Textarea
              rows={3}
              value={toLines(config.cached_phrases.on_init)}
              onChange={(event) => patch((d) => { d.cached_phrases.on_init = parseLines(event.target.value); })}
            />
          </label>
          <label className="space-y-2">
            <span className="text-sm font-medium">{t('personality.fields.onWake')}</span>
            <Textarea
              rows={3}
              value={toLines(config.cached_phrases.on_wake)}
              onChange={(event) => patch((d) => { d.cached_phrases.on_wake = parseLines(event.target.value); })}
            />
          </label>
          <label className="space-y-2">
            <span className="text-sm font-medium">{t('personality.fields.onError')}</span>
            <Textarea
              rows={3}
              value={toLines(config.cached_phrases.on_error_generic)}
              onChange={(event) => patch((d) => { d.cached_phrases.on_error_generic = parseLines(event.target.value); })}
            />
          </label>
          <label className="space-y-2">
            <span className="text-sm font-medium">{t('personality.fields.onSuccess')}</span>
            <Textarea
              rows={3}
              value={toLines(config.cached_phrases.on_success)}
              onChange={(event) => patch((d) => { d.cached_phrases.on_success = parseLines(event.target.value); })}
            />
          </label>
          <label className="space-y-2 md:col-span-2">
            <span className="text-sm font-medium">{t('personality.fields.onSwitchAttempt')}</span>
            <Textarea
              rows={3}
              value={toLines(config.cached_phrases.on_switch_attempt)}
              onChange={(event) => patch((d) => { d.cached_phrases.on_switch_attempt = parseLines(event.target.value); })}
            />
          </label>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>{t('personality.sections.appearance')}</CardTitle></CardHeader>
        <CardContent>
          <label className="space-y-2">
            <span className="text-sm font-medium">{t('personality.fields.appearancePrompt')}</span>
            <Textarea
              rows={4}
              value={config.appearance_prompt}
              onChange={(event) => patch((d) => { d.appearance_prompt = event.target.value; })}
            />
          </label>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>{t('personality.sections.stateTransitionProtocol')}</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          {config.state_transition_protocol.map((item, index) => (
            <div key={`${index}-${item.target_state_name}`} className="rounded-md border p-3">
              <div className="mb-3 text-sm font-medium">{t('personality.fields.stateTransitionItem', { index: index + 1 })}</div>
              <div className="grid gap-3 md:grid-cols-1">
                <label className="space-y-1">
                  <span className="text-xs text-muted-foreground">{t('personality.fields.triggerCondition')}</span>
                  <Input
                    value={item.trigger_condition}
                    onChange={(event) => patch((d) => {
                      d.state_transition_protocol[index] = normalizeTransition({
                        ...d.state_transition_protocol[index],
                        trigger_condition: event.target.value,
                      });
                    })}
                  />
                </label>
                <label className="space-y-1">
                  <span className="text-xs text-muted-foreground">{t('personality.fields.targetStateName')}</span>
                  <Input
                    value={item.target_state_name}
                    onChange={(event) => patch((d) => {
                      d.state_transition_protocol[index] = normalizeTransition({
                        ...d.state_transition_protocol[index],
                        target_state_name: event.target.value,
                      });
                    })}
                  />
                </label>
                <label className="space-y-1">
                  <span className="text-xs text-muted-foreground">{t('personality.fields.behaviorShift')}</span>
                  <Textarea
                    rows={3}
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
          >
            {t('personality.actions.addTransition')}
          </Button>
        </CardContent>
      </Card>

      <div className="flex justify-center">
        <Button onClick={save} disabled={saving || loading} size="lg">
          <Check className="mr-2 h-4 w-4" />
          {saving ? t('personality.saving') : t('personality.save')}
        </Button>
      </div>
    </div>
  );
};

export default PersonalityModern;
