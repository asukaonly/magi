import { afterEach, describe, expect, expectTypeOf, it, vi } from 'vitest';

import { api } from '@/api/client';
import { memoryPortraitSelfApi } from '@/api/modules/memoryPortraitSelf';
import {
  memoryApi,
  type MemoryCorrectionContextDimension,
  type MemoryCorrectionRecord,
  type MemoryCorrectionRequest,
} from '@/api/modules/memory';

const MAGI_CONTEXT_ID = `ctx_project_${'a'.repeat(64)}`;

describe('memoryApi endpoints', () => {
  it('rejects experience snapshots without a valid annotation version', async () => {
    const get = vi.spyOn(api, 'get');
    for (const annotation_revision of [undefined, 'invalid', 123]) {
      get.mockResolvedValue({ success: true, message: 'ok', data: { experience_id: 'exp-1', annotation_revision } });
      await expect(memoryApi.getExperience('exp-1')).rejects.toThrow();
    }
    get.mockResolvedValue({ success: true, message: 'ok', data: { experience_id: 'other', annotation_revision: 'a'.repeat(64) } });
    await expect(memoryApi.getExperience('exp-1')).rejects.toThrow();
  });

  it('sends the captured annotation revision with a cover and uses its receipt', async () => {
    const saved = { experience_id: 'exp-1', annotation_revision: 'b'.repeat(64) };
    const post = vi.spyOn(api, 'post').mockResolvedValue({ success: true, message: 'ok', data: saved });
    const get = vi.spyOn(api, 'get');
    await expect(memoryApi.uploadExperienceCover('exp-1', new File(['image'], 'cover.png'), 'a'.repeat(64))).resolves.toEqual(saved);
    expect((post.mock.calls[0][1] as FormData).get('expected_revision')).toBe('a'.repeat(64));
    expect(get).not.toHaveBeenCalled();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('allows only project scopes in writes while retaining all stored dimensions', () => {
    type WritableScope = NonNullable<MemoryCorrectionRequest['scope']>;
    type StoredScope = NonNullable<MemoryCorrectionRecord['scope']>;

    expectTypeOf<WritableScope['all_of'][number]['dimension']>().toEqualTypeOf<'project'>();
    expectTypeOf<StoredScope['all_of'][number]['dimension']>()
      .toEqualTypeOf<MemoryCorrectionContextDimension>();
  });

  it('loads an episode detail by id', async () => {
    const getSpy = vi.spyOn(api, 'get').mockResolvedValue({
      success: true,
      message: 'ok',
      data: { episode_id: 'ep-1', events: [], inferred: [] },
    });

    await memoryApi.getEpisode('ep-1');

    expect(getSpy).toHaveBeenCalledWith('/memory/l2/episodes/ep-1');
  });

  it('creates an experience seed from selected episodes', async () => {
    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({
      success: true,
      message: 'ok',
      data: { seed_id: 'seed-1', promoted_experience_id: 'exp-1' },
    });

    await memoryApi.createExperienceSeed({
      episode_ids: ['ep-1', 'ep-2'],
      title_hint: 'Japan planning',
      promote_now: true,
    });

    expect(postSpy).toHaveBeenCalledWith('/memory/l2/experience-seeds', {
      episode_ids: ['ep-1', 'ep-2'],
      event_ids: [],
      title_hint: 'Japan planning',
      promote_now: true,
    });
  });

  it('loads the memory dashboard read model', async () => {
    const getSpy = vi.spyOn(api, 'get').mockResolvedValue({
      success: true,
      message: 'ok',
      data: {
        statistics: {
          l0: { active_sessions: 0, total_attention_items: 0 },
          l1: { event_count: 0 },
          l2: { relation_count: 0, assertion_count: 0 },
          l3: { summary_count: 0 },
          l4: { skill_count: 0, open_circuit_breakers: 0 },
          attention: { pending_assertions: 0, open_circuit_breakers: 0 },
        },
        source_counts: [],
        attention: { pending_assertions: 0, open_circuit_breakers: 0 },
        pending_assertions: { items: [], total: 0, limit: 8, offset: 0 },
      },
    });

    await memoryApi.getDashboard({ pending_limit: 8 });

    expect(getSpy).toHaveBeenCalledWith('/memory/dashboard', { params: { pending_limit: 8 } });
  });

  it('posts a governed correction without reshaping its concurrency fields', async () => {
    const payload = {
      request_id: 'request-1',
      target: { kind: 'assertion' as const, id: 'assertion-1' },
      correction_kind: 'scope_refinement' as const,
      replacement: { value: '直白' },
      scope: { all_of: [{ dimension: 'project' as const, context_id: MAGI_CONTEXT_ID }] },
      expected_updated_at: 1719301200,
    };
    const response = {
      correction: {
        correction_id: 'correction-1',
        request_id: 'request-1',
        actor_id: 'user:self',
        target_kind: 'assertion' as const,
        target_id: 'assertion-1',
        slot_key: 'slot-1',
        claim_fingerprint: 'claim-1',
        correction_kind: 'scope_refinement' as const,
        before: { trait_value: '直白', display_text: '用户偏好直白的回答。', display_status: 'complete' as const },
        replacement: { value: '直白', display_text: '用户偏好直白的回答。', display_status: 'complete' as const },
        scope: { all_of: [{ dimension: 'project', context_id: MAGI_CONTEXT_ID }] },
        created_at: 1719301300,
        state: 'active' as const,
      },
      current_claim: { trait_value: '直白', display_text: '用户偏好直白的回答。', display_status: 'complete' as const },
      derivation_state: 'completed' as const,
      created: true,
    };
    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({
      success: true,
      message: 'ok',
      data: response,
    });

    await expect(memoryApi.applyCorrection(payload)).resolves.toEqual(response);

    expect(postSpy).toHaveBeenCalledWith('/memory/l2/corrections', payload);
  });

  it('loads correction history with both target coordinates', async () => {
    const response = {
      target: { kind: 'edge' as const, id: 'edge-1' },
      versions: [],
      corrections: [],
      context_labels: {},
    };
    const getSpy = vi.spyOn(api, 'get').mockResolvedValue({
      success: true,
      message: 'ok',
      data: response,
    });

    await expect(memoryApi.getCorrectionHistory('edge', 'edge-1')).resolves.toEqual(response);

    expect(getSpy).toHaveBeenCalledWith('/memory/l2/corrections', {
      params: { target_kind: 'edge', target_id: 'edge-1' },
    });
  });

  it('loads workspace-bound project options for correction scopes', async () => {
    const response = {
      items: [{
        context_id: MAGI_CONTEXT_ID,
        dimension: 'project' as const,
        label: 'Magi',
      }],
    };
    const getSpy = vi.spyOn(api, 'get').mockResolvedValue({
      success: true,
      message: 'ok',
      data: response,
    });

    await expect(memoryApi.getCorrectionContextOptions()).resolves.toEqual(response);

    expect(getSpy).toHaveBeenCalledWith('/memory/l2/context-options');
  });

  it('encodes a correction id before posting a revert request', async () => {
    const response = {
      correction: {
        correction_id: 'correction/with space',
        request_id: 'revert-1',
        actor_id: 'user:self',
        target_kind: 'assertion' as const,
        target_id: 'assertion-1',
        slot_key: 'slot-1',
        claim_fingerprint: 'claim-1',
        correction_kind: 'record_error' as const,
        before: { trait_value: '直白', display_text: '用户偏好直白的回答。', display_status: 'complete' as const },
        created_at: 1719301300,
        state: 'reverted' as const,
      },
      current_claim: { trait_value: '直白', display_text: '用户偏好直白的回答。', display_status: 'complete' as const },
      derivation_state: 'completed' as const,
      created: false,
    };
    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({
      success: true,
      message: 'ok',
      data: response,
    });

    await expect(memoryApi.revertCorrection('correction/with space', 'revert-1', 'assertion')).resolves.toEqual(response);

    expect(postSpy).toHaveBeenCalledWith(
      '/memory/l2/corrections/correction%2Fwith%20space/revert',
      { request_id: 'revert-1' }
    );
  });
});


describe('memory fact display response boundaries', () => {
  afterEach(() => vi.restoreAllMocks());

  const response = (data: unknown) => ({ success: true, message: 'ok', data });

  const fact = {
    assertion_id: 'assert-strawberry',
    entity_id: 'user:self',
    trait_name: 'preference.affinity',
    trait_value: 'like',
    target_entity_id: 'entity-strawberry',
    display_text: '用户喜欢草莓。', display_status: 'complete' as const,
    natural_summary: '用户喜欢草莓。',
    entity_name: '用户',
    target_entity_name: '草莓',
    value_options: ['like', 'dislike'],
  };

  const invalidFields = [
    { display_text: undefined },
    { display_text: '' },
    { display_text: '   ' },
    { display_status: undefined },
    { display_status: 'tentative' },
    { display_text: undefined, display_status: undefined },
    { display_text: { value: 'like' } },
    { natural_summary: ['用户喜欢草莓。'] },
    { entity_name: 42 },
    { target_entity_name: { entity_id: 'entity-strawberry' } },
    { value_options: 'like' },
    { value_options: ['like', 42] },
  ];

  it.each(invalidFields)('rejects malformed display fields in assertion lists: %j', async (invalid) => {
    vi.spyOn(api, 'get').mockResolvedValue(response({ items: [{ ...fact, ...invalid }], total: 1, limit: 10, offset: 0 }));
    await expect(memoryApi.getL2Assertions()).rejects.toThrow();
  });

  it.each(invalidFields)('rejects malformed display fields in dashboard assertions: %j', async (invalid) => {
    vi.spyOn(api, 'get').mockResolvedValue(response({ pending_assertions: { items: [{ ...fact, ...invalid }] } }));
    await expect(memoryApi.getDashboard()).rejects.toThrow();
  });

  it.each(invalidFields)('rejects malformed display fields in pending proposals: %j', async (invalid) => {
    vi.spyOn(api, 'get').mockResolvedValue(response({ items: [{ review_id: 'review-strawberry', proposed: { ...fact, ...invalid } }], total: 1 }));
    await expect(memoryApi.listPendingReviews()).rejects.toThrow();
  });

  it.each(invalidFields)('rejects malformed display fields after confirmation: %j', async (invalid) => {
    vi.spyOn(api, 'patch').mockResolvedValue(response({ ...fact, ...invalid }));
    await expect(memoryApi.submitAssertionFeedback('assert-strawberry', 'confirmed')).rejects.toThrow();
  });

  it.each(invalidFields)('rejects incomplete fact contracts in search results: %j', async (invalid) => {
    vi.spyOn(api, 'post').mockResolvedValue(response({ l2_assertions: [{ ...fact, ...invalid }] }));
    await expect(memoryApi.search('草莓')).rejects.toThrow();
  });

  it('retains complete facts and their independent semantic correction values', async () => {
    const list = { items: [fact], total: 1, limit: 10, offset: 0 };
    vi.spyOn(api, 'get').mockResolvedValue({ success: true, message: 'ok', data: list });
    const result = await memoryApi.getL2Assertions();
    expect(result).toEqual(list);
    expect(result.items[0].trait_value).toBe('like');
    expect(result.items[0].display_text).toBe('用户喜欢草莓。');
    expect(result.items[0].target_entity_name).toBe('草莓');
    expect(result.items[0].value_options).toEqual(['like', 'dislike']);
  });

  it.each([
    ['partial', '用户喜欢尚未解析的对象。'],
    ['unavailable', '完整事实暂不可用'],
  ] as const)('preserves explicit %s host presentation without filling missing names or summaries', async (display_status, display_text) => {
    const unresolved = { ...fact, display_text, display_status, entity_name: null, target_entity_name: null, natural_summary: null, value_options: null };
    vi.spyOn(api, 'patch').mockResolvedValue(response(unresolved));
    expect(await memoryApi.submitAssertionFeedback('assert-strawberry', 'confirmed')).toEqual(unresolved);
  });

  it('rejects malformed conflict comparison display fields', async () => {
    vi.spyOn(api, 'patch').mockResolvedValue(response({ ...fact, conflict_context: { previous_display_text: 42 } }));
    await expect(memoryApi.submitAssertionFeedback('assert-strawberry', 'confirmed')).rejects.toThrow();
  });
});


describe('correction and portrait display response boundaries', () => {
  afterEach(() => vi.restoreAllMocks());
  const response = (data: unknown) => ({ success: true, message: 'ok', data });
  const request: MemoryCorrectionRequest = {
    request_id: 'correct-strawberry', target: { kind: 'assertion', id: 'strawberry' },
    correction_kind: 'record_error', replacement: { value: 'dislike' },
  };

  it.each([
    { current_claim: { display_text: 42 } },
    { correction: { before: { display_text: ['用户喜欢草莓。'] } } },
    { correction: { replacement: { value_options: 'like' } } },
  ])('rejects invalid comparison text or semantic choices in command responses: %j', async (invalid) => {
    vi.spyOn(api, 'post').mockResolvedValue(response({ correction: {}, ...invalid }));
    await expect(memoryApi.applyCorrection(request)).rejects.toThrow();
    await expect(memoryApi.revertCorrection('correction-1', 'revert-1', 'assertion')).rejects.toThrow();
  });

  it.each([
    { versions: [{ display_text: false }] },
    { corrections: [{ before: { target_entity_name: [] } }] },
    { corrections: [{ replacement: { value_options: ['like', {}] } }] },
  ])('rejects invalid presentation fields in correction history: %j', async (invalid) => {
    vi.spyOn(api, 'get').mockResolvedValue(response({ versions: [], corrections: [], ...invalid }));
    await expect(memoryApi.getCorrectionHistory('assertion', 'strawberry')).rejects.toThrow();
  });

  it('preserves host correction text, semantic values, and options independently', async () => {
    const payload = {
      correction: {
        before: { trait_value: 'like', display_text: '用户喜欢草莓。', display_status: 'complete' as const },
        replacement: { value: 'dislike', display_text: '用户不喜欢草莓。', display_status: 'complete' as const, value_options: ['like', 'dislike'] },
      },
      current_claim: { trait_value: 'dislike', display_text: '用户不喜欢草莓。', display_status: 'complete' as const, value_options: ['like', 'dislike'] },
    };
    vi.spyOn(api, 'post').mockResolvedValue(response(payload));
    expect(await memoryApi.applyCorrection(request)).toEqual(payload);
  });

  it.each(['world', 'review', 'recent'] as const)('validates portrait correction fields in %s items', async (group) => {
    const view = { world: { groups: [] as Array<{ items: unknown[] }> }, review: { items: [] as unknown[] }, recent: { items: [] as unknown[] } };
    const item = { assertion_id: 'assert-strawberry', display_status: 'complete', correction_value: 'like', correction_trait_name: 'preference.affinity', correction_value_options: { 0: 'like' } };
    if (group === 'world') view.world.groups.push({ items: [item] });
    else view[group].items.push(item);
    vi.spyOn(api, 'get').mockResolvedValue(response({ self_view: view }));
    await expect(memoryPortraitSelfApi.get('local_user')).rejects.toThrow();
  });

  it('preserves portrait natural text separately from nullable correction metadata', async () => {
    const item = { assertion_id: 'assert-strawberry', display_status: 'complete', text: '用户喜欢草莓。', correction_value: 'like', correction_trait_name: 'preference.affinity', correction_value_options: ['like', 'dislike'] };
    const payload = { self_view: { world: { groups: [{ items: [item] }] }, review: { items: [] }, recent: { items: [] } } };
    vi.spyOn(api, 'get').mockResolvedValue(response(payload));
    expect(await memoryPortraitSelfApi.get('local_user')).toEqual(payload);
  });

  it.each([
    { display_status: undefined },
    { display_status: 'tentative' },
    { correction_value: undefined },
    { correction_trait_name: '' },
    { correction_value_options: undefined },
  ])('rejects assertion-backed portrait items with incomplete display metadata: %j', async (invalid) => {
    const item = {
      assertion_id: 'assert-strawberry', display_status: 'complete', text: '用户喜欢草莓。',
      correction_value: 'like', correction_trait_name: 'preference.affinity', correction_value_options: ['like', 'dislike'],
      ...invalid,
    };
    const payload = { self_view: { world: { groups: [{ items: [item] }] }, review: { items: [] }, recent: { items: [] } } };
    vi.spyOn(api, 'get').mockResolvedValue(response(payload));
    await expect(memoryPortraitSelfApi.get('local_user')).rejects.toThrow();
  });
});
