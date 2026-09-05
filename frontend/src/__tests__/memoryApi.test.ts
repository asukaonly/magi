import { afterEach, describe, expect, expectTypeOf, it, vi } from 'vitest';

import { api } from '@/api/client';
import {
  memoryApi,
  type MemoryCorrectionContextDimension,
  type MemoryCorrectionRecord,
  type MemoryCorrectionRequest,
} from '@/api/modules/memory';

const MAGI_CONTEXT_ID = `ctx_project_${'a'.repeat(64)}`;

describe('memoryApi endpoints', () => {
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
        before: { trait_value: '直白' },
        replacement: { value: '直白' },
        scope: { all_of: [{ dimension: 'project', context_id: MAGI_CONTEXT_ID }] },
        created_at: 1719301300,
        state: 'active' as const,
      },
      current_claim: { trait_value: '直白' },
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
        before: { trait_value: '直白' },
        created_at: 1719301300,
        state: 'reverted' as const,
      },
      current_claim: { trait_value: '直白' },
      derivation_state: 'completed' as const,
      created: false,
    };
    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({
      success: true,
      message: 'ok',
      data: response,
    });

    await expect(memoryApi.revertCorrection('correction/with space', 'revert-1')).resolves.toEqual(response);

    expect(postSpy).toHaveBeenCalledWith(
      '/memory/l2/corrections/correction%2Fwith%20space/revert',
      { request_id: 'revert-1' }
    );
  });
});
