import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { messagesApi } from '@/api';
import { DEFAULT_USER_ID } from '@/constants';
import type { TurnExecutionControlState } from '@/domain/chat/presentation';

const USER_ID = DEFAULT_USER_ID;
const TERMINAL_EXECUTION_STATES = new Set(['cancelled', 'completed', 'failed', 'interrupted', 'merged']);

type UseChatExecutionControlsOptions = {
  currentSessionId: string | null;
  onTerminalExecutionState?: () => void;
};

export function useChatExecutionControls({
  currentSessionId,
  onTerminalExecutionState,
}: UseChatExecutionControlsOptions) {
  const { t } = useTranslation('app');
  const [cancellingTurnIds, setCancellingTurnIds] = useState<string[]>([]);
  const [detachingTurnIds, setDetachingTurnIds] = useState<string[]>([]);
  const [executionControlByTurnId, setExecutionControlByTurnId] = useState<Record<string, TurnExecutionControlState>>({});

  useEffect(() => {
    setCancellingTurnIds([]);
    setDetachingTurnIds([]);
    setExecutionControlByTurnId({});
  }, [currentSessionId]);

  const requestRunCancel = useCallback(async (turnId: string) => {
    const normalizedTurnId = String(turnId || '').trim();
    if (!currentSessionId || !normalizedTurnId) return;
    if (cancellingTurnIds.includes(normalizedTurnId)) return;
    setCancellingTurnIds((current) => [...current, normalizedTurnId]);
    try {
      await messagesApi.cancelRun(USER_ID, currentSessionId, {
        reason: 'user_cancel',
        turnId: normalizedTurnId,
      });
    } catch (error) {
      console.error(error);
      toast.error(t('chat.trace.cancelFailed'));
    } finally {
      setCancellingTurnIds((current) => current.filter((item) => item !== normalizedTurnId));
    }
  }, [cancellingTurnIds, currentSessionId, t]);

  const requestRunDetach = useCallback(async (turnId: string) => {
    const normalizedTurnId = String(turnId || '').trim();
    if (!currentSessionId || !normalizedTurnId) return;
    if (detachingTurnIds.includes(normalizedTurnId)) return;
    setDetachingTurnIds((current) => [...current, normalizedTurnId]);
    try {
      await messagesApi.detachRun(USER_ID, currentSessionId, {
        reason: 'user_detach',
        turnId: normalizedTurnId,
      });
    } catch (error) {
      console.error(error);
      toast.error(t('chat.trace.detachFailed'));
      setDetachingTurnIds((current) => current.filter((item) => item !== normalizedTurnId));
    }
  }, [currentSessionId, detachingTurnIds, t]);

  const handleTurnExecutionControlEvent = useCallback((payload: any) => {
    const sessionId = String(payload?.session_id || currentSessionId || '').trim();
    const turnId = String(payload?.turn_id || '').trim();
    const state = String(payload?.state || '').trim();
    if (!sessionId || !turnId || !state) return;

    setExecutionControlByTurnId((current) => ({
      ...current,
      [turnId]: {
        state,
        label: payload?.label ? String(payload.label).trim() || null : null,
      },
    }));

    if (state === 'cancelling') {
      setCancellingTurnIds((current) => (current.includes(turnId) ? current : [...current, turnId]));
      return;
    }

    if (state === 'detaching') {
      setDetachingTurnIds((current) => (current.includes(turnId) ? current : [...current, turnId]));
      return;
    }

    if (TERMINAL_EXECUTION_STATES.has(state)) {
      setCancellingTurnIds((current) => current.filter((item) => item !== turnId));
      setDetachingTurnIds((current) => current.filter((item) => item !== turnId));
      onTerminalExecutionState?.();
    }
  }, [currentSessionId, onTerminalExecutionState]);

  return {
    cancellingTurnIds,
    detachingTurnIds,
    executionControlByTurnId,
    requestRunCancel,
    requestRunDetach,
    handleTurnExecutionControlEvent,
  };
}