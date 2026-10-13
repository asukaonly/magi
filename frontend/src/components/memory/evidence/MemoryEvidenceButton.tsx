import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { memoryApi } from '@/api/modules/memory';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { MemoryCorrectionDialog } from '@/components/memory/correction/MemoryCorrectionDialog';
import type { MemoryCorrectionUiTarget } from '@/components/memory/correction/memoryCorrectionModel';
import { getReadablePredicateLabel } from '@/components/memory/l2KnowledgeModelHelpers';
import { getAssertionDisplayText, getAssertionStatusLabel } from '@/utils/memory-assertion-copy';
import { useRequestOwner } from '@/hooks/useRequestOwner';
import { MemoryEvidenceRecords } from './MemoryEvidenceRecords';
import { memoryEvidenceIds, type MemoryEvidenceTarget } from '@/domain/memory/evidence';

type Detail = { title: string; eventIds: string[]; correction: MemoryCorrectionUiTarget | null; status?: string };

export function MemoryEvidenceButton({ target, onChanged, onCorrect, label }: { target: MemoryEvidenceTarget; onChanged?: () => void; onCorrect?: () => void; label?: string }) {
  const { t } = useTranslation('app');
  const [open, setOpen] = useState(false);
  return <>
    <Button type="button" variant="ghost" size="sm" className="h-auto min-h-8 whitespace-normal px-2 text-xs" onClick={() => setOpen(true)}>{label || t('memory.evidence.open')}</Button>
    {open ? <MemoryEvidenceDetail target={target} onChanged={onChanged} onCorrect={onCorrect} onClose={() => setOpen(false)} /> : null}
  </>;
}

function MemoryEvidenceDetail({ target, onChanged, onCorrect, onClose }: { target: MemoryEvidenceTarget; onChanged?: () => void; onCorrect?: () => void; onClose: () => void }) {
  const { t } = useTranslation('app');
  const scope = JSON.stringify(target);
  const ownRequest = useRequestOwner(scope);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [missing, setMissing] = useState(false);
  const [correcting, setCorrecting] = useState(false);
  const [correctionTarget, setCorrectionTarget] = useState<MemoryCorrectionUiTarget | null>(null);
  const load = useCallback(async () => {
    const current = ownRequest('detail');
    setLoading(true);
    setFailed(false);
    setMissing(false);
    setDetail(null);
    try {
      const ref = target.recordRef;
      let next: Detail = { title: target.title, eventIds: memoryEvidenceIds(target.eventIds), correction: null };
      if (ref?.kind === 'assertion') {
        const result = await memoryApi.getL2Assertions({ assertion_id: ref.id, include_inactive: true, limit: 1 });
        const record = result.items.find((item) => item.assertion_id === ref.id);
        if (!record) { if (current()) setMissing(true); }
        else next = {
          title: getAssertionDisplayText(record), eventIds: memoryEvidenceIds(record.evidence_events), status: record.status || record.validation_state,
          correction: { kind: 'assertion', id: record.assertion_id, displaySentence: getAssertionDisplayText(record), editableValue: record.trait_value, traitName: record.trait_name, valueOptions: record.value_options, expectedUpdatedAt: record.updated_at ?? undefined },
        };
      } else if (ref?.kind === 'relationship') {
        const result = await memoryApi.getL2Relations({ triple_id: ref.id, include_inactive: true, limit: 1 });
        const record = result.items.find((item) => item.triple_id === ref.id);
        if (!record) { if (current()) setMissing(true); }
        else {
          const subjectName = record.subject_name || t('memory.evidence.unnamedEntity');
          const objectName = record.object_name || t('memory.evidence.unnamedEntity');
          const predicateLabel = getReadablePredicateLabel(t, record.predicate);
          const title = t('memory.pages.knowledge.readable.relation', { subject: subjectName, predicate: predicateLabel, object: objectName });
          next = { title, eventIds: memoryEvidenceIds(record.evidence_event_ids), status: record.status, correction: {
            kind: 'edge', id: record.triple_id, displaySentence: title, expectedUpdatedAt: record.updated_at,
            relationship: { subjectId: record.subject_id, subjectType: record.subject_type, subjectName, predicate: record.predicate, predicateLabel, objectId: record.object_id, objectType: record.object_type, objectName },
            entityOptions: [{ id: record.subject_id, name: subjectName, type: record.subject_type }, { id: record.object_id, name: objectName, type: record.object_type }],
          } };
        }
      } else if (ref?.kind === 'event') next.eventIds = [ref.id];
      if (current()) setDetail(next);
    } catch { if (current()) setFailed(true); }
    finally { if (current()) setLoading(false); }
  }, [ownRequest, target, t]);
  useEffect(() => { void load(); return () => { ownRequest('detail'); }; }, [load, ownRequest]);
  const changed = () => { onChanged?.(); void load(); };
  return <>
    <Dialog open={!correcting} onOpenChange={(value) => { if (!value) onClose(); }}>
      <DialogContent className="max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t('memory.evidence.title')}</DialogTitle>
          <DialogDescription>{t('memory.evidence.description')}</DialogDescription>
        </DialogHeader>
        <div className="space-y-4 px-6 pb-6">
          <p className="whitespace-pre-wrap wrap-break-word font-medium">{detail?.title || target.title}</p>
          {loading ? <p role="status">{t('memory.identity.loading')}</p> : null}
          {failed ? <div role="alert"><p>{t('memory.evidence.loadFailed')}</p><Button variant="outline" onClick={() => { void load(); }}>{t('common.retry')}</Button></div> : null}
          {missing ? <p className="text-sm text-muted-foreground">{t('memory.evidence.recordUnavailable')}</p> : null}
          {detail ? <>
            {detail.status ? <p className="text-xs text-muted-foreground">{getAssertionStatusLabel(detail.status, t)}</p> : null}
            {detail.correction ? <Button variant="outline" onClick={() => { setCorrectionTarget(detail.correction); setCorrecting(true); }}>{t('memory.evidence.correct')}</Button> : null}
            {!detail.correction && onCorrect ? <Button variant="outline" onClick={() => { onClose(); onCorrect(); }}>{t('memory.pending.actions.editReview')}</Button> : null}
            <MemoryEvidenceRecords eventIds={detail.eventIds} onChanged={changed} />
          </> : null}
        </div>
      </DialogContent>
    </Dialog>
    <MemoryCorrectionDialog open={correcting} target={correctionTarget} onOpenChange={setCorrecting} onSaved={changed} onConflict={changed} />
  </>;
}
