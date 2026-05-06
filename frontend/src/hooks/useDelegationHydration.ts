/**
 * Lazy hydration for delegation cards.
 *
 * When a card is mounted for a delegation we haven't seen via realtime
 * (e.g. after page reload, or for a historical chat message), this hook
 * fetches the persisted ``result.json`` + last 50 events so the UI can
 * render the same shape as live delegations.
 */
import { useEffect } from 'react';

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

  useEffect(() => {
    if (!sessionId || !delegationId || !workspace) {
      console.log('[useDelegationHydration] Skip: missing data', { sessionId, delegationId, workspace });
      return;
    }
    // Only skip if we already have diff_text OR we're already hydrating
    if (card?.diffText || card?.hydrating) {
      console.log('[useDelegationHydration] Skip: already has data', { hasDiffText: !!card?.diffText, hydrating: card?.hydrating });
      return;
    }
    console.log('[useDelegationHydration] Starting hydration', { sessionId, delegationId, workspace });

    let cancelled = false;
    setHydrating(sessionId, delegationId, true);
    codeAgentApi
      .getDelegation(sessionId, delegationId, workspace)
      .then(({ result, events_tail, diff_text }) => {
        console.log('[useDelegationHydration] API response', {
          hasResult: !!result,
          eventsCount: events_tail?.length,
          diffLength: diff_text?.length,
        });
        if (cancelled) return;
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
        if (!cancelled) {
          setHydrating(sessionId, delegationId, false);
        }
      });
    return () => {
      cancelled = true;
    };
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
