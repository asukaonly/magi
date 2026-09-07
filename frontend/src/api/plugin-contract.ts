import { z } from 'zod';
import { ApiContractError } from './config-contract';
import * as validators from './generated/plugins-validators';
import type { components } from './generated/plugins-types';
import type {
  PluginInstallCandidate, PluginInstallJobSnapshot, PluginPackageState, PluginRegistryResponse,
  PluginSettingsActionRunResponse, PluginSettingsResourcePayload, PluginsListResponse,
  PluginConnection, PluginInstallPlan,
} from './modules/plugins';

function parse<T>(name: string, value: unknown, validate: (value: unknown) => value is T): T {
  if (!validate(value)) throw new ApiContractError(name);
  return value;
}

export const parsePluginPackage = (value: unknown): PluginPackageState =>
  parse('plugin package', value, validators.validatePluginPackageResponse);
export const parsePluginsList = (value: unknown): PluginsListResponse =>
  parse('plugin list', value, validators.validatePluginsListResponse);
export const parsePluginCandidate = (value: unknown): PluginInstallCandidate =>
  parse('plugin candidate', value, validators.validatePluginInstallCandidateResponse);
export const parsePluginRegistry = (value: unknown): PluginRegistryResponse =>
  parse('plugin registry', value, validators.validatePluginRegistryResponse);
export function parsePluginPlan(value: unknown, pluginId: string, update: boolean): PluginInstallPlan {
  const plan = parse('plugin install plan', value, validators.validatePluginInstallPlanResponse);
  const ids = plan.changes.map(change => change.entry.plugin_id);
  if (plan.target_id !== pluginId || plan.update !== update || !ids.includes(pluginId) || new Set(ids).size !== ids.length) {
    throw new ApiContractError('plugin install plan identity');
  }
  return plan;
}

export const parsePluginAction = (value: unknown): PluginSettingsActionRunResponse =>
  parse('plugin action', value, validators.validatePluginSettingsActionRunResponse);

export function parsePluginConnection(value: unknown, pluginId: string, connectionId?: string): PluginConnection {
  const connection = parse('plugin connection', value, validators.validatePluginConnectionResponse);
  if (connection.plugin_id !== pluginId || (connectionId !== undefined && connection.connection_id !== connectionId)) {
    throw new ApiContractError('Plugin connection identity mismatch');
  }
  return connection;
}

export function parsePluginConnections(value: unknown, pluginId: string): PluginConnection[] {
  const result = parse('plugin connections', value, validators.validatePluginConnectionsResponse);
  return result.connections.map(connection => parsePluginConnection(connection, pluginId));
}

export function parsePluginJob(value: unknown): PluginInstallJobSnapshot {
  const job = parse('plugin install job', value, validators.validatePluginInstallJobSnapshot);
  if (job.status === 'completed' && !job.result) throw new ApiContractError('completed plugin install job');
  return job;
}

export function parsePluginResource(value: unknown): PluginSettingsResourcePayload {
  const resource = parse('plugin resource', value, validators.validatePluginSettingsResourceResponse);
  const data = z.record(z.string(), z.unknown()).safeParse(resource.data);
  if (!data.success) throw new ApiContractError('plugin resource data');
  return { ...resource, data: data.data };
}

const resourceGroups = z.array(z.object({
  group_id: z.string(), label: z.string(),
  items: z.array(z.object({ item_id: z.string(), label: z.string(), description: z.string().optional(), accent_color: z.string().nullable().optional() })),
}));
const permissionItems = z.array(z.object({
  id: z.string(), label: z.string(), description: z.string().optional(),
  label_i18n_key: z.string().optional(), description_i18n_key: z.string().optional(),
  required: z.boolean().optional(), settings_url: z.string().optional(),
  status: z.enum(['granted', 'denied', 'not_determined', 'unknown']),
}));

export function parsePluginResourceGroups(value: unknown) {
  const result = resourceGroups.safeParse(value);
  if (!result.success) throw new ApiContractError('plugin resource groups');
  return result.data;
}

export function parsePluginPermissionItems(value: unknown) {
  const result = permissionItems.safeParse(value);
  if (!result.success) throw new ApiContractError('plugin permission items');
  return result.data;
}

export type PluginWireTypes = components['schemas'];
