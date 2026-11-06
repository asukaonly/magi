import { useTranslation } from 'react-i18next';
import { Button } from './button';

export function InlineLoadError({ message, onRetry, retrying }: {
  message: string;
  onRetry?: () => void;
  retrying?: boolean;
}) {
  const { t } = useTranslation('app');
  return (
    <div role="alert" className="flex flex-wrap items-center gap-3 rounded-lg border border-border/60 bg-muted/30 px-4 py-3 text-sm">
      <p className="flex-1 text-muted-foreground">{message}</p>
      {onRetry ? <Button variant="outline" size="sm" disabled={retrying} onClick={onRetry}>{t('common.retry')}</Button> : null}
    </div>
  );
}
