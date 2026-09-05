import { asEventHandler } from '@/utils/as-event-handler';
import { getCurrentWindow } from '@tauri-apps/api/window';
import { useTranslation } from 'react-i18next';
import { Minus, Square, X } from 'lucide-react';
import { cn } from '@/lib/utils';

/** Native window actions used by the Windows/Linux custom title bar. */
export const AppWindowControls = ({ className }: { className?: string }) => {
  const { t } = useTranslation('app');
  return (
    <div className={cn('flex h-full items-stretch', className)}>
      <WindowButton onClick={asEventHandler(() => getCurrentWindow().minimize())} aria-label={t('shell.windowMinimize')}>
        <Minus className="h-3.5 w-3.5" />
      </WindowButton>
      <WindowButton onClick={asEventHandler(() => getCurrentWindow().toggleMaximize())} aria-label={t('shell.windowMaximize')}>
        <Square className="h-3 w-3" />
      </WindowButton>
      <WindowButton onClick={asEventHandler(() => getCurrentWindow().close())} aria-label={t('shell.windowClose')} variant="close">
        <X className="h-3.5 w-3.5" />
      </WindowButton>
    </div>
  );
};

const WindowButton = ({
  onClick,
  variant,
  children,
  ...rest
}: {
  onClick: () => void;
  variant?: 'close';
  children: React.ReactNode;
} & React.ButtonHTMLAttributes<HTMLButtonElement>) => (
  <button
    type="button"
    onClick={onClick}
    className={cn(
      'flex w-11 items-center justify-center text-muted-foreground transition-colors',
      variant === 'close'
        ? 'hover:bg-destructive hover:text-destructive-foreground'
        : 'hover:bg-muted hover:text-foreground',
    )}
    {...rest}
  >
    {children}
  </button>
);
