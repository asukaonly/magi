import { createHash } from 'node:crypto';
import examples from '../../../../contracts/api/frontend-plugins-examples.json';
import { parsePluginPlan } from '@/api/plugin-contract';
import type { PluginInstallPlan } from '@/api/modules/plugins';

export const closurePlan = (): PluginInstallPlan => parsePluginPlan(structuredClone(examples.plan), 'fixture-source', true);

export function planFor(pluginId: string, update = false): PluginInstallPlan {
  const template = closurePlan();
  const change = template.changes[1];
  const plan: PluginInstallPlan = {
    ...template,
    target_id: pluginId,
    update,
    coordinated: false,
    changes: [{
      ...change,
      entry: { ...change.entry, plugin_id: pluginId, name: pluginId, name_i18n: {}, depends_on: [], capabilities: [] },
      reason: 'requested',
      action: update ? 'update' : 'install',
      current_version: update ? '1.0.0' : null,
      current_package_sha256: update ? change.current_package_sha256 : null,
      current_installed_package_sha256: update ? change.current_installed_package_sha256 : null,
      current_dependency_package_sha256: {},
      dependency_package_sha256: {},
    }],
  };
  plan.fingerprint = createHash('sha256').update(JSON.stringify(plan)).digest('hex');
  return plan;
}
