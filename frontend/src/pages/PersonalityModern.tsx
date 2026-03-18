import React from 'react';
import { useTranslation } from 'react-i18next';
import {
  Check,
  Loader2,
  Plus,
  RefreshCw,
  Sparkles,
  Trash2,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { cn } from '@/lib/utils';
import {
  usePersonality,
  CONFIDENCE_OPTIONS,
  parseLines,
  toLines,
  getInitials,
  normalizeTransition,
} from '@/hooks';

const sectionCardClass = 'border-border/50 bg-card';

interface PersonalityModernProps {
  embedded?: boolean;
}

const PersonalityModern: React.FC<PersonalityModernProps> = ({ embedded = false }) => {
  const { t } = useTranslation('app');

  const {
    // State
    config,
    list,
    currentName,
    selectedName,
    isNewMode,
    loading,
    saving,
    generating,
    switching,
    selectedInfo,
    switchPrompt,

    // Form state
    prompt,
    setPrompt,
    targetLanguage,
    setTargetLanguage,

    // Actions
    patch,
    selectPersonality,
    startNewPersonality,
    cancelNewPersonality,
    save,
    generate,
    switchPersonality,
    confirmSwitchPersonality,
    cancelSwitchPersonality,
    deletePersonality,
    reload,
  } = usePersonality();

  return (
    <div className={cn('flex h-full min-h-0 flex-col overflow-hidden', embedded ? 'bg-transparent' : 'bg-background')}>
      <div
        className={cn(
          'border-b border-border/40 bg-muted/20',
          embedded ? 'border-b-0 bg-transparent px-0 pb-3 pt-1' : 'px-6 py-5'
        )}
      >
      {/* Title row */}
      {!embedded ? (
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-foreground">
              {t('personality.title')}
            </h1>
            <p className="mt-1 text-sm text-muted-foreground">
              {t('settings.personalityDesc')}
            </p>
          </div>
        </div>
      ) : null}
      {/* Avatar selector row */}
      <div className="flex gap-3 overflow-x-auto pb-2">
          {/* Add button – hidden in create mode */}
          {!isNewMode && (
            <button
              onClick={startNewPersonality}
              className="group flex shrink-0 flex-col items-center gap-2"
            >
              <div className="flex h-16 w-16 items-center justify-center rounded-2xl border-2 border-dashed border-border bg-muted/30 transition group-hover:border-primary group-hover:bg-primary/5">
                <Plus className="h-6 w-6 text-muted-foreground transition group-hover:text-primary" />
              </div>
              <span className="text-xs font-medium text-muted-foreground transition group-hover:text-foreground">
                {t('personality.create')}
              </span>
            </button>
          )}

          {/* Personality Avatars */}
          {list.map((item) => {
            const isSelected = item.name === selectedName;
            const isCurrent = item.name === currentName;
            const initials = getInitials(item.displayName);

            return (
              <button
                key={item.name}
                onClick={() => selectPersonality(item.name)}
                className="group relative flex shrink-0 flex-col items-center gap-2"
              >
                <div
                  className={cn(
                    'relative flex h-16 w-16 items-center justify-center rounded-2xl border-2 transition',
                    isSelected
                      ? 'border-primary bg-primary/10 shadow-sm'
                      : 'border-border/50 bg-muted/30 hover:border-primary/50 hover:bg-muted/50'
                  )}
                >
                  <span
                    className={cn(
                      'text-lg font-semibold',
                      isSelected ? 'text-primary' : 'text-muted-foreground'
                    )}
                  >
                    {initials}
                  </span>
                  {/* Current-in-use badge */}
                  {isCurrent && (
                    <div className="absolute -right-1 -top-1 flex h-5 w-5 items-center justify-center rounded-full bg-primary text-primary-foreground shadow-sm">
                      <Check className="h-3 w-3" />
                    </div>
                  )}
                </div>
                <div className="max-w-[80px] truncate text-center">
                  <span
                    className={cn(
                      'block text-xs font-medium',
                      isSelected ? 'text-foreground' : 'text-muted-foreground'
                    )}
                  >
                    {item.displayName}
                  </span>
                </div>
              </button>
            );
          })}
        </div>
      </div>

      {/* Detail section: Scrollable config cards */}
      <div className={cn('flex-1 overflow-y-auto', embedded ? 'pt-3' : 'p-6')}>
        <div className="space-y-5">
          {/* Detail Header with Actions */}
          <div className="flex flex-col gap-4 rounded-3xl border border-primary/20 bg-muted/20 p-5">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
              <div className="max-w-2xl">
                <p className="text-xs font-semibold uppercase tracking-[0.22em] text-primary/80">
                  {isNewMode ? t('personality.creating') : t('personality.current')}
                </p>
                <h2 className="mt-2 text-2xl font-semibold tracking-tight text-foreground">
                  {isNewMode
                    ? (config.persona_entity.basic_profile.name || t('personality.newPersonality'))
                    : (config.persona_entity.basic_profile.name || selectedInfo?.displayName || t('personality.title'))}
                </h2>
                <p className="mt-2 text-sm leading-6 text-muted-foreground">
                  {isNewMode
                    ? t('personality.newPersonalityDesc')
                    : (config.persona_entity.basic_profile.description || selectedInfo?.subtitle || t('settings.personalityDesc'))}
                </p>
              </div>

              {/* Action Buttons */}
              <div className="flex flex-wrap gap-2">
                {!isNewMode && selectedName !== currentName && (
                  <Button onClick={switchPersonality} disabled={switching} className="rounded-2xl">
                    <Check className="mr-2 h-4 w-4" />
                    {switching ? t('personality.switching') : t('personality.switch')}
                  </Button>
                )}
                {isNewMode ? (
                  <Button
                    variant="outline"
                    onClick={cancelNewPersonality}
                    className="rounded-2xl"
                  >
                    {t('personality.cancel')}
                  </Button>
                ) : (
                  <Button
                    variant="outline"
                    onClick={reload}
                    className="rounded-2xl"
                  >
                    <RefreshCw className="mr-2 h-4 w-4" />
                    {t('personality.reload')}
                  </Button>
                )}
                <Button
                  onClick={save}
                  disabled={saving || loading}
                  className="rounded-2xl"
                >
                  <Check className="mr-2 h-4 w-4" />
                  {isNewMode
                    ? (saving ? t('personality.creating') : t('personality.create'))
                    : (saving ? t('personality.saving') : t('personality.save'))}
                </Button>
                {!isNewMode && (
                  <Button
                    variant="outline"
                    onClick={deletePersonality}
                    disabled={selectedName === 'default'}
                    className="rounded-2xl border-destructive/35 text-destructive hover:bg-destructive/10 hover:text-destructive"
                  >
                    <Trash2 className="mr-2 h-4 w-4" />
                    {t('personality.delete')}
                  </Button>
                )}
              </div>
            </div>

            {/* AI Generate Section */}
            <div className="w-full max-w-2xl space-y-3 border-t border-border/30 pt-4">
              <div className="flex items-center gap-2 text-sm font-medium text-foreground">
                <Sparkles className="h-4 w-4 text-primary" />
                {t('personality.generate')}
              </div>
              <div className="flex flex-col gap-2 xl:flex-row">
                <Input
                  value={prompt}
                  onChange={(event) => setPrompt(event.target.value)}
                  placeholder={t('personality.generatePlaceholder')}
                  className="h-11 rounded-2xl"
                />
                <select
                  className="h-11 rounded-2xl border border-input bg-background px-4 text-sm outline-none transition focus:border-primary focus:ring-2 focus:ring-primary/20"
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

          {/* Configuration Cards */}
          {loading ? (
            <div className="flex min-h-[360px] items-center justify-center rounded-3xl border border-border/50 bg-muted/30">
              <Loader2 className="h-6 w-6 animate-spin text-primary" />
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
                      className="rounded-xl"
                      value={config.persona_entity.basic_profile.name}
                      onChange={(event) => patch((d) => { d.persona_entity.basic_profile.name = event.target.value; })}
                    />
                  </label>
                  <label className="space-y-2">
                    <span className="text-sm font-medium">{t('personality.fields.age')}</span>
                    <Input
                      className="rounded-xl"
                      value={config.persona_entity.basic_profile.age}
                      onChange={(event) => patch((d) => { d.persona_entity.basic_profile.age = event.target.value; })}
                    />
                  </label>
                  <label className="space-y-2">
                    <span className="text-sm font-medium">{t('personality.fields.gender')}</span>
                    <Input
                      className="rounded-xl"
                      value={config.persona_entity.basic_profile.gender}
                      onChange={(event) => patch((d) => { d.persona_entity.basic_profile.gender = event.target.value; })}
                    />
                  </label>
                  <label className="space-y-2 md:col-span-3">
                    <span className="text-sm font-medium">{t('personality.fields.occupation')}</span>
                    <Input
                      className="rounded-xl"
                      value={config.persona_entity.basic_profile.occupation}
                      onChange={(event) => patch((d) => { d.persona_entity.basic_profile.occupation = event.target.value; })}
                    />
                  </label>
                  <label className="space-y-2 md:col-span-3">
                    <span className="text-sm font-medium">{t('personality.fields.coreBackground')}</span>
                    <Textarea
                      rows={6}
                      className="rounded-xl"
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
                      className="rounded-xl"
                      value={config.persona_entity.psychological_traits.communication_tone}
                      onChange={(event) => patch((d) => { d.persona_entity.psychological_traits.communication_tone = event.target.value; })}
                    />
                  </label>
                  <label className="space-y-2">
                    <span className="text-sm font-medium">{t('personality.fields.confidenceLevel')}</span>
                    <select
                      className="h-10 w-full rounded-xl border border-input bg-background px-3 text-sm outline-none transition focus:border-primary focus:ring-2 focus:ring-primary/20"
                      value={config.persona_entity.psychological_traits.confidence_level}
                      onChange={(event) => patch((d) => { d.persona_entity.psychological_traits.confidence_level = event.target.value; })}
                    >
                      {CONFIDENCE_OPTIONS.map((item) => <option key={item} value={item}>{item}</option>)}
                    </select>
                  </label>
                  <label className="space-y-2 md:col-span-2">
                    <span className="text-sm font-medium">{t('personality.fields.empathyThreshold')}</span>
                    <Input
                      className="rounded-xl"
                      value={config.persona_entity.psychological_traits.empathy_threshold}
                      onChange={(event) => patch((d) => { d.persona_entity.psychological_traits.empathy_threshold = event.target.value; })}
                    />
                  </label>
                  <label className="space-y-2 md:col-span-2">
                    <span className="text-sm font-medium">{t('personality.fields.highFrequencyKeywords')}</span>
                    <Input
                      className="rounded-xl"
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

              <Card className={sectionCardClass}>
                <CardHeader>
                  <CardTitle>{t('personality.sections.socialResponses')}</CardTitle>
                </CardHeader>
                  <CardContent className="grid gap-4">
                    <label className="space-y-2">
                      <span className="text-sm font-medium">{t('personality.fields.praiseReaction')}</span>
                      <Input
                        className="rounded-xl"
                        value={config.persona_entity.social_responses.praise_reaction}
                        onChange={(event) => patch((d) => { d.persona_entity.social_responses.praise_reaction = event.target.value; })}
                      />
                    </label>
                    <label className="space-y-2">
                      <span className="text-sm font-medium">{t('personality.fields.criticismReaction')}</span>
                      <Input
                        className="rounded-xl"
                        value={config.persona_entity.social_responses.criticism_reaction}
                        onChange={(event) => patch((d) => { d.persona_entity.social_responses.criticism_reaction = event.target.value; })}
                      />
                    </label>
                    <label className="space-y-2">
                      <span className="text-sm font-medium">{t('personality.fields.obedienceStrategy')}</span>
                      <Textarea
                        rows={4}
                        className="rounded-xl"
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
                      className="rounded-xl"
                      value={config.persona_entity.behavioral_strategies.error_handling}
                      onChange={(event) => patch((d) => { d.persona_entity.behavioral_strategies.error_handling = event.target.value; })}
                    />
                  </label>
                  <label className="space-y-2">
                    <span className="text-sm font-medium">{t('personality.fields.refusalStyle')}</span>
                    <Textarea
                      rows={4}
                      className="rounded-xl"
                      value={config.persona_entity.behavioral_strategies.refusal_style}
                      onChange={(event) => patch((d) => { d.persona_entity.behavioral_strategies.refusal_style = event.target.value; })}
                    />
                  </label>
                </CardContent>
              </Card>

              <Card className={sectionCardClass}>
                <CardHeader>
                  <CardTitle>{t('personality.sections.cachedPhrases')}</CardTitle>
                </CardHeader>
                <CardContent className="grid gap-4 md:grid-cols-2">
                  <label className="space-y-2">
                    <span className="text-sm font-medium">{t('personality.fields.onInit')}</span>
                    <Textarea
                      rows={3}
                      className="rounded-xl"
                      value={toLines(config.cached_phrases.on_init)}
                      onChange={(event) => patch((d) => { d.cached_phrases.on_init = parseLines(event.target.value); })}
                    />
                  </label>
                  <label className="space-y-2">
                    <span className="text-sm font-medium">{t('personality.fields.onWake')}</span>
                    <Textarea
                      rows={3}
                      className="rounded-xl"
                      value={toLines(config.cached_phrases.on_wake)}
                      onChange={(event) => patch((d) => { d.cached_phrases.on_wake = parseLines(event.target.value); })}
                    />
                  </label>
                  <label className="space-y-2">
                    <span className="text-sm font-medium">{t('personality.fields.onError')}</span>
                    <Textarea
                      rows={3}
                      className="rounded-xl"
                      value={toLines(config.cached_phrases.on_error_generic)}
                      onChange={(event) => patch((d) => { d.cached_phrases.on_error_generic = parseLines(event.target.value); })}
                    />
                  </label>
                  <label className="space-y-2">
                    <span className="text-sm font-medium">{t('personality.fields.onSuccess')}</span>
                    <Textarea
                      rows={3}
                      className="rounded-xl"
                      value={toLines(config.cached_phrases.on_success)}
                      onChange={(event) => patch((d) => { d.cached_phrases.on_success = parseLines(event.target.value); })}
                    />
                  </label>
                  <label className="space-y-2 md:col-span-2">
                    <span className="text-sm font-medium">{t('personality.fields.onSwitchAttempt')}</span>
                    <Textarea
                      rows={3}
                      className="rounded-xl"
                      value={toLines(config.cached_phrases.on_switch_attempt)}
                      onChange={(event) => patch((d) => { d.cached_phrases.on_switch_attempt = parseLines(event.target.value); })}
                    />
                  </label>
                </CardContent>
              </Card>

              <Card className={sectionCardClass}>
                <CardHeader>
                  <CardTitle>{t('personality.sections.appearance')}</CardTitle>
                </CardHeader>
                <CardContent>
                  <label className="space-y-2">
                    <span className="text-sm font-medium">{t('personality.fields.appearancePrompt')}</span>
                    <Textarea
                      rows={8}
                      className="rounded-xl"
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
                          'rounded-2xl border border-border/50 bg-muted/30 p-4'
                        )}
                      >
                        <div className="mb-3 text-sm font-medium">{t('personality.fields.stateTransitionItem', { index: index + 1 })}</div>
                        <div className="grid gap-3">
                          <label className="space-y-1.5">
                            <span className="text-xs text-muted-foreground">{t('personality.fields.triggerCondition')}</span>
                            <Input
                              className="rounded-xl"
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
                              className="rounded-xl"
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
                              className="rounded-xl"
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
                              className="rounded-xl"
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
                      className="rounded-xl"
                    >
                      {t('personality.actions.addTransition')}
                    </Button>
                  </CardContent>
              </Card>
            </>
          )}
        </div>
      </div>

      <Dialog
        open={Boolean(switchPrompt)}
        onOpenChange={(open) => {
          if (!open && !switching) {
            cancelSwitchPersonality();
          }
        }}
      >
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>{t('personality.switchPromptTitle')}</DialogTitle>
            <DialogDescription>
              {switchPrompt
                ? t('personality.switchConfirm', {
                    from: switchPrompt.fromName,
                    to: switchPrompt.toName,
                  })
                : ''}
            </DialogDescription>
          </DialogHeader>
          <div className="px-6 pb-2">
            <div className="rounded-2xl border border-primary/20 bg-primary/6 px-4 py-4 text-sm leading-7 text-foreground">
              {switchPrompt?.phrase}
            </div>
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={cancelSwitchPersonality}
              disabled={switching}
            >
              {t('personality.cancel')}
            </Button>
            <Button
              type="button"
              onClick={() => {
                void confirmSwitchPersonality();
              }}
              disabled={switching}
            >
              {switching ? t('personality.switching') : t('personality.confirmSwitch')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default PersonalityModern;
