import { motion } from 'framer-motion';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router';
import { Check, Loader2, ShieldCheck, SlidersHorizontal, X } from 'lucide-react';
import { toast } from 'sonner';
import { backgroundTasksApi } from '@/api';
import { respondPermission } from '@/api/modules/control';
import { Button } from '@/components/ui/button';
import { MarkdownBlock } from '@/components/ui/markdown-block';
import { OPEN_PERMISSION_REQUEST_EVENT } from '@/components/control/ui-events';
import { isInteractionExpired, remainingInteractionSeconds } from '@/components/control/interaction-expiry';
import {
  isControlStatusMessage as isControlStatusTimelineMessage,
  projectControlStatusCardPresentation,
} from '@/domain/chat/presentation';
import type { ChatTimelineMessage } from '@/domain/chat/state';
import { useConversationStore } from '@/stores';

type ControlStatusCardProps = {
  message: ChatTimelineMessage;
  shouldReduceMotion: boolean;
};

export const isControlStatusMessage = (message: ChatTimelineMessage): boolean => (
  isControlStatusTimelineMessage(message)
);

const cardMotionProps = (shouldReduceMotion: boolean) => ({
  initial: shouldReduceMotion ? false : { opacity: 0, y: 8 },
  animate: { opacity: 1, y: 0 },
  transition: { duration: shouldReduceMotion ? 0 : 0.2, ease: 'easeOut' as const },
});

const toneClassNameByTone = {
  neutral: 'border-border/60 bg-muted/40 text-muted-foreground',
  warning: 'border-amber-500/30 bg-amber-500/10 text-amber-600 dark:text-amber-300',
  danger: 'border-rose-500/30 bg-rose-500/10 text-rose-600 dark:text-rose-300',
  success: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-300',
} as const;

type BackgroundTaskPendingPresentation = Extract<
  ReturnType<typeof projectControlStatusCardPresentation>,
  { kind: 'background_task_pending' }
>;

type PermissionRequestPresentation = Extract<
  ReturnType<typeof projectControlStatusCardPresentation>,
  { kind: 'permission_request' }
>;

const resolveMessageIdentity = (
  message: ChatTimelineMessage,
  payloadSessionId: string | null | undefined,
  currentSessionId: string | null,
) => ({
  sessionId: payloadSessionId || currentSessionId,
  messageId: String(message.messageId || message.id || '').trim(),
});

const useInteractionNow = (expiresAtMs: number | null | undefined): number => {
  const [nowMs, setNowMs] = useState(() => Date.now());

  useEffect(() => {
    if (!expiresAtMs) {
      return () => undefined;
    }
    setNowMs(Date.now());
    const handle = window.setInterval(() => {
      setNowMs(Date.now());
    }, 1000);
    return () => {
      window.clearInterval(handle);
    };
  }, [expiresAtMs]);

  return nowMs;
};

const BackgroundTaskPendingCard = ({
  message,
  presentation,
  shouldReduceMotion,
}: {
  message: ChatTimelineMessage;
  presentation: BackgroundTaskPendingPresentation;
  shouldReduceMotion: boolean;
}) => {
  const { t } = useTranslation('app');
  const navigate = useNavigate();
  const [cancelling, setCancelling] = useState(false);

  const handleCancel = async () => {
    if (!presentation.taskId) return;
    setCancelling(true);
    try {
      await backgroundTasksApi.cancel(presentation.taskId, 'user_requested');
      toast.success(
        t('chat.skills.backgroundCancelRequested', {
          defaultValue: 'Cancellation requested.',
        }),
      );
    } catch (exc: any) {
      toast.error(exc?.message ?? String(exc));
    } finally {
      setCancelling(false);
    }
  };

  const title =
    presentation.title || presentation.invocationText || t('tasks.chatCard.defaultTitle');

  return (
    <motion.div
      {...cardMotionProps(shouldReduceMotion)}
      key={message.id}
      className="mb-5 flex justify-center"
    >
      <div className="flex w-full max-w-[75%] flex-col gap-2 rounded-xl border border-border/40 bg-background/60 px-4 py-3 shadow-sm">
        <div className="flex items-center gap-2">
          <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-muted-foreground" />
          <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            {t('chat.skills.backgroundRunning', {
              defaultValue: 'Background task running',
            })}
          </span>
          <span className="ml-auto inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium border-border/60 bg-muted/40 text-muted-foreground">
            {t('chat.skills.backgroundPendingBadge', {
              defaultValue: 'Pending',
            })}
          </span>
        </div>
        <div className="text-sm font-semibold text-foreground">{title}</div>
        <div className="flex items-center justify-end gap-2">
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="h-7 px-2 text-xs"
            onClick={() => {
              if (presentation.taskId) {
                navigate(`/tasks?taskId=${encodeURIComponent(presentation.taskId)}`);
                return;
              }
              navigate('/tasks');
            }}
          >
            {t('tasks.chatCard.viewDetails')}
          </Button>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="h-7 px-2 text-xs text-destructive hover:bg-destructive/10 hover:text-destructive"
            onClick={() => void handleCancel()}
            disabled={cancelling || !presentation.taskId}
          >
            {cancelling ? <Loader2 className="mr-1.5 h-3 w-3 animate-spin" /> : null}
            {t('chat.skills.backgroundCancel', { defaultValue: 'Cancel' })}
          </Button>
        </div>
      </div>
    </motion.div>
  );
};

