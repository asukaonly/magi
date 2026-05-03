import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Plus, Play, Square, Trash2, RefreshCw, Pencil, Loader2 } from 'lucide-react';

import { mcpApi } from '@/api/modules/mcp';
import type {
  MCPServerCreatePayload,
  MCPServerStatus,
  MCPTransport,
  MCPTransportKind,
} from '@/api/modules/mcp';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';

type DraftState = {
  id: string;
  name: string;
  description: string;
  enabled: boolean;
  autostart: boolean;
  transportKind: MCPTransportKind;
  command: string;
  argsText: string;
  envText: string;
  url: string;
  headersText: string;
};

const EMPTY_DRAFT: DraftState = {
  id: '',
  name: '',
  description: '',
  enabled: true,
  autostart: false,
  transportKind: 'stdio',
  command: '',
  argsText: '',
  envText: '',
  url: '',
  headersText: '',
};

const STATE_BADGE: Record<MCPServerStatus['state'], string> = {
  connected: 'bg-emerald-500/15 text-emerald-700 border-emerald-500/30',
  connecting: 'bg-amber-500/15 text-amber-700 border-amber-500/30',
  disconnected: 'bg-muted text-muted-foreground border-muted-foreground/20',
  disabled: 'bg-muted text-muted-foreground border-muted-foreground/20',
  error: 'bg-destructive/15 text-destructive border-destructive/30',
};

const draftFromServer = (server: MCPServerStatus): DraftState => {
  if (server.transport.kind === 'stdio') {
    const env = Object.entries(server.transport.env ?? {})
      .map(([k, v]) => `${k}=${v}`)
      .join('\n');
    return {
      id: server.id,
      name: server.name,
      description: server.description ?? '',
      enabled: server.enabled,
      autostart: server.autostart,
      transportKind: 'stdio',
      command: server.transport.command,
      argsText: (server.transport.args ?? []).join(' '),
      envText: env,
      url: '',
      headersText: '',
    };
  }
  const headers = Object.entries(server.transport.headers ?? {})
    .map(([k, v]) => `${k}=${v}`)
    .join('\n');
  return {
    ...EMPTY_DRAFT,
    id: server.id,
    name: server.name,
    description: server.description ?? '',
    enabled: server.enabled,
    autostart: server.autostart,
    transportKind: 'http',
    url: server.transport.url,
    headersText: headers,
  };
};

const parseKVText = (text: string): Record<string, string> => {
  const out: Record<string, string> = {};
  for (const line of text.split('\n')) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;
    const idx = trimmed.indexOf('=');
    if (idx === -1) continue;
    const key = trimmed.slice(0, idx).trim();
    const value = trimmed.slice(idx + 1).trim();
    if (key) out[key] = value;
  }
  return out;
};

const buildPayload = (draft: DraftState): MCPServerCreatePayload => {
  let transport: MCPTransport;
  if (draft.transportKind === 'stdio') {
    const args = draft.argsText
      .trim()
      .split(/\s+/)
      .filter(Boolean);
    transport = {
      kind: 'stdio',
      command: draft.command.trim(),
      args,
      cwd: '',
      env: parseKVText(draft.envText),
    };
  } else {
    transport = {
      kind: 'http',
      url: draft.url.trim(),
      headers: parseKVText(draft.headersText),
    };
  }
  return {
    server: {
      id: draft.id.trim(),
      name: draft.name.trim() || draft.id.trim(),
      description: draft.description,
      enabled: draft.enabled,
      autostart: draft.autostart,
    },
    transport,
  };
};

interface ServerEditorDialogProps {
  open: boolean;
  initialDraft: DraftState | null;
  isEdit: boolean;
  onClose: () => void;
  onSave: (payload: MCPServerCreatePayload, isEdit: boolean) => Promise<void>;
}

