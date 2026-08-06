import { useEffect, useState } from 'react';
import { Loader2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { L2PendingReview } from '@/api/modules/memory';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';

export function PendingMemoryReviewEditDialog({
  review,
  busy,
  onOpenChange,
  onSubmit,
}: {
  review: L2PendingReview | null;
  busy: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (edit: { trait_value: string; natural_summary?: string }) => void;
}) {
  const { t } = useTranslation('app');
  const [traitValue, setTraitValue] = useState('');
  const [naturalSummary, setNaturalSummary] = useState('');

  useEffect(() => {
    setTraitValue(String(review?.proposed.trait_value || ''));
    setNaturalSummary(String(review?.proposed.natural_summary || ''));
  }, [review]);

  const normalizedValue = traitValue.trim();
  const normalizedSummary = naturalSummary.trim();

  return (
    <Dialog open={review !== null} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg" closeLabel={t('common.close')}>
        <DialogHeader>
          <DialogTitle>{t('memory.pending.reviewEdit.title')}</DialogTitle>
          <DialogDescription>{t('memory.pending.reviewEdit.description')}</DialogDescription>
        </DialogHeader>
        <div className="space-y-5 px-6 pb-6 pt-2">
          <label className="block space-y-2 text-sm font-medium text-foreground">
            <span>{t('memory.pending.reviewEdit.valueLabel')}</span>
            <Input
              value={traitValue}
              maxLength={1000}
              disabled={busy}
              onChange={(event) => setTraitValue(event.target.value)}
            />
          </label>
          <label className="block space-y-2 text-sm font-medium text-foreground">
            <span>{t('memory.pending.reviewEdit.summaryLabel')}</span>
            <Textarea
              value={naturalSummary}
              maxLength={500}
              disabled={busy}
              placeholder={t('memory.pending.reviewEdit.summaryPlaceholder')}
              onChange={(event) => setNaturalSummary(event.target.value)}
            />
          </label>
        </div>
        <DialogFooter>
          <Button type="button" variant="ghost" disabled={busy} onClick={() => onOpenChange(false)}>
            {t('common.cancel')}
          </Button>
          <Button
            type="button"
            disabled={busy || !normalizedValue}
            onClick={() => onSubmit({
              trait_value: normalizedValue,
              ...(normalizedSummary ? { natural_summary: normalizedSummary } : {}),
            })}
          >
            {busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
            {t('memory.pending.reviewEdit.confirm')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
