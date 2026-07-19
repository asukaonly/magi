import { act, renderHook, waitFor } from '@testing-library/react';
import { StrictMode, type ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { codeAgentApi } from '@/api/modules/codeAgent';
import { useDelegationHydration } from '@/hooks/useDelegationHydration';
import {
  resetRealtimeChatProjectionRetirementForTests,
  retireRealtimeChatTurn,
} from '@/realtime/chat-projection-retirement';
import { useDelegationsStore } from '@/stores/delegations-store';

vi.mock('@/api/modules/codeAgent', async () => {
  const actual = await vi.importActual<typeof import('@/api/modules/codeAgent')>(
    '@/api/modules/codeAgent',
  );
  return {
    ...actual,
    codeAgentApi: {
      ...actual.codeAgentApi,
      getDelegation: vi.fn(),
    },
  };
});

const SESSION_ID = 'session-1';
const TURN_ID = 'turn-1';
const DELEGATION_ID = 'delegation-1';
const WORKSPACE = '/tmp/workspace';

describe('useDelegationHydration', () => {
  beforeEach(() => {
    vi.mocked(codeAgentApi.getDelegation).mockReset();
    useDelegationsStore.getState().reset();
    resetRealtimeChatProjectionRetirementForTests();
  });

  afterEach(() => {
    useDelegationsStore.getState().reset();
    resetRealtimeChatProjectionRetirementForTests();
  });

  it('marks an empty response hydrated and does not fetch it again', async () => {
    vi.mocked(codeAgentApi.getDelegation).mockResolvedValue({
      result: null,
      events_tail: [],
      diff_text: '',
    });
    const { rerender } = renderHook(() => useDelegationHydration(
      SESSION_ID,
      DELEGATION_ID,
      TURN_ID,
      WORKSPACE,
    ));

    await waitFor(() => {
      expect(
        useDelegationsStore.getState()
          .delegationsBySession[SESSION_ID]?.[DELEGATION_ID]?.hydrated,
      ).toBe(true);
    });
    rerender();

    expect(codeAgentApi.getDelegation).toHaveBeenCalledTimes(1);
  });

  it('records a failed attempt without entering a fetch loop', async () => {
    vi.mocked(codeAgentApi.getDelegation).mockRejectedValue(new Error('offline'));
    const { rerender } = renderHook(() => useDelegationHydration(
      SESSION_ID,
      DELEGATION_ID,
      TURN_ID,
      WORKSPACE,
    ));

    await waitFor(() => {
      const card = useDelegationsStore.getState()
        .delegationsBySession[SESSION_ID]?.[DELEGATION_ID];
      expect(card?.hydrationAttempted).toBe(true);
      expect(card?.lifecycle).toBe('failed');
    });
    rerender();

    expect(codeAgentApi.getDelegation).toHaveBeenCalledTimes(1);
  });

  it('does not mark an existing realtime card failed when a best-effort read fails', async () => {
    useDelegationsStore.getState().upsertState(
      SESSION_ID,
      DELEGATION_ID,
      TURN_ID,
      'started',
      {},
    );
    vi.mocked(codeAgentApi.getDelegation).mockRejectedValue(new Error('offline'));

    renderHook(() => useDelegationHydration(
      SESSION_ID,
      DELEGATION_ID,
      TURN_ID,
      WORKSPACE,
    ));

    await waitFor(() => {
      const card = useDelegationsStore.getState()
        .delegationsBySession[SESSION_ID]?.[DELEGATION_ID];
      expect(card?.hydrationAttempted).toBe(true);
      expect(card?.lifecycle).toBe('started');
    });
  });

  it('completes hydration after StrictMode replays the mount effect', async () => {
    vi.mocked(codeAgentApi.getDelegation).mockResolvedValue({
      result: null,
      events_tail: [],
      diff_text: '',
    });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <StrictMode>{children}</StrictMode>
    );

    renderHook(() => useDelegationHydration(
      SESSION_ID,
      DELEGATION_ID,
      TURN_ID,
      WORKSPACE,
    ), { wrapper });

    await waitFor(() => {
      expect(
        useDelegationsStore.getState()
          .delegationsBySession[SESSION_ID]?.[DELEGATION_ID]?.hydrated,
      ).toBe(true);
    });
  });

  it('does not recreate a cleared turn when hydration resolves late', async () => {
    let resolveRequest!: (
      value: Awaited<ReturnType<typeof codeAgentApi.getDelegation>>,
    ) => void;
    vi.mocked(codeAgentApi.getDelegation).mockReturnValue(
      new Promise((resolve) => {
        resolveRequest = resolve;
      }),
    );
    renderHook(() => useDelegationHydration(
      SESSION_ID,
      DELEGATION_ID,
      TURN_ID,
      WORKSPACE,
    ));
    await waitFor(() => {
      expect(codeAgentApi.getDelegation).toHaveBeenCalledTimes(1);
    });

    retireRealtimeChatTurn(SESSION_ID, TURN_ID);
    useDelegationsStore.getState().remove(SESSION_ID, DELEGATION_ID);
    await act(async () => {
      resolveRequest({
        result: null,
        events_tail: [],
        diff_text: '',
      });
      await Promise.resolve();
    });

    expect(
      useDelegationsStore.getState().delegationsBySession[SESSION_ID],
    ).toBeUndefined();
  });
});
