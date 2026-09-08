import { api, unwrapGatewayPayload } from '../client';
import { ApiContractError } from '../config-contract';
import type { components } from '../generated/identity-types';
import {
  validateEntityChangePreview, validateEntityChangeResult, validateEntityIdentityAudit,
  validateEntityTypeReviewList, validateEntityReviewRejectResult,
} from '../generated/identity-validators';

export type IdentityWire<Name extends keyof components['schemas']> = components['schemas'][Name];
export type IdentityEntity = IdentityWire<'IdentityEntity'>;
export type EntityChangeCommand = IdentityWire<'EntityChangeCommand'>;
export type EntityTypeReview = IdentityWire<'EntityTypeReview'>;

export function parseIdentityPreview(value: unknown, command: EntityChangeCommand): IdentityWire<'EntityChangePreview'> {
  if (!validateEntityChangePreview(value)
    || Object.keys(command).some((key) => Reflect.get(value.command, key) !== Reflect.get(command, key))
    || value.entity.entity_id !== command.entity_id
    || (value.target?.entity_id ?? null) !== command.target_entity_id) {
    throw new ApiContractError('entity identity preview');
  }
  return value;
}

export function parseIdentityResult(value: unknown, preview: IdentityWire<'EntityChangePreview'>): IdentityWire<'EntityChangeResult'> {
  const expectedId = preview.target?.entity_id ?? preview.entity.entity_id;
  const expectedType = preview.command.new_type ?? preview.target?.entity_type;
  if (!validateEntityChangeResult(value) || value.kind !== preview.command.kind
    || value.entity_id !== expectedId || value.current_type !== expectedType || !value.operation_id.trim()) {
    throw new ApiContractError('entity identity result');
  }
  return value;
}

const base = '/memory/l2/entities';
export const entityIdentityApi = {
  preview: async (command: EntityChangeCommand) => parseIdentityPreview(
    unwrapGatewayPayload(await api.post<unknown>(`${base}/changes/preview`, command)), command,
  ),
  apply: async (preview: IdentityWire<'EntityChangePreview'>, requestId: string) => parseIdentityResult(
    unwrapGatewayPayload(await api.post<unknown>(`${base}/changes/apply`, {
      command: preview.command, expected_fingerprint: preview.fingerprint, request_id: requestId,
    } satisfies IdentityWire<'EntityChangeApplyRequest'>)), preview,
  ),
  reviews: async (offset = 0) => {
    const value = unwrapGatewayPayload(await api.get<unknown>(`${base}/reviews`, { params: { limit: 25, offset } }));
    if (!validateEntityTypeReviewList(value)) throw new ApiContractError('entity type reviews');
    return value;
  },
  reject: async (review: EntityTypeReview) => {
    const value = unwrapGatewayPayload(await api.post<unknown>(`${base}/reviews/${encodeURIComponent(review.review_id)}/reject`, {
      expected_version: review.version,
    }));
    if (!validateEntityReviewRejectResult(value) || value.review_id !== review.review_id) throw new ApiContractError('entity review rejection');
    return value;
  },
  audit: async (offset = 0) => {
    const value = unwrapGatewayPayload(await api.get<unknown>(`${base}/identity-audit`, { params: { limit: 25, offset } }));
    if (!validateEntityIdentityAudit(value)) throw new ApiContractError('entity identity audit');
    return value;
  },
};
