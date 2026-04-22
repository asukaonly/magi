/**
 * Modal that prompts the user to allow or deny a pending tool call.
 *
 * Consumers pass a ``PendingPermissionDTO``; the component handles
 * posting the response via ``respondPermission`` and calls
 * ``onResolved`` once the server acknowledges.
 */
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import {
  PendingPermissionDTO,
  PermissionRespondInput,
  PermissionScope,
  respondPermission,
} from '@/api/modules/control';

export interface PermissionModalProps {
  request: PendingPermissionDTO | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onResolved?: (requestId: string, outcome: 'allow' | 'deny') => void;
}

const SCOPES: PermissionScope[] = [
  'one_shot',
  'session',
  'persistent_exact',
  'persistent_pattern',
];

export function PermissionModal({
  request,
  open,
  onOpenChange,
  onResolved,
}: PermissionModalProps) {
  const { t } = useTranslation('control');
  const [scope, setScope] = useState<PermissionScope>('one_shot');
  const [pattern, setPattern] = useState('');
  const [reason, setReason] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const riskLabel = useMemo(() => {
    if (!request) return '';
    const key = `permission.risk_${request.risk_level.toLowerCase()}`;
    return t(key, { defaultValue: request.risk_level });
  }, [request, t]);

  const argsPreview = useMemo(() => {
    if (!request) return '';
    try {
      return JSON.stringify(request.tool_args, null, 2);
    } catch {
      return String(request.tool_args);
    }
  }, [request]);

  const submit = async (outcome: 'allow' | 'deny') => {
    if (!request) return;
    setSubmitting(true);
    setError(null);
    const payload: PermissionRespondInput = { outcome, scope };
    if (scope === 'persistent_pattern' && pattern.trim()) {
      payload.pattern = pattern.trim();
    }
    if (reason.trim()) {
      payload.reason = reason.trim();
    }
    try {
      await respondPermission(request.request_id, payload);
      onResolved?.(request.request_id, outcome);
      onOpenChange(false);
      // reset local state for the next prompt
      setScope('one_shot');
      setPattern('');
      setReason('');
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  if (!request) return null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl" data-testid="permission-modal">
        <DialogHeader>
          <DialogTitle>{t('permission.title')}</DialogTitle>
          <DialogDescription>{t('permission.subtitle')}</DialogDescription>
        </DialogHeader>
        <div className="space-y-3 text-sm">
          <div className="flex items-center gap-2">
            <span className="text-muted-foreground">
              {t('permission.tool')}:
            </span>
            <code className="rounded bg-muted px-2 py-0.5 font-mono">
              {request.tool}
            </code>
            <Badge
              variant={
                request.risk_level.toLowerCase() === 'high'
                  ? 'destructive'
                  : 'secondary'
              }
            >
              {riskLabel}
            </Badge>
          </div>
          {request.origin && (
            <div className="text-muted-foreground">
              {t('permission.origin')}: {request.origin}
            </div>
          )}
          <div>
            <div className="mb-1 text-muted-foreground">
              {t('permission.tool_args')}
            </div>
            <pre className="max-h-48 overflow-auto rounded bg-muted p-2 text-xs">
              {argsPreview}
            </pre>
          </div>
          <div>
            <div className="mb-1 text-muted-foreground">
              {t('permission.scope')}
            </div>
            <div className="flex flex-wrap gap-2">
              {SCOPES.map((s) => (
                <Button
                  key={s}
                  type="button"
                  size="sm"
                  variant={scope === s ? 'default' : 'outline'}
                  onClick={() => setScope(s)}
                  data-testid={`scope-${s}`}
                >
                  {t(`permission.scope_${s}`)}
                </Button>
              ))}
            </div>
          </div>
          {scope === 'persistent_pattern' && (
            <div>
              <label className="mb-1 block text-muted-foreground">
                {t('permission.pattern_label')}
              </label>
              <Input
                value={pattern}
                onChange={(e) => setPattern(e.target.value)}
                placeholder={t('permission.pattern_placeholder') ?? ''}
                data-testid="pattern-input"
              />
            </div>
          )}
          <div>
            <label className="mb-1 block text-muted-foreground">
              {t('permission.reason_label')}
            </label>
            <Textarea
              rows={2}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder={t('permission.reason_placeholder') ?? ''}
            />
          </div>
          {error && <div className="text-sm text-destructive">{error}</div>}
        </div>
        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => submit('deny')}
            disabled={submitting}
            data-testid="deny-btn"
          >
            {t('permission.deny')}
          </Button>
          <Button
            onClick={() => submit('allow')}
            disabled={submitting}
            data-testid="allow-btn"
          >
            {t('permission.allow')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
