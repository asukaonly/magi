import type { ActivationFlowSpec } from '@/api/modules/plugins';

/** Scheduler choices remain explicit even when other first-run defaults are hidden. */
export function firstContextSyncKeys(flow: ActivationFlowSpec) {
  const enabledKey = flow.enabled_key ?? '';
  if (!enabledKey.startsWith('sources.') || !enabledKey.endsWith('.enabled')) return [];
  const prefix = enabledKey.slice(0, -'.enabled'.length);
  return [`${prefix}.sync_mode`, `${prefix}.sync_interval_minutes`];
}
