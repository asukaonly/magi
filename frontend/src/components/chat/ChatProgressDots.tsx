import { useTranslation } from 'react-i18next';

export const ChatProgressDots = ({ shouldReduceMotion = false }: { shouldReduceMotion?: boolean }) => {
  const { t } = useTranslation('app');
  return (
    <span role="status" aria-label={t('chat.runtime.preparing')} className="inline-flex items-center gap-1.5 py-2">
      {[0, 180, 360].map((delay) => (
        <span
          key={delay}
          aria-hidden="true"
          className="block h-1.5 w-1.5 rounded-full bg-muted-foreground/70 motion-reduce:animate-none!"
          style={shouldReduceMotion ? undefined : { animation: `magiPendingDot 1.2s ease-in-out ${delay}ms infinite` }}
        />
      ))}
    </span>
  );
};
