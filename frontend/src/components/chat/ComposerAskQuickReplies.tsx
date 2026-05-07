import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { isInteractionExpired, remainingInteractionSeconds } from '@/components/control/interaction-expiry';

type ComposerAskQuickRepliesProps = {
  options: string[];
  allowFreeText: boolean;
  expiresAtMs: number | null;
  onPick: (value: string) => void;
};

const optionTestId = (option: string): string => option
  .trim()
  .toLowerCase()
  .replace(/[^a-z0-9_-]+/g, '-');

const useInteractionNow = (expiresAtMs: number | null): number => {
  const [nowMs, setNowMs] = useState(() => Date.now());

  useEffect(() => {
    if (!expiresAtMs) {
      return () => undefined;
    }
    setNowMs(Date.now());
    const handle = window.setInterval(() => {
      setNowMs(Date.now());
    }, 1000);
    return () => {
      window.clearInterval(handle);
    };
  }, [expiresAtMs]);

  return nowMs;
};

export const ComposerAskQuickReplies = ({
  options,
  allowFreeText,
  expiresAtMs,
  onPick,
}: ComposerAskQuickRepliesProps) => {
  const { t } = useTranslation('control');
  const nowMs = useInteractionNow(expiresAtMs);
  const expired = isInteractionExpired(expiresAtMs, nowMs);
  const remainingSeconds = remainingInteractionSeconds(expiresAtMs, nowMs);
  const uniqueOptions = useMemo(
    () => Array.from(new Set(options.map((option) => option.trim()).filter(Boolean))),
    [options],
  );

  if (!uniqueOptions.length && !expiresAtMs) {
    return null;
  }

  return (
    <div
      className="mb-2 flex flex-wrap items-center gap-2 border-b border-border/45 pb-2"
      data-testid="ask-composer-quick-replies"
    >
      <span className="inline-flex h-6 items-center rounded-full border border-border/60 bg-muted/40 px-2 text-[11px] font-medium text-muted-foreground">
        {remainingSeconds !== null
          ? (expired ? t('ask.expired') : t('ask.expires_in', { seconds: remainingSeconds }))
          : t('ask.title')}
      </span>
      {uniqueOptions.map((option) => (
        <button
          key={option}
          type="button"
          className="inline-flex h-7 max-w-full items-center rounded-full border border-border/60 bg-background px-2.5 text-xs text-foreground transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/35 disabled:cursor-not-allowed disabled:opacity-50"
          disabled={expired}
          onClick={() => onPick(option)}
          data-testid={`ask-composer-option-${optionTestId(option)}`}
        >
          <span className="truncate">{option}</span>
        </button>
      ))}
      {!uniqueOptions.length && allowFreeText ? (
        <span className="text-xs text-muted-foreground">{t('ask.quick.no_options')}</span>
      ) : null}
    </div>
  );
};