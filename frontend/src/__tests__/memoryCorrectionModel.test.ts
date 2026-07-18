import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  MEMORY_CORRECTION_VALIDATION_ERROR_CODES,
  buildMemoryCorrectionRequest,
  canRevertMemoryCorrection,
  createInitialMemoryCorrectionDraft,
  createMemoryCorrectionRequestId,
  formatMemoryCorrectionValue,
  isMemoryCorrectionScopeOccupied,
  memoryCorrectionHistoryStatus,
  memoryCorrectionLifecycleStatus,
  selectableProjectContextOptions,
  shouldExplainUnavailableMemoryCorrectionRevert,
  validateMemoryCorrectionDraft,
  type MemoryCorrectionDraft,
  type MemoryCorrectionUiTarget,
} from '@/components/memory/correction/memoryCorrectionModel';
import type { MemoryCorrectionRecord } from '@/api/modules/memory';

const MAGI_CONTEXT_ID = `ctx_project_${'a'.repeat(64)}`;
const WEBSITE_CONTEXT_ID = `ctx_project_${'b'.repeat(64)}`;
const UNKNOWN_CONTEXT_ID = `ctx_project_${'9'.repeat(64)}`;

const assertionTarget: MemoryCorrectionUiTarget = {
  kind: 'assertion',
  id: 'assertion-1',
  displaySentence: '你的常用回复风格是直白',
  editableValue: '直白',
  expectedUpdatedAt: 1719301200,
};

const structuredAssertionTarget: MemoryCorrectionUiTarget = {
  kind: 'assertion',
  id: 'assertion-structured',
  displaySentence: '你常用的称呼包括子涵、哈基米。',
  editableValue: '["子涵", "哈基米"]',
  expectedUpdatedAt: 1719301200,
};

const sentenceAssertionTarget: MemoryCorrectionUiTarget = {
  kind: 'assertion',
  id: 'assertion-sentence',
  displaySentence: '你的常住地点可能是杭州。',
  editableValue: '杭州',
  expectedUpdatedAt: 1719301200,
};

const edgeTarget: MemoryCorrectionUiTarget = {
  kind: 'edge',
  id: 'edge-1',
  displaySentence: '你使用 Magi',
  expectedUpdatedAt: 1719301300,
  relationship: {
    subjectId: 'user:self',
    subjectType: 'person',
    subjectName: '你',
    predicate: 'USES',
    predicateLabel: '使用',
    objectId: 'tool:magi',
    objectType: 'software',
    objectName: 'Magi',
  },
  entityOptions: [
    { id: 'tool:magi', name: 'Magi', type: 'software' },
    { id: 'tool:codex', name: 'Codex', type: 'software' },
  ],
};

const projectOptions = [{
  context_id: MAGI_CONTEXT_ID,
  dimension: 'project' as const,
  label: 'Magi',
}, {
  context_id: WEBSITE_CONTEXT_ID,
  dimension: 'project' as const,
  label: '个人网站',
}];

