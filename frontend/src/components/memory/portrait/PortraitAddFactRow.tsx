import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import { manualEntriesApi } from '@/api/modules/manualEntries';
import { Button } from '@/components/ui/button';
import { MEMORY_GHOST_ACTION_CLASS } from '@/components/memory/memoryActionStyles';

interface PortraitAddFactRowProps {
  onSubmitted?: () => void;
}

/** Single-line "tell Magi one thing about you" input. Submits through the
 * manual-entries channel (user_authored); the fact lands in the pending
 * review page once L2 extraction finishes. */
export const PortraitAddFactRow = ({ onSubmitted }: PortraitAddFactRowProps) => {
  const { t } = useTranslation('app');
  const [value, setValue] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const submit = async () => {
    const body = value.trim();
    if (!body || submitting) return;
    setSubmitting(true);
    try {
      await manualEntriesApi.create({
        entry_id: `me-${crypto.randomUUID()}`,
        body,
      });
      setValue('');
      toast.success(t('memory.portrait.addFact.success'));
      onSubmitted?.();
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : String(error);
      toast.error(t('memory.portrait.addFact.failed', { message }));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div data-testid="portrait-add-fact" className="mt-4 flex items-center gap-2">
      <input
        type="text"
        value={value}
        disabled={submitting}
        placeholder={t('memory.portrait.addFact.placeholder')}
        aria-label={t('memory.portrait.addFact.placeholder')}
        onChange={(event) => setValue(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter') {
            event.preventDefault();
            void submit();
          }
        }}
        className="h-9 min-w-0 flex-1 rounded-mem-sm border border-transparent bg-[hsl(var(--memory-panel-subtle)/0.4)] px-3 text-sm text-[hsl(var(--memory-title))] outline-none transition-colors placeholder:text-[hsl(var(--memory-muted))] hover:bg-[hsl(var(--memory-panel-subtle)/0.6)] focus:bg-[hsl(var(--memory-panel-elevated))] focus:ring-2 focus:ring-[hsl(var(--memory-accent)/0.14)]"
      />
      {value.trim() || submitting ? (
        <Button
          type="button"
          size="sm"
          onClick={() => void submit()}
          disabled={!value.trim() || submitting}
          className={MEMORY_GHOST_ACTION_CLASS}
        >
          {submitting ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
          ) : (
            t('memory.portrait.addFact.submit')
          )}
        </Button>
      ) : null}
    </div>
  );
};

export default PortraitAddFactRow;
