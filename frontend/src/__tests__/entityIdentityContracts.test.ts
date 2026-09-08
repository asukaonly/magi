import { afterEach, describe, expect, it, vi } from 'vitest';
import examples from '../../../contracts/api/frontend-identity-examples.json';
import { api } from '@/api/client';
import { entityIdentityApi, parseIdentityPreview, parseIdentityResult, type EntityChangeCommand } from '@/api/modules/entityIdentity';
import { ENTITY_TYPES } from '@/api/generated/entity-types';
import { EXTRACTABLE_ENTITY_TYPES, getEntityTypeLabel } from '@/utils/entity-types';
import { buildSelfEntityAliasSet, getEntityOverviewKey, getReadableEntityName } from '@/components/memory/l2KnowledgeModelHelpers';
import en from '@/i18n/locales/en/app.json';
import zh from '@/i18n/locales/zh-CN/app.json';

const command: EntityChangeCommand = { ...examples.preview.command, kind: 'type_correction' };
afterEach(() => vi.restoreAllMocks());

describe('entity identity response contracts', () => {
  it('reads production fixtures and checks the identity and type actually changed', () => {
    const preview = parseIdentityPreview(examples.preview, command);
    expect(parseIdentityResult(examples.result, preview).entity_id).toBe(command.entity_id);
    expect(() => parseIdentityPreview({ ...examples.preview, command: { ...command, entity_id: 'other' } }, command)).toThrow();
    expect(() => parseIdentityPreview({ ...examples.preview, entity: { ...examples.preview.entity, entity_id: 'other' } }, command)).toThrow();
    expect(() => parseIdentityResult({ ...examples.result, current_type: 'brand' }, preview)).toThrow();
    expect(() => parseIdentityResult({ ...examples.result, entity_id: 'other' }, preview)).toThrow();
    expect(() => parseIdentityResult({ ...examples.result, derivation_state: 'complete' }, preview)).toThrow();
    expect(() => parseIdentityPreview({ ...examples.preview, impact: { ...examples.preview.impact, claims: 'one' } }, command)).toThrow();
  });

  it('validates list and reject responses and sends the reviewed fingerprint with an idempotency key', async () => {
    const preview = parseIdentityPreview(examples.preview, command);
    const post = vi.spyOn(api, 'post').mockResolvedValue(examples.result as never);
    await entityIdentityApi.apply(preview, 'same-attempt');
    expect(post).toHaveBeenCalledWith('/memory/l2/entities/changes/apply', {
      command, expected_fingerprint: preview.fingerprint, request_id: 'same-attempt',
    });
    const get = vi.spyOn(api, 'get').mockResolvedValue({ total: 1, items: [{}] } as never);
    await expect(entityIdentityApi.reviews()).rejects.toThrow();
    get.mockResolvedValue({ total: 1, groups: [{ name: '苹果', entities: [{}] }] } as never);
    await expect(entityIdentityApi.audit()).rejects.toThrow();
    post.mockResolvedValue({ review_id: 'different-review', status: 'rejected' } as never);
    await expect(entityIdentityApi.reject({ review_id: 'review', version: 1, entity: examples.preview.entity, proposed_type: 'food', evidence_event_ids: [] })).rejects.toThrow();
  });
});

describe('one entity type registry and explicit self identity', () => {
  it('keeps prompt order, labels and every extractable option aligned', () => {
    expect(Object.keys(zh.memory.entityTypes)).toEqual(ENTITY_TYPES.map((item) => item.key));
    for (const item of ENTITY_TYPES) {
      expect(zh.memory.entityTypes[item.key]).toBe(item.label_zh);
      expect(en.memory.entityTypes[item.key]).toBe(item.label_en);
    }
    expect(EXTRACTABLE_ENTITY_TYPES.map((item) => item.key)).not.toContain('weather_state');
    expect(getEntityTypeLabel('service', (key) => key)).toBe('memory.entityTypes.service');
    expect(getEntityTypeLabel('brand', (key) => key)).toBe('memory.entityTypes.brand');
  });

  it('does not turn namesakes or matching ID suffixes into the user', () => {
    const ids = buildSelfEntityAliasSet('person:owner', []);
    const namesake = { entity_id: 'person:someone', canonical_name: 'local user', entity_type: 'person', aliases: ['owner', 'user:self'] };
    expect(getReadableEntityName((key) => key, namesake.entity_id, namesake, ids)).toBe('local user');
    expect(getEntityOverviewKey('other:owner', undefined, ids)).toBe('other:owner');
    expect(getEntityOverviewKey('person:owner', undefined, ids)).toBe('user:self');
  });
});