const makeDraft = (
  target: MemoryCorrectionUiTarget,
  overrides: Partial<MemoryCorrectionDraft> = {}
): MemoryCorrectionDraft => ({
  ...createInitialMemoryCorrectionDraft(target),
  requestId: 'request-1',
  ...overrides,
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('createMemoryCorrectionRequestId', () => {
  it('prefers crypto.randomUUID when available', () => {
    const randomUUID = vi.fn(() => '28f23771-caa4-4485-b5cf-49d3b8478461');
    vi.stubGlobal('crypto', { randomUUID });

    expect(createMemoryCorrectionRequestId()).toBe('28f23771-caa4-4485-b5cf-49d3b8478461');
    expect(randomUUID).toHaveBeenCalledOnce();
  });

  it('creates a non-empty fallback id when randomUUID is unavailable', () => {
    vi.stubGlobal('crypto', {});

    expect(createMemoryCorrectionRequestId()).toMatch(/^memory-correction-[a-z0-9-]+$/);
  });
});

describe('createInitialMemoryCorrectionDraft', () => {
  it('starts an assertion correction with the current value', () => {
    const draft = createInitialMemoryCorrectionDraft(assertionTarget);

    expect(draft).toMatchObject({
      correctionKind: 'record_error',
      recordErrorAction: 'replace',
      value: '直白',
      effectiveAt: '',
      scopeContextId: '',
      reason: '',
      relationObjectId: '',
    });
    expect(draft.requestId).not.toBe('');
  });

  it('starts a relationship correction with the current object selected', () => {
    const draft = createInitialMemoryCorrectionDraft(edgeTarget);

    expect(draft.value).toBe('');
    expect(draft.relationObjectId).toBe('tool:magi');
  });

  it('keeps a structured assertion value lossless while the display sentence stays separate', () => {
    const draft = createInitialMemoryCorrectionDraft(structuredAssertionTarget);

    expect(draft.value).toBe('["子涵", "哈基米"]');
  });

  it('never uses the display sentence as the editable assertion value', () => {
    const draft = createInitialMemoryCorrectionDraft(sentenceAssertionTarget);

    expect(draft.value).toBe('杭州');
  });
});

describe('formatMemoryCorrectionValue', () => {
  it('renders stored list and value-envelope assertions for people', () => {
    expect(formatMemoryCorrectionValue('["子涵", "哈基米"]')).toBe('子涵、哈基米');
    expect(formatMemoryCorrectionValue('{"value":["子涵","哈基米"]}')).toBe('子涵、哈基米');
  });
});

describe('canRevertMemoryCorrection', () => {
  const correction = (
    overrides: Partial<MemoryCorrectionRecord> = {}
  ): MemoryCorrectionRecord => ({
    correction_id: 'correction-1',
    correction_kind: 'record_error',
    before: {},
    created_at: 1,
    state: 'active',
    can_revert: true,
    ...overrides,
  });

  it('uses the server decision as the only source of revert eligibility', () => {
    expect(canRevertMemoryCorrection(correction())).toBe(true);
    expect(canRevertMemoryCorrection(correction({ can_revert: false }))).toBe(false);
    expect(canRevertMemoryCorrection(correction({ can_revert: undefined }))).toBe(false);
  });

  it('does not allow cancelled or reverted corrections to be reverted', () => {
    const cancelled = correction({
      transition_cancelled_at: 2,
    });
    const reverted = correction({
      state: 'reverted',
    });

    expect(canRevertMemoryCorrection(cancelled)).toBe(false);
    expect(canRevertMemoryCorrection(reverted)).toBe(false);
  });
});

describe('memory correction lifecycle presentation', () => {
  const base: MemoryCorrectionRecord = {
    correction_id: 'correction-1',
    correction_kind: 'situation_changed',
    before: {},
    created_at: 100,
    state: 'active',
    effective_at: 200,
  };

  it('uses the recorded transition result instead of assuming a due change is active', () => {
    expect(memoryCorrectionLifecycleStatus({
      ...base,
      transition_applied_at: null,
    }, 300)).toBe('scheduled');
    expect(memoryCorrectionLifecycleStatus({
      ...base,
      transition_applied_at: 250,
    }, 300)).toBe('active');
  });

  it('gives cancelled and reverted states precedence over scheduling', () => {
    expect(memoryCorrectionLifecycleStatus({
      ...base,
      transition_cancelled_at: 150,
      transition_applied_at: null,
    }, 300)).toBe('cancelled');
    expect(memoryCorrectionLifecycleStatus({
      ...base,
      state: 'reverted',
      transition_applied_at: null,
    }, 300)).toBe('reverted');
  });

  it('keeps a forget-affected correction in its real lifecycle state', () => {
    expect(memoryCorrectionLifecycleStatus({
      ...base,
      target_forgotten: true,
      forget_affected: true,
      transition_applied_at: 250,
    }, 300)).toBe('active');
  });

  it('does not present an applied transition as a cancelled plan after forgetting', () => {
    expect(memoryCorrectionLifecycleStatus({
      ...base,
      transition_applied_at: 220,
      transition_cancelled_at: 250,
      forget_affected: true,
      content_redacted: true,
    }, 300)).toBe('active');
  });

  it('keeps the future-time fallback for responses without transition state', () => {
    expect(memoryCorrectionLifecycleStatus(base, 150)).toBe('scheduled');
    expect(memoryCorrectionLifecycleStatus(base, 250)).toBe('active');
  });

  it('presents an active redacted record as deleted content without changing its lifecycle', () => {
    const correction = {
      ...base,
      transition_applied_at: 220,
      content_redacted: true,
    };

    expect(memoryCorrectionLifecycleStatus(correction, 300)).toBe('active');
    expect(memoryCorrectionHistoryStatus(correction, 300)).toBe('content_deleted');
    expect(memoryCorrectionHistoryStatus({
      ...base,
      transition_applied_at: null,
      content_redacted: true,
    }, 300)).toBe('content_deleted');
  });
});

describe('unavailable correction revert explanation', () => {
  const activeCorrection: MemoryCorrectionRecord = {
    correction_id: 'correction-1',
    correction_kind: 'record_error',
    before: {},
    created_at: 100,
    state: 'active',
    can_revert: false,
  };

  it('explains a server-denied active correction without inventing a reason', () => {
    expect(shouldExplainUnavailableMemoryCorrectionRevert(activeCorrection, 300)).toBe(true);
  });

  it('does not duplicate explanations for resolved or forget-affected corrections', () => {
    expect(shouldExplainUnavailableMemoryCorrectionRevert({
      ...activeCorrection,
      state: 'reverted',
    }, 300)).toBe(false);
    expect(shouldExplainUnavailableMemoryCorrectionRevert({
      ...activeCorrection,
      forget_affected: true,
    }, 300)).toBe(false);
    expect(shouldExplainUnavailableMemoryCorrectionRevert({
      ...activeCorrection,
      content_redacted: true,
    }, 300)).toBe(false);
    expect(shouldExplainUnavailableMemoryCorrectionRevert({
      ...activeCorrection,
      can_revert: true,
    }, 300)).toBe(false);
  });
});

describe('memory correction conflict classification', () => {
  it('treats assertion and relationship scope occupancy the same way', () => {
    expect(isMemoryCorrectionScopeOccupied('assertion_scope_occupied')).toBe(true);
    expect(isMemoryCorrectionScopeOccupied('relationship_scope_occupied')).toBe(true);
    expect(isMemoryCorrectionScopeOccupied('memory_forgotten')).toBe(false);
  });
});

describe('validateMemoryCorrectionDraft', () => {
  it('allows removing an incorrect assertion without a replacement', () => {
    const draft = makeDraft(assertionTarget, {
      recordErrorAction: 'remove',
      value: '',
    });

    expect(validateMemoryCorrectionDraft(assertionTarget, draft)).toEqual({
      valid: true,
      errors: {},
    });
  });

  it('requires a changed assertion value when replacing an incorrect record', () => {
    const empty = makeDraft(assertionTarget, { value: '   ' });
    const unchanged = makeDraft(assertionTarget, { value: ' 直白 ' });

    expect(validateMemoryCorrectionDraft(assertionTarget, empty).errors.value).toBe(
      MEMORY_CORRECTION_VALIDATION_ERROR_CODES.REPLACEMENT_REQUIRED
    );
    expect(validateMemoryCorrectionDraft(assertionTarget, unchanged).errors.value).toBe(
      MEMORY_CORRECTION_VALIDATION_ERROR_CODES.REPLACEMENT_UNCHANGED
    );
  });

  it('requires a changed assertion value and a valid effective time for changed situations', () => {
    const missingTime = makeDraft(assertionTarget, {
      correctionKind: 'situation_changed',
      value: '简洁',
      effectiveAt: '',
    });
    const invalidTime = makeDraft(assertionTarget, {
      correctionKind: 'situation_changed',
      value: '直白',
      effectiveAt: 'not-a-date',
    });

    expect(validateMemoryCorrectionDraft(assertionTarget, missingTime).errors.effectiveAt).toBe(
      MEMORY_CORRECTION_VALIDATION_ERROR_CODES.EFFECTIVE_AT_REQUIRED
    );
    expect(validateMemoryCorrectionDraft(assertionTarget, invalidTime).errors).toEqual({
      value: MEMORY_CORRECTION_VALIDATION_ERROR_CODES.REPLACEMENT_UNCHANGED,
      effectiveAt: MEMORY_CORRECTION_VALIDATION_ERROR_CODES.EFFECTIVE_AT_INVALID,
    });
  });

  it('allows the current assertion value for a scoped refinement but requires an available project', () => {
    const missingScope = makeDraft(assertionTarget, {
      correctionKind: 'scope_refinement',
      value: '直白',
      scopeContextId: '   ',
    });
    const unavailableScope = makeDraft(assertionTarget, {
      correctionKind: 'scope_refinement',
      value: '直白',
      scopeContextId: UNKNOWN_CONTEXT_ID,
    });
    const valid = makeDraft(assertionTarget, {
      correctionKind: 'scope_refinement',
      value: '直白',
      scopeContextId: MAGI_CONTEXT_ID,
    });

    expect(validateMemoryCorrectionDraft(assertionTarget, missingScope, projectOptions).errors.scopeContextId).toBe(
      MEMORY_CORRECTION_VALIDATION_ERROR_CODES.SCOPE_REQUIRED
    );
    expect(validateMemoryCorrectionDraft(assertionTarget, unavailableScope, projectOptions).errors.scopeContextId).toBe(
      MEMORY_CORRECTION_VALIDATION_ERROR_CODES.SCOPE_UNAVAILABLE
    );
    expect(validateMemoryCorrectionDraft(assertionTarget, valid, projectOptions)).toEqual({
      valid: true,
      errors: {},
    });
  });

  it('requires a different available relationship object when replacing the relationship', () => {
    const unchanged = makeDraft(edgeTarget);
    const missing = makeDraft(edgeTarget, { relationObjectId: '' });
    const unavailable = makeDraft(edgeTarget, { relationObjectId: 'tool:unknown' });

    expect(validateMemoryCorrectionDraft(edgeTarget, unchanged).errors.relationObjectId).toBe(
      MEMORY_CORRECTION_VALIDATION_ERROR_CODES.RELATION_OBJECT_UNCHANGED
    );
    expect(validateMemoryCorrectionDraft(edgeTarget, missing).errors.relationObjectId).toBe(
      MEMORY_CORRECTION_VALIDATION_ERROR_CODES.RELATION_OBJECT_REQUIRED
    );
    expect(validateMemoryCorrectionDraft(edgeTarget, unavailable).errors.relationObjectId).toBe(
      MEMORY_CORRECTION_VALIDATION_ERROR_CODES.RELATION_OBJECT_UNAVAILABLE
    );
  });

  it('does not require a changed relationship object for a scoped refinement', () => {
    const draft = makeDraft(edgeTarget, {
      correctionKind: 'scope_refinement',
      relationObjectId: edgeTarget.kind === 'edge' ? edgeTarget.relationship.objectId : '',
      scopeContextId: MAGI_CONTEXT_ID,
    });

    expect(validateMemoryCorrectionDraft(edgeTarget, draft, projectOptions)).toEqual({
      valid: true,
      errors: {},
    });
  });
});

describe('buildMemoryCorrectionRequest', () => {
  it('builds an assertion removal without a replacement and trims the reason', () => {
    const draft = makeDraft(assertionTarget, {
      recordErrorAction: 'remove',
      value: '',
      reason: '  这是一次误判  ',
    });

    expect(buildMemoryCorrectionRequest(assertionTarget, draft)).toEqual({
      request_id: 'request-1',
      target: { kind: 'assertion', id: 'assertion-1' },
      correction_kind: 'record_error',
      reason: '这是一次误判',
      expected_updated_at: 1719301200,
    });
  });

  it('builds an assertion replacement with a trimmed value and omits an empty reason', () => {
    const draft = makeDraft(assertionTarget, {
      value: '  简洁  ',
      reason: '   ',
    });

    expect(buildMemoryCorrectionRequest(assertionTarget, draft)).toEqual({
      request_id: 'request-1',
      target: { kind: 'assertion', id: 'assertion-1' },
      correction_kind: 'record_error',
      replacement: { value: '简洁' },
      expected_updated_at: 1719301200,
    });
  });

  it('submits only the edited value when the display sentence contains extra context', () => {
    const draft = makeDraft(sentenceAssertionTarget, {
      value: '上海',
    });

    expect(buildMemoryCorrectionRequest(sentenceAssertionTarget, draft)).toMatchObject({
      replacement: { value: '上海' },
    });
  });

  it('converts a datetime-local value into local epoch seconds for a changed assertion', () => {
    const effectiveAt = '2026-07-16T09:30';
    const draft = makeDraft(assertionTarget, {
      correctionKind: 'situation_changed',
      value: '简洁',
      effectiveAt,
    });

    expect(buildMemoryCorrectionRequest(assertionTarget, draft)).toMatchObject({
      correction_kind: 'situation_changed',
      replacement: { value: '简洁' },
      effective_at: Math.floor(new Date(effectiveAt).getTime() / 1000),
    });
  });

  it('keeps the assertion value unchanged when only its scope is refined', () => {
    const draft = makeDraft(assertionTarget, {
      correctionKind: 'scope_refinement',
      value: '不应被带入请求',
      scopeContextId: MAGI_CONTEXT_ID,
    });

    expect(buildMemoryCorrectionRequest(assertionTarget, draft, draft.requestId, projectOptions)).toMatchObject({
      correction_kind: 'scope_refinement',
      replacement: { value: '直白' },
      scope: { all_of: [{ dimension: 'project', context_id: MAGI_CONTEXT_ID }] },
    });
  });

  it('keeps the stored structured value when only its scope changes', () => {
    const draft = makeDraft(structuredAssertionTarget, {
      correctionKind: 'scope_refinement',
      value: '子涵、哈基米',
      scopeContextId: MAGI_CONTEXT_ID,
    });

    expect(buildMemoryCorrectionRequest(
      structuredAssertionTarget,
      draft,
      draft.requestId,
      projectOptions
    )).toMatchObject({
      correction_kind: 'scope_refinement',
      replacement: { value: '["子涵", "哈基米"]' },
      scope: { all_of: [{ dimension: 'project', context_id: MAGI_CONTEXT_ID }] },
    });
  });

  it('builds a relationship replacement with only the selected object identity', () => {
    const draft = makeDraft(edgeTarget, { relationObjectId: 'tool:codex' });

    expect(buildMemoryCorrectionRequest(edgeTarget, draft)).toEqual({
      request_id: 'request-1',
      target: { kind: 'edge', id: 'edge-1' },
      correction_kind: 'record_error',
      replacement: {
        object_id: 'tool:codex',
        object_type: 'software',
      },
      expected_updated_at: 1719301300,
    });
  });

  it('builds a scoped relationship replacement without requiring an object change', () => {
    const draft = makeDraft(edgeTarget, {
      correctionKind: 'scope_refinement',
      relationObjectId: 'tool:magi',
      scopeContextId: WEBSITE_CONTEXT_ID,
    });

    expect(buildMemoryCorrectionRequest(edgeTarget, draft, draft.requestId, projectOptions)).toEqual({
      request_id: 'request-1',
      target: { kind: 'edge', id: 'edge-1' },
      correction_kind: 'scope_refinement',
      replacement: {},
      scope: { all_of: [{ dimension: 'project', context_id: WEBSITE_CONTEXT_ID }] },
      expected_updated_at: 1719301300,
    });
  });

  it('returns null instead of building an invalid request', () => {
    const draft = makeDraft(assertionTarget, { value: '直白' });

    expect(buildMemoryCorrectionRequest(assertionTarget, draft)).toBeNull();
  });

  it('allows the caller to rotate the request id after the draft changes', () => {
    const draft = makeDraft(assertionTarget, { value: '简洁' });

    expect(buildMemoryCorrectionRequest(assertionTarget, draft, 'request-2')?.request_id).toBe(
      'request-2'
    );
  });
});

describe('selectableProjectContextOptions', () => {
  it('keeps only valid labeled project contexts', () => {
    expect(selectableProjectContextOptions([
      projectOptions[0],
      { ...projectOptions[0], label: 'Duplicate Magi' },
      {
        context_id: `ctx_project_${'e'.repeat(64)}`,
        dimension: 'project',
        label: '   ',
      },
      {
        context_id: `ctx_activity_${'1'.repeat(64)}`,
        dimension: 'activity',
        label: 'Code review',
      },
    ])).toEqual([projectOptions[0]]);
  });
});
