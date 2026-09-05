import { StrictMode, type PropsWithChildren } from 'react';
import { renderHook, act, cleanup } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import {
  sensorsApi,
  type MemoryReadinessResponse,
  type SensorSourceStatusItem,
  type SensorSourceStatusResponse,
} from '@/api/modules/sensors';
import {
  pluginsApi,
  type ActivationFlowSpec,
  type ExtensionFieldSpec,
  type PluginConnection,
  type PluginInstallJobSnapshot,
  type PluginPackageState,
} from '@/api/modules/plugins';
import { usePluginInstallFlow } from '@/hooks/usePluginInstallFlow';

const { translate } = vi.hoisted(() => ({ translate: (key: string) => key }));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: translate }) }));

const field = (key: string, overrides: Partial<ExtensionFieldSpec> = {}): ExtensionFieldSpec => ({
  key, type: 'input', label: key, description: '', required: false, options: [],
  section: 'general', surface: 'timeline', order: 0, ...overrides,
});
const FLOW = (fields: ExtensionFieldSpec[] = []): ActivationFlowSpec => ({
  title: 'Connect', description: 'Description', confirm_label: 'Connect', cancel_label: 'Cancel',
  authorize_on_confirm: false, enabled_key: 'sensors.s.enabled', configured_key: 'sensors.s.configured', fields,
});
const installed = (
  activation: ActivationFlowSpec | null = FLOW(),
  settingsFields: ExtensionFieldSpec[] = activation?.fields ?? [],
  pluginId = 'p',
): PluginPackageState => ({
  manifest: {
    plugin_id: pluginId, name: `Plugin ${pluginId}`, version: '1.0.0', description: 'Plugin description',
    author: '', official: false, contribution_types: ['sensor'], source: 'installed',
    plugin_dir: '', manifest_path: '', capabilities: [], protocol_version: 2,
    min_sdk_version: '0.2.0', execution_mode: 'restricted_process', settings_actions: [],
    settings_resources: [], settings_ui_blocks: [], activation_flow: activation,
    settings_fields: [
      field('sensors.s.enabled', { type: 'switch', default: false }),
      field('sensors.s.configured', { type: 'switch', default: false }),
      ...settingsFields,
    ],
  },
  enabled: false, trusted: true, loaded: false, healthy: false, contributions: [], current_settings: {},
});
const connection = (pluginId = 'p', overrides: Partial<PluginConnection> = {}): PluginConnection => ({
  plugin_id: pluginId, connection_id: `connection-${pluginId}`, display_name: `Account ${pluginId}`,
  enabled: true, settings: {}, credential_refs: {}, revision: 1, readiness: [], ...overrides,
});
const source = (overrides: Partial<SensorSourceStatusItem> = {}): SensorSourceStatusItem => ({
  source_name: 's', connection_id: 'connection-p', connection_display_name: 'Account p',
  connection_revision: 1, plugin_id: 'p', contribution_id: 's', display_name: 'Source', description: '',
  fields: [], current_settings: {}, enabled: true, sync_mode: 'interval', sync_interval_minutes: 10,
  storage_mode: 'events', fetch_page_content: false, edge_whitelist: [], supports_pull_sync: true,
  running: false, last_result_count: 12, last_raw_result_count: 15, last_success: null, ...overrides,
});
const readiness = (overrides: Partial<MemoryReadinessResponse> = {}): MemoryReadinessResponse => ({
  source_name: 's', connection_id: 'connection-p', l1_event_count: 12, l2_ready: true,
  l2_total_count: 12, l2_processed_count: 12, l2_remaining_count: 0, ...overrides,
});
const deferred = <T,>() => {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};
const advance = async (ms = 0) => { await act(async () => { await vi.advanceTimersByTimeAsync(ms); }); };
const mockPackages = (...packages: PluginPackageState[]) => {
  vi.mocked(pluginsApi.list).mockResolvedValue({ plugins: packages, total: packages.length });
};

