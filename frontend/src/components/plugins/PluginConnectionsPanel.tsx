import { useCenterRefresh } from '@/hooks/useCenterRefresh';
import { connectionInput } from '@/utils/plugin-connection-settings';
import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { pluginsApi, type ExtensionFieldSpec, type PluginConnection, type PluginSettingsActionSpec, type PluginSettingsUiBlockSpec } from '@/api/modules/plugins';
import { connectionSettingsSeed } from '@/hooks/useConnectionSettings';
import { useConnectionSettingsContext } from '@/components/settings/ConnectionSettingsContext';
import { PluginSettingsFields } from '@/components/settings/PluginSettingsFields';
import { PluginSettingsActions } from '@/components/settings/PluginSettingsActions';
import { PluginSettingsCustomBlocks } from '@/components/settings/PluginSettingsCustomBlocks';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { validateConnectionField } from './connection-validation';

interface PluginConnectionsPanelProps {
  pluginId: string;
  pluginName?: string;
  fields: ExtensionFieldSpec[];
  canEnable?: boolean;
  actions?: PluginSettingsActionSpec[];
  blocks?: PluginSettingsUiBlockSpec[];
  onConnect?: () => void;
  selectedConnectionId?: string | null;
  onSelectConnection?: (connectionId: string) => void;
  renderConnection?: (connection: PluginConnection) => ReactNode;
  onChanged?: () => void;
}
const NO_ACTIONS: PluginSettingsActionSpec[] = [];
const NO_BLOCKS: PluginSettingsUiBlockSpec[] = [];

