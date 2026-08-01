import { describe, expect, it, vi } from 'vitest';

import { recoverPendingFullDataClear } from '@/hooks/clearAllMemory';
import { finishPendingFullDataClearBeforeAppReady } from '@/runtime/fullDataClearBootstrap';
import { APP_EVENTS } from '@/constants/events';

vi.mock('@/hooks/clearAllMemory', () => ({
  recoverPendingFullDataClear: vi.fn(),
}));

describe('full data clear startup gate', () => {
  it('does not let startup continue until the pending clear finishes and restarts once', async () => {
    let finishRecovery: ((value: boolean) => void) | undefined;
    vi.mocked(recoverPendingFullDataClear).mockImplementation(() => new Promise(
      (resolve) => {
        finishRecovery = resolve;
      },
    ));
    const phases: string[] = [];
    let startupContinued = false;
    const restartedRuntime = {
      isDesktop: true,
      apiBaseUrl: 'http://127.0.0.1:9000/api',
      sessionToken: 'new-token',
    };
    const restartRuntime = vi.fn().mockResolvedValue(restartedRuntime);

    const gate = finishPendingFullDataClearBeforeAppReady((phase) => {
      phases.push(phase);
    }, { restartRuntime }).then((runtime) => {
      startupContinued = true;
      return runtime;
    });
    await Promise.resolve();

    expect(phases).toEqual(['recovering_data_clear']);
    expect(startupContinued).toBe(false);
    expect(restartRuntime).not.toHaveBeenCalled();

    finishRecovery?.(true);
    await expect(gate).resolves.toEqual(restartedRuntime);
    expect(startupContinued).toBe(true);
    expect(restartRuntime).toHaveBeenCalledOnce();
  });

  it('does not restart when there is no pending clear', async () => {
    vi.mocked(recoverPendingFullDataClear).mockResolvedValue(false);
    const restartRuntime = vi.fn();
    const released = vi.fn();
    window.addEventListener(APP_EVENTS.MEMORY_CLEAR_RECOVERY_RELEASED, released);

    await expect(
      finishPendingFullDataClearBeforeAppReady(vi.fn(), { restartRuntime }),
    ).resolves.toBeNull();

    expect(restartRuntime).not.toHaveBeenCalled();
    expect(released).not.toHaveBeenCalled();
    window.removeEventListener(APP_EVENTS.MEMORY_CLEAR_RECOVERY_RELEASED, released);
  });

  it('releases a failed manual clear gate when retry finds no desktop marker', async () => {
    vi.mocked(recoverPendingFullDataClear).mockResolvedValue(false);
    const released = vi.fn();
    window.addEventListener(APP_EVENTS.MEMORY_CLEAR_RECOVERY_RELEASED, released);

    await expect(
      finishPendingFullDataClearBeforeAppReady(vi.fn(), {
        releaseInteractionGateWhenNotPending: true,
      }),
    ).resolves.toBeNull();

    expect(released).toHaveBeenCalledOnce();
    window.removeEventListener(APP_EVENTS.MEMORY_CLEAR_RECOVERY_RELEASED, released);
  });

  it('keeps startup blocked when recovery fails', async () => {
    vi.mocked(recoverPendingFullDataClear).mockRejectedValue(
      new Error('clear marker remains pending'),
    );

    const restartRuntime = vi.fn();
    await expect(
      finishPendingFullDataClearBeforeAppReady(vi.fn(), { restartRuntime }),
    ).rejects.toThrow('clear marker remains pending');
    expect(restartRuntime).not.toHaveBeenCalled();
  });
});