const PermissionRequestCard = ({
  message,
  presentation,
  shouldReduceMotion,
}: {
  message: ChatTimelineMessage;
  presentation: PermissionRequestPresentation;
  shouldReduceMotion: boolean;
}) => {
  const { t } = useTranslation(['control']);
  const currentSessionId = useConversationStore((state) => state.currentSessionId);
  const removeMessage = useConversationStore((state) => state.removeMessage);
  const [submitting, setSubmitting] = useState<'allow' | 'deny' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const nowMs = useInteractionNow(presentation.expiresAtMs);
  const expired = isInteractionExpired(presentation.expiresAtMs, nowMs);
  const remainingSeconds = remainingInteractionSeconds(presentation.expiresAtMs, nowMs);
  const riskLabel = t(`permission.risk_${presentation.riskLevel}`, {
    defaultValue: presentation.riskLevel || 'pending',
  });
  const { sessionId, messageId } = resolveMessageIdentity(
    message,
    presentation.sessionId,
    currentSessionId,
  );

  const finish = () => {
    if (sessionId && messageId) {
      removeMessage(sessionId, messageId);
    }
  };

  const submit = async (outcome: 'allow' | 'deny') => {
    if (!presentation.requestId || expired) return;
    setSubmitting(outcome);
    setError(null);
    try {
      await respondPermission(presentation.requestId, {
        outcome,
        scope: 'one_shot',
      });
      finish();
    } catch (exc: any) {
      setError(exc?.message ?? String(exc));
    } finally {
      setSubmitting(null);
    }
  };

  return (
    <motion.div {...cardMotionProps(shouldReduceMotion)} key={message.id} className="mb-5 flex justify-center">
      <div className="flex w-[92%] max-w-2xl flex-col gap-3 rounded-lg border border-border/50 bg-background/80 px-4 py-3 shadow-sm">
        <div className="flex items-center gap-2">
          <ShieldCheck className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
          <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            {t('permission.title')}
          </span>
          <span className={`ml-auto inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium ${toneClassNameByTone[presentation.riskTone]}`}>
            {riskLabel}
          </span>
        </div>
        <div className="space-y-1">
          <div className="break-words text-sm font-semibold text-foreground">{presentation.tool}</div>
          <p className="m-0 text-sm text-muted-foreground">
            {expired ? t('permission.expired') : t('permission.card.waiting')}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          {presentation.origin ? <span>{t('permission.origin')}: {presentation.origin}</span> : null}
          {remainingSeconds !== null ? (
            <span>{expired ? t('permission.expired') : t('permission.expires_in', { seconds: remainingSeconds })}</span>
          ) : null}
        </div>
        {presentation.argsPreview ? (
          <pre className="max-h-40 overflow-auto rounded-md bg-muted/50 p-2 text-xs text-muted-foreground">{presentation.argsPreview}</pre>
        ) : null}
        {error ? <div className="text-sm text-destructive">{error}</div> : null}
        <div className="flex flex-wrap items-center justify-end gap-2">
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="h-8 px-2.5 text-xs text-destructive hover:bg-destructive/10 hover:text-destructive"
            onClick={() => void submit('deny')}
            disabled={Boolean(submitting) || expired || !presentation.requestId}
            data-testid="permission-card-deny"
          >
            {submitting === 'deny' ? <Loader2 className="mr-1.5 h-3 w-3 animate-spin" /> : <X className="mr-1.5 h-3 w-3" />}
            {t('permission.card.deny_once')}
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="h-8 px-2.5 text-xs"
            onClick={() => {
              window.dispatchEvent(new CustomEvent(OPEN_PERMISSION_REQUEST_EVENT, {
                detail: { requestId: presentation.requestId || '' },
              }));
            }}
            disabled={expired || !presentation.requestId}
          >
            <SlidersHorizontal className="mr-1.5 h-3 w-3" aria-hidden="true" />
            {t('permission.card.review')}
          </Button>
          <Button
            type="button"
            size="sm"
            className="h-8 px-2.5 text-xs"
            onClick={() => void submit('allow')}
            disabled={Boolean(submitting) || expired || !presentation.requestId}
            data-testid="permission-card-allow"
          >
            {submitting === 'allow' ? <Loader2 className="mr-1.5 h-3 w-3 animate-spin" /> : <Check className="mr-1.5 h-3 w-3" />}
            {t('permission.card.allow_once')}
          </Button>
        </div>
      </div>
    </motion.div>
  );
};

