import { api, unwrapGatewayPayload } from '../client';

export type MemoryPortabilityOperationKind = 'backup' | 'export' | 'inspect' | 'restore';

export type MemoryPortabilityOperationStatus =
  | 'pending'
  | 'running'
  | 'succeeded'
  | 'failed';

export type MemoryRestoreInspectionState = 'password_required' | 'ready';

export type MemoryRestoreCompatibility =
  | 'compatible'
  | 'upgrade_required'
  | 'unsupported';

export type MemoryPortabilityTimestamp = string;

export interface MemoryPortabilityOperation {
  operation_id: string;
  kind: MemoryPortabilityOperationKind;
  status: MemoryPortabilityOperationStatus;
  phase: string;
  progress_percent: number;
  record_counts: Record<string, number>;
  output_path: string | null;
  file_size_bytes: number | null;
  created_at: MemoryPortabilityTimestamp;
  completed_at: MemoryPortabilityTimestamp | null;
  error_code: string | null;
  error_message: string | null;
  rollback_performed: boolean;
  safety_backup_path: string | null;
  index_rebuild_status: string | null;
  inspection: MemoryRestoreInspection | null;
}

export interface PasswordRequiredMemoryRestoreInspection {
  state: 'password_required';
  encrypted: true;
}

export interface ReadyMemoryRestoreInspection {
  state: 'ready';
  candidate_id: string;
  encrypted: boolean;
  format_version: number;
  magi_version: string;
  created_at: MemoryPortabilityTimestamp;
  scope: string[];
  record_counts: Record<string, number>;
  compatibility: MemoryRestoreCompatibility;
  warnings: string[];
  expires_at: MemoryPortabilityTimestamp;
  source_fingerprint: string;
}

export type MemoryRestoreInspection =
  | PasswordRequiredMemoryRestoreInspection
  | ReadyMemoryRestoreInspection;

export interface CreateMemoryBackupInput {
  destinationDirectory: string;
  encryption: 'password' | 'none';
  password?: string;
}

export interface CreateMemoryExportInput {
  destinationDirectory: string;
}

export interface InspectMemoryRestoreInput {
  sourcePath: string;
  password?: string;
}

export const memoryPortabilityApi = {
  async createBackup(input: CreateMemoryBackupInput): Promise<MemoryPortabilityOperation> {
    const response = await api.post<MemoryPortabilityOperation>(
      '/memory/portability/backups',
      {
        destination_directory: input.destinationDirectory,
        encryption: input.encryption,
        ...(input.password === undefined ? {} : { password: input.password }),
      },
    );
    return unwrapGatewayPayload(response);
  },

  async createExport(input: CreateMemoryExportInput): Promise<MemoryPortabilityOperation> {
    const response = await api.post<MemoryPortabilityOperation>(
      '/memory/portability/exports',
      {
        destination_directory: input.destinationDirectory,
        include_l0: true,
      },
    );
    return unwrapGatewayPayload(response);
  },

  async inspectRestore(input: InspectMemoryRestoreInput): Promise<MemoryPortabilityOperation> {
    const response = await api.post<MemoryPortabilityOperation>(
      '/memory/portability/restores/inspect',
      {
        source_path: input.sourcePath,
        ...(input.password === undefined ? {} : { password: input.password }),
      },
    );
    return unwrapGatewayPayload(response);
  },

  async confirmRestore(candidateId: string): Promise<MemoryPortabilityOperation> {
    const response = await api.post<MemoryPortabilityOperation>(
      `/memory/portability/restores/${encodeURIComponent(candidateId)}/confirm`,
      {},
    );
    return unwrapGatewayPayload(response);
  },

  async discardRestoreCandidate(candidateId: string): Promise<void> {
    await api.delete(
      `/memory/portability/restores/${encodeURIComponent(candidateId)}`,
    );
  },

  async getActiveOperation(): Promise<MemoryPortabilityOperation | null> {
    const response = await api.get<MemoryPortabilityOperation | null>(
      '/memory/portability/operations/active',
    );
    return unwrapGatewayPayload(response);
  },

  async getLatestOperation(): Promise<MemoryPortabilityOperation | null> {
    const response = await api.get<MemoryPortabilityOperation | null>(
      '/memory/portability/operations/latest',
    );
    return unwrapGatewayPayload(response);
  },

  async getOperation(operationId: string): Promise<MemoryPortabilityOperation> {
    const response = await api.get<MemoryPortabilityOperation>(
      `/memory/portability/operations/${encodeURIComponent(operationId)}`,
    );
    return unwrapGatewayPayload(response);
  },
};