const ServerEditorDialog: React.FC<ServerEditorDialogProps> = ({
  open,
  initialDraft,
  isEdit,
  onClose,
  onSave,
}) => {
  const { t } = useTranslation('app');
  const [draft, setDraft] = useState<DraftState>(EMPTY_DRAFT);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setDraft(initialDraft ?? EMPTY_DRAFT);
      setError(null);
    }
  }, [open, initialDraft]);

  const handleSave = useCallback(async () => {
    setSaving(true);
    setError(null);
    try {
      await onSave(buildPayload(draft), isEdit);
      onClose();
    } catch (exc: any) {
      setError(exc?.message ?? String(exc));
    } finally {
      setSaving(false);
    }
  }, [draft, isEdit, onClose, onSave]);

  return (
    <Dialog open={open} onOpenChange={(next) => (next ? null : onClose())}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>
            {t(isEdit ? 'settings.mcp.editor.editTitle' : 'settings.mcp.editor.createTitle')}
          </DialogTitle>
          <DialogDescription>
            {t('settings.mcp.editor.description')}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <label className="text-sm">
              <span className="mb-1 block text-muted-foreground">
                {t('settings.mcp.editor.id')}
              </span>
              <Input
                value={draft.id}
                onChange={(e) => setDraft({ ...draft, id: e.target.value })}
                disabled={isEdit}
                placeholder="github"
              />
            </label>
            <label className="text-sm">
              <span className="mb-1 block text-muted-foreground">
                {t('settings.mcp.editor.name')}
              </span>
              <Input
                value={draft.name}
                onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                placeholder="GitHub"
              />
            </label>
          </div>

          <label className="block text-sm">
            <span className="mb-1 block text-muted-foreground">
              {t('settings.mcp.editor.descriptionLabel')}
            </span>
            <Input
              value={draft.description}
              onChange={(e) => setDraft({ ...draft, description: e.target.value })}
            />
          </label>

          <div className="flex items-center gap-6 text-sm">
            <label className="flex items-center gap-2">
              <Switch
                checked={draft.enabled}
                onCheckedChange={(v) => setDraft({ ...draft, enabled: v })}
              />
              {t('settings.mcp.editor.enabled')}
            </label>
            <label className="flex items-center gap-2">
              <Switch
                checked={draft.autostart}
                onCheckedChange={(v) => setDraft({ ...draft, autostart: v })}
              />
              {t('settings.mcp.editor.autostart')}
            </label>
          </div>

          <div className="rounded-md border bg-muted/30 p-3 text-sm">
            <div className="mb-2 flex items-center gap-3">
              <span className="text-muted-foreground">
                {t('settings.mcp.editor.transport')}
              </span>
              <Button
                type="button"
                size="sm"
                variant={draft.transportKind === 'stdio' ? 'default' : 'outline'}
                onClick={() => setDraft({ ...draft, transportKind: 'stdio' })}
              >
                stdio
              </Button>
              <Button
                type="button"
                size="sm"
                variant={draft.transportKind === 'http' ? 'default' : 'outline'}
                onClick={() => setDraft({ ...draft, transportKind: 'http' })}
              >
                http
              </Button>
            </div>

            {draft.transportKind === 'stdio' ? (
              <div className="space-y-3">
                <label className="block">
                  <span className="mb-1 block text-muted-foreground">
                    {t('settings.mcp.editor.command')}
                  </span>
                  <Input
                    value={draft.command}
                    onChange={(e) => setDraft({ ...draft, command: e.target.value })}
                    placeholder="npx"
                  />
                </label>
                <label className="block">
                  <span className="mb-1 block text-muted-foreground">
                    {t('settings.mcp.editor.args')}
                  </span>
                  <Input
                    value={draft.argsText}
                    onChange={(e) => setDraft({ ...draft, argsText: e.target.value })}
                    placeholder="-y @modelcontextprotocol/server-everything"
                  />
                </label>
                <label className="block">
                  <span className="mb-1 block text-muted-foreground">
                    {t('settings.mcp.editor.env')}
                  </span>
                  <Textarea
                    value={draft.envText}
                    onChange={(e) => setDraft({ ...draft, envText: e.target.value })}
                    rows={3}
                    placeholder="GITHUB_TOKEN=${env:GITHUB_TOKEN}"
                  />
                </label>
              </div>
            ) : (
              <div className="space-y-3">
                <label className="block">
                  <span className="mb-1 block text-muted-foreground">
                    {t('settings.mcp.editor.url')}
                  </span>
                  <Input
                    value={draft.url}
                    onChange={(e) => setDraft({ ...draft, url: e.target.value })}
                    placeholder="https://example.com/mcp"
                  />
                </label>
                <label className="block">
                  <span className="mb-1 block text-muted-foreground">
                    {t('settings.mcp.editor.headers')}
                  </span>
                  <Textarea
                    value={draft.headersText}
                    onChange={(e) => setDraft({ ...draft, headersText: e.target.value })}
                    rows={3}
                    placeholder="Authorization=Bearer ..."
                  />
                </label>
              </div>
            )}
          </div>

          {error ? <p className="text-sm text-destructive">{error}</p> : null}
        </div>

        <DialogFooter>
          <DialogClose asChild>
            <Button type="button" variant="outline" disabled={saving}>
              {t('settings.mcp.editor.cancel')}
            </Button>
          </DialogClose>
          <Button type="button" onClick={() => void handleSave()} disabled={saving || !draft.id.trim()}>
            {saving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
            {t('settings.mcp.editor.save')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

export const MCPServersSection: React.FC = () => {
  const { t } = useTranslation('app');
  const [servers, setServers] = useState<MCPServerStatus[]>([]);
  const [loading, setLoading] = useState(false);
  const [refreshError, setRefreshError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [editingDraft, setEditingDraft] = useState<DraftState | null>(null);
  const [editingIsEdit, setEditingIsEdit] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    setRefreshError(null);
    try {
      const list = await mcpApi.listServers();
      setServers(list);
    } catch (exc: any) {
      setRefreshError(exc?.message ?? String(exc));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleSave = useCallback(
    async (payload: MCPServerCreatePayload, isEdit: boolean) => {
      if (isEdit) {
        await mcpApi.updateServer(payload.server.id, payload);
      } else {
        await mcpApi.createServer(payload);
      }
      await refresh();
    },
    [refresh],
  );

  const onCreate = () => {
    setEditingDraft(EMPTY_DRAFT);
    setEditingIsEdit(false);
    setEditorOpen(true);
  };

  const onEdit = (server: MCPServerStatus) => {
    setEditingDraft(draftFromServer(server));
    setEditingIsEdit(true);
    setEditorOpen(true);
  };

  const onStart = async (server: MCPServerStatus) => {
    setBusyId(server.id);
    try {
      await mcpApi.startServer(server.id);
      await refresh();
    } finally {
      setBusyId(null);
    }
  };

  const onStop = async (server: MCPServerStatus) => {
    setBusyId(server.id);
    try {
      await mcpApi.stopServer(server.id);
      await refresh();
    } finally {
      setBusyId(null);
    }
  };

  const onDelete = async (server: MCPServerStatus) => {
    if (!confirm(t('settings.mcp.confirmDelete', { id: server.id }))) return;
    setBusyId(server.id);
    try {
      await mcpApi.deleteServer(server.id);
      await refresh();
    } finally {
      setBusyId(null);
    }
  };

  const totalTools = useMemo(
    () => servers.reduce((acc, s) => acc + s.tool_count, 0),
    [servers],
  );

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Badge variant="secondary" className="rounded-md px-3 py-1">
            {t('settings.mcp.summary', {
              servers: servers.length,
              tools: totalTools,
            })}
          </Badge>
          <Button type="button" variant="outline" size="sm" onClick={() => void refresh()} disabled={loading}>
            <RefreshCw className="mr-2 h-4 w-4" />
            {t('settings.mcp.refresh')}
          </Button>
        </div>
        <Button type="button" size="sm" onClick={onCreate}>
          <Plus className="mr-2 h-4 w-4" />
          {t('settings.mcp.actions.add')}
        </Button>
      </div>

      {refreshError ? (
        <div className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
          {refreshError}
        </div>
      ) : null}

      {loading && servers.length === 0 ? (
        <div className="rounded-md border border-dashed py-8 text-center text-sm text-muted-foreground">
          {t('settings.mcp.loading')}
        </div>
      ) : servers.length === 0 ? (
        <div className="rounded-md border border-dashed py-10 text-center text-sm text-muted-foreground">
          {t('settings.mcp.empty')}
        </div>
      ) : (
        <ul className="divide-y rounded-md border">
          {servers.map((server) => {
            const isRunning = server.state === 'connected' || server.state === 'connecting';
            const busy = busyId === server.id;
            return (
              <li key={server.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
                <div className="flex flex-1 flex-col gap-1">
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{server.name || server.id}</span>
                    <Badge variant="outline" className={STATE_BADGE[server.state]}>
                      {t(`settings.mcp.state.${server.state}`)}
                    </Badge>
                    <span className="text-xs text-muted-foreground">
                      {server.transport.kind} · {server.id}
                    </span>
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {t('settings.mcp.toolsAndResources', {
                      tools: server.tool_count,
                      resources: server.resource_count,
                    })}
                    {server.last_error ? (
                      <span className="ml-2 text-destructive">{server.last_error}</span>
                    ) : null}
                  </div>
                </div>
                <div className="flex items-center gap-1.5">
                  {isRunning ? (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => void onStop(server)}
                      disabled={busy}
                    >
                      <Square className="mr-1.5 h-3.5 w-3.5" />
                      {t('settings.mcp.actions.stop')}
                    </Button>
                  ) : (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => void onStart(server)}
                      disabled={busy || !server.enabled}
                    >
                      <Play className="mr-1.5 h-3.5 w-3.5" />
                      {t('settings.mcp.actions.start')}
                    </Button>
                  )}
                  <Button size="sm" variant="ghost" onClick={() => onEdit(server)} disabled={busy}>
                    <Pencil className="mr-1.5 h-3.5 w-3.5" />
                    {t('settings.mcp.actions.edit')}
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => void onDelete(server)}
                    disabled={busy}
                    className="text-destructive hover:bg-destructive/10 hover:text-destructive"
                  >
                    <Trash2 className="mr-1.5 h-3.5 w-3.5" />
                    {t('settings.mcp.actions.delete')}
                  </Button>
                </div>
              </li>
            );
          })}
        </ul>
      )}

      <ServerEditorDialog
        open={editorOpen}
        initialDraft={editingDraft}
        isEdit={editingIsEdit}
        onClose={() => setEditorOpen(false)}
        onSave={handleSave}
      />
    </div>
  );
};

export default MCPServersSection;
