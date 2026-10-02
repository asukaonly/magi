import { useCallback, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { pluginsApi, type ExtensionFieldSpec, type PluginConnection } from '@/api/modules/plugins';
import type { SourceStatusItem } from '@/api/modules/sources';
import { validateConnectionField } from '@/components/plugins/connection-validation';
import { mergeConnectionSettings, readConnectionSetting } from '@/utils/plugin-connection-settings';

export interface ConnectionSettingsSeed {
  pluginId: string;
  connectionId: string;
  revision: number;
  name: string;
  enabled: boolean;
  values: Record<string, unknown>;
  fields: ExtensionFieldSpec[];
  credentialRefs?: Record<string, string>;
}
interface ConnectionChanges {
  values: Record<string, unknown>;
  name?: string;
  enabled?: boolean;
}
interface ConnectionDraft {
  base: ConnectionSettingsSeed;
  changes: ConnectionChanges;
  error?: 'conflict' | 'saveFailed';
}
const identity = (seed: ConnectionSettingsSeed) => `${seed.pluginId}:${seed.connectionId}`;
const changed = (draft: ConnectionDraft) => Object.keys(draft.changes.values).length > 0
  || draft.changes.name !== undefined || draft.changes.enabled !== undefined;
const equal = (left: unknown, right: unknown) => JSON.stringify(left) === JSON.stringify(right);

export const connectionSettingsSeed = (connection: PluginConnection, fields: ExtensionFieldSpec[]): ConnectionSettingsSeed => ({
  pluginId: connection.plugin_id, connectionId: connection.connection_id, revision: connection.revision,
  name: connection.display_name, enabled: connection.enabled, fields, credentialRefs: connection.credential_refs,
  values: Object.fromEntries(fields.map(field => [field.key, field.type === 'secret' ? '' : readConnectionSetting(connection.settings, field.key, field.default)])),
});
export const sourceSettingsSeed = (source: SourceStatusItem): ConnectionSettingsSeed => ({
  pluginId: source.plugin_id, connectionId: source.connection_id, revision: source.connection_revision,
  name: source.connection_display_name, enabled: true, fields: source.fields, values: source.current_settings,
});

/** Settings owns drafts across navigation; each connection retains its revision and write boundary. */
export function useConnectionSettings() {
  const { t } = useTranslation('app');
  const [drafts, setDrafts] = useState<Record<string, ConnectionDraft>>({});
  const current = useRef(drafts);
  const [saving, setSaving] = useState(false);
  const pending = useRef(false);
  const update = useCallback((fn: (value: Record<string, ConnectionDraft>) => Record<string, ConnectionDraft>) => {
    current.current = fn(current.current);
    setDrafts(current.current);
  }, []);

  const patch = useCallback((seed: ConnectionSettingsSeed, values: Record<string, unknown>, meta?: { name?: string; enabled?: boolean }) => {
    update(previous => {
      const id = identity(seed);
      const existing = previous[id];
      const base = existing && (changed(existing) || existing.base.revision >= seed.revision)
        ? { ...existing.base, fields: [...new Map([...seed.fields, ...existing.base.fields].map(field => [field.key, field])).values()],
          values: { ...seed.values, ...existing.base.values }, credentialRefs: { ...seed.credentialRefs, ...existing.base.credentialRefs } }
        : structuredClone(seed);
      const changes = { values: { ...existing?.changes.values, ...values }, name: meta?.name ?? existing?.changes.name,
        enabled: meta?.enabled ?? existing?.changes.enabled };
      for (const [key, value] of Object.entries(changes.values)) {
        if (equal(value, base.values[key])) delete changes.values[key];
      }
      if (changes.name === base.name) delete changes.name;
      if (changes.enabled === base.enabled) delete changes.enabled;
      return { ...previous, [id]: { base, changes, error: existing?.error } };
    });
  }, [update]);

  const read = (seed: ConnectionSettingsSeed) => {
    const draft = drafts[identity(seed)];
    const base = draft && (changed(draft) || draft.base.revision >= seed.revision) ? draft.base : seed;
    return { values: { ...seed.values, ...base.values, ...draft?.changes.values },
      name: draft?.changes.name ?? base.name, enabled: draft?.changes.enabled ?? base.enabled,
      dirty: !!draft && changed(draft),
      error: draft?.error ?? (draft && changed(draft) && seed.revision > draft.base.revision ? 'conflict' : undefined) };
  };
  const discard = useCallback((seed?: ConnectionSettingsSeed) => {
    update(previous => {
      if (!seed) return Object.fromEntries(Object.entries(previous).map(([id, draft]) => [id, { base: draft.base, changes: { values: {} } }]));
      const next = { ...previous }; delete next[identity(seed)]; return next;
    });
  }, [update]);

  const validateDraft = useCallback((draft: ConnectionDraft): string | null => {
    const { base, changes } = draft;
    if (changes.name !== undefined && !changes.name.trim()) return t('plugins.connections.nameRequired');
    const values = { ...base.values, ...changes.values };
    for (const field of base.fields) {
      if (!(field.key in changes.values) && changes.enabled !== true) continue;
      const value = field.type === 'secret' && !(field.key in changes.values) ? base.credentialRefs?.[field.key] : values[field.key];
      const issue = validateConnectionField(field, value === null && field.type === 'secret' ? undefined : value,
        values, changes.enabled ?? base.enabled);
      if (issue) return t('settings.dynamicValidation.fieldInvalid', {
        field: field.label_translated || field.label, reason: t(`settings.dynamicValidation.${issue}`),
      });
    }
    return null;
  }, [t]);
  const capture = useCallback(() => structuredClone(current.current), []);
  const validate = useCallback((snapshot = current.current) => Object.values(snapshot).filter(changed).map(validateDraft).find(Boolean) ?? null, [validateDraft]);

  const save = useCallback(async (snapshot = current.current) => {
    if (pending.current) return;
    const validation = validate(snapshot);
    if (validation) throw new Error(validation);
    const submitted = structuredClone(snapshot);
    pending.current = true; setSaving(true);
    const failures: string[] = [];
    try {
      for (const [id, draft] of Object.entries(submitted)) {
        if (!changed(draft)) continue;
        const { base, changes } = draft;
        try {
          const connection = await pluginsApi.getConnection(base.pluginId, base.connectionId);
          if (connection.plugin_id !== base.pluginId || connection.connection_id !== base.connectionId) throw new Error('Connection response identity mismatch');
          if (connection.revision !== base.revision) throw Object.assign(new Error('Connection revision conflict'), { status: 409 });
          const settings = { ...changes.values };
          const credentials: Record<string, string | null> = {};
          for (const field of base.fields) {
            if (field.type !== 'secret' || !(field.key in settings)) continue;
            const value = settings[field.key];
            if (typeof value === 'string' && value || value === null) credentials[field.key] = value;
            delete settings[field.key];
          }
          const saved = await pluginsApi.updateConnection(base.pluginId, base.connectionId, {
            expected_revision: base.revision, settings: mergeConnectionSettings(connection.settings, settings), credentials,
            ...(changes.name !== undefined ? { display_name: changes.name.trim() } : {}),
            ...(changes.enabled !== undefined ? { enabled: changes.enabled } : {}),
          });
          if (saved.plugin_id !== base.pluginId || saved.connection_id !== base.connectionId) throw new Error('Saved connection identity mismatch');
          update(previous => {
            const latest = previous[id];
            if (!latest) return previous;
            const remaining = { ...latest.changes, values: { ...latest.changes.values } };
            for (const [key, value] of Object.entries(changes.values)) {
              if (equal(remaining.values[key], value)) delete remaining.values[key];
            }
            if (remaining.name === changes.name) delete remaining.name;
            if (remaining.enabled === changes.enabled) delete remaining.enabled;
            const canonical = connectionSettingsSeed(saved, latest.base.fields);
            canonical.values = { ...latest.base.values, ...Object.fromEntries(Object.keys(settings).map(key => [key, readConnectionSetting(saved.settings, key)])), ...canonical.values };
            return { ...previous, [id]: { base: canonical, changes: remaining } };
          });
        } catch (error) {
          const conflict = typeof error === 'object' && error !== null && 'status' in error && (error.status === 409 || error.status === 428);
          const code = conflict ? 'conflict' : 'saveFailed';
          failures.push(`${base.name}: ${t(`plugins.connections.${code}`)}`);
          update(previous => previous[id] ? { ...previous, [id]: { ...previous[id], error: code } } : previous);
        }
      }
      if (failures.length) throw new Error(failures.join('\n'));
    } finally { pending.current = false; setSaving(false); }
  }, [t, update, validate]);

  return { dirty: Object.values(drafts).some(changed), saving, read, patch, discard, capture, validate, save };
}
export type ConnectionSettingsController = ReturnType<typeof useConnectionSettings>;
