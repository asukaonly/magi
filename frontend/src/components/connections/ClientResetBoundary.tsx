import { useEffect, useSyncExternalStore, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { PreAppWindowFrame } from '@/components/layout/PreAppWindowFrame';
import { inspectClientReset, performClientReset, readClientResetPhase, reopenClientWelcome,
  requestClientReset, subscribeClientReset } from '@/runtime/client-reset';

export function ClientResetBoundary({ children }: { children: ReactNode }) {
  const { t } = useTranslation('app');
  const phase = useSyncExternalStore(subscribeClientReset, readClientResetPhase);
  useEffect(() => { void inspectClientReset(); }, []);
  useEffect(() => {
    if (phase === 'resetting') void performClientReset();
    if (phase === 'complete') reopenClientWelcome();
  }, [phase]);
  if (phase === 'idle') return children;
  const pending = phase === 'checking' || phase === 'resetting';
  const title = phase === 'checking' ? 'clientReset.checkTitle' : phase === 'check_failed' ? 'clientReset.checkFailed'
    : pending ? 'clientReset.progress' : phase === 'complete' ? 'clientReset.complete' : 'clientReset.failed';
  return <PreAppWindowFrame>
    <div className="flex min-h-full items-center justify-center p-8">
      <section className="w-full max-w-lg space-y-4" aria-busy={pending}>
        <h1 className="flex items-center gap-3 text-xl font-semibold" role="status">
          {pending && <Loader2 className="h-5 w-5 animate-spin" aria-hidden="true" />}{t(title)}
        </h1>
        <p className="text-sm leading-6 text-muted-foreground">{t(phase === 'checking' || phase === 'check_failed'
          ? 'clientReset.checkHint' : phase === 'failed' ? 'clientReset.failedHint' : 'clientReset.progressHint')}</p>
        {!pending && <Button onClick={() => {
          if (phase === 'check_failed') void inspectClientReset();
          else if (phase === 'complete') reopenClientWelcome();
          else requestClientReset();
        }}>{t(phase === 'complete' ? 'clientReset.returnWelcome' : 'clientReset.retry')}</Button>}
      </section>
    </div>
  </PreAppWindowFrame>;
}
