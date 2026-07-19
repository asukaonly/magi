import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { applyRealtimeStoreProjection } from '@/realtime/store-projection';
import {
  canApplyRealtimeChatDelegationProjection,
  resetRealtimeChatProjectionRetirementForTests,
  retireRealtimeChatMessage,
  retireRealtimeChatTurn,
} from '@/realtime/chat-projection-retirement';
import { useDelegationsStore } from '@/stores/delegations-store';

const SESSION = 'session-A';
const DID = 'b'.repeat(32);


describe('delegations realtime projection', () => {
  beforeEach(() => {
    useDelegationsStore.getState().reset();
    resetRealtimeChatProjectionRetirementForTests();
  });
  afterEach(() => {
    useDelegationsStore.getState().reset();
    resetRealtimeChatProjectionRetirementForTests();
  });

  it('projects code_agent_delegation_event', () => {
    const ok = applyRealtimeStoreProjection({
      event: 'code_agent_delegation_event',
      data: {
        user_id: 'u',
        session_id: SESSION,
        turn_id: 'turn-A',
        delegation_id: DID,
        event: { kind: 'status', ts_ms: 1, payload: { hi: true } },
      },
    });
    expect(ok).toBe(true);
    const card = useDelegationsStore.getState().delegationsBySession[SESSION]?.[DID];
    expect(card?.events).toHaveLength(1);
    expect(card?.events[0].kind).toBe('status');
  });

  it('projects code_agent_delegation_state and hydrates result on terminal', () => {
    const ok = applyRealtimeStoreProjection({
      event: 'code_agent_delegation_state',
      data: {
        user_id: 'u',
        session_id: SESSION,
        turn_id: 'turn-A',
        delegation_id: DID,
        state: 'finished',
        summary: {
          delegation_id: DID,
          success: true,
          exit_code: 0,
          duration_ms: 100,
          diff_path: '/tmp/x',
          diff_stats: { files_changed: 1, additions: 1, deletions: 0 },
          files_changed: ['x.py'],
          summary: 'fine',
          logs_path: '/tmp/logs',
          events_path: '/tmp/events',
          error: null,
          cost: null,
        },
      },
    });
    expect(ok).toBe(true);
    const card = useDelegationsStore.getState().delegationsBySession[SESSION]?.[DID];
    expect(card?.lifecycle).toBe('finished');
    expect(card?.result?.summary).toBe('fine');
  });

  it('rejects malformed events', () => {
    const ok = applyRealtimeStoreProjection({
      event: 'code_agent_delegation_event',
      data: {
        session_id: SESSION,
        turn_id: 'turn-A',
        delegation_id: DID,
      },  // no event payload
    });
    expect(ok).toBe(false);
    expect(Object.keys(useDelegationsStore.getState().delegationsBySession)).toHaveLength(0);
  });

  it('rejects malformed state messages', () => {
    const ok = applyRealtimeStoreProjection({
      event: 'code_agent_delegation_state',
      data: {
        turn_id: 'turn-A',
        delegation_id: DID,
        state: 'finished',
      },  // no session_id
    });
    expect(ok).toBe(false);
  });

  it('rejects an unknown delegation event after its turn was cleared', () => {
    retireRealtimeChatTurn(SESSION, 'turn-A');

    const ok = applyRealtimeStoreProjection({
      event: 'code_agent_delegation_event',
      data: {
        user_id: 'u',
        session_id: SESSION,
        turn_id: 'turn-A',
        delegation_id: DID,
        event: { kind: 'status', ts_ms: 1, payload: {} },
      },
    });

    expect(ok).toBe(false);
    expect(
      useDelegationsStore.getState().delegationsBySession[SESSION],
    ).toBeUndefined();
  });

  it('retires every explicit code delegation without retiring a background task id', () => {
    const secondDelegationId = 'c'.repeat(32);
    retireRealtimeChatMessage(SESSION, {
      id: 'message-A',
      messageId: 'message-A',
      payload: {
        code_agent_delegations: [
          {
            delegation_id: DID,
            turn_id: 'turn-A',
            workspace_path: '/tmp/workspace-A',
          },
          {
            delegation_id: secondDelegationId,
            turn_id: 'turn-B',
            workspace_path: '/tmp/workspace-B',
          },
        ],
        background_task_id: 'ordinary-background-task',
      },
    });

    expect(
      canApplyRealtimeChatDelegationProjection(SESSION, DID),
    ).toBe(false);
    expect(
      canApplyRealtimeChatDelegationProjection(SESSION, secondDelegationId),
    ).toBe(false);
    expect(
      canApplyRealtimeChatDelegationProjection(
        SESSION,
        'ordinary-background-task',
      ),
    ).toBe(true);
  });
});
