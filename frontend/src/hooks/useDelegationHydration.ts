/**
 * Lazy hydration for delegation cards.
 *
 * When a card is mounted for a delegation we haven't seen via realtime
 * (e.g. after page reload, or for a historical chat message), this hook
 * fetches the persisted ``result.json`` + last 50 events so the UI can
 * render the same shape as live delegations.
 */
import { useEffect, useRef } from 'react';

import { codeAgentApi } from '@/api/modules/codeAgent';
import { useDelegationsStore } from '@/stores/delegations-store';


export function useDelegationHydration(
  sessionId: string | null,
  delegationId: string | null,
  turnId: string | null,
  workspace: string | null,
): void {
  const setHydrating = useDelegationsStore((s) => s.setHydrating);
  const markHydrated = useDelegationsStore((s) => s.markHydrated);
  const markHydrationFailed = useDelegationsStore((s) => s.markHydrationFailed);
  const setResult = useDelegationsStore((s) => s.setResult);
  const setEventsTail = useDelegationsStore((s) => s.setEventsTail);
  const setLifecycle = useDelegationsStore((s) => s.setLifecycle);
  const setDiffText = useDelegationsStore((s) => s.setDiffText);

  // Track the latest request ID to handle React StrictMode double invocation
  const requestIdRef = useRef<number>(0);

  useEffect(() => {
    if (!sessionId || !delegationId || !turnId || !workspace) {
      return;
    }
    const card = useDelegationsStore
      .getState()
      .delegationsBySession[sessionId]?.[delegationId];
    if (card?.hydrated || card?.hydrating || card?.hydrationAttempted) {
      return;
    }

    // Increment request ID for this effect invocation
    const currentRequestId = ++requestIdRef.current;
    setHydrating(sessionId, delegationId, true, turnId);

    codeAgentApi
      .getDelegation(sessionId, delegationId, workspace)
      .then((response) => {
        // Only process if this is still the latest request
        if (currentRequestId !== requestIdRef.current) {
          return;
        }
        const { result, events_tail, diff_text } = response;

        if (result) {
          setResult(sessionId, delegationId, result);
          if (result.applied_at) {
            setLifecycle(sessionId, delegationId, 'applied');
          } else if (result.discarded_at) {
            setLifecycle(sessionId, delegationId, 'discarded');
          } else if (result.success === false) {
            setLifecycle(sessionId, delegationId, 'failed');
          } else {
            setLifecycle(sessionId, delegationId, 'finished');
          }
        }
        if (Array.isArray(events_tail) && events_tail.length > 0) {
          setEventsTail(sessionId, delegationId, events_tail);
        }
        if (typeof diff_text === 'string') {
          setDiffText(sessionId, delegationId, diff_text);
        }
        markHydrated(sessionId, delegationId);
      })
      .catch(() => {
        if (currentRequestId === requestIdRef.current) {
          markHydrationFailed(sessionId, delegationId);
        }
      })
      .finally(() => {
        // Only clear hydrating if this is still the latest request
        if (currentRequestId === requestIdRef.current) {
          setHydrating(sessionId, delegationId, false);
        }
      });
    return () => {
      if (currentRequestId === requestIdRef.current) {
        requestIdRef.current += 1;
        setHydrating(sessionId, delegationId, false, turnId);
      }
    };
  }, [
    sessionId,
    delegationId,
    turnId,
    workspace,
    setHydrating,
    markHydrated,
    markHydrationFailed,
    setResult,
    setEventsTail,
    setLifecycle,
    setDiffText,
  ]);
}
