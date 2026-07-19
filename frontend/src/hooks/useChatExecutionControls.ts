import { useCallback, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { messagesApi } from '@/api';
import { DEFAULT_USER_ID } from '@/constants';
import type { TurnExecutionControlState } from '@/domain/chat/presentation';
import { isTerminalRunState } from '@/domain/chat/turn-completion';

const USER_ID = DEFAULT_USER_ID;

type RunControlIdentity = {
  sessionId: string;
  turnId: string;
};

export type RunCancelOutcome = 'pending' | 'settled' | 'failed' | 'ignored';

type UseChatExecutionControlsOptions = {
  currentSessionId: string | null;
};

const runControlKey = ({ sessionId, turnId }: RunControlIdentity): string => (
  `${sessionId}\u0000${turnId}`
);

export function useChatExecutionControls({
  currentSessionId,
}: UseChatExecutionControlsOptions) {
  const { t } = useTranslation('app');
  const [cancellingTurns, setCancellingTurns] = useState<RunControlIdentity[]>([]);
  const [detachingTurns, setDetachingTurns] = useState<RunControlIdentity[]>([]);
  const [executionControlBySession, setExecutionControlBySession] = useState<
    Record<string, Record<string, TurnExecutionControlState>>
  >({});
  const cancellingKeysRef = useRef(new Set<string>());

  const cancellingTurnIds = useMemo(() => (
    currentSessionId
      ? cancellingTurns
        .filter((identity) => identity.sessionId === currentSessionId)
        .map((identity) => identity.turnId)
      : []
  ), [cancellingTurns, currentSessionId]);
  const detachingTurnIds = useMemo(() => (
    currentSessionId
      ? detachingTurns
        .filter((identity) => identity.sessionId === currentSessionId)
        .map((identity) => identity.turnId)
      : []
  ), [currentSessionId, detachingTurns]);
  const executionControlByTurnId = currentSessionId
    ? executionControlBySession[currentSessionId] || {}
    : {};

  const releaseCancelling = useCallback((identity: RunControlIdentity) => {
    const key = runControlKey(identity);
    cancellingKeysRef.current.delete(key);
    setCancellingTurns((current) => (
      current.filter((item) => runControlKey(item) !== key)
    ));
  }, []);

  const settleTurnFromHistory = useCallback((
    sessionId: string,
    turnId: string,
    terminalRunState: string,
  ) => {
    const normalizedSessionId = String(sessionId || '').trim();
    const normalizedTurnId = String(turnId || '').trim();
    const normalizedState = String(terminalRunState || '').trim().toLowerCase();
    if (
      !normalizedSessionId
      || !normalizedTurnId
      || !isTerminalRunState(normalizedState)
    ) {
      return;
    }
    const identity = {
      sessionId: normalizedSessionId,
      turnId: normalizedTurnId,
    };
    const key = runControlKey(identity);
    setExecutionControlBySession((current) => ({
      ...current,
      [normalizedSessionId]: {
        ...(current[normalizedSessionId] || {}),
        [normalizedTurnId]: {
          state: normalizedState,
          label: null,
        },
      },
    }));
    releaseCancelling(identity);
    setDetachingTurns((current) => (
      current.filter((item) => runControlKey(item) !== key)
    ));
  }, [releaseCancelling]);

  const requestRunCancel = useCallback(async (turnId: string): Promise<RunCancelOutcome> => {
    const sessionId = String(currentSessionId || '').trim();
    const normalizedTurnId = String(turnId || '').trim();
    if (!sessionId || !normalizedTurnId) return 'ignored';
    const identity = { sessionId, turnId: normalizedTurnId };
    const key = runControlKey(identity);
    if (cancellingKeysRef.current.has(key)) return 'ignored';
    cancellingKeysRef.current.add(key);
    setCancellingTurns((current) => (
      current.some((item) => runControlKey(item) === key)
        ? current
        : [...current, identity]
    ));
    try {
      const response = await messagesApi.cancelRun(USER_ID, sessionId, {
        reason: 'user_cancel',
        turnId: normalizedTurnId,
      });
      if (response.success === false) {
        releaseCancelling(identity);
        return 'settled';
      }
      const state = String(response.data?.status || '').trim().toLowerCase();
      if (isTerminalRunState(state)) {
        setExecutionControlBySession((current) => ({
          ...current,
          [sessionId]: {
            ...(current[sessionId] || {}),
            [normalizedTurnId]: {
              state,
              label: null,
            },
          },
        }));
        releaseCancelling(identity);
        return 'settled';
      }
      return 'pending';
    } catch (error) {
      console.error(error);
      toast.error(t('chat.trace.cancelFailed'));
      releaseCancelling(identity);
      return 'failed';
    }
  }, [currentSessionId, releaseCancelling, t]);

  const requestRunDetach = useCallback(async (turnId: string) => {
    const sessionId = String(currentSessionId || '').trim();
    const normalizedTurnId = String(turnId || '').trim();
    if (!sessionId || !normalizedTurnId) return;
    const identity = { sessionId, turnId: normalizedTurnId };
    const key = runControlKey(identity);
    if (detachingTurns.some((item) => runControlKey(item) === key)) return;
    setDetachingTurns((current) => [...current, identity]);
    try {
      await messagesApi.detachRun(USER_ID, sessionId, {
        reason: 'user_detach',
        turnId: normalizedTurnId,
      });
    } catch (error) {
      console.error(error);
      toast.error(t('chat.trace.detachFailed'));
      setDetachingTurns((current) => (
        current.filter((item) => runControlKey(item) !== key)
      ));
    }
  }, [currentSessionId, detachingTurns, t]);

  const handleTurnExecutionControlEvent = useCallback((payload: any) => {
    const sessionId = String(payload?.session_id || currentSessionId || '').trim();
    const turnId = String(payload?.turn_id || '').trim();
    const state = String(payload?.state || '').trim().toLowerCase();
    if (!sessionId || !turnId || !state) return;
    const identity = { sessionId, turnId };
    const key = runControlKey(identity);

    setExecutionControlBySession((current) => ({
      ...current,
      [sessionId]: {
        ...(current[sessionId] || {}),
        [turnId]: {
          state,
          label: payload?.label ? String(payload.label).trim() || null : null,
        },
      },
    }));

    if (state === 'cancelling') {
      cancellingKeysRef.current.add(key);
      setCancellingTurns((current) => (
        current.some((item) => runControlKey(item) === key)
          ? current
          : [...current, identity]
      ));
      return;
    }

    if (state === 'detaching') {
      setDetachingTurns((current) => (
        current.some((item) => runControlKey(item) === key)
          ? current
          : [...current, identity]
      ));
      return;
    }

    if (isTerminalRunState(state)) {
      releaseCancelling(identity);
      setDetachingTurns((current) => (
        current.filter((item) => runControlKey(item) !== key)
      ));
    }
  }, [currentSessionId, releaseCancelling]);

  return {
    cancellingTurnIds,
    detachingTurnIds,
    executionControlByTurnId,
    requestRunCancel,
    requestRunDetach,
    handleTurnExecutionControlEvent,
    settleTurnFromHistory,
  };
}
