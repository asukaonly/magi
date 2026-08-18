import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type {
  MemoryPortabilityOperation,
  ReadyMemoryRestoreInspection,
} from '@/api/modules/memoryPortability';
import { MemoryDataManagementSection } from '@/components/settings/memory-data/MemoryDataManagementSection';

const {
  createBackupMock,
  createExportMock,
  inspectRestoreMock,
  confirmRestoreMock,
  discardRestoreCandidateMock,
  getActiveOperationMock,
  getOperationMock,
  pickDirectoryMock,
  pickMemoryBackupFileMock,
  translateMock,
} = vi.hoisted(() => ({
  createBackupMock: vi.fn(),
  createExportMock: vi.fn(),
  inspectRestoreMock: vi.fn(),
  confirmRestoreMock: vi.fn(),
  discardRestoreCandidateMock: vi.fn(),
  getActiveOperationMock: vi.fn(),
  getOperationMock: vi.fn(),
  pickDirectoryMock: vi.fn(),
  pickMemoryBackupFileMock: vi.fn(),
  translateMock: (key: string, params?: Record<string, unknown>) => {
    if (!params) {
      return key;
    }
    return Object.entries(params).reduce(
      (value, [name, replacement]) => value.replace(`{{${name}}}`, String(replacement)),
      key,
    );
  },
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: translateMock,
    i18n: { language: 'en' },
  }),
}));

vi.mock('@/api/modules/memoryPortability', () => ({
  memoryPortabilityApi: {
    createBackup: createBackupMock,
    createExport: createExportMock,
    inspectRestore: inspectRestoreMock,
    confirmRestore: confirmRestoreMock,
    discardRestoreCandidate: discardRestoreCandidateMock,
    getActiveOperation: getActiveOperationMock,
    getOperation: getOperationMock,
  },
}));

vi.mock('@/runtime/desktop', () => ({
  pickDirectory: pickDirectoryMock,
  pickMemoryBackupFile: pickMemoryBackupFileMock,
}));

function createOperation(
  overrides: Partial<MemoryPortabilityOperation> = {},
): MemoryPortabilityOperation {
  return {
    operation_id: 'operation-1',
    kind: 'backup',
    status: 'pending',
    phase: 'queued',
    progress_percent: 0,
    record_counts: {},
    output_path: null,
    file_size_bytes: null,
    created_at: '2026-08-18T09:00:00Z',
    completed_at: null,
    error_code: null,
    error_message: null,
    rollback_performed: false,
    safety_backup_path: null,
    index_rebuild_status: null,
    ...overrides,
  };
}

