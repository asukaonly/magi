import { api, apiClient } from '../client';
import { type LifecycleWire, parseMemoryOperation } from '../lifecycle-contract';
import { ApiContractError } from '../config-contract';

export type MemoryPortabilityOperation = LifecycleWire<'MemoryPortabilityOperation'>;
export type PasswordRequiredMemoryRestoreInspection = LifecycleWire<'PasswordRequiredMemoryRestoreInspection'>;
export type ReadyMemoryRestoreInspection = LifecycleWire<'ReadyMemoryRestoreInspection'>;
export type MemoryPortabilityOperationKind = MemoryPortabilityOperation['kind'];
export type MemoryPortabilityOperationStatus = MemoryPortabilityOperation['status'];
export type MemoryRestoreInspection = NonNullable<MemoryPortabilityOperation['inspection']>;
export type MemoryRestoreInspectionState = MemoryRestoreInspection['state'];
export type MemoryRestoreCompatibility = ReadyMemoryRestoreInspection['compatibility'];
export type MemoryPortabilityTimestamp = string;

export interface CreateMemoryBackupInput {
  destinationDirectory: string;
  encryption: 'password' | 'none';
  password?: string;
}

export interface CreateMemoryExportInput {
  destinationDirectory: string;
  includeL0?: boolean;
}

export interface InspectMemoryRestoreInput {
  sourcePath: string;
  password?: string;
}

export const memoryPortabilityApi = {
  async createBackup(input: CreateMemoryBackupInput): Promise<MemoryPortabilityOperation> {
    const response = await api.post<unknown>(
      '/memory/portability/backups',
      {
        destination_directory: input.destinationDirectory,
        encryption: input.encryption,
        ...(input.password === undefined ? {} : { password: input.password }),
      },
    );
    return parseMemoryOperation(response, { kind: 'backup' });
  },

  async createExport(input: CreateMemoryExportInput): Promise<MemoryPortabilityOperation> {
    const response = await api.post<unknown>(
      '/memory/portability/exports',
      {
        destination_directory: input.destinationDirectory,
        include_l0: input.includeL0 ?? false,
      },
    );
    return parseMemoryOperation(response, { kind: 'export' });
  },

  async inspectRestore(input: InspectMemoryRestoreInput): Promise<MemoryPortabilityOperation> {
    const response = await api.post<unknown>(
      '/memory/portability/restores/inspect',
      {
        source_path: input.sourcePath,
        ...(input.password === undefined ? {} : { password: input.password }),
      },
    );
    return parseMemoryOperation(response, { kind: 'inspect' });
  },

  async confirmRestore(candidateId: string): Promise<MemoryPortabilityOperation> {
    const response = await api.post<unknown>(
      `/memory/portability/restores/${encodeURIComponent(candidateId)}/confirm`,
      {},
    );
    return parseMemoryOperation(response, { kind: 'restore' });
  },

  async discardRestoreCandidate(candidateId: string): Promise<void> {
    const response = await apiClient.delete<unknown>(
      `/memory/portability/restores/${encodeURIComponent(candidateId)}`,
    );
    if (response.status !== 204) throw new ApiContractError('Restore candidate deletion was not confirmed');
  },

  async getActiveOperation(): Promise<MemoryPortabilityOperation | null> {
    const response = await api.get<unknown>(
      '/memory/portability/operations/active',
    );
    return response === null ? null : parseMemoryOperation(response);
  },

  async getLatestOperation(): Promise<MemoryPortabilityOperation | null> {
    const response = await api.get<unknown>(
      '/memory/portability/operations/latest',
    );
    return response === null ? null : parseMemoryOperation(response);
  },

  async getOperation(operationId: string): Promise<MemoryPortabilityOperation> {
    const response = await api.get<unknown>(
      `/memory/portability/operations/${encodeURIComponent(operationId)}`,
    );
    return parseMemoryOperation(response, { operationId });
  },
};
