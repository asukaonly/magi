/**
 * Per-session delegation runtime state.
 *
 * Populated from two sources:
 * 1. Realtime ``code_agent_delegation_event`` / ``code_agent_delegation_state``
 *    notifications projected by ``store-projection.ts``.
 * 2. ``codeAgentApi.getDelegation`` REST hydration when the UI mounts a card
 *    for a delegation that wasn't seen via realtime (e.g. after page reload).
 */
import { create } from 'zustand';

import type {
  ApplyOutcome,
  DelegateResult,
  DelegationLifecycle,
  RunEvent,
} from '@/api/modules/codeAgent';

const MAX_EVENTS_PER_DELEGATION = 200;


export interface DelegationCardState {
  delegation_id: string;
  session_id: string;
  lifecycle: DelegationLifecycle;
  result: DelegateResult | null;
  events: RunEvent[];
  hydrating: boolean;
  applyOutcome: ApplyOutcome | null;
  error: string | null;
  diffText: string;
}

interface DelegationsStoreState {
  delegationsBySession: Record<string, Record<string, DelegationCardState>>;
  upsertEvent: (sessionId: string, did: string, event: RunEvent) => void;
  upsertState: (
    sessionId: string,
    did: string,
    lifecycle: DelegationLifecycle,
    summary: Record<string, unknown>,
  ) => void;
  setResult: (sessionId: string, did: string, result: DelegateResult) => void;
  setEventsTail: (sessionId: string, did: string, events: RunEvent[]) => void;
  setHydrating: (sessionId: string, did: string, hydrating: boolean) => void;
  setApplyOutcome: (sessionId: string, did: string, outcome: ApplyOutcome) => void;
  setLifecycle: (sessionId: string, did: string, lifecycle: DelegationLifecycle) => void;
  setDiffText: (sessionId: string, did: string, diffText: string) => void;
  reset: () => void;
}

const defaultCard = (sessionId: string, did: string): DelegationCardState => ({
  delegation_id: did,
  session_id: sessionId,
  lifecycle: 'started',
  result: null,
  events: [],
  hydrating: false,
  applyOutcome: null,
  error: null,
  diffText: '',
});

const upsertCard = (
  state: DelegationsStoreState,
  sessionId: string,
  did: string,
  patch: Partial<DelegationCardState>,
): Pick<DelegationsStoreState, 'delegationsBySession'> => {
  const existing = state.delegationsBySession[sessionId]?.[did] ?? defaultCard(sessionId, did);
  const next: DelegationCardState = { ...existing, ...patch };
  return {
    delegationsBySession: {
      ...state.delegationsBySession,
      [sessionId]: {
        ...(state.delegationsBySession[sessionId] ?? {}),
        [did]: next,
      },
    },
  };
};


export const useDelegationsStore = create<DelegationsStoreState>((set) => ({
  delegationsBySession: {},

  upsertEvent: (sessionId, did, event) =>
    set((state) => {
      const existing = state.delegationsBySession[sessionId]?.[did] ?? defaultCard(sessionId, did);
      const events = [...existing.events, event];
      if (events.length > MAX_EVENTS_PER_DELEGATION) {
        events.splice(0, events.length - MAX_EVENTS_PER_DELEGATION);
      }
      return upsertCard(state, sessionId, did, {
        events,
        // Promote 'started' to 'running' once we see actual events flow.
        lifecycle: existing.lifecycle === 'started' ? 'running' : existing.lifecycle,
      });
    }),

  upsertState: (sessionId, did, lifecycle, summary) =>
    set((state) => {
      const patch: Partial<DelegationCardState> = { lifecycle };
      // When the broadcast carries a result-shaped summary on terminal states,
      // hydrate the card's result so the UI renders without a separate fetch.
      if (
        (lifecycle === 'finished' || lifecycle === 'failed' || lifecycle === 'cancelled') &&
        summary &&
        typeof summary === 'object' &&
        'delegation_id' in summary
      ) {
        patch.result = summary as unknown as DelegateResult;
      }
      return upsertCard(state, sessionId, did, patch);
    }),

  setResult: (sessionId, did, result) =>
    set((state) => upsertCard(state, sessionId, did, { result })),

  setEventsTail: (sessionId, did, events) =>
    set((state) => upsertCard(state, sessionId, did, { events })),

  setHydrating: (sessionId, did, hydrating) =>
    set((state) => upsertCard(state, sessionId, did, { hydrating })),

  setApplyOutcome: (sessionId, did, outcome) =>
    set((state) => upsertCard(state, sessionId, did, {
      applyOutcome: outcome,
      lifecycle: outcome.applied ? 'applied' : state.delegationsBySession[sessionId]?.[did]?.lifecycle ?? 'finished',
    })),

  setLifecycle: (sessionId, did, lifecycle) =>
    set((state) => upsertCard(state, sessionId, did, { lifecycle })),

  setDiffText: (sessionId, did, diffText) =>
    set((state) => upsertCard(state, sessionId, did, { diffText })),

  reset: () => set({ delegationsBySession: {} }),
}));


export const selectDelegationCard =
  (sessionId: string, did: string) =>
  (state: DelegationsStoreState): DelegationCardState | null =>
    state.delegationsBySession[sessionId]?.[did] ?? null;
