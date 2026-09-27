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
  compact?: boolean;
  footer: ReactNode;
}

export function OnboardingFrame({ children, steps, current, language, onLanguageChange, languageDisabled = false, scrollable = false, compact = false, footer }: OnboardingFrameProps) {
  return <div className="absolute inset-0 overflow-hidden bg-muted/25">
    <GuidedConfigFrame
      className="h-full"
      layoutClassName="h-full"
      contentClassName={cn(scrollable ? 'overflow-y-auto' : 'overflow-hidden', compact && 'px-0 sm:px-0 lg:px-0 xl:px-0 [--onboarding-content-width:44rem]')}
      sidebar={<div className="flex min-w-max items-center lg:h-full lg:min-w-0 lg:flex-col lg:items-stretch">
        <div className="hidden select-none px-3 pt-1 lg:block" aria-hidden="true"><span className="font-onboarding-display text-2xl font-bold tracking-[0.22em] text-foreground/85">Magi</span></div>
        <div className="lg:flex lg:min-h-0 lg:flex-1 lg:flex-col lg:justify-center"><StepIndicator steps={steps} current={current} /></div>
        <div className="hidden px-1 lg:block"><OnboardingLanguageSelector language={language} onChange={onLanguageChange} disabled={languageDisabled} /></div>
      </div>}
      footer={<div className="mx-auto w-full max-w-6xl">{footer}</div>}
    >
      <div className={cn('mx-auto flex w-full flex-1 flex-col', !compact && 'max-w-6xl', !scrollable && 'min-h-0')}>
        {children}
      </div>
    </GuidedConfigFrame>
  </div>;
}

export function OnboardingScrollPane({ header, children }: { header: ReactNode; children: ReactNode }) {
  const inset = 'px-4 sm:px-6 lg:px-8 xl:px-10';
  const column = 'mx-auto w-full max-w-[var(--onboarding-content-width)]';
  return <div className="flex min-h-0 flex-1 flex-col">
    <div className={cn('shrink-0 overflow-hidden pb-3 [scrollbar-gutter:stable_both-edges]', inset)}>
      <div className={column}>{header}</div>
    </div>
    <div data-testid="onboarding-app-scroll" className={cn('min-h-0 flex-1 overflow-y-auto overscroll-contain [scrollbar-gutter:stable_both-edges]', inset)}>
      <div className={column}>{children}</div>
    </div>
  </div>;
}