const readyInspection: ReadyMemoryRestoreInspection = {
  state: 'ready',
  candidate_id: 'candidate-1',
  encrypted: true,
  format_version: 1,
  magi_version: '0.1.26',
  created_at: '2026-08-18T08:00:00Z',
  scope: ['l1', 'l2', 'manual_entry_assets'],
  record_counts: {
    l1_events: 12,
    l2_entities: 3,
    manual_entry_assets: 2,
  },
  compatibility: 'compatible',
  warnings: ['restore_replaces_current_memory'],
  expires_at: '2026-08-18T08:30:00Z',
  source_fingerprint: 'a'.repeat(64),
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

describe('MemoryDataManagementSection', () => {
  beforeEach(() => {
    createBackupMock.mockReset();
    createExportMock.mockReset();
    inspectRestoreMock.mockReset();
    confirmRestoreMock.mockReset();
    discardRestoreCandidateMock.mockReset();
    getActiveOperationMock.mockReset();
    getOperationMock.mockReset();
    pickDirectoryMock.mockReset();
    pickMemoryBackupFileMock.mockReset();

    getActiveOperationMock.mockResolvedValue(null);
    discardRestoreCandidateMock.mockResolvedValue(undefined);
    pickDirectoryMock.mockResolvedValue(undefined);
    pickMemoryBackupFileMock.mockResolvedValue(undefined);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('defaults to password protection and clears both password fields as soon as backup starts', async () => {
    const user = userEvent.setup();
    const request = deferred<MemoryPortabilityOperation>();
    pickDirectoryMock.mockResolvedValue('/Users/example/very private backups');
    createBackupMock.mockReturnValue(request.promise);
    render(<MemoryDataManagementSection />);

    await user.click(screen.getByRole('button', {
      name: 'settings.memory.dataManagement.backup.action',
    }));
    expect(screen.getByRole('switch', {
      name: 'settings.memory.dataManagement.backup.passwordProtection',
    })).toBeChecked();

    await user.click(screen.getByRole('button', {
      name: 'settings.memory.dataManagement.common.chooseDirectory',
    }));
    expect(screen.getByText('/Users/example/very private backups')).toHaveClass('break-all');

    const password = screen.getByLabelText('settings.memory.dataManagement.backup.password');
    const confirmation = screen.getByLabelText('settings.memory.dataManagement.backup.confirmPassword');
    await user.type(password, 'secret backup password');
    await user.type(confirmation, 'secret backup password');
    await user.click(screen.getByRole('button', {
      name: 'settings.memory.dataManagement.backup.start',
    }));

    expect(createBackupMock).toHaveBeenCalledWith({
      destinationDirectory: '/Users/example/very private backups',
      encryption: 'password',
      password: 'secret backup password',
    });
    expect(password).toHaveValue('');
    expect(confirmation).toHaveValue('');

    request.resolve(createOperation());
    await waitFor(() => {
      expect(screen.getByRole('progressbar', {
        name: 'settings.memory.dataManagement.operation.progressLabel',
      })).toBeInTheDocument();
    });
    expect(screen.getByRole('button', {
      name: 'settings.memory.dataManagement.restore.action',
    })).toBeDisabled();
  });

  it('requires a second explicit confirmation before creating an unencrypted backup', async () => {
    const user = userEvent.setup();
    pickDirectoryMock.mockResolvedValue('/tmp/plain backup');
    createBackupMock.mockResolvedValue(createOperation());
    render(<MemoryDataManagementSection />);

    await user.click(screen.getByRole('button', {
      name: 'settings.memory.dataManagement.backup.action',
    }));
    await user.click(screen.getByRole('button', {
      name: 'settings.memory.dataManagement.common.chooseDirectory',
    }));
    await user.click(screen.getByRole('switch', {
      name: 'settings.memory.dataManagement.backup.passwordProtection',
    }));
    await user.click(screen.getByRole('button', {
      name: 'settings.memory.dataManagement.backup.start',
    }));

    expect(createBackupMock).not.toHaveBeenCalled();
    expect(screen.getByRole('alert')).toHaveTextContent(
      'settings.memory.dataManagement.backup.errors.plaintextConfirmationRequired',
    );

    await user.click(screen.getByText(
      'settings.memory.dataManagement.backup.plaintextConfirmation',
    ));
    await user.click(screen.getByRole('button', {
      name: 'settings.memory.dataManagement.backup.start',
    }));

    expect(createBackupMock).toHaveBeenCalledWith({
      destinationDirectory: '/tmp/plain backup',
      encryption: 'none',
      password: undefined,
    });
  });

  it('requires a privacy acknowledgement before starting a readable export', async () => {
    const user = userEvent.setup();
    pickDirectoryMock.mockResolvedValue('/tmp/readable export');
    createExportMock.mockResolvedValue(createOperation({ kind: 'export' }));
    render(<MemoryDataManagementSection />);

    await user.click(screen.getByRole('button', {
      name: 'settings.memory.dataManagement.export.action',
    }));
    await user.click(screen.getByRole('button', {
      name: 'settings.memory.dataManagement.common.chooseDirectory',
    }));
    await user.click(screen.getByRole('button', {
      name: 'settings.memory.dataManagement.export.start',
    }));

    expect(createExportMock).not.toHaveBeenCalled();
    await user.click(screen.getByText(
      'settings.memory.dataManagement.export.readabilityConfirmation',
    ));
    await user.click(screen.getByRole('button', {
      name: 'settings.memory.dataManagement.export.start',
    }));

    expect(createExportMock).toHaveBeenCalledWith({
      destinationDirectory: '/tmp/readable export',
    });
  });

  it('moves from password-required inspection to review and confirms only the candidate id', async () => {
    const user = userEvent.setup();
    const unlockedInspection = deferred<ReadyMemoryRestoreInspection>();
    const restoreOperation = createOperation({ kind: 'restore', operation_id: 'restore-1' });
    pickMemoryBackupFileMock.mockResolvedValue('/tmp/a very long/private.magibackup');
    inspectRestoreMock
      .mockResolvedValueOnce({ state: 'password_required', encrypted: true })
      .mockReturnValueOnce(unlockedInspection.promise);
    confirmRestoreMock.mockResolvedValue(restoreOperation);
    render(<MemoryDataManagementSection />);

    await user.click(screen.getByRole('button', {
      name: 'settings.memory.dataManagement.restore.action',
    }));
    expect(pickMemoryBackupFileMock).toHaveBeenCalledWith(
      'settings.memory.dataManagement.restore.fileFilter',
    );
    expect(await screen.findByText(
      'settings.memory.dataManagement.restore.passwordRequiredTitle',
    )).toBeInTheDocument();
    expect(screen.getByText('/tmp/a very long/private.magibackup')).toHaveClass('break-all');

    const password = screen.getByLabelText('settings.memory.dataManagement.restore.password');
    await user.type(password, 'restore secret');
    await user.click(screen.getByRole('button', {
      name: 'settings.memory.dataManagement.restore.unlockAndInspect',
    }));
    expect(password).toHaveValue('');
    expect(inspectRestoreMock).toHaveBeenNthCalledWith(2, {
      sourcePath: '/tmp/a very long/private.magibackup',
      password: 'restore secret',
    });

    unlockedInspection.resolve(readyInspection);
    expect(await screen.findByText(
      'settings.memory.dataManagement.restore.recordCountsTitle',
    )).toBeInTheDocument();
    const confirmButton = screen.getByRole('button', {
      name: 'settings.memory.dataManagement.restore.confirmReplace',
    });
    expect(confirmButton).toBeDisabled();

    await user.click(screen.getByText(
      'settings.memory.dataManagement.restore.replaceConfirmation',
    ));
    expect(confirmButton).toBeEnabled();
    await user.click(confirmButton);

    expect(confirmRestoreMock).toHaveBeenCalledWith('candidate-1');
    await waitFor(() => expect(discardRestoreCandidateMock).not.toHaveBeenCalled());
    expect(screen.getByRole('progressbar')).toBeInTheDocument();
  });

  it('keeps polling across a transient backend restart and reports restore completion once', async () => {
    vi.useFakeTimers();
    const onRestoreCompleted = vi.fn();
    const running = createOperation({
      operation_id: 'restore-running',
      kind: 'restore',
      status: 'running',
      phase: 'restarting',
      progress_percent: 75,
    });
    const succeeded = createOperation({
      ...running,
      status: 'succeeded',
      phase: 'complete',
      progress_percent: 100,
      completed_at: '2026-08-18T09:02:00Z',
    });
    getActiveOperationMock.mockResolvedValue(running);
    getOperationMock
      .mockRejectedValueOnce({
        message: 'Backend restarting',
        code: 'BACKEND_NOT_READY',
        kind: 'backend-not-ready',
      })
      .mockResolvedValueOnce(succeeded);

    render(<MemoryDataManagementSection onRestoreCompleted={onRestoreCompleted} />);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '75');

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1_500);
    });
    expect(screen.getByText(
      'settings.memory.dataManagement.operation.reconnecting',
    )).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1_500);
    });
    expect(screen.getByText(
      'settings.memory.dataManagement.operation.status.succeeded',
    )).toBeInTheDocument();
    expect(onRestoreCompleted).toHaveBeenCalledTimes(1);
    expect(getOperationMock).toHaveBeenCalledTimes(2);
  });
});
