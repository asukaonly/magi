import { describe, it, expect } from 'vitest';
import {
  capabilityMeta,
  groupCapabilities,
  capabilitiesExceedingConsent,
} from '@/lib/pluginCapabilities';
import type { PluginCapability } from '@/api/modules/plugins';

const cap = (capability: string, scope: string[] = []): PluginCapability => ({
  capability, scope, optional: false, reason: '', reason_i18n: {},
});

describe('capabilityMeta', () => {
  it('maps a known capability to a group', () => {
    expect(capabilityMeta('calendar').group).toBe('system');
    expect(capabilityMeta('network').group).toBe('data');
  });
  it('falls back gracefully for unknown', () => {
    const m = capabilityMeta('future_thing');
    expect(m.group).toBe('data');
    expect(m.known).toBe(false);
  });
});

describe('groupCapabilities', () => {
  it('splits into system and data', () => {
    const g = groupCapabilities([cap('calendar'), cap('network')]);
    expect(g.system.map((c) => c.capability)).toEqual(['calendar']);
    expect(g.data.map((c) => c.capability)).toEqual(['network']);
  });
});

describe('capabilitiesExceedingConsent', () => {
  it('returns [] when declared is a scope-subset of consented', () => {
    const declared = [cap('network', ['a.com'])];
    const consented = [cap('network', ['a.com', 'b.com'])];
    expect(capabilitiesExceedingConsent(declared, consented)).toEqual([]);
  });
  it('flags a new category', () => {
    const out = capabilitiesExceedingConsent([cap('subprocess', ['git'])], [cap('network')]);
    expect(out.map((c) => c.capability)).toEqual(['subprocess']);
  });
  it('flags a new scope entry', () => {
    const out = capabilitiesExceedingConsent([cap('network', ['evil.com'])], [cap('network', ['a.com'])]);
    expect(out.map((c) => c.capability)).toEqual(['network']);
  });
  it('flags broadening specific -> any', () => {
    const out = capabilitiesExceedingConsent([cap('network', [])], [cap('network', ['a.com'])]);
    expect(out.length).toBe(1);
  });
  it('any covered by consented-any', () => {
    expect(capabilitiesExceedingConsent([cap('network', [])], [cap('network', [])])).toEqual([]);
  });
  it('treats null consented as empty (all exceed)', () => {
    expect(capabilitiesExceedingConsent([cap('calendar')], null).length).toBe(1);
  });
});
