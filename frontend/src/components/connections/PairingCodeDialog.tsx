import { useEffect, useId, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Check, Copy, Plus } from 'lucide-react';
import { serverApi } from '@/api/modules/server';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { getRuntimeConfig } from '@/runtime/config';

type Grant = Awaited<ReturnType<typeof serverApi.pairingGrant>> & { address: string; loopback: boolean };

/** Keep generated credentials scoped to the open pairing dialog. */
export function PairingCodeDialog({ disabled = false }: { disabled?: boolean }) {
  const { t, i18n } = useTranslation('app');
  const [open, setOpen] = useState(false);
  const [grant, setGrant] = useState<Grant | null>(null);
  const [pending, setPending] = useState(false);
  const [expired, setExpired] = useState(false);
  const [copied, setCopied] = useState<'address' | 'code' | null>(null);
  const [error, setError] = useState<'generate' | 'copy' | null>(null);
  const owner = useRef(0);
  const actionPending = useRef(false);
  const codeRef = useRef<HTMLTextAreaElement>(null);
  const id = useId();

  useEffect(() => () => { owner.current += 1; }, []);
  useEffect(() => {
    if (!grant) return;
    codeRef.current?.focus({ preventScroll: true });
    const timer = window.setTimeout(() => {
      setGrant(null);
      setCopied(null);
      setExpired(true);
    }, Math.max(0, grant.expires_at_ms - Date.now()));
    return () => window.clearTimeout(timer);
  }, [grant]);

  const generate = async () => {
    if (actionPending.current) return;
    actionPending.current = true;
    const request = ++owner.current;
    setPending(true); setError(null); setExpired(false); setCopied(null); setGrant(null);
    try {
      const address = new URL(getRuntimeConfig().apiBaseUrl);
      const next = await serverApi.pairingGrant();
      if (request !== owner.current) return;
      if (next.expires_at_ms <= Date.now()) { setExpired(true); return; }
      setGrant({ ...next, address: address.origin, loopback: ['127.0.0.1', 'localhost', '[::1]'].includes(address.hostname) });
    } catch {
      if (request === owner.current) setError('generate');
    } finally {
      if (request === owner.current) { actionPending.current = false; setPending(false); }
    }
  };

  const changeOpen = (next: boolean) => {
    setOpen(next);
    if (next) { void generate(); return; }
    owner.current += 1;
    actionPending.current = false;
    setGrant(null); setCopied(null); setError(null); setPending(false); setExpired(false);
  };

  const copy = async (field: 'address' | 'code') => {
    if (!grant) return;
    const request = owner.current;
    try {
      await navigator.clipboard.writeText(field === 'address' ? grant.address : grant.pairing_token);
      if (request === owner.current) { setCopied(field); setError(null); }
    } catch {
      if (request === owner.current) setError('copy');
    }
  };

  return <Dialog open={open} onOpenChange={changeOpen}>
    <DialogTrigger asChild>
      <Button variant="outline" size="sm" disabled={disabled} className="shrink-0">
        <Plus className="mr-1.5 h-4 w-4" aria-hidden="true" />{t('connections.access.createCode')}
      </Button>
    </DialogTrigger>
    <DialogContent className="flex max-h-[calc(100dvh-2rem)] w-[calc(100%-2rem)] max-w-lg flex-col overflow-hidden"
      onOpenAutoFocus={(event) => {
        if (codeRef.current) { event.preventDefault(); codeRef.current.focus({ preventScroll: true }); }
      }}>
      <DialogHeader className="shrink-0 pr-14">
        <DialogTitle>{t('connections.access.pairingTitle')}</DialogTitle>
        <DialogDescription className="leading-6">{t('connections.access.pairingDescription')}</DialogDescription>
      </DialogHeader>
      <div className="min-h-0 space-y-5 overflow-y-auto px-6 pb-6">
        {pending ? <p role="status" className="py-6 text-sm text-muted-foreground">{t('connections.access.generating')}</p> : null}
        {grant ? <>
          <div className="space-y-2">
            <div className="flex items-center justify-between gap-3">
              <label htmlFor={`${id}-code`} className="text-sm font-medium">{t('connections.pairingCode')}</label>
              <Button variant="ghost" size="sm" onClick={() => { void copy('code'); }}>
                {copied === 'code' ? <Check className="mr-1.5 h-4 w-4" aria-hidden="true" /> : <Copy className="mr-1.5 h-4 w-4" aria-hidden="true" />}
                {t(copied === 'code' ? 'connections.access.copied' : 'connections.access.copy')}
              </Button>
            </div>
            <textarea ref={codeRef} id={`${id}-code`} readOnly autoComplete="off" spellCheck={false} rows={3}
              aria-describedby={`${id}-expiry`} value={grant.pairing_token}
              className="block w-full resize-none rounded-xl border border-primary/20 bg-primary/5 p-4 font-mono text-base leading-7 text-foreground outline-hidden focus-visible:ring-2 focus-visible:ring-primary/20" />
            <p id={`${id}-expiry`} className="text-xs leading-5 text-muted-foreground">{t('connections.access.expiresAt', { time: new Date(grant.expires_at_ms).toLocaleTimeString(i18n?.language, { hour: '2-digit', minute: '2-digit' }) })}</p>
          </div>
          <div className="space-y-2">
            <label htmlFor={`${id}-address`} className="text-sm font-medium">{t('connections.address')}</label>
            <div className="flex flex-wrap gap-2">
              <Input id={`${id}-address`} className="min-w-0 flex-1 basis-48" readOnly value={grant.address} />
              <Button variant="outline" onClick={() => { void copy('address'); }}>{t(copied === 'address' ? 'connections.access.copied' : 'connections.access.copyAddress')}</Button>
            </div>
            {grant.loopback ? <p className="text-xs leading-5 text-muted-foreground">{t('connections.access.localAddressHint')}</p> : null}
          </div>
          <p className="text-xs leading-5 text-muted-foreground">{t('connections.access.codeHint')}</p>
        </> : null}
        {expired ? <p role="status" className="text-sm text-muted-foreground">{t('connections.access.expired')}</p> : null}
        {error ? <p role="alert" className="text-sm text-destructive">{t(error === 'generate' ? 'connections.access.generateFailed' : 'connections.access.copyFailed')}</p> : null}
      </div>
      <DialogFooter className="shrink-0">
        {(expired || error === 'generate') ? <Button variant="outline" onClick={() => { void generate(); }}>{t('connections.access.regenerate')}</Button> : null}
        <Button onClick={() => changeOpen(false)}>{t('common.close')}</Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>;
}
