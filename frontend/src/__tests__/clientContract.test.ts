import { describe, expect, it } from 'vitest';
import { parseSendConfirmation, parseTurnSnapshot } from '@/api/client-contract';

describe('client product contracts', () => {
  const snapshot = {
    session_id: 's', turn_id: 't', acceptance: 'accepted', state: 'completed',
    terminal: true, response_complete: true, can_resubmit: false,
    presentation_ends_at_ms: 1000, revision: 'r:2',
  };
  it('rejects wrong identities, incomplete responses and contradictory retry decisions', () => {
    expect(parseTurnSnapshot(snapshot, 's', 't')).toEqual(snapshot);
    expect(() => parseTurnSnapshot(snapshot, 's', 'other')).toThrow();
    expect(() => parseTurnSnapshot({ ...snapshot, terminal: false }, 's', 't')).toThrow();
    expect(() => parseTurnSnapshot({ ...snapshot, can_resubmit: true }, 's', 't')).toThrow();
    expect(() => parseTurnSnapshot({ ...snapshot, revision: undefined }, 's', 't')).toThrow();
    expect(() => parseTurnSnapshot({ ...snapshot, state: 'invented' }, 's', 't')).toThrow();
    const request = { kind: 'turn' as const, session_id: 's', turn_id: 't' };
    const receipt = { session_id: 's', identity: 't', status: 'confirmed', safe_to_retry: false };
    expect(parseSendConfirmation(receipt, request)).toEqual(receipt);
    expect(() => parseSendConfirmation({ ...receipt, identity: 'other' }, request)).toThrow();
    expect(() => parseSendConfirmation({ ...receipt, safe_to_retry: true }, request)).toThrow();
  });
});
