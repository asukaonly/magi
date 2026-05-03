import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, Loader2 } from 'lucide-react';

import type { CommandDescriptor, CommandParameter } from '@/api';
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
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';

type ToolArgsDialogProps = {
  open: boolean;
  descriptor: CommandDescriptor | null;
  onClose: () => void;
  onRun: (
    descriptor: CommandDescriptor,
    args: Record<string, unknown>,
    invocationText: string,
  ) => Promise<void>;
};

const buildInitial = (descriptor: CommandDescriptor | null): Record<string, string> => {
  if (!descriptor) return {};
  const out: Record<string, string> = {};
  for (const p of descriptor.parameters) {
    if (p.default === undefined || p.default === null) {
      out[p.name] = '';
    } else if (typeof p.default === 'string') {
      out[p.name] = p.default;
    } else if (typeof p.default === 'boolean') {
      out[p.name] = p.default ? 'true' : 'false';
    } else {
      out[p.name] = JSON.stringify(p.default);
    }
  }
  return out;
};

const coerceValue = (
  param: CommandParameter,
  raw: string,
): { value?: unknown; error?: string } => {
  const trimmed = raw.trim();
  if (!trimmed) {
    if (param.required) return { error: 'required' };
    return { value: undefined };
  }
  switch (param.type) {
    case 'string':
      return { value: raw };
    case 'integer': {
      const n = Number(trimmed);
      if (!Number.isInteger(n)) return { error: 'integer' };
      return { value: n };
    }
    case 'float': {
      const n = Number(trimmed);
      if (Number.isNaN(n)) return { error: 'number' };
      return { value: n };
    }
    case 'boolean':
      if (trimmed === 'true') return { value: true };
      if (trimmed === 'false') return { value: false };
      return { error: 'boolean' };
    case 'array':
    case 'object':
      try {
        return { value: JSON.parse(trimmed) };
      } catch {
        return { error: param.type === 'array' ? 'array_json' : 'object_json' };
      }
    default:
      return { value: raw };
  }
};

const formatInvocationText = (
  descriptor: CommandDescriptor,
  args: Record<string, unknown>,
): string => {
  const parts: string[] = [`/${descriptor.name}`];
  for (const p of descriptor.parameters) {
    const value = args[p.name];
    if (value === undefined) continue;
    const formatted =
      typeof value === 'string' ? value : JSON.stringify(value);
    parts.push(`${p.name}=${formatted}`);
  }
  return parts.join(' ');
};

export const ToolArgsDialog = ({
  open,
  descriptor,
  onClose,
  onRun,
}: ToolArgsDialogProps) => {
  const { t } = useTranslation();
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setDraft(buildInitial(descriptor));
      setErrors({});
      setSubmitError(null);
    }
  }, [open, descriptor]);

  const params = useMemo(() => descriptor?.parameters ?? [], [descriptor]);

  const handleSubmit = async () => {
    if (!descriptor) return;
    const out: Record<string, unknown> = {};
    const nextErrors: Record<string, string> = {};
    for (const p of params) {
      const { value, error } = coerceValue(p, draft[p.name] ?? '');
      if (error) {
        nextErrors[p.name] = error;
        continue;
      }
      if (value !== undefined) {
        out[p.name] = value;
      }
    }
    if (Object.keys(nextErrors).length > 0) {
      setErrors(nextErrors);
      return;
    }
    setErrors({});
    setSubmitting(true);
    setSubmitError(null);
    try {
      const invocationText = formatInvocationText(descriptor, out);
      await onRun(descriptor, out, invocationText);
      onClose();
    } catch (exc: any) {
      setSubmitError(exc?.message ?? String(exc));
    } finally {
      setSubmitting(false);
    }
  };

  if (!descriptor) return null;

  return (
    <Dialog open={open} onOpenChange={(next) => (next ? null : onClose())}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            /{descriptor.name}
            {descriptor.dangerous ? (
              <AlertTriangle className="h-4 w-4 text-amber-500" />
            ) : null}
          </DialogTitle>
          <DialogDescription>
            {descriptor.description || t('chat.commands.dialogDescription', {
              defaultValue: 'Provide the arguments for this command. The result will be inserted into the chat timeline.',
            })}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          {params.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              {t('chat.commands.noArguments', { defaultValue: 'This command takes no arguments.' })}
            </p>
          ) : (
            params.map((p) => {
              const errKey = errors[p.name];
              return (
                <label key={p.name} className="block text-sm">
                  <span className="mb-1 flex items-center gap-2 text-muted-foreground">
                    <span className="font-medium text-foreground">{p.name}</span>
                    <span className="text-xs">({p.type})</span>
                    {p.required ? (
                      <span className="text-xs text-destructive">*</span>
                    ) : null}
                  </span>
                  {p.description ? (
                    <span className="mb-1 block text-xs text-muted-foreground/80">{p.description}</span>
                  ) : null}
                  {p.type === 'boolean' ? (
                    <Switch
                      checked={draft[p.name] === 'true'}
                      onCheckedChange={(checked) =>
                        setDraft({ ...draft, [p.name]: checked ? 'true' : 'false' })
                      }
                    />
                  ) : p.type === 'array' || p.type === 'object' ? (
                    <Textarea
                      value={draft[p.name] ?? ''}
                      onChange={(e) => setDraft({ ...draft, [p.name]: e.target.value })}
                      rows={3}
                      className="font-mono text-xs"
                      placeholder={p.type === 'array' ? '["a", "b"]' : '{"key": "value"}'}
                    />
                  ) : (
                    <Input
                      value={draft[p.name] ?? ''}
                      type={p.type === 'integer' || p.type === 'float' ? 'number' : 'text'}
                      onChange={(e) => setDraft({ ...draft, [p.name]: e.target.value })}
                    />
                  )}
                  {errKey ? (
                    <span className="mt-1 block text-xs text-destructive">
                      {t(`chat.commands.errors.${errKey}`, {
                        defaultValue: `Invalid ${errKey}`,
                      })}
                    </span>
                  ) : null}
                </label>
              );
            })
          )}

          {descriptor.dangerous ? (
            <div className="rounded-md border border-amber-500/40 bg-amber-500/10 p-2 text-xs text-amber-700 dark:text-amber-400">
              {t('chat.commands.dangerousNotice', {
                defaultValue: 'This is a dangerous tool. You will be prompted to approve it.',
              })}
            </div>
          ) : null}

          {submitError ? (
            <p className="text-sm text-destructive">{submitError}</p>
          ) : null}
        </div>

        <DialogFooter>
          <DialogClose asChild>
            <Button type="button" variant="outline" disabled={submitting}>
              {t('chat.commands.cancel', { defaultValue: 'Cancel' })}
            </Button>
          </DialogClose>
          <Button type="button" onClick={() => void handleSubmit()} disabled={submitting}>
            {submitting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
            {t('chat.commands.run', { defaultValue: 'Run' })}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
