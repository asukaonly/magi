import { describe, expect, it, vi } from 'vitest';
import {
  ChatTurnAdmissionCoordinator,
  type ChatTurnSubmissionKind,
} from '@/hooks/chatTurnAdmission';

describe('ChatTurnAdmissionCoordinator', () => {
  const historyReady = async () => true;

  it.each<ChatTurnSubmissionKind>([
    'message',
    'recall_feedback',
    'inline_skill',
  ])('blocks %s while the same session has a pending turn', async (kind) => {
    const coordinator = new ChatTurnAdmissionCoordinator();
    const operation = vi.fn().mockResolvedValue(undefined);
    coordinator.markPendingTurn('session-1', 'turn-running');

    await expect(
      coordinator.run('session-1', kind, historyReady, operation),
    ).resolves.toEqual({
      entered: false,
      reason: 'pending_turn',
    });
    expect(operation).not.toHaveBeenCalled();
  });

  it('allows ask responses and other sessions through a pending-turn gate', async () => {
    const coordinator = new ChatTurnAdmissionCoordinator();
    coordinator.markPendingTurn('session-1', 'turn-running');

    await expect(
      coordinator.run(
        'session-1',
        'ask_response',
        historyReady,
        async () => 'answer',
      ),
    ).resolves.toEqual({
      entered: true,
      value: 'answer',
    });
    await expect(
      coordinator.run(
        'session-2',
        'message',
        historyReady,
        async () => 'other-session',
      ),
    ).resolves.toEqual({
      entered: true,
      value: 'other-session',
    });
  });

  it('only permits interjection after the setting is explicitly loaded as enabled', async () => {
    const coordinator = new ChatTurnAdmissionCoordinator();
    coordinator.markPendingTurn('session-1', 'turn-running');

    coordinator.setInterjectionPolicy({ loaded: false, allow: true });
    await expect(
      coordinator.run(
        'session-1',
        'message',
        historyReady,
        async () => 'too-early',
      ),
    ).resolves.toEqual({
      entered: false,
      reason: 'pending_turn',
    });

    coordinator.setInterjectionPolicy({ loaded: true, allow: true });
    await expect(
      coordinator.run(
        'session-1',
        'message',
        historyReady,
        async () => 'allowed',
      ),
    ).resolves.toEqual({
      entered: true,
      value: 'allowed',
    });
  });

  it('fails closed when initial history cannot be verified', async () => {
    const coordinator = new ChatTurnAdmissionCoordinator();
    const operation = vi.fn().mockResolvedValue('not-run');

    await expect(
      coordinator.run(
        'session-1',
        'message',
        async () => false,
        operation,
      ),
    ).resolves.toEqual({
      entered: false,
      reason: 'history_unavailable',
    });
    expect(operation).not.toHaveBeenCalled();
  });

  it('only clears the exact pending turn', async () => {
    const coordinator = new ChatTurnAdmissionCoordinator();
    coordinator.markPendingTurn('session-1', 'turn-new');
    coordinator.clearPendingTurn('session-1', 'turn-old');

    await expect(
      coordinator.run(
        'session-1',
        'message',
        historyReady,
        async () => 'blocked',
      ),
    ).resolves.toEqual({
      entered: false,
      reason: 'pending_turn',
    });

    coordinator.clearPendingTurn('session-1', 'turn-new');
    await expect(
      coordinator.run(
        'session-1',
        'message',
        historyReady,
        async () => 'ready',
      ),
    ).resolves.toEqual({
      entered: true,
      value: 'ready',
    });
  });

  it('lets authoritative history clear an explicitly resolved pending-turn lock', async () => {
    const coordinator = new ChatTurnAdmissionCoordinator();
    coordinator.markPendingTurn('session-1', 'turn-stale');

    await expect(
      coordinator.run(
        'session-1',
        'message',
        async (sessionId) => {
          coordinator.clearPendingTurn(sessionId);
          return true;
        },
        async () => 'ready',
      ),
    ).resolves.toEqual({
      entered: true,
      value: 'ready',
    });
  });

  it('allows a background skill during a pending ask while still checking history', async () => {
    const coordinator = new ChatTurnAdmissionCoordinator();
    coordinator.markPendingTurn('session-1', 'turn-pending');
    const ensureHistoryReady = vi.fn().mockResolvedValue(true);

    await expect(coordinator.run(
      'session-1',
      'background_skill',
      ensureHistoryReady,
      async () => 'queued',
    )).resolves.toEqual({
      entered: true,
      value: 'queued',
    });
    expect(ensureHistoryReady).toHaveBeenCalledWith('session-1');
  });

  it('waits for the active send before entering an exclusive action', async () => {
    const coordinator = new ChatTurnAdmissionCoordinator();
    let finishSend!: () => void;
    const sendFinished = new Promise<void>((resolve) => {
      finishSend = resolve;
    });
    const send = coordinator.run(
      'session-1',
      'message',
      historyReady,
      async () => {
        await sendFinished;
        return 'sent';
      },
    );
    const clearOperation = vi.fn().mockResolvedValue('cleared');
    const clear = coordinator.runExclusive(
      'session-1',
      clearOperation,
    );

    await Promise.resolve();
    expect(clearOperation).not.toHaveBeenCalled();

    finishSend();
    await expect(send).resolves.toEqual({
      entered: true,
      value: 'sent',
    });
    await expect(clear).resolves.toEqual({
      entered: true,
      value: 'cleared',
    });
    expect(clearOperation).toHaveBeenCalledTimes(1);
  });

  it('blocks new sends while an exclusive action is waiting or running', async () => {
    const coordinator = new ChatTurnAdmissionCoordinator();
    let finishSend!: () => void;
    let finishClear!: () => void;
    const sendFinished = new Promise<void>((resolve) => {
      finishSend = resolve;
    });
    const clearFinished = new Promise<void>((resolve) => {
      finishClear = resolve;
    });
    const send = coordinator.run(
      'session-1',
      'message',
      historyReady,
      () => sendFinished,
    );
    const clear = coordinator.runExclusive(
      'session-1',
      () => clearFinished,
    );

    await expect(coordinator.run(
      'session-1',
      'message',
      historyReady,
      async () => 'must-not-send',
    )).resolves.toEqual({
      entered: false,
      reason: 'exclusive_action',
    });

    finishSend();
    await send;
    await Promise.resolve();

    await expect(coordinator.run(
      'session-1',
      'message',
      historyReady,
      async () => 'must-not-send',
    )).resolves.toEqual({
      entered: false,
      reason: 'exclusive_action',
    });

    finishClear();
    await clear;
    await expect(coordinator.run(
      'session-1',
      'message',
      historyReady,
      async () => 'ready',
    )).resolves.toEqual({
      entered: true,
      value: 'ready',
    });
  });
});
