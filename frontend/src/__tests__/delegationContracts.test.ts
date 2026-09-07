import { beforeEach, expect, it, vi } from 'vitest';
import fixtures from '../../../contracts/api/frontend-events-examples.json';
import { codeAgentApi } from '@/api/modules/codeAgent';
import { applyRealtimeStoreProjection } from '@/realtime/store-projection';
import { useDelegationsStore } from '@/stores/delegations-store';

const get = vi.hoisted(() => vi.fn());
vi.mock('@/api/client', () => ({ api: { get } }));
const did = fixtures.delegateResult.delegation_id;
const response = { result: fixtures.delegateResult, events_tail: [fixtures.runEvent], diff_text: '' };

beforeEach(() => { get.mockReset(); useDelegationsStore.getState().reset(); });

it('accepts the production result through REST and live terminal projection', async () => {
  get.mockResolvedValue(response);
  await expect(codeAgentApi.getDelegation('session', did, '/workspace')).resolves.toEqual(response);
  expect(applyRealtimeStoreProjection({ event: 'code_agent_delegation_state', data: {
    session_id: 'session', turn_id: 'turn', delegation_id: did, state: 'finished', summary: fixtures.delegateResult,
  } })).toBe(true);
  expect(useDelegationsStore.getState().delegationsBySession.session[did].result).toEqual(fixtures.delegateResult);
});

it.each([
  { ...fixtures.delegateResult, delegation_id: 'foreign' },
  { ...fixtures.delegateResult, files_changed: 'not-an-array' },
  { ...fixtures.delegateResult, success: 'yes' },
  { ...fixtures.delegateResult, diff_stats: { files_changed: -1, additions: 0, deletions: 0 } },
  { ...fixtures.delegateResult, cost: { usd: null, input_tokens: '1', output_tokens: 0 } },
  { ...fixtures.delegateResult, discarded_at: 'yesterday' },
  { delegation_id: did },
])('rejects malformed or foreign results at both boundaries', async result => {
  get.mockResolvedValue({ ...response, result });
  await expect(codeAgentApi.getDelegation('session', did, '/workspace')).rejects.toThrow();
  expect(applyRealtimeStoreProjection({ event: 'code_agent_delegation_state', data: {
    session_id: 'session', turn_id: 'turn', delegation_id: did, state: 'finished', summary: result,
  } })).toBe(false);
  expect(useDelegationsStore.getState().delegationsBySession).toEqual({});
});

it('validates persisted discard metadata and accepts a running delegation without a result', async () => {
  const discarded = { ...response, result: { ...fixtures.delegateResult, discarded_at: 1000 } };
  get.mockResolvedValueOnce(discarded).mockResolvedValueOnce({ ...response, result: null });
  await expect(codeAgentApi.getDelegation('session', did, '/workspace')).resolves.toEqual(discarded);
  await expect(codeAgentApi.getDelegation('session', did, '/workspace')).resolves.toMatchObject({ result: null });
});

it.each([
  {}, { ...response, events_tail: [{ kind: 'invented', ts_ms: 0, payload: {} }] },
  { ...response, diff_text: 3 }, { success: true, data: response },
])('rejects incomplete or wrapped persisted responses', async value => {
  get.mockResolvedValue(value);
  await expect(codeAgentApi.getDelegation('session', did, '/workspace')).rejects.toThrow();
});
