import type { PluginCapability } from '@/api/modules/plugins';

export type CapabilityGroup = 'system' | 'data';

export interface CapabilityMeta {
  group: CapabilityGroup;
  icon: string;          // lucide icon name used by the dialog
  i18nKey: string;       // settings.marketplace.capability.<key>
  known: boolean;
}

const KNOWN: Record<string, { group: CapabilityGroup; icon: string }> = {
  screen_recording: { group: 'system', icon: 'Monitor' },
  accessibility: { group: 'system', icon: 'Accessibility' },
  calendar: { group: 'system', icon: 'Calendar' },
  photos: { group: 'system', icon: 'Image' },
  contacts: { group: 'system', icon: 'Users' },
  system_media: { group: 'system', icon: 'Music' },
  filesystem_read: { group: 'data', icon: 'FileText' },
  filesystem_write: { group: 'data', icon: 'FilePen' },
  network: { group: 'data', icon: 'Globe' },
  subprocess: { group: 'data', icon: 'Terminal' },
};

export function capabilityMeta(capability: string): CapabilityMeta {
  const entry = KNOWN[capability];
  if (entry) {
    return { ...entry, i18nKey: `settings.marketplace.capability.${capability}`, known: true };
  }
  return { group: 'data', icon: 'ShieldQuestionMark', i18nKey: 'settings.marketplace.capability.unknown', known: false };
}

export function groupCapabilities(caps: PluginCapability[]): {
  system: PluginCapability[];
  data: PluginCapability[];
} {
  const system: PluginCapability[] = [];
  const data: PluginCapability[] = [];
  for (const c of caps) {
    (capabilityMeta(c.capability).group === 'system' ? system : data).push(c);
  }
  return { system, data };
}

/** Returns the declared capabilities NOT covered by the consented set
 *  (a new category, a new scope entry, or broadening to "any" scope). */
export function capabilitiesExceedingConsent(
  declared: PluginCapability[],
  consented: PluginCapability[] | null | undefined,
): PluginCapability[] {
  const cons = consented ?? [];
  const isCovered = (c: PluginCapability): boolean => {
    const peers = cons.filter((p) => p.capability === c.capability);
    if (peers.length === 0) return false;
    const cScope = c.scope ?? [];
    if (cScope.length === 0) {
      return peers.some((p) => (p.scope ?? []).length === 0);
    }
    return peers.some((p) => {
      const ps = p.scope ?? [];
      if (ps.length === 0) return true;
      return cScope.every((s) => ps.includes(s));
    });
  };
  return declared.filter((c) => !isCovered(c));
}
