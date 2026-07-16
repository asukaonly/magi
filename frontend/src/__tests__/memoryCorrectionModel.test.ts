import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  MEMORY_CORRECTION_VALIDATION_ERROR_CODES,
  buildMemoryCorrectionRequest,
  createInitialMemoryCorrectionDraft,
  createMemoryCorrectionRequestId,
  formatMemoryCorrectionValue,
  validateMemoryCorrectionDraft,
  type MemoryCorrectionDraft,
  type MemoryCorrectionUiTarget,
} from '@/components/memory/correction/memoryCorrectionModel';

const assertionTarget: MemoryCorrectionUiTarget = {
  kind: 'assertion',
  id: 'assertion-1',
  statement: '你的常用回复风格是直白',
  currentValue: '直白',
  expectedUpdatedAt: 1719301200,
};

const structuredAssertionTarget: MemoryCorrectionUiTarget = {
  kind: 'assertion',
  id: 'assertion-structured',
  statement: '子涵、哈基米',
  currentValue: '["子涵", "哈基米"]',
  displayValue: '子涵、哈基米',
  expectedUpdatedAt: 1719301200,
};

const edgeTarget: MemoryCorrectionUiTarget = {
  kind: 'edge',
  id: 'edge-1',
  statement: '你使用 Magi',
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
      scopeType: 'project',
      scopeValue: '',
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

  it('shows a readable structured value instead of its stored representation', () => {
    const draft = createInitialMemoryCorrectionDraft(structuredAssertionTarget);

    expect(draft.value).toBe('子涵、哈基米');
  });
});

describe('formatMemoryCorrectionValue', () => {
  it('renders stored list and value-envelope assertions for people', () => {
    expect(formatMemoryCorrectionValue('["子涵", "哈基米"]')).toBe('子涵、哈基米');
    expect(formatMemoryCorrectionValue('{"value":["子涵","哈基米"]}')).toBe('子涵、哈基米');
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

  it('allows the current assertion value for a scoped refinement but requires a scope', () => {
    const missingScope = makeDraft(assertionTarget, {
      correctionKind: 'scope_refinement',
      value: '直白',
      scopeValue: '   ',
    });
    const valid = makeDraft(assertionTarget, {
      correctionKind: 'scope_refinement',
      value: '直白',
      scopeType: 'activity',
      scopeValue: '代码评审',
    });

    expect(validateMemoryCorrectionDraft(assertionTarget, missingScope).errors.scopeValue).toBe(
      MEMORY_CORRECTION_VALIDATION_ERROR_CODES.SCOPE_REQUIRED
    );
    expect(validateMemoryCorrectionDraft(assertionTarget, valid)).toEqual({
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
      scopeType: 'person',
      scopeValue: '小林',
    });

    expect(validateMemoryCorrectionDraft(edgeTarget, draft)).toEqual({
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

  it('builds an assertion scope refinement even when the value is unchanged', () => {
    const draft = makeDraft(assertionTarget, {
      correctionKind: 'scope_refinement',
      value: '直白',
      scopeType: 'place',
      scopeValue: '办公室',
    });

    expect(buildMemoryCorrectionRequest(assertionTarget, draft)).toMatchObject({
      correction_kind: 'scope_refinement',
      replacement: { value: '直白' },
      scope: { place: '办公室' },
    });
  });

  it('keeps the stored structured value when only its scope changes', () => {
    const draft = makeDraft(structuredAssertionTarget, {
      correctionKind: 'scope_refinement',
      value: '子涵、哈基米',
      scopeType: 'project',
      scopeValue: 'Magi',
    });

    expect(buildMemoryCorrectionRequest(structuredAssertionTarget, draft)).toMatchObject({
      correction_kind: 'scope_refinement',
      replacement: { value: '["子涵", "哈基米"]' },
      scope: { project: 'Magi' },
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
      scopeType: 'project',
      scopeValue: '个人网站',
    });

    expect(buildMemoryCorrectionRequest(edgeTarget, draft)).toEqual({
      request_id: 'request-1',
      target: { kind: 'edge', id: 'edge-1' },
      correction_kind: 'scope_refinement',
      replacement: {},
      scope: { project: '个人网站' },
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
