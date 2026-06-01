import { Bell } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { useNotifications } from '@/hooks/useNotifications';
import { NotificationCenter } from '@/components/notifications/NotificationCenter';

export function NotificationBell(): JSX.Element {
  const { t } = useTranslation('app');
  const { unreadCount } = useNotifications();
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          data-no-drag
          onMouseDown={(e) => e.stopPropagation()}
          aria-label={t('notifications.bellAria')}
          className="relative flex h-7 w-7 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        >
          <Bell className="h-4 w-4" />
          {unreadCount > 0 ? (
            <span className="absolute -right-0.5 -top-0.5 flex h-3.5 min-w-3.5 items-center justify-center rounded-full bg-primary px-1 text-[10px] leading-none text-primary-foreground">
              {Math.min(unreadCount, 99)}
            </span>
          ) : null}
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-96 p-0" onMouseDown={(e) => e.stopPropagation()}>
        <NotificationCenter />
      </PopoverContent>
    </Popover>
  );
}

export default NotificationBell;