beforeEach(() => {
  vi.useFakeTimers();
  const syncCounts = new Map<string, number>();
  vi.spyOn(pluginsApi, 'list').mockResolvedValue({ plugins: [installed()], total: 1 });
  vi.spyOn(pluginsApi, 'createConnection').mockImplementation(async (pluginId) => connection(pluginId));
  vi.spyOn(pluginsApi, 'getConnection').mockImplementation(async (pluginId, id) => connection(pluginId, { connection_id: id }));
  vi.spyOn(pluginsApi, 'updateConnection').mockImplementation(async (pluginId, id, input) =>
    connection(pluginId, { connection_id: id, revision: input.expected_revision + 1 }));
  vi.spyOn(pluginsApi, 'installFromRegistryWithProgress').mockResolvedValue(installed());
  vi.spyOn(sensorsApi, 'getStatus').mockImplementation(async () => ({
    sources: [
      source({ connection_id: 'other-account', last_success: '2026-01-02T00:00:00Z', last_result_count: 999 }),
      ...['p', 'q'].map((id) => {
        const count = syncCounts.get(`connection-${id}`) ?? 0;
        return source({ plugin_id: id, connection_id: `connection-${id}`,
          last_success: count ? `2026-01-01T00:00:0${count}Z` : null });
      }),
    ],
  }));
  vi.spyOn(sensorsApi, 'requestSync').mockImplementation(async (name, id) => {
    syncCounts.set(id, (syncCounts.get(id) ?? 0) + 1);
    return { source_name: name, connection_id: id, queued: true };
  });
  vi.spyOn(sensorsApi, 'requestAuthorization').mockResolvedValue({
    authorized: true, requested_types: [], granted_types: [], denied_types: [],
  });
  vi.spyOn(sensorsApi, 'getMemoryReadiness').mockImplementation(async (name, id) =>
    readiness({ source_name: name, connection_id: id }));
});
afterEach(() => {
  cleanup();
  vi.clearAllTimers();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe('usePluginInstallFlow', () => {
  it('uses installed manifest metadata and scopes creation, sync and readiness to one new account', async () => {
    const { result } = renderHook(() => usePluginInstallFlow('p', false));
    await advance(1500);
    expect(result.current.phase).toBe('done');
    expect(pluginsApi.createConnection).toHaveBeenCalledExactlyOnceWith('p', {
      display_name: 'Plugin p', enabled: true,
      settings: { sensors: { s: { enabled: true, configured: true } } }, credentials: {},
    });
    expect(sensorsApi.requestSync).toHaveBeenCalledWith('s', 'connection-p', undefined);
    expect(sensorsApi.getMemoryReadiness).toHaveBeenCalledWith('s', 'connection-p', { maxWaitMs: 1500 });
    expect(result.current).toMatchObject({
      connectionId: 'connection-p', sourceName: 's', syncedCount: 12, syncedRawCount: 15,
      memoryReady: true, memoryTotalCount: 12, memoryProcessedCount: 12, memoryRemainingCount: 0,
    });
    expect(result.current.steps.every((step) => step.status === 'done')).toBe(true);
  });

  it('collects canonical required fields before any connection, authorization or status lookup', async () => {
    const path = field('directory', { type: 'path', required: true });
    const token = field('account.token', { type: 'secret', required: true });
    mockPackages(installed({ ...FLOW([field('directory')]), authorize_on_confirm: true }, [path, token]));
    const { result } = renderHook(() => usePluginInstallFlow('p', false));
    await advance();
    expect(result.current.phase).toBe('awaiting_fields');
    expect(result.current.flow?.fields).toEqual([path, token]);
    expect(pluginsApi.createConnection).not.toHaveBeenCalled();
    expect(sensorsApi.getStatus).not.toHaveBeenCalled();
    expect(sensorsApi.requestAuthorization).not.toHaveBeenCalled();
    act(() => result.current.submitFields({ directory: '/accounts/work', 'account.token': 'private-token' }));
    await advance(1500);
    expect(pluginsApi.createConnection).toHaveBeenCalledWith('p', {
      display_name: 'Plugin p', enabled: true,
      settings: { directory: '/accounts/work', sensors: { s: { enabled: true, configured: true } } },
      credentials: { 'account.token': 'private-token' },
    });
    expect(sensorsApi.requestAuthorization).toHaveBeenCalledWith('s', 'connection-p', expect.objectContaining({ directory: '/accounts/work' }));
    expect(result.current.phase).toBe('done');
  });

  it('first context applies manifest defaults and caps without asking for optional default fields', async () => {
    const fields = [
      field('sensors.s.lookback_days', { type: 'number', default: 7 }),
      field('sensors.s.max_items_per_sync', { type: 'number', default: 500 }),
    ];
    mockPackages(installed(FLOW(fields)));
    const { result } = renderHook(() => usePluginInstallFlow('p', false, 'first_context'));
    await advance(1500);
    expect(result.current.flow?.fields).toEqual([]);
    expect(pluginsApi.createConnection).toHaveBeenCalledWith('p', expect.objectContaining({
      settings: { sensors: { s: { enabled: true, configured: true, lookback_days: 7, max_items_per_sync: 200 } } },
    }));
    expect(sensorsApi.requestSync).toHaveBeenCalledWith('s', 'connection-p', { firstContext: true });
    expect(sensorsApi.getMemoryReadiness).toHaveBeenCalledWith('s', 'connection-p', { maxWaitMs: 0 });
  });

  it('first context applies declared overrides and still asks for required directories', async () => {
    const fields = [
      field('sensors.s.paths', { type: 'tags', required: true }),
      field('sensors.s.lookback_days', { type: 'number', default: 90 }),
      field('sensors.s.max_items_per_sync', { type: 'number', default: 500 }),
    ];
    mockPackages(installed({ ...FLOW(fields), first_context: {
      max_items_per_sync: 75, settings_overrides: { 'sensors.s.lookback_days': 14 },
    } }));
    const { result } = renderHook(() => usePluginInstallFlow('p', false, 'first_context'));
    await advance();
    expect(result.current.flow?.fields.map((item) => item.key)).toEqual(['sensors.s.paths']);
    act(() => result.current.submitFields({ 'sensors.s.paths': ['/history'] }));
    await advance(1500);
    expect(pluginsApi.createConnection).toHaveBeenCalledWith('p', expect.objectContaining({
      settings: { sensors: { s: { enabled: true, configured: true, paths: ['/history'], lookback_days: 14, max_items_per_sync: 75 } } },
    }));
    expect(result.current.phase).toBe('done');
  });

  it('first context completes when L1 input is known without waiting for L2', async () => {
    vi.mocked(sensorsApi.getMemoryReadiness).mockResolvedValue(readiness({ l2_ready: false, l2_processed_count: 0, l2_remaining_count: 12 }));
    const { result } = renderHook(() => usePluginInstallFlow('p', false, 'first_context'));
    await advance(1500);
    expect(result.current.phase).toBe('done');
    expect(result.current.memoryReady).toBe(false);
    expect(result.current.steps.find((step) => step.id === 'memory')?.status).toBe('done');
    expect(result.current.backfillNote).toBe(false);
    expect(sensorsApi.getMemoryReadiness).toHaveBeenCalledOnce();
  });

  it('finishes empty memory input without a background organizing note', async () => {
    vi.mocked(sensorsApi.getStatus)
      .mockResolvedValueOnce({ sources: [source()] })
      .mockResolvedValue({ sources: [source({ last_success: '2026-01-01T00:00:01Z', last_result_count: 0, last_raw_result_count: 7 })] });
    vi.mocked(sensorsApi.getMemoryReadiness).mockResolvedValue(readiness({ l1_event_count: 0, l2_ready: false, l2_total_count: 0, l2_processed_count: 0 }));
    const { result } = renderHook(() => usePluginInstallFlow('p', false));
    await advance(1500);
    expect(result.current).toMatchObject({ phase: 'done', syncedCount: 0, syncedRawCount: 7, memoryReady: false, memoryTotalCount: 0, backfillNote: false });
    expect(sensorsApi.getMemoryReadiness).toHaveBeenCalledOnce();
  });

  it('keeps sync pending for this account despite another account completing and skips memory on timeout', async () => {
    vi.mocked(sensorsApi.getStatus).mockResolvedValue({ sources: [
      source({ connection_id: 'other-account', last_success: '2026-01-01T00:00:01Z' }), source(),
    ] });
    const { result } = renderHook(() => usePluginInstallFlow('p', false));
    await advance(95_000);
    expect(result.current).toMatchObject({ phase: 'done', syncDeferred: true, backfillNote: true });
    expect(result.current.steps.find((step) => step.id === 'memory')?.status).toBe('skipped');
    expect(sensorsApi.getMemoryReadiness).not.toHaveBeenCalled();
  });

  it('polls bounded memory progress and refreshes completion in the background', async () => {
    vi.mocked(sensorsApi.getMemoryReadiness).mockResolvedValue(readiness({ l1_event_count: 3, l2_ready: false, l2_total_count: 3, l2_processed_count: 1, l2_remaining_count: 2 }));
    const { result } = renderHook(() => usePluginInstallFlow('p', false));
    await advance(22_000);
    expect(result.current).toMatchObject({ phase: 'done', memoryProcessedCount: 1, memoryTotalCount: 3, backfillNote: true });
    expect(result.current.steps.find((step) => step.id === 'memory')?.status).toBe('background');
    vi.mocked(sensorsApi.getMemoryReadiness).mockResolvedValue(readiness({ l1_event_count: 3, l2_total_count: 3, l2_processed_count: 3 }));
    await advance(3000);
    expect(result.current.memoryReady).toBe(true);
    expect(result.current.backfillNote).toBe(false);
    expect(result.current.steps.find((step) => step.id === 'memory')?.status).toBe('done');
  });

  it('rejects readiness for a different connection without showing its counts', async () => {
    vi.mocked(sensorsApi.getMemoryReadiness).mockResolvedValue(readiness({ connection_id: 'other-account', l1_event_count: 999 }));
    const { result } = renderHook(() => usePluginInstallFlow('p', false));
    await advance(1500);
    expect(result.current.phase).toBe('error');
    expect(result.current.memoryCount).toBeNull();
  });

  it('rejects a mismatched sync receipt instead of polling another account', async () => {
    vi.mocked(sensorsApi.requestSync).mockResolvedValue({ source_name: 's', connection_id: 'other-account', queued: true });
    const { result } = renderHook(() => usePluginInstallFlow('p', false));
    await advance();
    expect(result.current.phase).toBe('error');
    expect(sensorsApi.getStatus).toHaveBeenCalledOnce();
    expect(sensorsApi.getMemoryReadiness).not.toHaveBeenCalled();
  });

  it('does not create a connection for an absent package or use live sensor activation metadata', async () => {
    mockPackages();
    const { result } = renderHook(() => usePluginInstallFlow('p', false));
    await advance();
    expect(result.current.phase).toBe('error');
    expect(pluginsApi.createConnection).not.toHaveBeenCalled();
    expect(sensorsApi.getStatus).not.toHaveBeenCalled();
  });

  it('reports missing activation metadata as unsupported without enabling', async () => {
    mockPackages(installed(null));
    const { result } = renderHook(() => usePluginInstallFlow('p', false));
    await advance();
    expect(result.current.phase).toBe('unsupported');
    expect(pluginsApi.createConnection).not.toHaveBeenCalled();
  });

  it('history import creates and returns an explicit connection without invoking sensor APIs', async () => {
    // Import-only packages can declare no sensor settings at all.
    const importer = installed(null, []);
    importer.manifest.settings_fields = [];
    mockPackages(importer);
    const { result } = renderHook(() => usePluginInstallFlow('p', false, 'history_import'));
    await advance();
    expect(result.current).toMatchObject({ phase: 'done', connectionId: 'connection-p', sourceName: null });
    expect(result.current.steps).toEqual([{ id: 'enable', status: 'done' }]);
    expect(pluginsApi.createConnection).toHaveBeenCalledExactlyOnceWith('p', {
      display_name: 'Plugin p', enabled: true, settings: {}, credentials: {},
    });
    expect(sensorsApi.getStatus).not.toHaveBeenCalled();
    expect(sensorsApi.requestSync).not.toHaveBeenCalled();
    expect(sensorsApi.getMemoryReadiness).not.toHaveBeenCalled();
  });

  it('history import collects required manifest configuration and scoped credentials before creation', async () => {
    const importer = installed(null);
    importer.manifest.settings_fields = [field('directory', { type: 'path', required: true }), field('token', { type: 'secret', required: true })];
    mockPackages(importer);
    const { result } = renderHook(() => usePluginInstallFlow('p', false, 'history_import'));
    await advance();
    expect(result.current.phase).toBe('awaiting_fields');
    expect(pluginsApi.createConnection).not.toHaveBeenCalled();
    act(() => result.current.submitFields({ directory: '/history', token: 'secret' }));
    await advance();
    expect(result.current.connectionId).toBe('connection-p');
    expect(pluginsApi.createConnection).toHaveBeenCalledWith('p', {
      display_name: 'Plugin p', enabled: true, settings: { directory: '/history' }, credentials: { token: 'secret' },
    });
    expect(sensorsApi.requestSync).not.toHaveBeenCalled();
  });

  it('installs with the confirmed fingerprint and retries sync without another install, account, or credential write', async () => {
    const token = field('token', { type: 'secret', required: true });
    mockPackages(installed(FLOW([token])));
    vi.mocked(sensorsApi.requestSync).mockRejectedValueOnce(new Error('Temporary sync failure'));
    const { result } = renderHook(() => usePluginInstallFlow('p', true, 'default', 'fingerprint-1'));
    await advance();
    act(() => result.current.submitFields({ token: 'private-token' }));
    await advance();
    expect(result.current.phase).toBe('error');
    act(() => { result.current.retry(); result.current.retry(); });
    await advance(1500);
    expect(result.current.phase).toBe('done');
    expect(pluginsApi.installFromRegistryWithProgress).toHaveBeenCalledExactlyOnceWith('p', 'fingerprint-1', expect.any(Function));
    expect(pluginsApi.createConnection).toHaveBeenCalledOnce();
    expect(pluginsApi.getConnection).toHaveBeenCalledExactlyOnceWith('p', 'connection-p');
    expect(pluginsApi.updateConnection).not.toHaveBeenCalled();
    expect(sensorsApi.requestSync).toHaveBeenCalledTimes(2);
  });

  it('resumes a disabled connection with its current revision while retaining its settings', async () => {
    vi.mocked(sensorsApi.requestSync).mockRejectedValueOnce(new Error('Temporary sync failure'));
    vi.mocked(pluginsApi.getConnection).mockResolvedValue(connection('p', { enabled: false, revision: 9, settings: { changedDuringSetup: true } }));
    const { result } = renderHook(() => usePluginInstallFlow('p', false));
    await advance();
    act(() => result.current.retry());
    await advance(1500);
    expect(result.current.phase).toBe('done');
    expect(pluginsApi.updateConnection).toHaveBeenCalledExactlyOnceWith('p', 'connection-p', { enabled: true, expected_revision: 9 });
    expect(pluginsApi.createConnection).toHaveBeenCalledOnce();
  });

  it('ignores retry while connection creation is still pending', async () => {
    const pending = deferred<PluginConnection>();
    vi.mocked(pluginsApi.createConnection).mockReturnValue(pending.promise);
    const { result } = renderHook(() => usePluginInstallFlow('p', false));
    await advance();
    act(() => result.current.retry());
    await advance();
    expect(pluginsApi.createConnection).toHaveBeenCalledOnce();
    await act(async () => pending.resolve(connection()));
    await advance(1500);
    expect(result.current.phase).toBe('done');
  });

  it('isolates a late old create result from the next account, including its retry target', async () => {
    const oldCreate = deferred<PluginConnection>();
    vi.mocked(pluginsApi.createConnection).mockReturnValueOnce(oldCreate.promise);
    mockPackages(installed(), installed(FLOW(), [], 'q'));
    vi.mocked(sensorsApi.requestSync).mockRejectedValueOnce(new Error('Retry q'));
    const { result, rerender } = renderHook(({ id }) => usePluginInstallFlow(id, false), { initialProps: { id: 'p' } });
    await advance();
    rerender({ id: 'q' });
    await advance();
    expect(result.current).toMatchObject({ phase: 'error', connectionId: 'connection-q' });
    await act(async () => oldCreate.resolve(connection('p')));
    act(() => result.current.retry());
    await advance(1500);
    expect(pluginsApi.getConnection).toHaveBeenCalledExactlyOnceWith('q', 'connection-q');
    expect(result.current).toMatchObject({ phase: 'done', connectionId: 'connection-q', syncedCount: 12 });
    expect(vi.mocked(sensorsApi.requestSync).mock.calls.every((call) => call[1] === 'connection-q')).toBe(true);
  });

  it('does not update the previous account after a retry read finishes during a switch', async () => {
    const oldRead = deferred<PluginConnection>();
    mockPackages(installed(), installed(FLOW(), [], 'q'));
    vi.mocked(sensorsApi.requestSync).mockRejectedValueOnce(new Error('Retry p'));
    vi.mocked(pluginsApi.getConnection).mockReturnValueOnce(oldRead.promise);
    const { result, rerender } = renderHook(({ id }) => usePluginInstallFlow(id, false), { initialProps: { id: 'p' } });
    await advance();
    act(() => result.current.retry());
    await advance();
    rerender({ id: 'q' });
    await advance(1500);
    await act(async () => oldRead.resolve(connection('p', { enabled: false, revision: 7 })));
    expect(result.current).toMatchObject({ phase: 'done', connectionId: 'connection-q' });
    expect(pluginsApi.updateConnection).not.toHaveBeenCalled();
  });

  it('does not authorize or sync an account after its delayed source lookup becomes stale', async () => {
    const oldStatus = deferred<SensorSourceStatusResponse>();
    mockPackages(installed({ ...FLOW(), authorize_on_confirm: true }), installed(FLOW(), [], 'q'));
    vi.mocked(sensorsApi.getStatus).mockReturnValueOnce(oldStatus.promise);
    const { result, rerender } = renderHook(({ id }) => usePluginInstallFlow(id, false), { initialProps: { id: 'p' } });
    await advance();
    rerender({ id: 'q' });
    await advance(1500);
    await act(async () => oldStatus.resolve({ sources: [source()] }));
    expect(result.current.connectionId).toBe('connection-q');
    expect(sensorsApi.requestAuthorization).not.toHaveBeenCalled();
    expect(sensorsApi.requestSync).toHaveBeenCalledExactlyOnceWith('s', 'connection-q', undefined);
  });

  it('keeps stale readiness and field submissions out of the new account', async () => {
    const oldReadiness = deferred<MemoryReadinessResponse>();
    const required = field('directory', { required: true });
    mockPackages(installed(), installed(FLOW([required]), [required], 'q'));
    vi.mocked(sensorsApi.getMemoryReadiness).mockReturnValueOnce(oldReadiness.promise);
    const { result, rerender } = renderHook(({ id }) => usePluginInstallFlow(id, false), { initialProps: { id: 'p' } });
    await advance(1500);
    const oldSubmit = result.current.submitFields;
    rerender({ id: 'q' });
    await advance();
    act(() => oldSubmit({ directory: '/old' }));
    await act(async () => oldReadiness.resolve(readiness({ l1_event_count: 999 })));
    expect(result.current).toMatchObject({ phase: 'awaiting_fields', memoryCount: null, connectionId: null });
    expect(pluginsApi.createConnection).toHaveBeenCalledOnce();
    act(() => result.current.submitFields({ directory: '/new' }));
    await advance(1500);
    expect(result.current).toMatchObject({ phase: 'done', connectionId: 'connection-q', memoryCount: 12 });
  });

  it('isolates a late create when the same package is closed and reopened for a different account', async () => {
    const oldCreate = deferred<PluginConnection>();
    vi.mocked(pluginsApi.createConnection).mockReturnValueOnce(oldCreate.promise);
    const { result, rerender } = renderHook(({ id }: { id: string | null }) => usePluginInstallFlow(id, false), { initialProps: { id: 'p' as string | null } });
    await advance();
    rerender({ id: null });
    rerender({ id: 'p' });
    await advance(1500);
    await act(async () => oldCreate.resolve(connection('p', { connection_id: 'closed-account' })));
    expect(result.current).toMatchObject({ phase: 'done', connectionId: 'connection-p' });
    expect(sensorsApi.requestSync).toHaveBeenCalledExactlyOnceWith('s', 'connection-p', undefined);
  });

  it('stops after unmount even if account creation completes later', async () => {
    const pending = deferred<PluginConnection>();
    vi.mocked(pluginsApi.createConnection).mockReturnValueOnce(pending.promise);
    const { unmount } = renderHook(() => usePluginInstallFlow('p', false));
    await advance();
    unmount();
    await act(async () => pending.resolve(connection()));
    expect(sensorsApi.getStatus).not.toHaveBeenCalled();
    expect(sensorsApi.requestSync).not.toHaveBeenCalled();
  });

  it('does not create duplicate connections under strict effect replay', async () => {
    const wrapper = ({ children }: PropsWithChildren) => <StrictMode>{children}</StrictMode>;
    const { result } = renderHook(() => usePluginInstallFlow('p', false), { wrapper });
    await advance(1500);
    expect(result.current.phase).toBe('done');
    expect(pluginsApi.createConnection).toHaveBeenCalledOnce();
  });

  it('waits for registry consent and reports progress from the actual install', async () => {
    const snapshot: PluginInstallJobSnapshot = {
      job_id: 'install-1', operation: 'install', plugin_id: 'p', filename: null, status: 'running',
      stage: 'download', progress_pct: 25, message: 'Downloading', logs: [], created_at_ms: 1, updated_at_ms: 2,
    };
    const pending = deferred<PluginPackageState>();
    vi.mocked(pluginsApi.installFromRegistryWithProgress).mockImplementation((_id, _fingerprint, onProgress) => {
      onProgress?.(snapshot);
      return pending.promise;
    });
    const { result, rerender } = renderHook(({ fingerprint }: { fingerprint: string | null }) =>
      usePluginInstallFlow('p', true, 'default', fingerprint), { initialProps: { fingerprint: null as string | null } });
    await advance();
    expect(pluginsApi.installFromRegistryWithProgress).not.toHaveBeenCalled();
    expect(pluginsApi.list).not.toHaveBeenCalled();
    rerender({ fingerprint: 'confirmed' });
    await advance();
    expect(result.current.installProgress).toEqual(snapshot);
    expect(pluginsApi.list).not.toHaveBeenCalled();
    await act(async () => pending.resolve(installed()));
    await advance(1500);
    expect(result.current.phase).toBe('done');
  });

  it('clears running state before requesting new consent for a changed registry', async () => {
    const onRegistryChanged = vi.fn();
    vi.mocked(pluginsApi.installFromRegistryWithProgress).mockRejectedValue({ code: 'PLUGIN_REGISTRY_CHANGED', message: 'Registry changed' });
    const { result } = renderHook(() => usePluginInstallFlow('p', true, 'default', 'old', onRegistryChanged));
    await advance();
    expect(onRegistryChanged).toHaveBeenCalledOnce();
    expect(result.current).toMatchObject({ phase: 'loading', steps: [], installProgress: null, error: null, connectionId: null });
    expect(pluginsApi.createConnection).not.toHaveBeenCalled();
  });
});
