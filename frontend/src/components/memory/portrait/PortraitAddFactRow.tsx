import { useRef, useState } from 'react';
import { shouldSubmitOnEnter } from '@/utils/keyboard';
import { useTranslation } from 'react-i18next';
import { Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import { manualEntriesApi } from '@/api/modules/manualEntries';
import { Button } from '@/components/ui/button';
import { MEMORY_GHOST_ACTION_CLASS } from '@/components/memory/memoryActionStyles';

interface PortraitAddFactRowProps {
  onSubmitted?: () => void;
}

/** Submit user-authored evidence through the ordinary memory pipeline. */
export const PortraitAddFactRow = ({ onSubmitted }: PortraitAddFactRowProps) => {
  const { t } = useTranslation('app');
  const [value, setValue] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const composing = useRef(false);
  const draftIdentity = useRef<{ body: string; id: string } | null>(null);

  const submit = async () => {
    const body = value.trim();
    if (!body || submitting) return;
    setSubmitting(true);
    try {
      if (draftIdentity.current?.body !== body) {
        draftIdentity.current = { body, id: `me-${crypto.randomUUID()}` };
      }
      const entry = await manualEntriesApi.create({
        entry_id: draftIdentity.current.id,
        body,
      });
      draftIdentity.current = null;
      setValue('');
      toast.success(t(entry.memory_status === 'pending'
        ? 'memory.portrait.addFact.pending' : 'memory.portrait.addFact.success'));
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
        onCompositionStart={() => { composing.current = true; }}
        onCompositionEnd={() => { composing.current = false; }}
        onKeyDown={(event) => {
          if (shouldSubmitOnEnter(event, composing.current)) {
            event.preventDefault();
            void submit();
          }
        }}
        className="h-9 min-w-0 flex-1 rounded-mem-sm border border-transparent bg-[hsl(var(--memory-panel-subtle)/0.4)] px-3 text-sm text-[hsl(var(--memory-title))] outline-hidden transition-colors placeholder:text-[hsl(var(--memory-muted))] hover:bg-[hsl(var(--memory-panel-subtle)/0.6)] focus:bg-[hsl(var(--memory-panel-elevated))] focus:ring-2 focus:ring-[hsl(var(--memory-accent)/0.14)]"
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
