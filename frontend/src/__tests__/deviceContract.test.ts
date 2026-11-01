import { describe, expect, it } from 'vitest';
import { validateCollectorScope, validateSourceObservation } from '@/api/generated/device-validators';

describe('device capability wire contracts', () => {
  const identity = { capability_id: 'notes.observe', protocol: 'source.change.v1', schema_id: 'notes.item', schema_version: 1 };
  const connection = { connection_id: 'conn_11111111111111111111111111111111', connection_epoch: '11111111-1111-1111-1111-111111111111', source_type: 'notes' };
  it('accepts a portable observation and rejects plugin routing and unsupported resources', () => {
    const observation = { ...identity, ...connection, kind: 'source_observation', change: { object_id: 'note:1', version: 'r1', payload: { text: 'Note' } } };
    expect(validateSourceObservation(observation)).toBe(true);
    expect(validateSourceObservation({ ...observation, plugin_target: 'arbitrary-plugin' })).toBe(false);
    expect(validateSourceObservation({ ...observation, schema_version: 0 })).toBe(false);
    expect(validateSourceObservation({ ...observation, change: { ...observation.change, resources: [{}] } })).toBe(false);
  });
  it('requires a declared payload schema without depending on package identity', () => {
    const scope = { ...connection, capability: { ...identity, direction: 'observe', supports_resources: false, payload_schema: { type: 'object' } }, claimed_by: 'device' };
    expect(validateCollectorScope(scope)).toBe(true);
    expect(validateCollectorScope({ ...scope, plugin_version: '1.0.0' })).toBe(false);
    expect(validateCollectorScope({ ...scope, capability: { ...identity } })).toBe(false);
  });
});
