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
import { canApplyRealtimeChatDelegationProjection } from '@/realtime/chat-projection-retirement';

const MAX_EVENTS_PER_DELEGATION = 200;


export interface DelegationCardState {
  delegation_id: string;
  session_id: string;
  turn_id: string | null;
  lifecycle: DelegationLifecycle;
  result: DelegateResult | null;
  events: RunEvent[];
  hydrating: boolean;
  applyOutcome: ApplyOutcome | null;
  error: string | null;
  diffText: string;
  hydrated: boolean;
  hydrationAttempted: boolean;
  hydrationPlaceholder: boolean;
}

interface DelegationsStoreState {
  delegationsBySession: Record<string, Record<string, DelegationCardState>>;
  upsertEvent: (
    sessionId: string,
    did: string,
    turnId: string,
    event: RunEvent,
  ) => void;
  upsertState: (
    sessionId: string,
    did: string,
    turnId: string,
    lifecycle: DelegationLifecycle,
    summary: Record<string, unknown>,
  ) => void;
  setResult: (sessionId: string, did: string, result: DelegateResult) => void;
  setEventsTail: (sessionId: string, did: string, events: RunEvent[]) => void;
  setHydrating: (
    sessionId: string,
    did: string,
    hydrating: boolean,
    turnId?: string | null,
  ) => void;
  markHydrated: (sessionId: string, did: string) => void;
  markHydrationFailed: (sessionId: string, did: string) => void;
  setApplyOutcome: (sessionId: string, did: string, outcome: ApplyOutcome) => void;
  setLifecycle: (sessionId: string, did: string, lifecycle: DelegationLifecycle) => void;
  setDiffText: (sessionId: string, did: string, diffText: string) => void;
  remove: (sessionId: string, did: string) => void;
  clearSession: (sessionId: string) => void;
  reset: () => void;
}

const defaultCard = (
  sessionId: string,
  did: string,
  turnId: string | null = null,
): DelegationCardState => ({
  delegation_id: did,
  session_id: sessionId,
  turn_id: turnId,
  lifecycle: 'started',
  result: null,
  events: [],
  hydrating: false,
  applyOutcome: null,
  error: null,
  diffText: '',
  hydrated: false,
  hydrationAttempted: false,
  hydrationPlaceholder: false,
});

const upsertCard = (
  state: DelegationsStoreState,
  sessionId: string,
  did: string,
  patch: Partial<DelegationCardState>,
): Pick<DelegationsStoreState, 'delegationsBySession'> => {
  const existing = state.delegationsBySession[sessionId]?.[did];
  if (!existing && !String(patch.turn_id ?? '').trim()) {
    return { delegationsBySession: state.delegationsBySession };
  }
  const turnId = String(patch.turn_id ?? existing?.turn_id ?? '').trim() || null;
  if (!canApplyRealtimeChatDelegationProjection(sessionId, did, turnId)) {
    return { delegationsBySession: state.delegationsBySession };
  }
  const current = existing ?? defaultCard(sessionId, did, turnId);
  const next: DelegationCardState = { ...current, ...patch, turn_id: turnId };
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

  upsertEvent: (sessionId, did, turnId, event) =>
    set((state) => {
      const existing = state.delegationsBySession[sessionId]?.[did]
        ?? defaultCard(sessionId, did, turnId);
      const events = [...existing.events, event];
      if (events.length > MAX_EVENTS_PER_DELEGATION) {
        events.splice(0, events.length - MAX_EVENTS_PER_DELEGATION);
      }
      return upsertCard(state, sessionId, did, {
        turn_id: turnId,
        events,
        hydrationPlaceholder: false,
        // Promote 'started' to 'running' once we see actual events flow.
        lifecycle: existing.lifecycle === 'started' ? 'running' : existing.lifecycle,
      });
    }),

  upsertState: (sessionId, did, turnId, lifecycle, summary) =>
    set((state) => {
      const patch: Partial<DelegationCardState> = {
        lifecycle,
        turn_id: turnId,
        hydrationPlaceholder: false,
      };
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

  setHydrating: (sessionId, did, hydrating, turnId = null) =>
    set((state) => {
      const existing = state.delegationsBySession[sessionId]?.[did];
      return upsertCard(state, sessionId, did, {
        hydrating,
        turn_id: turnId,
        hydrationPlaceholder: existing?.hydrationPlaceholder ?? hydrating,
      });
    }),

  markHydrated: (sessionId, did) =>
    set((state) => upsertCard(state, sessionId, did, {
      hydrated: true,
      hydrationAttempted: true,
      hydrating: false,
      hydrationPlaceholder: false,
    })),

  markHydrationFailed: (sessionId, did) =>
    set((state) => {
      const existing = state.delegationsBySession[sessionId]?.[did];
      return upsertCard(state, sessionId, did, {
        hydrationAttempted: true,
        hydrating: false,
        lifecycle: existing?.hydrationPlaceholder
          ? 'failed'
          : existing?.lifecycle,
      });
    }),

  setApplyOutcome: (sessionId, did, outcome) =>
    set((state) => upsertCard(state, sessionId, did, {
      applyOutcome: outcome,
      lifecycle: outcome.applied ? 'applied' : state.delegationsBySession[sessionId]?.[did]?.lifecycle ?? 'finished',
    })),

  setLifecycle: (sessionId, did, lifecycle) =>
    set((state) => upsertCard(state, sessionId, did, { lifecycle })),

  setDiffText: (sessionId, did, diffText) =>
    set((state) => upsertCard(state, sessionId, did, { diffText })),

  remove: (sessionId, did) =>
    set((state) => {
      const sessionDelegations = state.delegationsBySession[sessionId];
      if (!sessionDelegations?.[did]) {
        return state;
      }
      const { [did]: _removedDelegation, ...remainingDelegations } =
        sessionDelegations;
      if (Object.keys(remainingDelegations).length === 0) {
        const { [sessionId]: _removedSession, ...delegationsBySession } =
          state.delegationsBySession;
        return { delegationsBySession };
      }
      return {
        delegationsBySession: {
          ...state.delegationsBySession,
          [sessionId]: remainingDelegations,
        },
      };
    }),

  clearSession: (sessionId) =>
    set((state) => {
      if (!state.delegationsBySession[sessionId]) {
        return state;
      }
      const { [sessionId]: _removed, ...delegationsBySession } =
        state.delegationsBySession;
      return { delegationsBySession };
    }),

  reset: () => set({ delegationsBySession: {} }),
}));


export const selectDelegationCard =
  (sessionId: string, did: string) =>
  (state: DelegationsStoreState): DelegationCardState | null =>
    state.delegationsBySession[sessionId]?.[did] ?? null;
