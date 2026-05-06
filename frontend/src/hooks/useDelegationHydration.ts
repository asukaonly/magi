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
import { useDelegationsStore, selectDelegationCard } from '@/stores/delegations-store';


export function useDelegationHydration(
  sessionId: string | null,
  delegationId: string | null,
  workspace: string | null,
): void {
  const card = useDelegationsStore(
    sessionId && delegationId ? selectDelegationCard(sessionId, delegationId) : () => null,
  );
  const setHydrating = useDelegationsStore((s) => s.setHydrating);
  const setResult = useDelegationsStore((s) => s.setResult);
  const setEventsTail = useDelegationsStore((s) => s.setEventsTail);
  const setLifecycle = useDelegationsStore((s) => s.setLifecycle);
  const setDiffText = useDelegationsStore((s) => s.setDiffText);

  // Track the latest request ID to handle React StrictMode double invocation
  const requestIdRef = useRef<number>(0);

  useEffect(() => {
    if (!sessionId || !delegationId || !workspace) {
      return;
    }
    // Only skip if we already have diff_text OR we're already hydrating
    if (card?.diffText || card?.hydrating) {
      return;
    }

    // Increment request ID for this effect invocation
    const currentRequestId = ++requestIdRef.current;
    setHydrating(sessionId, delegationId, true);

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
      })
      .catch(() => {
        // Hydration is best-effort. The card stays in its current shape.
      })
      .finally(() => {
        // Only clear hydrating if this is still the latest request
        if (currentRequestId === requestIdRef.current) {
          setHydrating(sessionId, delegationId, false);
        }
      });
  }, [
    sessionId,
    delegationId,
    workspace,
    card?.diffText,
    card?.hydrating,
    setHydrating,
    setResult,
    setEventsTail,
    setLifecycle,
    setDiffText,
  ]);
}
