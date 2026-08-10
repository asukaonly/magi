import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Plus,
  Play,
  Square,
  Trash2,
  RefreshCw,
  Pencil,
  Loader2,
  MoreHorizontal,
  FileText,
  Upload,
  ScrollText,
} from 'lucide-react';

import { mcpApi } from '@/api/modules/mcp';
import type {
  MCPServerCreatePayload,
  MCPAvailableTool,
  MCPServerLogs,
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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
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
  callTimeoutMs: number;
  initTimeoutMs: number;
  maxRestartAttempts: number;
  toolInclude: string[] | null;
  availableTools: MCPAvailableTool[];
  toolOverridesJson: string;
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
  callTimeoutMs: 60000,
  initTimeoutMs: 15000,
  maxRestartAttempts: 5,
  toolInclude: null,
  availableTools: [],
  toolOverridesJson: '{}',
};

const STATE_BADGE: Record<MCPServerStatus['state'], string> = {
  connected: 'bg-emerald-500/15 text-emerald-700 border-emerald-500/30',
  connecting: 'bg-amber-500/15 text-amber-700 border-amber-500/30',
  disconnected: 'bg-muted text-muted-foreground border-muted-foreground/20',
  disabled: 'bg-muted text-muted-foreground border-muted-foreground/20',
  error: 'bg-destructive/15 text-destructive border-destructive/30',
};

const draftFromServer = (server: MCPServerStatus): DraftState => {
  const base: DraftState = {
    ...EMPTY_DRAFT,
    id: server.id,
    name: server.name,
    description: server.description ?? '',
    enabled: server.enabled,
    autostart: server.autostart,
    callTimeoutMs: server.runtime.call_timeout_ms,
    initTimeoutMs: server.runtime.init_timeout_ms,
    maxRestartAttempts: server.runtime.max_restart_attempts,
    toolInclude: server.tools?.include ?? null,
    availableTools: server.available_tools ?? [],
    toolOverridesJson: JSON.stringify(server.tool_overrides ?? {}, null, 2),
  };
  if (server.transport.kind === 'stdio') {
    return {
      ...base,
      transportKind: 'stdio',
      command: server.transport.command,
      argsText: (server.transport.args ?? []).join(' '),
      envText: kvToText(server.transport.env ?? {}),
    };
  }
  return {
    ...base,
    transportKind: 'http',
    url: server.transport.url,
    headersText: kvToText(server.transport.headers ?? {}),
  };
};

const kvToText = (obj: Record<string, string>): string =>
  Object.entries(obj)
    .map(([k, v]) => `${k}=${v}`)
    .join('\n');

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

const buildPayload = (
  draft: DraftState,
): { payload: MCPServerCreatePayload; error?: string } => {
  let transport: MCPTransport;
  if (draft.transportKind === 'stdio') {
    const args = draft.argsText.trim().split(/\s+/).filter(Boolean);
    if (!draft.command.trim()) {
      return { payload: null as unknown as MCPServerCreatePayload, error: 'command' };
    }
    transport = {
      kind: 'stdio',
      command: draft.command.trim(),
      args,
      cwd: '',
      env: parseKVText(draft.envText),
    };
  } else {
    if (!draft.url.trim()) {
      return { payload: null as unknown as MCPServerCreatePayload, error: 'url' };
    }
    transport = {
      kind: 'http',
      url: draft.url.trim(),
      headers: parseKVText(draft.headersText),
    };
  }

  let toolOverrides: MCPServerCreatePayload['tool_overrides'];
  if (draft.toolOverridesJson.trim() && draft.toolOverridesJson.trim() !== '{}') {
    try {
      toolOverrides = JSON.parse(draft.toolOverridesJson);
    } catch {
      return { payload: null as unknown as MCPServerCreatePayload, error: 'tool_overrides' };
    }
  }

  return {
    payload: {
      server: {
        id: draft.id.trim(),
        name: draft.name.trim() || draft.id.trim(),
        description: draft.description,
        enabled: draft.enabled,
        autostart: draft.autostart,
      },
      transport,
      runtime: {
        call_timeout_ms: draft.callTimeoutMs,
        init_timeout_ms: draft.initTimeoutMs,
        max_restart_attempts: draft.maxRestartAttempts,
      },
      tools: { include: draft.toolInclude },
      tool_overrides: toolOverrides,
    },
  };
};

// -----------------------------------------------------------------------
// Import: try to parse `mcp.json` or `claude_desktop_config.json` shape
// and produce a list of partial drafts. Both shapes share an
// `mcpServers: { <id>: { command, args, env, url, headers } }` structure.
// -----------------------------------------------------------------------

