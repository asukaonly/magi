/**
 * Dialog surfaced when an ``ask_user_question`` tool call is awaiting
 * a reply. Fetches the current ask state for the session and posts
 * the user's answer via ``respondAsk``.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
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
import { Textarea } from '@/components/ui/textarea';
import {
  AskStateDTO,
  getAskState,
  respondAsk,
} from '@/api/modules/control';
import { useControlEvents } from '@/realtime/useControlEvents';
import { useConversationStore } from '@/stores';
import { OPEN_ASK_REQUEST_EVENT } from './ui-events';

export interface AskDialogProps {
  sessionId: string | null | undefined;
  /** Poll interval in ms; set to 0 to disable polling. */
  intervalMs?: number;
  /** Called after a successful answer. */
  onAnswered?: (requestId: string, answer: string) => void;
  /** Optional flag to indicate this ask is from a suspended background task. */
  background?: boolean;
}

export function AskDialog({
  sessionId,
  intervalMs = 5000,
  onAnswered,
  background = false,
}: AskDialogProps) {
  const { t } = useTranslation('control');
  const upsertMessage = useConversationStore((state) => state.upsertMessage);
  const removeMessage = useConversationStore((state) => state.removeMessage);
  const [ask, setAsk] = useState<AskStateDTO | null>(null);
  const [answer, setAnswer] = useState('');
  const [selection, setSelection] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const pull = useCallback(async () => {
    if (!sessionId) {
      setAsk(null);
      return;
    }
    try {
      const current = await getAskState(sessionId);
      if (current && current.status === 'pending') {
        setAsk((prev) =>
          prev && prev.request_id === current.request_id ? prev : current,
        );
      } else {
        setAsk(null);
      }
    } catch {
      // swallow — transient fetch errors shouldn't crash the host
    }
  }, [sessionId]);

  useEffect(() => {
    if (!sessionId) {
      setAsk(null);
      return;
    }
    void pull();
    if (intervalMs <= 0) return () => undefined;
    const handle = setInterval(() => {
      void pull();
    }, intervalMs);
    return () => {
      clearInterval(handle);
    };
  }, [sessionId, intervalMs, pull]);

  useControlEvents({
    sessionId: sessionId ?? null,
    onAskRequested: () => {
      void pull();
    },
  });

  useEffect(() => {
    const handleOpenAsk = () => {
      void pull();
    };

    window.addEventListener(OPEN_ASK_REQUEST_EVENT, handleOpenAsk);
    return () => {
      window.removeEventListener(OPEN_ASK_REQUEST_EVENT, handleOpenAsk);
    };
  }, [pull]);

  useEffect(() => {
    if (!sessionId) {
      return;
    }
    const state = useConversationStore.getState();
    if (!state.sessionsById[sessionId]) {
      return;
    }
    const currentMessages = state.messagesBySession[sessionId] || [];
    const askMessages = currentMessages.filter((message) => message.messageKind === 'ask_request');

    if (!ask) {
      askMessages.forEach((message) => {
        const messageId = String(message.messageId || '').trim();
        if (messageId) {
          removeMessage(sessionId, messageId);
        }
      });
      return;
    }

    const activeMessageId = `ask:${ask.request_id}`;
    askMessages.forEach((message) => {
      const messageId = String(message.messageId || '').trim();
      if (messageId && messageId !== activeMessageId) {
        removeMessage(sessionId, messageId);
      }
    });

    upsertMessage(sessionId, {
      id: activeMessageId,
      messageId: activeMessageId,
      role: 'assistant',
      kind: 'status',
      messageKind: 'ask_request',
      content: ask.question,
      timestamp: Number(ask.created_at_ms || Date.now()),
      payload: {
        ask_request_id: ask.request_id,
        question: ask.question,
        options: ask.options,
        allow_free_text: ask.allow_free_text,
        background,
      },
    });
  }, [ask, background, removeMessage, sessionId, upsertMessage]);

  const canSubmit = useMemo(() => {
    if (!ask) return false;
    if (selection) return true;
    if (ask.allow_free_text) return answer.trim().length > 0;
    return false;
  }, [ask, selection, answer]);

  const submit = async () => {
    if (!ask) return;
    const payload = selection ?? answer.trim();
    if (!payload) return;
    setSubmitting(true);
    setError(null);
    try {
      await respondAsk(ask.request_id, payload);
      onAnswered?.(ask.request_id, payload);
      setAsk(null);
      setAnswer('');
      setSelection(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog
      open={ask !== null}
      onOpenChange={(open) => {
        if (!open) setAsk(null);
      }}
    >
      <DialogContent className="max-w-lg" data-testid="ask-dialog">
        <DialogHeader>
          <DialogTitle>{t('ask.title')}</DialogTitle>
          {background && (
            <Badge variant="secondary" className="self-start">
              {t('ask.background_badge')}
            </Badge>
          )}
          <DialogDescription>
            {ask?.question}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3 text-sm">
          {ask?.options?.length ? (
            <div className="space-y-2">
              <div className="text-muted-foreground">{t('ask.options')}</div>
              <div className="flex flex-wrap gap-2">
                {ask.options.map((opt) => (
                  <Button
                    key={opt}
                    size="sm"
                    variant={selection === opt ? 'default' : 'outline'}
                    onClick={() =>
                      setSelection((prev) => (prev === opt ? null : opt))
                    }
                    data-testid={`ask-option-${opt}`}
                  >
                    {opt}
                  </Button>
                ))}
              </div>
            </div>
          ) : null}
          {ask?.allow_free_text && (
            <Textarea
              rows={3}
              value={answer}
              onChange={(e) => {
                setAnswer(e.target.value);
                setSelection(null);
              }}
              placeholder={t('ask.answer_placeholder') ?? ''}
              data-testid="ask-textarea"
            />
          )}
          {!ask?.allow_free_text && !ask?.options?.length && (
            <div className="text-sm text-muted-foreground">
              {t('ask.free_text_disabled')}
            </div>
          )}
          {error && <div className="text-sm text-destructive">{error}</div>}
        </div>
        <DialogFooter>
          <Button
            onClick={() => {
              void submit();
            }}
            disabled={!canSubmit || submitting}
            data-testid="ask-submit"
          >
            {t('ask.submit')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
