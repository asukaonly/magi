import { useCallback, useEffect, useRef } from 'react';
import { APP_EVENTS } from '@/constants/events';
import {
  createChatRealtimeResponseTracker,
  projectChatRealtimeEffectPlan,
} from '@/domain/chat/realtime';
import type {
  PendingResponseTurnIdentity,
  PendingTurnHistoryResolution,
  PendingResponseTurnsBySession,
} from '@/domain/chat/turn-completion';
import { useRealtime, type RealtimeMessage as WSMessage } from '@/realtime/provider';

export const PENDING_HISTORY_RECONCILE_DELAY_MS = 25_000;
const PENDING_HISTORY_RETRY_DELAY_MS = 5_000;
const PENDING_HISTORY_MAX_RETRY_DELAY_MS = 30_000;

type UseChatRealtimeEffectsOptions = {
  allowInterjection: boolean;
  pendingResponseTurnsBySession: PendingResponseTurnsBySession;
  refreshVisibleTrace: (turnId: string) => void;
  handleTurnExecutionControlEvent: (payload: any) => void;
  reconcilePendingResponseTurn: (
    sessionId: string,
    turnId: string,
  ) => Promise<PendingTurnHistoryResolution>;
  settleTurnFromHistory?: (
    sessionId: string,
    turnId: string,
    terminalRunState: string,
  ) => void;
  clearPendingResponseTurn: (expected?: Partial<PendingResponseTurnIdentity>) => void;
};

export function useChatRealtimeEffects({
  allowInterjection,
  pendingResponseTurnsBySession,
  refreshVisibleTrace,
  handleTurnExecutionControlEvent,
  reconcilePendingResponseTurn,
  settleTurnFromHistory,
  clearPendingResponseTurn,
}: UseChatRealtimeEffectsOptions) {
  const { subscribe } = useRealtime();
  const responseTrackerRef = useRef(createChatRealtimeResponseTracker());
  const reconciliationKeysRef = useRef(new Set<string>());
  const pendingReconciliationKeysRef = useRef(new Set<string>());
  const reconciliationTimersRef = useRef(new Map<string, number>());

  const reconcileAndClearPendingTurn = useCallback(async (
    sessionId: string,
    turnId: string,
  ): Promise<PendingTurnHistoryResolution> => {
    const normalizedSessionId = String(sessionId || '').trim();
    const normalizedTurnId = String(turnId || '').trim();
    if (!normalizedSessionId || !normalizedTurnId) {
      return { resolved: false };
    }
    const key = `${normalizedSessionId}\u0000${normalizedTurnId}`;
    if (reconciliationKeysRef.current.has(key)) {
      return { resolved: false };
    }
    reconciliationKeysRef.current.add(key);
    try {
      const resolution = await reconcilePendingResponseTurn(
        normalizedSessionId,
        normalizedTurnId,
      );
      if (resolution.terminalRunState) {
        settleTurnFromHistory?.(
          normalizedSessionId,
          normalizedTurnId,
          resolution.terminalRunState,
        );
      }
      if (resolution.resolved) {
        responseTrackerRef.current.reset({
          sessionId: normalizedSessionId,
          turnId: normalizedTurnId,
        });
        clearPendingResponseTurn({
          sessionId: normalizedSessionId,
          turnId: normalizedTurnId,
        });
      }
      return resolution;
    } finally {
      reconciliationKeysRef.current.delete(key);
    }
  }, [
    clearPendingResponseTurn,
    reconcilePendingResponseTurn,
    settleTurnFromHistory,
  ]);

  const handleRealtimeEvent = useCallback((data: WSMessage) => {
    const plan = projectChatRealtimeEffectPlan(data, {
      allowInterjection,
      turnsBySession: pendingResponseTurnsBySession,
    }, responseTrackerRef.current);

    if (plan.syncSession) {
      window.dispatchEvent(new Event(APP_EVENTS.SESSION_SYNC));
    }

    if (plan.refreshTraceTurnId !== undefined) {
      refreshVisibleTrace(plan.refreshTraceTurnId);
    }

    if (plan.turnExecutionControlPayload !== undefined) {
      handleTurnExecutionControlEvent(plan.turnExecutionControlPayload);
    }

    if (plan.reconcilePendingResponseTurn) {
      void reconcileAndClearPendingTurn(
        plan.reconcilePendingResponseTurn.sessionId,
        plan.reconcilePendingResponseTurn.turnId,
      );
    }

    if (plan.clearPendingResponseTurn) {
      responseTrackerRef.current.reset(plan.clearPendingResponseTurn);
      clearPendingResponseTurn(plan.clearPendingResponseTurn);
    }
  }, [
    allowInterjection,
    clearPendingResponseTurn,
    handleTurnExecutionControlEvent,
    pendingResponseTurnsBySession,
    reconcileAndClearPendingTurn,
    refreshVisibleTrace,
  ]);

  useEffect(() => subscribe(handleRealtimeEvent), [handleRealtimeEvent, subscribe]);

  useEffect(() => {
    const pendingEntries = allowInterjection
      ? []
      : Object.entries(pendingResponseTurnsBySession)
        .map(([sessionId, turnId]) => ({
          sessionId: String(sessionId || '').trim(),
          turnId: String(turnId || '').trim(),
        }))
        .filter((identity) => identity.sessionId && identity.turnId);
    const activeKeys = new Set(
      pendingEntries.map(
        ({ sessionId, turnId }) => `${sessionId}\u0000${turnId}`,
      ),
    );
    pendingReconciliationKeysRef.current = activeKeys;

    for (const [key, timer] of reconciliationTimersRef.current) {
      if (!activeKeys.has(key)) {
        window.clearTimeout(timer);
        reconciliationTimersRef.current.delete(key);
      }
    }

    const schedule = (
      identity: PendingResponseTurnIdentity,
      delayMs: number,
      retryAttempt: number,
    ) => {
      const key = `${identity.sessionId}\u0000${identity.turnId}`;
      const timer = window.setTimeout(async () => {
        reconciliationTimersRef.current.delete(key);
        const resolution = await reconcileAndClearPendingTurn(
          identity.sessionId,
          identity.turnId,
        );
        if (!resolution.resolved && pendingReconciliationKeysRef.current.has(key)) {
          const retryDelay = resolution.retryAfterMs ?? Math.min(
            PENDING_HISTORY_MAX_RETRY_DELAY_MS,
            PENDING_HISTORY_RETRY_DELAY_MS * (2 ** retryAttempt),
          );
          schedule(identity, retryDelay, retryAttempt + 1);
        }
      }, delayMs);
      reconciliationTimersRef.current.set(key, timer);
    };

    for (const identity of pendingEntries) {
      const key = `${identity.sessionId}\u0000${identity.turnId}`;
      if (!reconciliationTimersRef.current.has(key)) {
        schedule(identity, PENDING_HISTORY_RECONCILE_DELAY_MS, 0);
      }
    }
  }, [
    allowInterjection,
    pendingResponseTurnsBySession,
    reconcileAndClearPendingTurn,
  ]);

  useEffect(() => () => {
    pendingReconciliationKeysRef.current.clear();
    for (const timer of reconciliationTimersRef.current.values()) {
      window.clearTimeout(timer);
    }
    reconciliationTimersRef.current.clear();
  }, []);
}
