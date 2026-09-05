import { ApiContractError } from './config-contract';
import type { components } from './generated/lifecycle-types';
import {
  validateHistoryImportJobResponse, validateHistoryImportAppendResponse,
  validateHistoryImporterResponse, validateHistoryImportSourcePreviewResponse,
  validateMemoryPortabilityOperation, validateClearMemoryResponseModel,
  validateDeleteL1EventResponse, validateForgetEntityResponse, validateForgetEpisodeResponse,
} from './generated/lifecycle-validators';

export type LifecycleWire<Name extends keyof components['schemas']> = components['schemas'][Name];

/** Check a confirmation against the exact identity requested by the caller. */
export function parseConfirmed<T extends { success: boolean }>(
  value: unknown, validate: (value: unknown) => value is T, expected: Partial<T>,
): T {
  if (!validate(value) || value.success !== true) throw new ApiContractError('Operation was not confirmed');
  for (const key in expected) {
    if (value[key] !== expected[key]) throw new ApiContractError('Operation response identity does not match the request');
  }
  return value;
}

export function parseHistoryImportJob(value: unknown, jobId?: string): LifecycleWire<'HistoryImportJobResponse'> {
  if (!validateHistoryImportJobResponse(value) || !value.job_id.trim() || (jobId !== undefined && value.job_id !== jobId)) {
    throw new ApiContractError('Invalid history import job response');
  }
  return value;
}

export function parseHistoryImportAppend(value: unknown, jobId: string): LifecycleWire<'HistoryImportAppendResponse'> {
  if (!validateHistoryImportAppendResponse(value)) throw new ApiContractError('Invalid history import append response');
  parseHistoryImportJob(value.job, jobId);
  return value;
}

export function parseHistoryImporters(value: unknown): LifecycleWire<'HistoryImporterResponse'>[] {
  if (!Array.isArray(value) || !value.every(validateHistoryImporterResponse)) throw new ApiContractError('Invalid history importer list');
  return value;
}

export function parseHistoryImportList(value: unknown): LifecycleWire<'HistoryImportJobResponse'>[] {
  if (!Array.isArray(value)) throw new ApiContractError('Invalid history import list');
  return value.map((job: unknown) => parseHistoryImportJob(job));
}

export function parseHistorySourcePreview(value: unknown, sourceId: string): LifecycleWire<'HistoryImportSourcePreviewResponse'> {
  if (!validateHistoryImportSourcePreviewResponse(value) || value.source_id !== sourceId) throw new ApiContractError('Invalid history source preview');
  return value;
}

export function parseMemoryOperation(
  value: unknown, expected?: { operationId?: string; kind?: LifecycleWire<'MemoryPortabilityOperation'>['kind'] },
): LifecycleWire<'MemoryPortabilityOperation'> {
  if (!validateMemoryPortabilityOperation(value) || !value.operation_id.trim()
    || (expected?.operationId !== undefined && value.operation_id !== expected.operationId)
    || (expected?.kind !== undefined && value.kind !== expected.kind)) {
    throw new ApiContractError('Invalid memory portability operation');
  }
  if (value.status === 'succeeded') {
    if ((value.kind === 'backup' || value.kind === 'export') && (!value.output_path?.trim() || value.file_size_bytes === null)) {
      throw new ApiContractError('Completed memory output is missing its file');
    }
    if (value.kind === 'inspect' && value.inspection === null) throw new ApiContractError('Completed inspection is missing its result');
  }
  return value;
}

export function parseClearMemory(value: unknown): LifecycleWire<'ClearMemoryResponseModel'> {
  const result = parseConfirmed(value, validateClearMemoryResponseModel, {});
  if (Object.values(result.results).some((area) => !area.cleared)) throw new ApiContractError('Memory clear did not confirm every area');
  return result;
}

export function parseDeletedEvent(value: unknown, eventId: string): LifecycleWire<'DeleteL1EventResponse'> {
  if (!validateDeleteL1EventResponse(value) || !value.deleted || value.event_id !== eventId) throw new ApiContractError('Event deletion was not confirmed');
  return value;
}

export function parseForgottenEntity(value: unknown): LifecycleWire<'ForgetEntityResponse'> {
  if (!validateForgetEntityResponse(value)) throw new ApiContractError('Invalid entity deletion result');
  return value;
}

export function parseForgottenEpisode(value: unknown, episodeId: string): LifecycleWire<'ForgetEpisodeResponse'> {
  if (!validateForgetEpisodeResponse(value) || value.episode_id !== episodeId) throw new ApiContractError('Invalid episode deletion result');
  return value;
}
