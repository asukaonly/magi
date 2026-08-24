import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2, Sparkles } from 'lucide-react';

import type { SkillCommandDescriptor } from '@/api';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';

type SkillArgsDialogProps = {
  open: boolean;
  descriptor: SkillCommandDescriptor | null;
  onClose: () => void;
  onSubmit: (
    descriptor: SkillCommandDescriptor,
    argsText: string,
  ) => Promise<
    | { kind: 'accepted' }
    | { kind: 'not_sent'; message: string }
  >;
};

export const SkillArgsDialog = ({
  open,
  descriptor,
  onClose,
  onSubmit,
}: SkillArgsDialogProps) => {
  const { t } = useTranslation();
  const [argsText, setArgsText] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setArgsText('');
      setError(null);
    }
  }, [open, descriptor]);

  if (!descriptor) return null;

  const handleSubmit = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const outcome = await onSubmit(descriptor, argsText);
      if (outcome.kind === 'not_sent') {
        setError(outcome.message);
        return;
      }
      onClose();
    } catch (exc: any) {
      setError(exc?.message ?? String(exc));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(next) => (next ? null : onClose())}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-primary" />
            /{descriptor.name}
          </DialogTitle>
          <DialogDescription>
            {descriptor.description ||
              t('chat.skills.dialogDescription', {
                defaultValue:
                  'Provide arguments for this skill. The skill will be attached to your next agent run.',
              })}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <label className="block text-sm">
            <span className="mb-1 block text-muted-foreground">
              {t('chat.skills.argsLabel', { defaultValue: 'Arguments' })}
              {descriptor.argument_hint ? (
                <span className="ml-2 font-mono text-xs">
                  {descriptor.argument_hint}
                </span>
              ) : null}
            </span>
            <Input
              value={argsText}
              onChange={(e) => setArgsText(e.target.value)}
              placeholder={descriptor.argument_hint ?? ''}
              autoFocus
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  void handleSubmit();
                }
              }}
            />
          </label>

          {error ? <p className="text-sm text-destructive">{error}</p> : null}

          {descriptor.context_mode === 'fork' ? (
            <div className="rounded-md border border-border/50 bg-muted/40 p-2 text-xs text-muted-foreground">
              {t('chat.skills.forkNotice', {
                defaultValue:
                  'This skill runs as a background task. The result will appear here when finished — you can keep chatting in the meantime.',
              })}
            </div>
          ) : null}
        </div>

        <DialogFooter>
          <DialogClose asChild>
            <Button type="button" variant="outline" disabled={submitting}>
              {t('chat.skills.cancel', { defaultValue: 'Cancel' })}
            </Button>
          </DialogClose>
          <Button type="button" onClick={() => void handleSubmit()} disabled={submitting}>
            {submitting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
            {t('chat.skills.send', { defaultValue: 'Send' })}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
