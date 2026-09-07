import { ApiContractError } from './config-contract';
import { validateDelegateResult, validateRunEvent } from './generated/events-validators';
import type { DelegateResult, DelegationFetchResponse } from './modules/codeAgent';
import { isRecord } from '@/utils/value-guards';

export function isDelegateResult(value: unknown, delegationId: string): value is DelegateResult {
  if (!isRecord(value) || value.delegation_id !== delegationId) return false;
  // Discard stamps are added by the persisted-artifact owner after execution.
  const { discarded_at, ...execution } = value;
  return validateDelegateResult(execution) && (discarded_at === undefined
    || (typeof discarded_at === 'number' && Number.isSafeInteger(discarded_at) && discarded_at >= 0));
}

export function parseDelegationResponse(value: unknown, delegationId: string): DelegationFetchResponse {
  if (!isRecord(value)) throw new ApiContractError('Invalid delegation response');
  const { result, events_tail, diff_text } = value;
  if ((result !== null && !isDelegateResult(result, delegationId))
    || !Array.isArray(events_tail) || !events_tail.every(validateRunEvent)
    || typeof diff_text !== 'string') throw new ApiContractError('Invalid or mismatched delegation result');
  return { result, events_tail, diff_text };
}