const draftsFromImportJson = (raw: unknown): DraftState[] => {
  if (!raw || typeof raw !== 'object') return [];
  const obj = raw as Record<string, unknown>;
  const root = (obj.mcpServers ?? obj.servers ?? obj) as Record<string, unknown>;
  if (!root || typeof root !== 'object') return [];
  const drafts: DraftState[] = [];
  for (const [id, val] of Object.entries(root)) {
    if (!val || typeof val !== 'object') continue;
    const v = val as Record<string, unknown>;
    const next: DraftState = { ...EMPTY_DRAFT, id, name: id };
    if (typeof v.command === 'string') {
      next.transportKind = 'stdio';
      next.command = v.command;
      next.argsText = Array.isArray(v.args) ? (v.args as unknown[]).join(' ') : '';
      next.envText = v.env && typeof v.env === 'object'
        ? kvToText(v.env as Record<string, string>)
        : '';
    } else if (typeof v.url === 'string') {
      next.transportKind = 'http';
      next.url = v.url;
      next.headersText = v.headers && typeof v.headers === 'object'
        ? kvToText(v.headers as Record<string, string>)
        : '';
    } else {
      continue;
    }
    drafts.push(next);
  }
  return drafts;
};

interface ServerEditorDrawerProps {
  open: boolean;
  initialDraft: DraftState | null;
  isEdit: boolean;
  onClose: () => void;
  onSave: (payload: MCPServerCreatePayload, isEdit: boolean) => Promise<void>;
}