/** Creation is an explicit setup action. Existing settings belong to the Settings draft. */
export const PluginConnectionsPanel = ({ pluginId, pluginName, fields, canEnable = false, actions = NO_ACTIONS, blocks = NO_BLOCKS,
  onConnect, selectedConnectionId, onSelectConnection, renderConnection, onChanged }: PluginConnectionsPanelProps) => {
  const { t } = useTranslation('app');
  const settings = useConnectionSettingsContext();
  const titleId = useId();
  const nameId = useId();
  const [connections, setConnections] = useState<PluginConnection[]>([]);
  const [localSelection, setLocalSelection] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const [error, setError] = useState<string | null>(null);
  const [creation, setCreation] = useState<{ name: string; values: Record<string, unknown> } | null>(null);
  const [confirmation, setConfirmation] = useState<{ connection: PluginConnection; action: 'clear' | 'disconnect' } | null>(null);
  const requestGeneration = useRef(0);
  const mutationGeneration = useRef(0);
  const currentPlugin = useRef(pluginId);
  currentPlugin.current = pluginId;

  const refresh = useCallback(async (silent = false) => {
    const generation = ++requestGeneration.current;
    if (!silent) setLoading(true);
    try {
      const result = await pluginsApi.listConnections(pluginId);
      if (generation === requestGeneration.current) { setConnections(result); setError(null); }
    } catch {
      if (generation === requestGeneration.current) setError('loadFailed');
    } finally {
      if (generation === requestGeneration.current) setLoading(false);
    }
  }, [pluginId]);
  useEffect(() => {
    mutationGeneration.current += 1; busyRef.current = false; setBusy(false);
    setConnections([]); setLocalSelection(null); setCreation(null); setConfirmation(null); setError(null);
    void refresh();
    return () => { requestGeneration.current += 1; mutationGeneration.current += 1; };
  }, [refresh]);
  useCenterRefresh(() => refresh(true), ['plugins']);
  const wasSaving = useRef(false);
  useEffect(() => {
    if (wasSaving.current && !settings.saving) void refresh(true);
    wasSaving.current = settings.saving;
  }, [settings.saving, refresh]);

  const mutate = async (operation: () => Promise<unknown>, onSuccess?: () => void) => {
    if (busyRef.current) return;
    busyRef.current = true; setBusy(true); setError(null);
    const owner = pluginId;
    const generation = mutationGeneration.current;
    try {
      await operation();
      if (currentPlugin.current !== owner || mutationGeneration.current !== generation) return;
      onSuccess?.(); await refresh(); onChanged?.();
    } catch (failure) {
      if (currentPlugin.current !== owner || mutationGeneration.current !== generation) return;
      const status = typeof failure === 'object' && failure !== null && 'status' in failure ? failure.status : undefined;
      setError(status === 409 ? 'conflict' : status === 403 ? 'authorizationRequired' : 'saveFailed');
    } finally {
      if (currentPlugin.current === owner && mutationGeneration.current === generation) { busyRef.current = false; setBusy(false); }
    }
  };
  const openSetup = () => {
    if (onConnect) { onConnect(); return; }
    setCreation({ name: pluginName || pluginId,
      values: Object.fromEntries(fields.filter(field => field.default != null).map(field => [field.key, field.default])) });
  };
  const creationIssue = creation ? fields.map(field => {
    const issue = validateConnectionField(field, creation.values[field.key], creation.values, false);
    return issue ? { field, issue } : null;
  }).find(Boolean) : null;
  const create = async () => {
    if (!creation?.name.trim() || creationIssue) return;
    const generation = mutationGeneration.current;
    await mutate(async () => {
      const connection = await pluginsApi.createConnection(pluginId, {
        display_name: creation.name.trim(), enabled: false, ...connectionInput(fields, creation.values),
      });
      if (currentPlugin.current === pluginId && mutationGeneration.current === generation) { setLocalSelection(connection.connection_id); onSelectConnection?.(connection.connection_id); }
    }, () => setCreation(null));
  };
  const selected = connections.find(connection => connection.connection_id === (selectedConnectionId === undefined ? localSelection : selectedConnectionId)) ?? (connections.length === 1 ? connections[0] : undefined);
  const seed = selected ? connectionSettingsSeed(selected, fields) : null;
  const draft = seed ? settings.read(seed) : null;
  const visibleFields = fields.filter(field => field.section !== 'advanced' && field.section !== 'activation');
  const secretFields = visibleFields.filter(field => field.type === 'secret');
  const blocked = busy || settings.saving;

  return <section aria-labelledby={titleId} className="space-y-5">
    {loading ? <p role="status" className="text-sm text-muted-foreground">{t('plugins.connections.loading')}</p> : null}
    {error ? <div role="alert" className="space-y-2 text-sm text-destructive">
      <p>{t(`plugins.connections.${error}`)}</p>
      <Button variant="outline" size="sm" disabled={blocked || loading} onClick={() => void refresh()}>{t('plugins.connections.retry')}</Button>
    </div> : null}
    {!loading && !connections.length && !error ? <div className="space-y-3 py-2">
      <h3 id={titleId} className="text-base font-medium">{t('plugins.connections.setupTitle')}</h3>
      <p className="max-w-xl text-sm text-muted-foreground">{t('plugins.connections.setupDescription')}</p>
      <Button disabled={blocked || !canEnable} onClick={openSetup}>{t('plugins.connections.connect')}</Button>
    </div> : null}
    {!canEnable ? <p className="text-xs text-muted-foreground">{t('plugins.connections.authorizationRequired')}</p> : null}
    {connections.length > 1 ? <label className="flex items-center gap-3 text-sm">
      <span id={titleId}>{t('plugins.connections.choose')}</span>
      <select className="rounded-md border border-input bg-background px-3 py-2" value={selected?.connection_id ?? ''}
        onChange={event => { setLocalSelection(event.target.value); onSelectConnection?.(event.target.value); }}>
        <option value="" disabled>{t('plugins.connections.choose')}</option>
        {connections.map(connection => <option key={connection.connection_id} value={connection.connection_id}>{settings.read(connectionSettingsSeed(connection, fields)).name}</option>)}
      </select>
    </label> : null}
    {selected && seed && draft ? <>
      <div className="flex flex-wrap items-center justify-between gap-4">
        <p id={connections.length === 1 ? titleId : undefined} className="text-sm font-medium">{draft.name}</p>
        <label className="flex items-center gap-3 text-sm">{t('plugins.connections.usePlugin')}
          <Switch checked={draft.enabled} disabled={blocked || (!draft.enabled && !canEnable)} onCheckedChange={enabled => settings.patch(seed, {}, { enabled })} />
        </label>
      </div>
      {selected.readiness.length ? <p className="text-xs text-muted-foreground" role="status">
        {[...new Set(selected.readiness.map(item => item.status))].map(status => t(`plugins.connections.status.${status}`)).join(' · ')}
      </p> : null}
      {draft.error ? <div role="alert" className="space-y-2 text-sm text-destructive">
        <p>{t(`plugins.connections.${draft.error}`)}</p>
        <Button size="sm" variant="outline" disabled={blocked} onClick={() => { settings.discard(seed); void refresh(); }}>{t('plugins.connections.reloadEditor')}</Button>
      </div> : null}
      <PluginSettingsCustomBlocks connectionId={selected.connection_id} blocks={blocks} values={draft.values}
        onChange={(key, value) => settings.patch(seed, { [key]: value })} />
      <PluginSettingsFields fields={visibleFields} values={draft.values} disabled={blocked}
        getValidationIssue={field => validateConnectionField(field, draft.values[field.key], draft.values, draft.enabled)}
        onChange={(key, value) => settings.patch(seed, { [key]: value })}
        renderField={field => {
          if (field.type !== 'secret') return undefined;
          const value = draft.values[field.key];
          const validationValue = value === null ? undefined : value || selected.credential_refs[field.key];
          const issue = validateConnectionField(field, validationValue, draft.values, draft.enabled);
          return <div className="space-y-2">
            <label className="block space-y-2 text-sm font-medium">
              <span>{field.label_translated || field.label}</span>
              <Input type="password" autoComplete="new-password" aria-invalid={!!issue} disabled={blocked}
                value={typeof value === 'string' ? value : ''} onChange={event => settings.patch(seed, { [field.key]: event.target.value })} />
            </label>
            {issue ? <p role="alert" className="text-xs text-destructive">{t(`settings.dynamicValidation.${issue}`)}</p> : null}
            {selected.credential_refs[field.key] ? <>
              <p className="text-xs text-muted-foreground">{t(value === null ? 'plugins.connections.credentialRemovalPending' : 'plugins.connections.credentialSaved')}</p>
              <Button type="button" size="sm" variant="ghost" disabled={blocked}
                onClick={() => settings.patch(seed, { [field.key]: null }, field.required ? { enabled: false } : {})}>{t('plugins.connections.removeCredential')}</Button>
            </> : null}
          </div>;
        }} />
      {secretFields.length ? <p className="text-xs text-muted-foreground">{t('plugins.connections.credentialsHelp')}</p> : null}
      {secretFields.some(field => field.required && draft.values[field.key] === null) ? <p className="text-xs text-muted-foreground">{t('plugins.connections.removalDisables')}</p> : null}
      {draft.dirty ? <p className="text-xs text-muted-foreground">{t('plugins.connections.saveBeforeAction')}</p> : null}
      <PluginSettingsActions key={selected.connection_id} pluginId={pluginId} connectionId={selected.connection_id} actions={actions}
        values={draft.values} disabled={blocked || draft.dirty} connectionEnabled={selected.enabled}
        onSettingsUpdates={(_id, updates) => settings.patch(seed, updates)} onActionSettled={() => refresh(true)} />
      {renderConnection?.(selected)}
      <details className="border-t border-border pt-4">
        <summary className="cursor-pointer text-sm text-muted-foreground">{t('plugins.connections.manage')}</summary>
        <div className="space-y-4 pt-4">
          <label className="block max-w-md space-y-2 text-sm"><span>{t('plugins.connections.name')}</span>
            <Input value={draft.name} maxLength={256} disabled={blocked} onChange={event => settings.patch(seed, {}, { name: event.target.value })} />
          </label>
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" disabled={blocked || !canEnable} onClick={openSetup}>{t('plugins.connections.add')}</Button>
            <Button variant="ghost" disabled={blocked || draft.dirty} onClick={() => setConfirmation({ connection: selected, action: 'clear' })}>{t('plugins.connections.clear')}</Button>
            <Button variant="ghost" disabled={blocked || draft.dirty} onClick={() => setConfirmation({ connection: selected, action: 'disconnect' })}>{t('plugins.connections.disconnect')}</Button>
          </div>
        </div>
      </details>
    </> : null}
    <Dialog open={creation !== null} onOpenChange={open => { if (!open && !busy) setCreation(null); }}>
      <DialogContent closeLabel={t('plugins.connections.cancel')} hideClose={busy} className="max-h-[85vh] overflow-y-auto">
        <DialogHeader><DialogTitle>{t('plugins.connections.connect')}</DialogTitle><DialogDescription>{t('plugins.connections.createDescription')}</DialogDescription></DialogHeader>
        {creation ? <form onSubmit={event => { event.preventDefault(); void create(); }}>
          <div className="space-y-5 px-6 pb-6">
            {error ? <p role="alert" className="text-sm text-destructive">{t(`plugins.connections.${error}`)}</p> : null}
            <label htmlFor={nameId} className="block space-y-2 text-sm"><span>{t('plugins.connections.name')}</span>
              <Input id={nameId} value={creation.name} maxLength={256} disabled={busy} onChange={event => setCreation({ ...creation, name: event.target.value })} />
            </label>
            <PluginSettingsFields fields={visibleFields} values={creation.values} disabled={busy}
              getValidationIssue={field => validateConnectionField(field, creation.values[field.key], creation.values, false)}
              onChange={(key, value) => setCreation({ ...creation, values: { ...creation.values, [key]: value } })} />
          </div>
          <DialogFooter>
            <Button type="button" variant="ghost" disabled={busy} onClick={() => setCreation(null)}>{t('plugins.connections.cancel')}</Button>
            <Button type="submit" disabled={busy || !creation.name.trim() || !!creationIssue}>{t(busy ? 'plugins.connections.saving' : 'plugins.connections.continue')}</Button>
          </DialogFooter>
        </form> : null}
      </DialogContent>
    </Dialog>
    <Dialog open={confirmation !== null} onOpenChange={open => { if (!open && !busy) setConfirmation(null); }}>
      <DialogContent closeLabel={t('plugins.connections.cancel')} hideClose={busy}>
        <DialogHeader><DialogTitle>{confirmation?.connection.display_name}</DialogTitle>
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
              : pluginsApi.disconnectConnection(pluginId, connection.connection_id, connection.revision), () => { settings.discard(connectionSettingsSeed(connection, fields)); setConfirmation(null); });
          }}>{t(confirmation?.action === 'clear' ? 'plugins.connections.clear' : 'plugins.connections.disconnect')}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </section>;
};
