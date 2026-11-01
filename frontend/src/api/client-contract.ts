import { ApiContractError } from './config-contract';
import type { components } from './generated/client-types';
import { validateSendConfirmation, validateTurnSnapshot } from './generated/client-validators';

export type ClientWire<Name extends keyof components['schemas']> = components['schemas'][Name];

export function parseTurnSnapshot(value: unknown, sessionId: string, turnId: string): ClientWire<'TurnSnapshot'> {
  if (!validateTurnSnapshot(value) || value.session_id !== sessionId || value.turn_id !== turnId
    || (value.acceptance !== 'accepted' && (value.terminal || value.response_complete || value.state !== null))
    || (value.response_complete && !value.terminal)
    || (value.can_resubmit !== (value.acceptance === 'absent'))) {
    throw new ApiContractError('Invalid turn snapshot');
  }
  return value;
}

export function parseSendConfirmation(value: unknown, request: ClientWire<'SendConfirmationRequest'>): ClientWire<'SendConfirmation'> {
  const identity = request.kind === 'turn' ? request.turn_id : request.request_id;
  if (!validateSendConfirmation(value) || value.session_id !== request.session_id || value.identity !== identity
    || (value.safe_to_retry && value.status !== 'absent')) {
    throw new ApiContractError('Invalid send confirmation');
  }
  return value;
}