export const ControlStatusCard = ({ message, shouldReduceMotion }: ControlStatusCardProps) => {
  const { t } = useTranslation(['app', 'control']);
  const navigate = useNavigate();
  const presentation = projectControlStatusCardPresentation(message);

  if (!presentation) {
    return null;
  }

  switch (presentation.kind) {
    case 'background_task_pending': {
      return (
        <BackgroundTaskPendingCard
          message={message}
          presentation={presentation}
          shouldReduceMotion={shouldReduceMotion}
        />
      );
    }
    case 'background_task_completion': {
      const title = presentation.title || t('tasks.chatCard.defaultTitle');
      const statusLabelKey = `tasks.chatCard.status.${presentation.status || 'unknown'}`;
      const statusLabel = t(statusLabelKey, {
        defaultValue: presentation.status || t('tasks.chatCard.status.unknown'),
      });

      return (
        <motion.div {...cardMotionProps(shouldReduceMotion)} key={message.id} className="mb-5 flex justify-center">
          <div className="flex w-full max-w-[75%] flex-col gap-2 rounded-xl border border-border/40 bg-background/60 px-4 py-3 shadow-sm">
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                {t('tasks.chatCard.eyebrow')}
              </span>
              <span className={`ml-auto inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium ${toneClassNameByTone[presentation.statusTone]}`}>
                {statusLabel}
              </span>
            </div>
            <div className="text-sm font-semibold text-foreground">{title}</div>
            {presentation.bodyText ? (
              <MarkdownBlock>{presentation.bodyText}</MarkdownBlock>
            ) : null}
            <div className="flex justify-end">
              <Button
                type="button"
                size="sm"
                variant="ghost"
                className="h-7 px-2 text-xs"
                onClick={() => {
                  if (presentation.taskId) {
                    navigate(`/tasks?taskId=${encodeURIComponent(presentation.taskId)}`);
                    return;
                  }
                  navigate('/tasks');
                }}
              >
                {t('tasks.chatCard.viewDetails')}
              </Button>
            </div>
          </div>
        </motion.div>
      );
    }
    case 'permission_request': {
      return (
        <PermissionRequestCard
          message={message}
          presentation={presentation}
          shouldReduceMotion={shouldReduceMotion}
        />
      );
    }
    case 'ask_request': {
      return null;
    }
    case 'plan_state': {
      return (
        <motion.div {...cardMotionProps(shouldReduceMotion)} key={message.id} className="mb-5 flex justify-center">
          <div className="flex w-full max-w-[75%] flex-col gap-3 rounded-xl border border-border/40 bg-background/60 px-4 py-3 shadow-sm">
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                {presentation.active ? t('control:plan.badge_active') : t('control:plan.badge_inactive')}
              </span>
              <span className="ml-auto inline-flex items-center rounded-full border border-border/60 bg-muted/40 px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
                {presentation.active ? t('control:plan.entered') : t('control:plan.exited')}
              </span>
            </div>
            {presentation.planText ? (
              <pre className="whitespace-pre-wrap text-sm leading-relaxed text-foreground">{presentation.planText}</pre>
            ) : (
              <p className="m-0 text-sm text-muted-foreground">{t('control:plan.empty')}</p>
            )}
          </div>
        </motion.div>
      );
    }
    case 'todo_state': {
      return (
        <motion.div {...cardMotionProps(shouldReduceMotion)} key={message.id} className="mb-5 flex justify-center">
          <div className="flex w-full max-w-[75%] flex-col gap-3 rounded-xl border border-border/40 bg-background/60 px-4 py-3 shadow-sm">
            <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{t('control:todo.title')}</div>
            {presentation.items.length ? (
              <ul className="space-y-2">
                {presentation.items.map((item) => {
                  const glyph = item.status === 'completed' ? '●' : item.status === 'in_progress' ? '◐' : '○';

                  return (
                    <li key={item.id} className={`flex items-start gap-2 text-sm ${item.status === 'completed' ? 'text-muted-foreground line-through' : 'text-foreground'}`}>
                      <span className="shrink-0 font-mono">{glyph}</span>
                      <span className="flex-1">{item.content}</span>
                      <span className="shrink-0 text-xs text-muted-foreground">{t(`control:todo.status.${item.status}`)}</span>
                    </li>
                  );
                })}
              </ul>
            ) : (
              <p className="m-0 text-sm text-muted-foreground">{t('control:todo.empty')}</p>
            )}
          </div>
        </motion.div>
      );
    }
    default:
      return null;
  }
};