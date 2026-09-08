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
import { MemoryAssertionValueInput } from '@/components/memory/correction/MemoryAssertionValueInput';
import { getAssertionDisplayText } from '@/utils/memory-assertion-copy';

export function PendingMemoryReviewEditDialog({
  review,
  busy,
  onOpenChange,
  onSubmit,
}: {
  review: L2PendingReview | null;
  busy: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (edit: { trait_value: string }) => void;
}) {
  const { t } = useTranslation('app');
  const [traitValue, setTraitValue] = useState('');

  useEffect(() => {
    setTraitValue(String(review?.proposed.trait_value || ''));
  }, [review]);

  const normalizedValue = traitValue.trim();
  const valueOptions = review?.proposed.value_options;
  const validValue = Boolean(normalizedValue)
    && (!valueOptions || valueOptions.includes(normalizedValue));

  return (
    <Dialog open={review !== null} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg" closeLabel={t('common.close')}>
        <DialogHeader>
          <DialogTitle>{t('memory.pending.reviewEdit.title')}</DialogTitle>
          <DialogDescription>{t('memory.pending.reviewEdit.description')}</DialogDescription>
        </DialogHeader>
        <div className="space-y-5 px-6 pb-6 pt-2">
          <div className="space-y-2 rounded-lg bg-muted/50 p-4">
            <p className="text-xs font-medium text-muted-foreground">
              {t('memory.pending.reviewEdit.currentFact')}
            </p>
            <p className="break-words text-sm leading-6 text-foreground">
              {review ? getAssertionDisplayText(review.proposed) : null}
            </p>
          </div>
          <label className="block space-y-2 text-sm font-medium text-foreground">
            <span>{t('memory.pending.reviewEdit.valueLabel')}</span>
            <MemoryAssertionValueInput
              id="pending-memory-review-value"
              value={traitValue}
              valueOptions={valueOptions}
              maxLength={1000}
              disabled={busy}
              onChange={setTraitValue}
            />
          </label>
        </div>
        <DialogFooter>
          <Button type="button" variant="ghost" disabled={busy} onClick={() => onOpenChange(false)}>
            {t('common.cancel')}
          </Button>
          <Button
            type="button"
            disabled={busy || !validValue}
            onClick={() => onSubmit({
              trait_value: normalizedValue,
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
