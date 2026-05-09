import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import type {
  ApplyOutcome,
  DelegateResult,
  RunEvent,
} from '@/api/modules/codeAgent';
import { useDelegationsStore } from '@/stores/delegations-store';


const SESSION = 'session-A';
const DID = 'a'.repeat(32);


function _runEvent(kind: RunEvent['kind'], payload: Record<string, unknown> = {}): RunEvent {
  return { kind, ts_ms: Date.now(), payload };
}

function _result(extra: Partial<DelegateResult> = {}): DelegateResult {
  const { adapter, ...rest } = extra;
  return {
    delegation_id: DID,
    success: true,
    exit_code: 0,
    duration_ms: 1234,
    adapter: adapter ?? 'codex',
    diff_path: '/tmp/changes.patch',
    diff_stats: { files_changed: 1, additions: 4, deletions: 2 },
    files_changed: ['src/a.py'],
    summary: 'done',
    logs_path: '/tmp/logs',
    events_path: '/tmp/events.jsonl',
    error: null,
    cost: null,
    ...rest,
  };
}


describe('delegations-store', () => {
  beforeEach(() => {
    useDelegationsStore.getState().reset();
  });
  afterEach(() => {
    useDelegationsStore.getState().reset();
  });

  it('appending events promotes started -> running on first event', () => {
    useDelegationsStore.getState().upsertState(SESSION, DID, 'started', {});
    expect(useDelegationsStore.getState().delegationsBySession[SESSION][DID].lifecycle).toBe('started');

    useDelegationsStore.getState().upsertEvent(SESSION, DID, _runEvent('status'));
    expect(useDelegationsStore.getState().delegationsBySession[SESSION][DID].lifecycle).toBe('running');
  });

  it('caps events at 200', () => {
    for (let i = 0; i < 250; i += 1) {
      useDelegationsStore.getState().upsertEvent(SESSION, DID, _runEvent('status', { i }));
    }
    const events = useDelegationsStore.getState().delegationsBySession[SESSION][DID].events;
    expect(events.length).toBe(200);
    // Oldest events were dropped; the first kept event should have i=50.
    expect((events[0].payload as { i: number }).i).toBe(50);
  });

  it('upsertState with a result-shaped summary populates result', () => {
    const summary = _result({ delegation_id: DID, summary: 'all good' });
    useDelegationsStore.getState().upsertState(
      SESSION, DID, 'finished', summary as unknown as Record<string, unknown>,
    );
    const card = useDelegationsStore.getState().delegationsBySession[SESSION][DID];
    expect(card.lifecycle).toBe('finished');
    expect(card.result?.summary).toBe('all good');
  });

  it('setResult attaches a fetched result without changing lifecycle', () => {
    useDelegationsStore.getState().upsertState(SESSION, DID, 'started', {});
    useDelegationsStore.getState().setResult(SESSION, DID, _result());
    const card = useDelegationsStore.getState().delegationsBySession[SESSION][DID];
    expect(card.lifecycle).toBe('started');
    expect(card.result?.success).toBe(true);
  });

  it('setApplyOutcome applied=true flips lifecycle to applied', () => {
    useDelegationsStore.getState().upsertState(SESSION, DID, 'finished', {});
    const outcome: ApplyOutcome = {
      applied: true,
      files_applied: ['src/a.py'],
      rejects: [],
      error: null,
    };
    useDelegationsStore.getState().setApplyOutcome(SESSION, DID, outcome);
    const card = useDelegationsStore.getState().delegationsBySession[SESSION][DID];
    expect(card.lifecycle).toBe('applied');
    expect(card.applyOutcome?.applied).toBe(true);
  });

  it('setApplyOutcome applied=false keeps prior lifecycle', () => {
    useDelegationsStore.getState().upsertState(SESSION, DID, 'finished', {});
    useDelegationsStore.getState().setApplyOutcome(SESSION, DID, {
      applied: false,
      files_applied: [],
      rejects: ['src/a.py.rej'],
      error: 'conflict',
    });
    const card = useDelegationsStore.getState().delegationsBySession[SESSION][DID];
    expect(card.lifecycle).toBe('finished');
    expect(card.applyOutcome?.rejects).toEqual(['src/a.py.rej']);
  });

  it('reset clears delegationsBySession', () => {
    useDelegationsStore.getState().upsertState(SESSION, DID, 'started', {});
    useDelegationsStore.getState().reset();
    expect(useDelegationsStore.getState().delegationsBySession).toEqual({});
  });
});
