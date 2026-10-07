import type { components } from '../generated/model-download-types';
import { validateModelDownloadStatus } from '../generated/model-download-validators';
import { ApiContractError } from '../config-contract';

export type ModelDownloadStatus = components['schemas']['ModelDownloadStatus'];
export type DownloadProgress = components['schemas']['DownloadProgress'];

export function readModelDownloadStatus(value: unknown): ModelDownloadStatus {
  if (!validateModelDownloadStatus(value)) throw new ApiContractError('Model download status');
  return value;
}
