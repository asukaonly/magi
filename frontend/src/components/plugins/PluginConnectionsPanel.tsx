import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { pluginsApi, type ExtensionFieldSpec, type PluginConnection, type PluginSettingsActionSpec, type PluginSettingsUiBlockSpec } from '@/api/modules/plugins';
import { PluginSettingsFields } from '@/components/settings/PluginSettingsFields';
import { PluginSettingsActions } from '@/components/settings/PluginSettingsActions';
import { PluginSettingsCustomBlocks } from '@/components/settings/PluginSettingsCustomBlocks';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';

interface PluginConnectionsPanelProps {
  pluginId: string;
  fields: ExtensionFieldSpec[];
  canEnable?: boolean;
  actions?: PluginSettingsActionSpec[];
  blocks?: PluginSettingsUiBlockSpec[];
  selectedConnectionId?: string | null;
  onSelectConnection?: (connectionId: string) => void;
  renderConnection?: (connection: PluginConnection) => ReactNode;
  onChanged?: () => void;
}

interface Editor {
  connection: PluginConnection | null;
  displayName: string;
  settings: Record<string, unknown>;
  credentials: Record<string, string | null>;
}

const errorStatus = (error: unknown): number | undefined => {
  if (!error || typeof error !== 'object') return undefined;
  const response = (error as { response?: { status?: number }; status?: number }).response;
  return response?.status ?? (error as { status?: number }).status;
};

const fieldValue = (settings: Record<string, unknown>, key: string): unknown => {
  if (Object.prototype.hasOwnProperty.call(settings, key)) return settings[key];
  return key.split('.').reduce<unknown>((value, part) => (
    value && typeof value === 'object' ? (value as Record<string, unknown>)[part] : undefined
  ), settings);
};

const writeSetting = (settings: Record<string, unknown>, key: string, value: unknown): Record<string, unknown> => {
  if (Object.prototype.hasOwnProperty.call(settings, key)) return { ...settings, [key]: value };
  const [first, ...rest] = key.split('.');
  if (!rest.length) return { ...settings, [first]: value };
  const child = settings[first];
  return { ...settings, [first]: writeSetting(
    child && typeof child === 'object' && !Array.isArray(child) ? child as Record<string, unknown> : {},
    rest.join('.'), value
  ) };
};

const NO_ACTIONS: PluginSettingsActionSpec[] = [];
const NO_BLOCKS: PluginSettingsUiBlockSpec[] = [];

