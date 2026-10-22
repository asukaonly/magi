import { describe, expect, it } from 'vitest';
import { endpointCatalogSchema, deliveryPreferencesSchema, endpointKey } from '@/api/modules/channelEndpoints';

const endpoint = {connection_id: 'account', contribution_id: 'telegram', target_id: 'group', thread_id: 'one', device_id: null};
describe('channel endpoint contracts', () => {
  it('preserves connection and thread identity', () => {
    const parsed = endpointCatalogSchema.parse({endpoints: [{endpoint, label: 'Family', capabilities: ['message'], available: false}]});
    expect(parsed.endpoints[0].endpoint).toEqual(endpoint);
    expect(endpointKey(endpoint)).not.toBe(endpointKey({...endpoint, thread_id: 'two'}));
    expect(endpointKey(endpoint)).not.toBe(endpointKey({...endpoint, connection_id: 'another'}));
  });
  it('rejects incomplete and malformed destinations', () => {
    for (const value of [{target_id: 'group'}, {...endpoint, target_id: ''}, {...endpoint, extra: true}]) {
      expect(deliveryPreferencesSchema.safeParse({targets: [value]}).success).toBe(false);
    }
    expect(endpointCatalogSchema.safeParse({endpoints: [{endpoint, label: 'Family', capabilities: ['execute'], available: true}]}).success).toBe(false);
  });
});