const ServerEditorDrawer: React.FC<ServerEditorDrawerProps> = ({
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
  const [advancedOpen, setAdvancedOpen] = useState(false);

  useEffect(() => {
    if (open) {
      setDraft(initialDraft ?? EMPTY_DRAFT);
      setError(null);
      setAdvancedOpen(false);
    }
  }, [open, initialDraft]);

  const handleSave = useCallback(async () => {
    setError(null);
    const { payload, error: buildError } = buildPayload(draft);
    if (buildError) {
      setError(t(`settings.mcp.editor.errors.${buildError}`));
      return;
    }
    setSaving(true);
    try {
      await onSave(payload, isEdit);
      onClose();
    } catch (exc: any) {
      setError(exc?.message ?? String(exc));
    } finally {
      setSaving(false);
    }
  }, [draft, isEdit, onClose, onSave, t]);

  const setToolEnabled = useCallback((name: string, enabled: boolean) => {
    setDraft((current) => {
      const visibleNames = current.availableTools.map((tool) => tool.name);
      const selected = new Set(current.toolInclude ?? visibleNames);
      if (enabled) selected.add(name);
      else selected.delete(name);
      return { ...current, toolInclude: visibleNames.filter((item) => selected.has(item)) };
    });
  }, []);

  return (
    <Dialog open={open} onOpenChange={(next) => (next ? null : onClose())}>
      <DialogContent className="settings-theme-surface flex max-h-[85vh] w-full max-w-2xl flex-col gap-0 overflow-hidden p-0">
        <DialogHeader className="border-b px-6 py-4">
          <DialogTitle>
            {t(isEdit ? 'settings.mcp.editor.editTitle' : 'settings.mcp.editor.createTitle')}
          </DialogTitle>
          <DialogDescription>{t('settings.mcp.editor.description')}</DialogDescription>
        </DialogHeader>

        <div className="flex-1 overflow-y-auto px-6 py-4">
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

            <button
              type="button"
              onClick={() => setAdvancedOpen((v) => !v)}
              className="text-sm font-medium text-muted-foreground hover:text-foreground"
            >
              {advancedOpen
                ? t('settings.mcp.editor.advancedHide')
                : t('settings.mcp.editor.advancedShow')}
            </button>

            {advancedOpen ? (
              <div className="space-y-3 rounded-md border bg-muted/20 p-3 text-sm">
                <div className="grid grid-cols-3 gap-3">
                  <label className="block">
                    <span className="mb-1 block text-muted-foreground">
                      {t('settings.mcp.editor.callTimeout')}
                    </span>
                    <Input
                      type="number"
                      min={1000}
                      value={draft.callTimeoutMs}
                      onChange={(e) =>
                        setDraft({ ...draft, callTimeoutMs: Number(e.target.value) || 0 })
                      }
                    />
                  </label>
                  <label className="block">
                    <span className="mb-1 block text-muted-foreground">
                      {t('settings.mcp.editor.initTimeout')}
                    </span>
                    <Input
                      type="number"
                      min={1000}
                      value={draft.initTimeoutMs}
                      onChange={(e) =>
                        setDraft({ ...draft, initTimeoutMs: Number(e.target.value) || 0 })
                      }
                    />
                  </label>
                  <label className="block">
                    <span className="mb-1 block text-muted-foreground">
                      {t('settings.mcp.editor.maxRestart')}
                    </span>
                    <Input
                      type="number"
                      min={0}
                      value={draft.maxRestartAttempts}
                      onChange={(e) =>
                        setDraft({
                          ...draft,
                          maxRestartAttempts: Number(e.target.value) || 0,
                        })
                      }
                    />
                  </label>
                </div>
                <div className="space-y-2 rounded-md border bg-background/60 p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div>
                      <div className="font-medium">
                        {t('settings.mcp.editor.exposedTools')}
                      </div>
                      <div className="text-xs text-muted-foreground">
                        {t('settings.mcp.editor.exposedToolsHint')}
                      </div>
                    </div>
                    <label className="flex items-center gap-2 text-xs text-muted-foreground">
                      <Switch
                        checked={draft.toolInclude === null}
                        onCheckedChange={(checked) =>
                          setDraft({
                            ...draft,
                            toolInclude: checked
                              ? null
                              : draft.availableTools.map((tool) => tool.name),
                          })
                        }
                      />
                      {t('settings.mcp.editor.autoExposeTools')}
                    </label>
                  </div>
                  {draft.availableTools.length > 0 ? (
                    <>
                      <div className="flex items-center gap-2">
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          onClick={() =>
                            setDraft({
                              ...draft,
                              toolInclude: draft.availableTools.map((tool) => tool.name),
                            })
                          }
                        >
                          {t('settings.mcp.editor.selectAllTools')}
                        </Button>
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          onClick={() => setDraft({ ...draft, toolInclude: [] })}
                        >
                          {t('settings.mcp.editor.clearTools')}
                        </Button>
                      </div>
                      <ul className="max-h-48 space-y-1 overflow-auto rounded-md border p-2">
                        {draft.availableTools.map((tool) => {
                          const checked =
                            draft.toolInclude === null || draft.toolInclude.includes(tool.name);
                          return (
                            <li key={tool.name} className="rounded px-2 py-1 hover:bg-accent/40">
                              <label className="flex items-start gap-2">
                                <input
                                  type="checkbox"
                                  className="mt-0.5"
                                  checked={checked}
                                  onChange={(event) =>
                                    setToolEnabled(tool.name, event.target.checked)
                                  }
                                />
                                <span className="min-w-0">
                                  <span className="block font-mono text-xs">{tool.name}</span>
                                  <span className="block text-xs text-muted-foreground">
                                    {tool.available
                                      ? tool.description || t('settings.mcp.editor.noToolDescription')
                                      : t('settings.mcp.editor.toolUnavailable')}
                                  </span>
                                </span>
                              </label>
                            </li>
                          );
                        })}
                      </ul>
                    </>
                  ) : (
                    <p className="text-xs text-muted-foreground">
                      {t('settings.mcp.editor.toolsUnavailableHint')}
                    </p>
                  )}
                </div>
                <label className="block">
                  <span className="mb-1 block text-muted-foreground">
                    {t('settings.mcp.editor.toolOverrides')}
                  </span>
                  <Textarea
                    value={draft.toolOverridesJson}
                    onChange={(e) => setDraft({ ...draft, toolOverridesJson: e.target.value })}
                    rows={4}
                    spellCheck={false}
                    className="font-mono text-xs"
                    placeholder='{"create_issue": {"risk": "high"}}'
                  />
                  <span className="mt-1 block text-xs text-muted-foreground">
                    {t('settings.mcp.editor.toolOverridesHint')}
                  </span>
                </label>
              </div>
            ) : null}

            {error ? <p className="text-sm text-destructive">{error}</p> : null}
          </div>
        </div>

        <DialogFooter className="border-t px-6 py-4">
          <DialogClose asChild>
            <Button type="button" variant="outline" size="sm" disabled={saving}>
              {t('settings.mcp.editor.cancel')}
            </Button>
          </DialogClose>
          <Button
            type="button"
            size="sm"
            onClick={() => void handleSave()}
            disabled={saving || !draft.id.trim()}
          >
            {saving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
            {t('settings.mcp.editor.save')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

interface LogsDialogProps {
  open: boolean;
  serverId: string | null;
  onClose: () => void;
}

const LogsDialog: React.FC<LogsDialogProps> = ({ open, serverId, onClose }) => {
  const { t } = useTranslation('app');
  const [logs, setLogs] = useState<MCPServerLogs | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!serverId) return;
    setLoading(true);
    setError(null);
    try {
      setLogs(await mcpApi.serverLogs(serverId));
    } catch (exc: any) {
      setError(exc?.message ?? String(exc));
    } finally {
      setLoading(false);
    }
  }, [serverId]);

  useEffect(() => {
    if (open) {
      void refresh();
    } else {
      setLogs(null);
    }
  }, [open, refresh]);

  return (
    <Dialog open={open} onOpenChange={(next) => (next ? null : onClose())}>
      <DialogContent className="settings-theme-surface max-w-2xl">
        <DialogHeader>
          <DialogTitle>
            {t('settings.mcp.logs.title', { id: serverId ?? '' })}
          </DialogTitle>
          <DialogDescription>{t('settings.mcp.logs.description')}</DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          {loading ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              {t('settings.mcp.logs.loading')}
            </div>
          ) : null}
          {error ? <p className="text-sm text-destructive">{error}</p> : null}
          {logs?.last_error ? (
            <div className="rounded-md border border-destructive/40 bg-destructive/10 p-2 text-xs text-destructive">
              {logs.last_error}
            </div>
          ) : null}
          <pre className="max-h-[60vh] overflow-auto rounded-md border bg-muted/30 p-3 font-mono text-xs">
            {(logs?.stderr ?? []).join('\n') || t('settings.mcp.logs.empty')}
          </pre>
        </div>

        <DialogFooter>
          <Button type="button" variant="outline" size="sm" onClick={() => void refresh()} disabled={loading}>
            <RefreshCw className="mr-2 h-4 w-4" />
            {t('settings.mcp.refresh')}
          </Button>
          <DialogClose asChild>
            <Button type="button" size="sm">{t('settings.mcp.editor.cancel')}</Button>
          </DialogClose>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

interface ImportPreviewDialogProps {
  open: boolean;
  drafts: DraftState[];
  existingIds: Set<string>;
  onClose: () => void;
  onImport: (drafts: DraftState[]) => Promise<void>;
}

const ImportPreviewDialog: React.FC<ImportPreviewDialogProps> = ({
  open,
  drafts,
  existingIds,
  onClose,
  onImport,
}) => {
  const { t } = useTranslation('app');
  const [selected, setSelected] = useState<Record<string, boolean>>({});
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      const next: Record<string, boolean> = {};
      drafts.forEach((d) => {
        next[d.id] = !existingIds.has(d.id);
      });
      setSelected(next);
      setError(null);
    }
  }, [open, drafts, existingIds]);

  const handleImport = useCallback(async () => {
    const chosen = drafts.filter((d) => selected[d.id]);
    if (chosen.length === 0) {
      onClose();
      return;
    }
    setImporting(true);
    setError(null);
    try {
      await onImport(chosen);
      onClose();
    } catch (exc: any) {
      setError(exc?.message ?? String(exc));
    } finally {
      setImporting(false);
    }
  }, [drafts, selected, onImport, onClose]);

  return (
    <Dialog open={open} onOpenChange={(next) => (next ? null : onClose())}>
      <DialogContent className="settings-theme-surface max-w-lg">
        <DialogHeader>
          <DialogTitle>{t('settings.mcp.import.title')}</DialogTitle>
          <DialogDescription>{t('settings.mcp.import.description')}</DialogDescription>
        </DialogHeader>

        <ul className="max-h-80 space-y-1 overflow-auto rounded-md border p-2 text-sm">
          {drafts.length === 0 ? (
            <li className="px-2 py-1 text-muted-foreground">
              {t('settings.mcp.import.empty')}
            </li>
          ) : (
            drafts.map((d) => {
              const conflict = existingIds.has(d.id);
              return (
                <li
                  key={d.id}
                  className="flex items-center gap-2 rounded px-2 py-1 hover:bg-accent/40"
                >
                  <input
                    type="checkbox"
                    checked={!!selected[d.id]}
                    onChange={(e) =>
                      setSelected({ ...selected, [d.id]: e.target.checked })
                    }
                  />
                  <span className="font-medium">{d.id}</span>
                  <span className="text-xs text-muted-foreground">
                    {d.transportKind} · {d.transportKind === 'stdio' ? d.command : d.url}
                  </span>
                  {conflict ? (
                    <span className="ml-auto text-xs text-amber-600">
                      {t('settings.mcp.import.conflict')}
                    </span>
                  ) : null}
                </li>
              );
            })
          )}
        </ul>

        {error ? <p className="text-sm text-destructive">{error}</p> : null}

        <DialogFooter>
          <DialogClose asChild>
            <Button type="button" variant="outline" size="sm" disabled={importing}>
              {t('settings.mcp.editor.cancel')}
            </Button>
          </DialogClose>
          <Button
            type="button"
            size="sm"
            onClick={() => void handleImport()}
            disabled={importing || drafts.length === 0}
          >
            {importing ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
            {t('settings.mcp.import.confirm')}
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

  const [logsServerId, setLogsServerId] = useState<string | null>(null);
  const [logsOpen, setLogsOpen] = useState(false);

  const [importDrafts, setImportDrafts] = useState<DraftState[]>([]);
  const [importOpen, setImportOpen] = useState(false);
  const importFileInput = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setRefreshError(null);
    try {
      setServers(await mcpApi.listServers());
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

  const onShowLogs = (server: MCPServerStatus) => {
    setLogsServerId(server.id);
    setLogsOpen(true);
  };

  const handleImportFile = async (file: File) => {
    try {
      const text = await file.text();
      const parsed = JSON.parse(text);
      const drafts = draftsFromImportJson(parsed);
      if (drafts.length === 0) {
        alert(t('settings.mcp.import.parseEmpty'));
        return;
      }
      setImportDrafts(drafts);
      setImportOpen(true);
    } catch (exc: any) {
      alert(t('settings.mcp.import.parseFailed', { message: exc?.message ?? String(exc) }));
    }
  };

  const onImport = async (drafts: DraftState[]) => {
    for (const d of drafts) {
      const { payload, error } = buildPayload(d);
      if (error) continue;
      try {
        await mcpApi.createServer(payload);
      } catch (exc) {
        // Continue importing the rest; user will see what landed via refresh.
        console.warn('[mcp] import skipped', d.id, exc);
      }
    }
    await refresh();
  };

  const totalTools = useMemo(
    () => servers.reduce((acc, s) => acc + s.tool_count, 0),
    [servers],
  );

  const existingIds = useMemo(
    () => new Set(servers.map((s) => s.id)),
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
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => void refresh()}
            disabled={loading}
          >
            <RefreshCw className="mr-2 h-4 w-4" />
            {t('settings.mcp.refresh')}
          </Button>
        </div>
        <div className="flex items-center gap-2">
          <input
            ref={importFileInput}
            type="file"
            accept="application/json,.json"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) void handleImportFile(f);
              e.target.value = '';
            }}
          />
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => importFileInput.current?.click()}
          >
            <Upload className="mr-2 h-4 w-4" />
            {t('settings.mcp.actions.import')}
          </Button>
          <Button type="button" size="sm" onClick={onCreate}>
            <Plus className="mr-2 h-4 w-4" />
            {t('settings.mcp.actions.add')}
          </Button>
        </div>
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
            const isRunning =
              server.state === 'connected' || server.state === 'connecting';
            const busy = busyId === server.id;
            return (
              <li
                key={server.id}
                className="flex flex-wrap items-center gap-3 px-4 py-3"
              >
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

                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={busy}
                        aria-label={t('settings.mcp.actions.more')}
                      >
                        <MoreHorizontal className="h-4 w-4" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      <DropdownMenuItem onSelect={() => onEdit(server)}>
                        <Pencil className="h-3.5 w-3.5" />
                        {t('settings.mcp.actions.edit')}
                      </DropdownMenuItem>
                      <DropdownMenuItem onSelect={() => onShowLogs(server)}>
                        <ScrollText className="h-3.5 w-3.5" />
                        {t('settings.mcp.actions.viewLogs')}
                      </DropdownMenuItem>
                      <DropdownMenuSeparator />
                      <DropdownMenuItem
                        destructive
                        onSelect={() => void onDelete(server)}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                        {t('settings.mcp.actions.delete')}
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </div>
              </li>
            );
          })}
        </ul>
      )}

      <ServerEditorDrawer
        open={editorOpen}
        initialDraft={editingDraft}
        isEdit={editingIsEdit}
        onClose={() => setEditorOpen(false)}
        onSave={handleSave}
      />

      <LogsDialog
        open={logsOpen}
        serverId={logsServerId}
        onClose={() => setLogsOpen(false)}
      />

      <ImportPreviewDialog
        open={importOpen}
        drafts={importDrafts}
        existingIds={existingIds}
        onClose={() => setImportOpen(false)}
        onImport={onImport}
      />

      {/* Footnote: hint anchor for keyboard users to find import format */}
      <p className="flex items-center gap-2 text-xs text-muted-foreground">
        <FileText className="h-3 w-3" />
        {t('settings.mcp.importHint')}
      </p>
    </div>
  );
};

export default MCPServersSection;
