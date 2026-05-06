import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { applyRealtimeStoreProjection } from '@/realtime/store-projection';
import { useDelegationsStore } from '@/stores/delegations-store';

const SESSION = 'session-A';
const DID = 'b'.repeat(32);


describe('delegations realtime projection', () => {
  beforeEach(() => {
    useDelegationsStore.getState().reset();
  });
  afterEach(() => {
    useDelegationsStore.getState().reset();
  });

  it('projects code_agent_delegation_event', () => {
    const ok = applyRealtimeStoreProjection({
      event: 'code_agent_delegation_event',
      data: {
        user_id: 'u',
        session_id: SESSION,
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
      data: { session_id: SESSION, delegation_id: DID },  // no event payload
    });
    expect(ok).toBe(false);
    expect(Object.keys(useDelegationsStore.getState().delegationsBySession)).toHaveLength(0);
  });

  it('rejects malformed state messages', () => {
    const ok = applyRealtimeStoreProjection({
      event: 'code_agent_delegation_state',
      data: { delegation_id: DID, state: 'finished' },  // no session_id
    });
    expect(ok).toBe(false);
  });
});
