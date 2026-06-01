import { useTranslation } from 'react-i18next';

export const PortraitColdStart = ({ line }: { line: string | null | undefined }) => {
  const { t } = useTranslation('app');
  const text = line && line.trim() ? line : t('chat.portrait.coldStartFallback');
  return (
    <div
      className="flex flex-col items-start gap-1.5 rounded-md border border-dashed border-border/50 px-3 py-3 text-[12.5px] text-muted-foreground"
      data-testid="portrait-cold-start"
    >
      <span aria-hidden="true">🪞</span>
      <span>{text}</span>
    </div>
  );
};