export const PluginConnectionsPanel = ({ pluginId, fields, canEnable = false, actions = NO_ACTIONS, blocks = NO_BLOCKS,
  selectedConnectionId, onSelectConnection, renderConnection, onChanged }: PluginConnectionsPanelProps) => {
  const { t } = useTranslation('app');
  const titleId = useId();
  const nameId = useId();
  const [connections, setConnections] = useState<PluginConnection[]>([]);
  const [localSelection, setLocalSelection] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const [error, setError] = useState<string | null>(null);
  const [editor, setEditor] = useState<Editor | null>(null);
  const [confirmation, setConfirmation] = useState<{ connection: PluginConnection; action: 'clear' | 'disconnect' } | null>(null);
  const requestGeneration = useRef(0);
  const currentPlugin = useRef(pluginId);
  currentPlugin.current = pluginId;

  const refresh = useCallback(async () => {
    const generation = ++requestGeneration.current;
    setLoading(true);
    try {
      const result = await pluginsApi.listConnections(pluginId);
      if (generation === requestGeneration.current) setConnections(result);
    } catch {
      if (generation === requestGeneration.current) {
        setConnections([]);
        setError('loadFailed');
      }
    } finally {
      if (generation === requestGeneration.current) setLoading(false);
    }
  }, [pluginId]);

  useEffect(() => {
    setConnections([]);
    setLocalSelection(null);
    setEditor(null);
    setConfirmation(null);
    setError(null);
    void refresh();
    return () => { requestGeneration.current += 1; };
  }, [refresh]);

  const mutate = async (operation: () => Promise<unknown>, onSuccess?: () => void) => {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setError(null);
    const owner = pluginId;
    try {
      await operation();
      if (currentPlugin.current !== owner) return;
      onSuccess?.();
      await refresh();
      onChanged?.();
    } catch (failure) {
      if (currentPlugin.current !== owner) return;
      const status = errorStatus(failure);
      setError(status === 409 ? 'conflict' : status === 403 ? 'authorizationRequired' : 'saveFailed');
      if (status === 409) await refresh();
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  };

  const startEditor = (connection: PluginConnection | null) => {
    let settings: Record<string, unknown> = connection ? structuredClone(connection.settings) : {};
    if (!connection) {
      for (const field of fields) {
        if (field.type !== 'secret' && field.default !== undefined) settings = writeSetting(settings, field.key, field.default);
      }
    }
    setError(null);
    setEditor({ connection, displayName: connection?.display_name ?? '', settings, credentials: {} });
  };

  const willDisableForCredentialRemoval = !!editor?.connection?.enabled && fields.some((field) => (
    field.type === 'secret' && field.required && editor.credentials[field.key] === null
    && !!editor.connection?.credential_refs[field.key]
  ));

  const saveEditor = async () => {
    if (!editor || !editor.displayName.trim()) return;
    const input = { display_name: editor.displayName.trim(), settings: editor.settings, credentials: editor.credentials };
    if (editor.connection) {
      await mutate(() => pluginsApi.updateConnection(pluginId, editor.connection!.connection_id, {
        ...input, expected_revision: editor.connection!.revision,
        ...(willDisableForCredentialRemoval ? { enabled: false } : {}),
      }), () => setEditor(null));
    } else {
      const credentials = Object.fromEntries(Object.entries(editor.credentials).filter((entry): entry is [string, string] => entry[1] !== null));
      await mutate(() => pluginsApi.createConnection(pluginId, { ...input, credentials, enabled: false }), () => setEditor(null));
    }
  };

  const normalFields = fields.filter((field) => field.type !== 'secret');
  const secretFields = fields.filter((field) => field.type === 'secret');
  const latestEditor = editor?.connection ? connections.find((item) => item.connection_id === editor.connection!.connection_id) : null;
  const editorConflicted = !!editor?.connection && !!latestEditor && latestEditor.revision !== editor.connection.revision;
  const selectedConnection = connections.find((connection) => connection.connection_id === (selectedConnectionId === undefined ? localSelection : selectedConnectionId));

  return (
    <section aria-labelledby={titleId} className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 id={titleId} className="text-sm font-semibold">{t('plugins.connections.title')}</h3>
          <p className="mt-1 text-sm text-muted-foreground">{t('plugins.connections.description')}</p>
        </div>
        <Button variant="outline" disabled={busy || loading} onClick={() => startEditor(null)}>{t('plugins.connections.add')}</Button>
      </div>
      {error && !editor && !confirmation ? <p role="alert" className="text-sm text-destructive">{t(`plugins.connections.${error}`)}</p> : null}
      {loading ? <p role="status" className="text-sm text-muted-foreground">{t('plugins.connections.loading')}</p> : null}
      {!loading && !connections.length ? <p className="py-4 text-sm text-muted-foreground">{t('plugins.connections.empty')}</p> : null}
      <ul className="divide-y divide-border">
        {connections.map((connection) => (
          <li key={connection.connection_id} className="flex flex-wrap items-center justify-between gap-3 py-4">
            {renderConnection || onSelectConnection ? <input type="radio" name={titleId} checked={selectedConnection?.connection_id === connection.connection_id}
              aria-label={t('plugins.connections.selectConnection', { name: connection.display_name })}
              onChange={() => { setLocalSelection(connection.connection_id); onSelectConnection?.(connection.connection_id); }} /> : null}
            <div className="min-w-0 flex-1 basis-40">
              <p className="break-words text-sm font-medium">{connection.display_name}</p>
              <div className="mt-1 flex flex-wrap gap-2 text-xs text-muted-foreground">
                {connection.readiness.map((readiness) => (
                  <span key={readiness.capability_id}>{t(`plugins.connections.status.${readiness.status}`)}</span>
                ))}
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button size="sm" variant="outline" disabled={busy} onClick={() => startEditor(connection)}>{t('plugins.connections.edit')}</Button>
              <Button size="sm" variant="outline" disabled={busy || (!connection.enabled && !canEnable)} onClick={() => void mutate(() => pluginsApi.updateConnection(pluginId, connection.connection_id, {
                expected_revision: connection.revision, enabled: !connection.enabled,
              }))}>{t(connection.enabled ? 'plugins.connections.disable' : 'plugins.connections.enable')}</Button>
              <Button size="sm" variant="ghost" disabled={busy} onClick={() => { setError(null); setConfirmation({ connection, action: 'clear' }); }}>{t('plugins.connections.clear')}</Button>
              <Button size="sm" variant="ghost" disabled={busy} onClick={() => { setError(null); setConfirmation({ connection, action: 'disconnect' }); }}>{t('plugins.connections.disconnect')}</Button>
            </div>
          </li>
        ))}
      </ul>
      {selectedConnection && renderConnection ? renderConnection(selectedConnection) : null}
      {!canEnable ? <p className="text-xs text-muted-foreground">{t('plugins.connections.authorizationRequired')}</p> : null}
      <Button size="sm" variant="ghost" disabled={busy || loading} onClick={() => { setError(null); void refresh(); }}>{t('plugins.connections.refresh')}</Button>

      <Dialog open={editor !== null} onOpenChange={(open) => { if (!open && !busy) setEditor(null); }}>
        <DialogContent closeLabel={t('plugins.connections.cancel')} hideClose={busy} className="max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{t(editor?.connection ? 'plugins.connections.edit' : 'plugins.connections.add')}</DialogTitle>
            <DialogDescription>{t('plugins.connections.description')}</DialogDescription>
          </DialogHeader>
          {editor ? <form onSubmit={(event) => { event.preventDefault(); void saveEditor(); }}>
            <div className="space-y-5 px-6 pb-6">
              {error ? <p role="alert" className="text-sm text-destructive">{t(`plugins.connections.${error}`)}</p> : null}
              {editorConflicted ? <Button type="button" variant="outline" onClick={() => startEditor(latestEditor!)}>{t('plugins.connections.reloadEditor')}</Button> : null}
              <div className="space-y-2">
                <label htmlFor={nameId} className="text-sm font-medium">{t('plugins.connections.name')}</label>
                <Input id={nameId} value={editor.displayName} maxLength={256} required disabled={busy} onChange={(event) => setEditor({ ...editor, displayName: event.target.value })} />
              </div>
              <PluginSettingsFields fields={normalFields} values={Object.fromEntries(normalFields.map((field) => [field.key, fieldValue(editor.settings, field.key)]))} disabled={busy}
                onChange={(key, value) => setEditor({ ...editor, settings: writeSetting(editor.settings, key, value) })} />
              {secretFields.length ? <p className="text-xs text-muted-foreground">{t('plugins.connections.credentialsHelp')}</p> : null}
              {secretFields.map((field) => <div key={field.key} className="space-y-2">
                <label className="block space-y-2 text-sm font-medium">
                  <span>{field.label_translated || field.label}</span>
                  <Input type="password" autoComplete="new-password" disabled={busy} value={editor.credentials[field.key] ?? ''}
                    onChange={(event) => {
                      const credentials = { ...editor.credentials };
                      if (event.target.value) credentials[field.key] = event.target.value;
                      else delete credentials[field.key];
                      setEditor({ ...editor, credentials });
                    }} />
                </label>
                {editor.connection?.credential_refs[field.key] ? <p className="text-xs text-muted-foreground">{t(editor.credentials[field.key] === null ? 'plugins.connections.credentialRemovalPending' : 'plugins.connections.credentialSaved')}</p> : null}
                {editor.connection?.credential_refs[field.key] ? <Button type="button" size="sm" variant="ghost" disabled={busy} onClick={() => setEditor({ ...editor, credentials: { ...editor.credentials, [field.key]: null } })}>{t('plugins.connections.removeCredential')}</Button> : null}
              </div>)}
              {willDisableForCredentialRemoval ? <p role="status" className="text-sm text-muted-foreground">{t('plugins.connections.removalDisables')}</p> : null}
              {editor.connection ? <>
                <PluginSettingsCustomBlocks connectionId={editor.connection.connection_id} blocks={blocks}
                  values={Object.fromEntries(fields.map((field) => [field.key, fieldValue(editor.settings, field.key)]))}
                  onChange={(key, value) => setEditor({ ...editor, settings: writeSetting(editor.settings, key, value) })} />
                <PluginSettingsActions key={editor.connection.connection_id} pluginId={pluginId} connectionId={editor.connection.connection_id}
                  actions={actions} values={Object.fromEntries(fields.map((field) => [field.key, fieldValue(editor.settings, field.key)]))}
                  disabled={busy || editorConflicted} connectionEnabled={editor.connection.enabled} onActionSettled={refresh} />
              </> : null}
            </div>
            <DialogFooter>
              <Button type="button" variant="ghost" disabled={busy} onClick={() => setEditor(null)}>{t('plugins.connections.cancel')}</Button>
              <Button type="submit" disabled={busy || !editor.displayName.trim() || editorConflicted}>{t(busy ? 'plugins.connections.saving' : 'plugins.connections.save')}</Button>
            </DialogFooter>
          </form> : null}
        </DialogContent>
      </Dialog>

      <Dialog open={confirmation !== null} onOpenChange={(open) => { if (!open && !busy) setConfirmation(null); }}>
        <DialogContent closeLabel={t('plugins.connections.cancel')} hideClose={busy}>
          <DialogHeader>
            <DialogTitle>{confirmation?.connection.display_name}</DialogTitle>
            <DialogDescription>{t(confirmation?.action === 'clear' ? 'plugins.connections.clearScope' : 'plugins.connections.disconnectScope')}</DialogDescription>
          </DialogHeader>
          {error ? <p role="alert" className="px-6 pb-4 text-sm text-destructive">{t(`plugins.connections.${error}`)}</p> : null}
          <DialogFooter>
            <Button variant="ghost" disabled={busy} onClick={() => setConfirmation(null)}>{t('plugins.connections.cancel')}</Button>
            <Button variant="destructive" disabled={busy} onClick={() => {
              if (!confirmation) return;
              const { connection, action } = confirmation;
              void mutate(() => action === 'clear'
                ? pluginsApi.clearConnectionContent(pluginId, connection.connection_id, connection.revision)
                : pluginsApi.disconnectConnection(pluginId, connection.connection_id, connection.revision), () => setConfirmation(null));
            }}>{t(confirmation?.action === 'clear' ? 'plugins.connections.clear' : 'plugins.connections.disconnect')}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
};
