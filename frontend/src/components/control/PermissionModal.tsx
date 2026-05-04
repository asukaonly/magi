/**
 * Modal that prompts the user to allow or deny a pending tool call.
 *
 * Consumers pass a ``PendingPermissionDTO``; the component handles
 * posting the response via ``respondPermission`` and calls
 * ``onResolved`` once the server acknowledges.
 */
import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, Check, ChevronDown } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import {
  PendingPermissionDTO,
  PermissionRespondInput,
  PermissionScope,
  respondPermission,
} from '@/api/modules/control';
import { cn } from '@/lib/utils';

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

const DEFAULT_SCOPE: PermissionScope = 'one_shot';

type PermissionAction = 'allow' | 'deny';

export function PermissionModal({
  request,
  open,
  onOpenChange,
  onResolved,
}: PermissionModalProps) {
  const { t } = useTranslation('control');
  const [allowScope, setAllowScope] = useState<PermissionScope>(DEFAULT_SCOPE);
  const [denyScope, setDenyScope] = useState<PermissionScope>(DEFAULT_SCOPE);
  const [pattern, setPattern] = useState('');
  const [reason, setReason] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || !request) return;
    setAllowScope(DEFAULT_SCOPE);
    setDenyScope(DEFAULT_SCOPE);
    setPattern('');
    setReason('');
    setError(null);
  }, [open, request?.request_id]);

  const riskLabel = useMemo(() => {
    if (!request) return '';
    const key = `permission.risk_${request.risk_level.toLowerCase()}`;
    return t(key, { defaultValue: request.risk_level });
  }, [request, t]);

  const argsPreview = useMemo(() => {
    if (!request) return '';
    try {
      return JSON.stringify(request.arguments, null, 2);
    } catch {
      return String(request.arguments);
    }
  }, [request]);

  const patternRequired = useMemo(
    () => allowScope === 'persistent_pattern' || denyScope === 'persistent_pattern',
    [allowScope, denyScope],
  );

  const submit = async (outcome: PermissionAction, scope: PermissionScope) => {
    if (!request) return;
    if (scope === 'persistent_pattern' && !pattern.trim()) {
      setError(t('permission.pattern_required'));
      return;
    }
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
      setAllowScope(DEFAULT_SCOPE);
      setDenyScope(DEFAULT_SCOPE);
      setPattern('');
      setReason('');
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  const actionTone = (action: PermissionAction) => {
    if (action === 'allow') {
      return {
        panel: 'border-emerald-200/80 bg-emerald-50/70',
        note: 'text-emerald-700',
        button: 'default' as const,
        itemHover: 'focus:bg-emerald-50/80 focus:text-foreground',
      };
    }

    return {
      panel: 'border-rose-200/80 bg-rose-50/70',
      note: 'text-rose-700',
      button: 'destructive' as const,
      itemHover: 'focus:bg-rose-50/80 focus:text-foreground',
    };
  };

  const renderActionCard = (
    action: PermissionAction,
    scope: PermissionScope,
    setScope: (next: PermissionScope) => void,
  ) => {
    const tone = actionTone(action);

    return (
      <div className={cn('rounded-2xl border p-3.5 shadow-sm', tone.panel)}>
        <div className="space-y-1">
          <div className="flex items-center justify-between gap-3">
            <p className="text-sm font-semibold text-foreground">
              {t(`permission.${action}`)}
            </p>
            <Badge variant="secondary" className="bg-background/80 text-foreground">
              {t(`permission.scope_short_${scope}`)}
            </Badge>
          </div>
          <p className={cn('text-xs', tone.note)}>
            {t(`permission.${action}_scope_${scope}`)}
          </p>
          <p className="text-xs text-muted-foreground">
            {t(`permission.scope_description_${scope}`)}
          </p>
        </div>
        <div className="mt-3.5 flex items-stretch">
          <Button
            variant={tone.button}
            size="sm"
            className="h-9 flex-1 rounded-r-none px-3 text-sm"
            onClick={() => submit(action, scope)}
            disabled={submitting}
            data-testid={`${action}-btn`}
          >
            {t(`permission.${action}`)}
          </Button>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant={tone.button}
                size="sm"
                className="h-9 w-10 rounded-l-none border-l border-background/20 px-0"
                disabled={submitting}
                aria-label={t(`permission.${action}_scope_menu`)}
                data-testid={`${action}-scope-trigger`}
              >
                <ChevronDown className="h-4 w-4" aria-hidden="true" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent
              align="end"
              className="w-72 border border-border/80 bg-background p-1.5 shadow-2xl backdrop-blur-none"
            >
              {SCOPES.map((candidate) => (
                <DropdownMenuItem
                  key={candidate}
                  onSelect={() => {
                    setScope(candidate);
                    setError(null);
                  }}
                  className={cn(
                    'rounded-xl px-3 py-2.5 focus:bg-muted/70 focus:text-foreground',
                    tone.itemHover,
                  )}
                  data-testid={`${action}-scope-${candidate}`}
                >
                  <Check
                    className={cn(
                      'h-4 w-4 text-primary transition-opacity',
                      scope === candidate ? 'opacity-100' : 'opacity-0',
                    )}
                    aria-hidden="true"
                  />
                  <div className="min-w-0">
                    <div className="truncate font-medium text-foreground">
                      {t(`permission.${action}_scope_${candidate}`)}
                    </div>
                    <div className="mt-0.5 truncate text-xs text-muted-foreground">
                      {t(`permission.scope_description_${candidate}`)}
                    </div>
                  </div>
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>
    );
  };

  if (!request) return null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="overflow-hidden border-border/70 bg-background p-0 shadow-2xl sm:max-w-2xl"
        data-testid="permission-modal"
      >
        <DialogHeader className="border-b border-border/60 bg-gradient-to-br from-amber-50 via-background to-background px-6 py-5 text-left">
          <div className="flex items-start gap-4">
            <div className="mt-0.5 flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-amber-100 text-amber-700">
              <AlertTriangle className="h-5 w-5" aria-hidden="true" />
            </div>
            <div className="min-w-0 space-y-2">
              <DialogTitle className="text-xl font-semibold tracking-tight">
                {t('permission.title')}
              </DialogTitle>
              <DialogDescription className="max-w-xl text-sm leading-6 text-muted-foreground">
                {t('permission.subtitle')}
              </DialogDescription>
              <div className="flex flex-wrap items-center gap-2 pt-1">
                <Badge variant="secondary" className="gap-1.5 rounded-full px-3 py-1 font-medium">
                  <span className="text-muted-foreground">{t('permission.tool')}</span>
                  <code className="font-mono text-xs">{request.tool_name}</code>
                </Badge>
                <Badge
                  variant={request.risk_level.toLowerCase() === 'high' ? 'destructive' : 'secondary'}
                  className="rounded-full px-3 py-1 font-medium"
                >
                  {riskLabel}
                </Badge>
                {request.origin ? (
                  <Badge variant="outline" className="rounded-full px-3 py-1 font-medium">
                    <span className="text-muted-foreground">{t('permission.origin')}</span>
                    <span>{request.origin}</span>
                  </Badge>
                ) : null}
              </div>
            </div>
          </div>
        </DialogHeader>
        <div className="space-y-5 px-6 py-5 text-sm">
          {request.preview ? (
            <section className="rounded-2xl border border-border/60 bg-muted/30 p-4">
              <div className="mb-2 text-xs font-medium uppercase tracking-[0.16em] text-muted-foreground">
                {t('permission.preview')}
              </div>
              <pre className="whitespace-pre-wrap break-words text-sm leading-6 text-foreground">
                {request.preview}
              </pre>
            </section>
          ) : null}
          <section className="rounded-2xl border border-border/60 bg-muted/20 p-4">
            <div className="mb-2 text-xs font-medium uppercase tracking-[0.16em] text-muted-foreground">
              {t('permission.tool_args')}
            </div>
            <pre className="max-h-64 overflow-auto rounded-xl bg-background/80 p-3 text-xs leading-6 text-foreground shadow-inner">
              {argsPreview}
            </pre>
          </section>
          <section className="grid gap-4 sm:grid-cols-2">
            {renderActionCard('allow', allowScope, setAllowScope)}
            {renderActionCard('deny', denyScope, setDenyScope)}
          </section>
          {patternRequired ? (
            <section className="rounded-2xl border border-border/60 bg-background p-4 shadow-sm">
              <label className="mb-2 block text-sm font-medium text-foreground">
                {t('permission.pattern_label')}
              </label>
              <Input
                value={pattern}
                onChange={(e) => setPattern(e.target.value)}
                placeholder={t('permission.pattern_placeholder') ?? ''}
                data-testid="pattern-input"
              />
              <p className="mt-2 text-xs text-muted-foreground">
                {t('permission.pattern_help')}
              </p>
            </section>
          ) : null}
          <section className="rounded-2xl border border-border/60 bg-background p-4 shadow-sm">
            <label className="mb-2 block text-sm font-medium text-foreground">
              {t('permission.reason_label')}
            </label>
            <Textarea
              rows={3}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder={t('permission.reason_placeholder') ?? ''}
            />
            <p className="mt-2 text-xs text-muted-foreground">
              {t('permission.reason_help')}
            </p>
          </section>
          {error && <div className="text-sm text-destructive">{error}</div>}
        </div>
      </DialogContent>
    </Dialog>
  );
}
