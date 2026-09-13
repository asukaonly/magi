import { beforeEach, describe, expect, it, vi } from 'vitest';
const { invoke, runtime } = vi.hoisted(() => ({ invoke: vi.fn(), runtime: { serverId:'f769608f-d9a8-44f8-bc56-e3fb6e77fb24', dataEpoch:'95f7d280-ed66-4b13-ad27-c240e3f967a0', profileId:'local', connectionGeneration:1 } }));
vi.mock('@tauri-apps/api/core', () => ({ invoke }));
vi.mock('@/runtime/config', async (importOriginal) => ({ ...await importOriginal<typeof import('@/runtime/config')>(), getRuntimeConfig: () => ({ ...runtime, apiBaseUrl:'http://127.0.0.1:19080/api', isDesktop:true }), getRuntimeGeneration: () => runtime.connectionGeneration }));
import { enqueueNotificationRead, readBackgroundDeliveryStatus } from '@/runtime/background-delivery';
import { useNotificationStore } from '@/stores/notifications';
import * as notifications from '@/api/modules/notifications';

const pending = { queue:{ pending:1, failed:0, bytes:40, next_retry_at_ms:0, last_error:null },notification_read_ids:[1] };
const row = { id:1, kind:'suggestion' as const, dedupe_key:'test', title:'t',body:'b',payload:{},status:'unread' as const,created_at_ms:1,read_at_ms:null };
beforeEach(() => { vi.restoreAllMocks(); invoke.mockReset(); runtime.connectionGeneration=1;runtime.profileId='local';useNotificationStore.getState().clearForMemoryClear(); });

describe('background delivery boundary', () => {
  it.each(['local','remote'])('persists %s reads before reporting success without a network request', async (profile) => {
    runtime.profileId=profile; invoke.mockResolvedValue(true);
    await enqueueNotificationRead([1,1,2]);
    expect(invoke).toHaveBeenCalledTimes(2);
    expect(invoke.mock.calls[0]).toEqual(['enqueue_background_event', {request:expect.objectContaining({scope:expect.objectContaining({profile_id:profile}),stream:'notification:1',policy:'latest',payload:{kind:'notification_read',notification_id:1}})}]);
  });
  it('keeps the original target if a multi-event enqueue crosses a connection change', async () => {
    invoke.mockImplementation(async () => { runtime.profileId='other';runtime.connectionGeneration=2; return true; });
    await enqueueNotificationRead([1,2]);
    for (const [, args] of invoke.mock.calls) expect(args.request).toMatchObject({generation:1,scope:{profile_id:'local'}});
  });
  it('does not claim persistence after a rejected or malformed native response', async () => {
    invoke.mockResolvedValue(false); await expect(enqueueNotificationRead([1])).rejects.toThrow('not stored');
    invoke.mockRejectedValue(new Error('disk full')); await expect(enqueueNotificationRead([1])).rejects.toThrow('disk full');
    invoke.mockResolvedValue({queue:{pending:'1'}}); await expect(readBackgroundDeliveryStatus()).rejects.toThrow();
  });
  it('projects queued reads over server snapshots after a restart', async () => {
    invoke.mockResolvedValue(pending);
    vi.spyOn(notifications,'listNotifications').mockResolvedValue({items:[row],total:1,unread_count:1});
    await useNotificationStore.getState().refresh();
    expect(useNotificationStore.getState().items[0].status).toBe('read');
    expect(useNotificationStore.getState().unreadCount).toBe(0);
  });
  it('marks read offline after disk acceptance and exposes local storage failure', async () => {
    useNotificationStore.setState({items:[row],unreadCount:1});
    invoke.mockResolvedValue(true);
    await useNotificationStore.getState().markRead([1]);
    expect(useNotificationStore.getState().unreadCount).toBe(0);
    useNotificationStore.setState({items:[row],unreadCount:1});
    invoke.mockRejectedValue(new Error('disk full'));
    await useNotificationStore.getState().markRead([1]);
    expect(useNotificationStore.getState()).toMatchObject({unreadCount:1,readError:true});
  });
  it('does not apply an old enqueue completion to another center', async () => {
    useNotificationStore.setState({items:[row],unreadCount:1});
    invoke.mockImplementation(async () => {runtime.connectionGeneration++;return true;});
    await useNotificationStore.getState().markRead([1]);
    expect(useNotificationStore.getState().unreadCount).toBe(1);
  });
});
