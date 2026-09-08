import { EntityEvidence } from './EntityEvidence';
import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { entityIdentityApi, type EntityTypeReview, type IdentityEntity, type IdentityWire } from '@/api/modules/entityIdentity';
import { memoryApi } from '@/api/modules/memory';
import { toApiClientError } from '@/api/client';
import { useRequestOwner } from '@/hooks/useRequestOwner';
import { asEventHandler } from '@/utils/as-event-handler';
import { canChangeEntityIdentity, EXTRACTABLE_ENTITY_TYPES, getEntityTypeLabel } from '@/utils/entity-types';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';

export function EntityIdentityDialog({ entity, review, initialTarget, onClose, onSaved }: {
  entity: IdentityEntity;
  review?: EntityTypeReview;
  initialTarget?: IdentityEntity;
  onClose: () => void;
  onSaved: () => void | Promise<void>;
}) {
  const { t } = useTranslation('app');
  const [kind, setKind] = useState<'type_correction' | 'merge'>(initialTarget ? 'merge' : 'type_correction');
  const [newType, setNewType] = useState(review?.proposed_type ?? entity.entity_type);
  const [target, setTarget] = useState<IdentityEntity | null>(initialTarget ?? null);
  const [query, setQuery] = useState('');
  const [searchOffset, setSearchOffset] = useState(0);
  const [searchTotal, setSearchTotal] = useState(0);
  const [candidates, setCandidates] = useState<IdentityEntity[]>([]);
  const [searchLoading, setSearchLoading] = useState(false);
  const [searchError, setSearchError] = useState(false);
  const [searchVersion, setSearchVersion] = useState(0);
  const [preview, setPreview] = useState<IdentityWire<'EntityChangePreview'> | null>(null);
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(false);
  const [error, setError] = useState<string | null>(null);
  const requestId = useRef(crypto.randomUUID());
  const ownRequest = useRequestOwner(entity.entity_id);

  useEffect(() => {
    const isCurrent = ownRequest('search');
    if (kind !== 'merge') return;
    setSearchLoading(true);
    if (searchOffset === 0) setCandidates([]);
    const timer = setTimeout(() => {
      void memoryApi.getL2Entities({ query, limit: 50, offset: searchOffset }).then((result) => {
        if (!isCurrent()) return;
        const eligible = result.items.filter((item) => item.entity_id !== entity.entity_id && canChangeEntityIdentity(item));
        setCandidates((items) => searchOffset === 0 ? eligible : [...items, ...eligible]);
        setSearchTotal(result.total);
        setSearchError(false);
      }).catch(() => {
        if (isCurrent()) setSearchError(true);
      }).finally(() => {
        if (isCurrent()) setSearchLoading(false);
      });
    }, 200);
    return () => { clearTimeout(timer); ownRequest('search'); };
  }, [kind, query, entity.entity_id, ownRequest, searchVersion, searchOffset]);

  const inspect = async () => {
    if (inFlight.current) return;
    const isCurrent = ownRequest('change');
    inFlight.current = true;
    setBusy(true);
    setError(null);
    try {
      const result = await entityIdentityApi.preview({
        kind, entity_id: entity.entity_id,
        target_entity_id: kind === 'merge' ? target?.entity_id ?? null : null,
        new_type: kind === 'type_correction' ? newType : null,
        review_id: kind === 'type_correction' ? review?.review_id ?? null : null,
      });
      if (!isCurrent()) return;
      requestId.current = crypto.randomUUID();
      setPreview(result);
    } catch {
      if (isCurrent()) setError(t('memory.identity.previewFailed'));
    } finally {
      inFlight.current = false;
      if (isCurrent()) setBusy(false);
    }
  };

  const apply = async () => {
    if (!preview || inFlight.current) return;
    const isCurrent = ownRequest('change');
    inFlight.current = true;
    setBusy(true);
    setError(null);
    try {
      await entityIdentityApi.apply(preview, requestId.current);
    } catch (cause) {
      if (isCurrent()) {
        const stale = toApiClientError(cause).status === 409;
        setError(t(stale ? 'memory.identity.stale' : 'memory.identity.applyFailed'));
        if (stale) setPreview(null);
        setBusy(false);
      }
      inFlight.current = false;
      return;
    }
    if (!isCurrent()) return;
    toast.success(t('memory.identity.saved'));
    try { await onSaved(); }
    catch { toast.warning(t('memory.identity.refreshFailed')); }
    finally { inFlight.current = false; if (isCurrent()) { setBusy(false); onClose(); } }
  };

  const describe = (item: IdentityEntity) => `${item.canonical_name} · ${getEntityTypeLabel(item.entity_type, t)}`;
  return (
    <Dialog open onOpenChange={(open) => { if (!open && !inFlight.current) onClose(); }}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{t('memory.identity.title')}</DialogTitle>
          <DialogDescription>{describe(entity)}</DialogDescription>
        </DialogHeader>
        {preview ? (
          <div className="space-y-4">
            <p>{preview.target
              ? t('memory.identity.mergePreview', { source: describe(preview.entity), target: describe(preview.target) })
              : t('memory.identity.typePreview', { name: preview.entity.canonical_name, from: getEntityTypeLabel(preview.entity.entity_type, t), to: getEntityTypeLabel(preview.command.new_type, t) })}</p>
            <p className="text-sm text-muted-foreground">{t('memory.identity.impact', preview.impact)}</p>
            {[preview.entity, ...(preview.target ? [preview.target] : [])].map((item) => <div key={item.entity_id} className="space-y-2"><p className="font-medium">{describe(item)}</p><EntityEvidence eventIds={preview.evidence_event_ids[item.entity_id] ?? []} /></div>)}
            {preview.correction_history_may_block_revert ? <p className="text-sm">{t('memory.identity.correctionImpact')}</p> : null}
          </div>
        ) : (
          <fieldset disabled={busy} className="space-y-4">
            {!review ? <div className="flex gap-2">
              <Button type="button" variant={kind === 'type_correction' ? 'default' : 'outline'} onClick={() => { setKind('type_correction'); setError(null); }}>{t('memory.identity.typeAction')}</Button>
              <Button type="button" variant={kind === 'merge' ? 'default' : 'outline'} onClick={() => { setKind('merge'); setError(null); }}>{t('memory.identity.mergeAction')}</Button>
            </div> : null}
            {kind === 'type_correction' ? <label className="block space-y-2">
              <span>{t('memory.identity.newType')}</span>
              <select aria-label={t('memory.identity.newType')} disabled={Boolean(review)} value={newType} onChange={(event) => setNewType(event.target.value)} className="block w-full rounded-md border bg-background p-2">
                {EXTRACTABLE_ENTITY_TYPES.map((item) => <option key={item.key} value={item.key}>{getEntityTypeLabel(item.key, t)}</option>)}
              </select>
            </label> : <div className="space-y-3">
              <p className="text-sm text-muted-foreground">{t('memory.identity.mergeHelp')}</p>
              <label className="block space-y-2"><span>{t('memory.identity.search')}</span><Input value={query} onChange={(event) => { setQuery(event.target.value); setSearchOffset(0); }} /></label>
              {target ? <p>{t('memory.identity.selected', { name: describe(target) })}</p> : null}
              {searchError ? <div role="alert">{t('memory.identity.searchFailed')} <Button variant="outline" onClick={() => setSearchVersion((value) => value + 1)}>{t('memory.identity.retry')}</Button></div> : null}
              {searchLoading ? <p role="status">{t('memory.identity.loading')}</p> : <div className="max-h-48 space-y-1 overflow-y-auto" aria-label={t('memory.identity.candidates')}>
                {candidates.map((item, index) => <Button key={item.entity_id} type="button" variant={target?.entity_id === item.entity_id ? 'secondary' : 'ghost'} className="h-auto w-full justify-start whitespace-normal text-left" aria-pressed={target?.entity_id === item.entity_id} onClick={() => setTarget(item)}>{candidates.filter((candidate) => describe(candidate) === describe(item)).length > 1 ? t('memory.identity.auditEntry', { name: item.canonical_name, type: getEntityTypeLabel(item.entity_type, t), index: index + 1 }) : describe(item)}</Button>)}
                {!searchError && candidates.length === 0 ? <p>{t('memory.identity.noCandidates')}</p> : null}
              </div>}
              {searchOffset + 50 < searchTotal ? <Button variant="outline" disabled={searchLoading} onClick={() => setSearchOffset((value) => value + 50)}>{t('memory.identity.loadMore')}</Button> : null}
            </div>}
          </fieldset>
        )}
        {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
        <DialogFooter>
          <Button variant="outline" disabled={busy} onClick={() => { if (preview) { setPreview(null); setError(null); } else onClose(); }}>{t(preview ? 'memory.identity.back' : 'memory.identity.cancel')}</Button>
          <Button disabled={busy || (!preview && (kind === 'merge' ? !target : newType === entity.entity_type))} onClick={asEventHandler(preview ? apply : inspect)}>{t(busy ? 'memory.identity.working' : preview ? 'memory.identity.confirm' : 'memory.identity.preview')}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
