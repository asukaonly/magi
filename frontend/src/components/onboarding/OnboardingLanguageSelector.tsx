import { cn } from '@/lib/utils';

interface OnboardingLanguageSelectorProps {
  language: 'zh' | 'en';
  onChange: (language: 'zh' | 'en') => void;
  disabled?: boolean;
}

export function OnboardingLanguageSelector({ language, onChange, disabled = false }: OnboardingLanguageSelectorProps) {
  return <div className="flex items-center gap-1">
    {(['zh', 'en'] as const).map((value) => <button
      key={value}
      type="button"
      disabled={disabled}
      onClick={() => onChange(value)}
      aria-pressed={language === value}
      className={cn(
        'relative flex h-11 min-w-12 items-center justify-center px-2 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/20 disabled:opacity-40',
        language === value
          ? 'text-primary after:absolute after:bottom-1.5 after:left-2 after:right-2 after:h-px after:bg-primary/55'
          : 'text-muted-foreground hover:text-foreground',
      )}
    >{value === 'zh' ? '中文' : 'EN'}</button>)}
  </div>;
}
