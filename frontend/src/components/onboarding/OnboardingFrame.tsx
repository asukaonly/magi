import type { ReactNode } from 'react';
import GuidedConfigFrame from '@/components/config-forms/GuidedConfigFrame';
import { cn } from '@/lib/utils';
import { OnboardingLanguageSelector } from './OnboardingLanguageSelector';
import StepIndicator from './StepIndicator';

interface OnboardingFrameProps {
  children: ReactNode;
  steps: string[];
  current: number;
  language: 'zh' | 'en';
  onLanguageChange: (language: 'zh' | 'en') => void;
  languageDisabled?: boolean;
  scrollable?: boolean;
  footer: ReactNode;
}

export function OnboardingFrame({ children, steps, current, language, onLanguageChange, languageDisabled = false, scrollable = false, footer }: OnboardingFrameProps) {
  return <div className="absolute inset-0 overflow-hidden bg-muted/25">
    <GuidedConfigFrame
      className="h-full"
      layoutClassName="h-full"
      contentClassName={scrollable ? 'overflow-y-auto' : 'overflow-hidden'}
      sidebar={<div className="flex min-w-max items-center lg:h-full lg:min-w-0 lg:flex-col lg:items-stretch">
        <div className="hidden select-none px-3 pt-1 lg:block" aria-hidden="true"><span className="font-onboarding-display text-2xl font-bold tracking-[0.22em] text-foreground/85">Magi</span></div>
        <div className="lg:flex lg:min-h-0 lg:flex-1 lg:flex-col lg:justify-center"><StepIndicator steps={steps} current={current} /></div>
        <div className="hidden px-1 lg:block"><OnboardingLanguageSelector language={language} onChange={onLanguageChange} disabled={languageDisabled} /></div>
      </div>}
      footer={<div className="mx-auto w-full max-w-6xl">{footer}</div>}
    >
      <div className={cn('mx-auto flex w-full max-w-6xl flex-1 flex-col', !scrollable && 'min-h-0')}>
        {children}
      </div>
    </GuidedConfigFrame>
  </div>;
}
