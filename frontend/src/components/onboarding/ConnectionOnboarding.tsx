import { useEffect, useId, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ArrowLeft, ArrowRight, Check, Laptop, Loader2, Server } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { RemoteConnectionForm, isRemoteConnectionDraftComplete } from '@/components/connections/RemoteConnectionForm';
import { useConnectionSetup } from '@/components/connections/useConnectionSetup';
import { resolveInitialLanguage, toI18nLanguage } from '@/utils/language';
import { cn } from '@/lib/utils';
import WelcomeScreen from './WelcomeScreen';
import { OnboardingFrame } from './OnboardingFrame';
import { ONBOARDING_DESCRIPTION_CLASS, ONBOARDING_PRIMARY_ACTION_CLASS, ONBOARDING_SECONDARY_ACTION_CLASS, ONBOARDING_TITLE_CLASS } from './onboardingStyles';

interface ConnectionOnboardingProps {
  initialStep?: 'welcome' | 'location';
  initialLocation?: 'local' | 'remote';
  onBack?: () => void;
  onUseActive?: () => void;
  onLanguageChange?: (language: 'zh' | 'en') => void;
}

/** Device-owned introduction, available before any center runtime is started. */
export function ConnectionOnboarding({ initialStep = 'welcome', initialLocation = 'local', onBack, onUseActive, onLanguageChange }: ConnectionOnboardingProps) {
  const { t, i18n } = useTranslation('onboarding');
  const { t: appT } = useTranslation('app');
  const [step, setStep] = useState<'welcome' | 'location' | 'remote'>(initialStep);
  const [location, setLocation] = useState(initialLocation);
  const [language, setLanguage] = useState(resolveInitialLanguage);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const formId = useId();
  const { profiles, draft, setDraft, busy, error, retry, connect, pair } = useConnectionSetup();

  useEffect(() => {
    if (step !== 'welcome') headingRef.current?.focus({ preventScroll: true });
  }, [step]);

  const changeLanguage = (value: 'zh' | 'en') => {
    setLanguage(value);
    localStorage.setItem('magi_language', value);
    document.documentElement.lang = toI18nLanguage(value);
    void i18n.changeLanguage(toI18nLanguage(value));
    onLanguageChange?.(value);
  };
  const connectProfile = (id: string) => {
    if (onUseActive && profiles?.state.active_profile_id === id) onUseActive();
    else void connect(id);
  };
  const back = () => {
    if (step === 'remote') setStep('location');
    else if (onBack) onBack();
    else setStep('welcome');
  };
  const steps = location === 'remote'
    ? [t('steps.location'), t('location.connectStep')]
    : [t('steps.location'), t('steps.llmSetup'), t('steps.personaPreview'), t('steps.firstContext'), t('steps.complete')];

  if (step === 'welcome') return <WelcomeScreen language={language} onLanguageChange={changeLanguage} onContinue={() => setStep('location')} />;

  return <OnboardingFrame
      steps={steps}
      current={step === 'remote' ? 1 : 0}
      language={language}
      onLanguageChange={changeLanguage}
      languageDisabled={busy}
      scrollable
      footer={<div className="flex items-center justify-between gap-3">
        <Button variant="ghost" className={ONBOARDING_SECONDARY_ACTION_CLASS} onClick={back} disabled={busy}><ArrowLeft className="h-4 w-4" aria-hidden="true" />{t('actions.previous')}</Button>
        {step === 'remote' ? <Button type="submit" form={formId} className={ONBOARDING_PRIMARY_ACTION_CLASS} disabled={busy || !isRemoteConnectionDraftComplete(draft)}>
          {busy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : null}{appT(busy ? 'connections.connecting' : 'connections.pair')}
        </Button> : <Button className={ONBOARDING_PRIMARY_ACTION_CLASS} disabled={busy || !profiles || (location === 'remote' && !profiles.supports_remote)} onClick={() => {
          if (location === 'remote') setStep('remote');
          else connectProfile('local');
        }}>{busy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : null}{busy ? appT('connections.connecting') : t('actions.next')}<ArrowRight className="h-4 w-4" aria-hidden="true" /></Button>}
      </div>}
    >
      <div className="w-full">
        <header className="mb-6">
          <h1 ref={headingRef} tabIndex={-1} className={ONBOARDING_TITLE_CLASS}>{t(step === 'remote' ? 'location.remoteTitle' : 'location.title')}</h1>
          <p className={ONBOARDING_DESCRIPTION_CLASS}>{t(step === 'remote' ? 'location.remoteIntro' : 'location.description')}</p>
        </header>
        {step === 'location' ? <>
          <fieldset className="grid gap-4 sm:grid-cols-2 sm:gap-y-0" disabled={busy || !profiles}>
            <legend className="sr-only">{t('location.title')}</legend>
            {(['local', 'remote'] as const).map((value) => {
              const Icon = value === 'local' ? Laptop : Server;
              const unavailable = value === 'remote' && profiles?.supports_remote === false;
              return <label key={value} className={cn(
                'relative flex cursor-pointer flex-col rounded-xl border p-6 transition-colors focus-within:ring-2 focus-within:ring-primary/30 sm:row-span-4 sm:grid sm:grid-rows-subgrid',
                location === value ? 'border-primary/60 bg-card shadow-sm' : 'border-border bg-card/40 hover:border-foreground/25',
                (busy || !profiles || unavailable) && 'cursor-default opacity-50',
              )}>
                <input type="radio" name="runtime-location" value={value} checked={location === value} onChange={() => setLocation(value)} disabled={unavailable} className="sr-only" aria-label={t(`location.${value}.title`)} />
                <div className="mb-6 flex items-center justify-between"><Icon className="h-7 w-7 text-foreground/75" aria-hidden="true" /><span className={cn('flex h-5 w-5 items-center justify-center rounded-full border', location === value ? 'border-primary bg-primary text-primary-foreground' : 'border-border')} aria-hidden="true">{location === value ? <Check className="h-3.5 w-3.5" /> : null}</span></div>
                <span className="text-base font-semibold text-foreground">{t(`location.${value}.title`)}</span>
                <span className="mt-3 text-sm leading-6 text-muted-foreground">{t(`location.${value}.description`)}</span>
                <span className="mt-5 border-t border-border/70 pt-4 text-xs leading-5 text-muted-foreground">{t(`location.${value}.hint`)}</span>
              </label>;
            })}
          </fieldset>
          <p className="mt-5 text-xs leading-5 text-muted-foreground">{t('location.changeLater')}</p>
          {!profiles && !error ? <p role="status" className="mt-4 text-sm text-muted-foreground">{appT('common.loading')}</p> : null}
        </> : <div className="w-full min-w-0 space-y-6">
          {profiles?.state.profiles.some((profile) => profile.mode === 'remote') ? <section className="space-y-3" aria-label={t('location.savedCenters')}>
            <h2 className="text-sm font-semibold">{t('location.savedCenters')}</h2>
            {profiles.state.profiles.filter((profile) => profile.mode === 'remote').map((profile) => <div key={profile.id} className="flex items-center gap-3 rounded-lg border border-border bg-card p-3">
              <Server className="h-5 w-5 shrink-0 text-muted-foreground" aria-hidden="true" />
              <div className="min-w-0 flex-1"><p className="truncate text-sm font-medium">{profile.name}</p><p className="truncate text-xs text-muted-foreground">{profile.api_base_url}</p></div>
              <Button size="sm" variant="outline" disabled={busy} onClick={() => connectProfile(profile.id)}>{appT('connections.connect')}</Button>
            </div>)}
          </section> : null}
          <RemoteConnectionForm id={formId} draft={draft} onChange={setDraft} onSubmit={pair} busy={busy} showSubmit={false} />
        </div>}
        {error ? <div role="alert" className="mt-5 space-y-2 text-sm text-destructive"><p className="break-words">{error}</p>{!profiles ? <Button variant="outline" onClick={retry}>{appT('common.retry')}</Button> : null}</div> : null}
      </div>
    </OnboardingFrame>;
}
