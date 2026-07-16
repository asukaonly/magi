import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { memoryApi, type MemoryCorrectionCommandResponse } from '@/api/modules/memory';
import MemoryCorrectionDialog from '@/components/memory/correction/MemoryCorrectionDialog';
import MemoryCorrectionHistory from '@/components/memory/correction/MemoryCorrectionHistory';
import type { MemoryCorrectionUiTarget } from '@/components/memory/correction/memoryCorrectionModel';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      const template = (opts?.defaultValue as string | undefined) ?? key;
      return template.replace(/\{\{(\w+)\}\}/g, (_match, name) =>
        name in (opts ?? {}) ? String(opts?.[name]) : `{{${name}}}`
      );
    },
    i18n: { language: 'zh-CN', resolvedLanguage: 'zh-CN' },
  }),
}));

vi.mock('@/api/modules/memory', () => ({
  memoryApi: {
    applyCorrection: vi.fn(),
    getCorrectionHistory: vi.fn(),
    revertCorrection: vi.fn(),
    getL2Entities: vi.fn(),
  },
}));

const assertionTarget: MemoryCorrectionUiTarget = {
  kind: 'assertion',
  id: 'assertion-1',
  statement: '你偏好直白的回答',
  currentValue: '直白',
  expectedUpdatedAt: 1719301200,
};

const relationshipTarget: MemoryCorrectionUiTarget = {
  kind: 'edge',
  id: 'edge-1',
  statement: '你 使用 Magi',
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

const correctionResponse = (
  overrides: Partial<MemoryCorrectionCommandResponse> = {}
): MemoryCorrectionCommandResponse => ({
  correction: {
    correction_id: 'correction-1',
    request_id: 'request-1',
    actor_id: 'user:self',
    target_kind: 'assertion',
    target_id: 'assertion-1',
    slot_key: 'slot-1',
    claim_fingerprint: 'claim-1',
    correction_kind: 'record_error',
    before: { trait_value: '直白' },
    replacement: { value: '简洁' },
    replacement_target_id: 'assertion-2',
    created_at: 1719301300,
    state: 'active',
  },
  current_claim: { trait_value: '简洁' },
  derivation_state: 'completed',
  created: true,
  ...overrides,
});

const apiError = (status: number) => ({
  isAxiosError: true,
  message: `HTTP ${status}`,
  response: {
    status,
    data: { detail: status === 404 ? 'Correction target not found' : 'Target changed' },
  },
});

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(memoryApi.getL2Entities).mockResolvedValue({
    items: [],
    total: 0,
    limit: 100,
    offset: 0,
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('MemoryCorrectionDialog request safety', () => {
  it('asks before discarding an edited correction and keeps the draft when cancelled', async () => {
    const onOpenChange = vi.fn();
    const user = userEvent.setup();

    render(
      <MemoryCorrectionDialog
        open
        target={assertionTarget}
        onOpenChange={onOpenChange}
      />
    );

    const dialog = await screen.findByRole('dialog', { name: '修正这条记忆' });
    const valueInput = within(dialog).getByLabelText('正确内容');
    await user.clear(valueInput);
    await user.type(valueInput, '简洁');
    await user.click(within(dialog).getByRole('button', { name: '取消' }));

    const discardDialog = await screen.findByRole('dialog', { name: '放弃未保存的修改？' });
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
    await user.click(within(discardDialog).getByRole('button', { name: '继续修改' }));
    expect(valueInput).toHaveValue('简洁');

    await user.click(within(dialog).getByRole('button', { name: '取消' }));
    await user.click(within(await screen.findByRole('dialog', { name: '放弃未保存的修改？' }))
      .getByRole('button', { name: '放弃修改' }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it('shows field-level validation and focuses the first invalid field', async () => {
    const user = userEvent.setup();

    render(
      <MemoryCorrectionDialog
        open
        target={assertionTarget}
        onOpenChange={vi.fn()}
      />
    );

    const dialog = await screen.findByRole('dialog', { name: '修正这条记忆' });
    const valueInput = within(dialog).getByLabelText('正确内容');
    expect(valueInput).toHaveValue('直白');
    await user.click(within(dialog).getByRole('button', { name: '保存修正' }));
    expect(memoryApi.applyCorrection).not.toHaveBeenCalled();
    await waitFor(() => expect(valueInput).toHaveAttribute('aria-invalid', 'true'));

    await waitFor(() => {
      expect(within(dialog).getByText('新内容和当前内容相同，请填写实际变化后的内容。')).toBeInTheDocument();
    });
    expect(within(dialog).getByRole('alert')).toHaveTextContent('请检查填写内容后再保存。');
    await waitFor(() => expect(valueInput).toHaveFocus());
    expect(valueInput).toHaveAttribute('aria-errormessage', 'memory-correction-value-error');

    await user.clear(valueInput);
    await user.type(valueInput, '简洁');
    await user.click(within(dialog).getByRole('button', { name: /以前是这样，现在变了/ }));
    await user.click(within(dialog).getByRole('button', { name: '保存修正' }));

    const effectiveAtInput = within(dialog).getByLabelText('从什么时候开始变化？');
    await waitFor(() => {
      expect(within(dialog).getByText('请选择变化开始的时间。')).toBeInTheDocument();
    });
    await waitFor(() => expect(effectiveAtInput).toHaveFocus());
  });

  it('submits once and locks the draft while the request is pending', async () => {
    let resolveRequest: ((value: MemoryCorrectionCommandResponse) => void) | undefined;
    vi.mocked(memoryApi.applyCorrection).mockImplementation(() => new Promise((resolve) => {
      resolveRequest = resolve;
    }));

    render(
      <MemoryCorrectionDialog
        open
        target={assertionTarget}
        onOpenChange={vi.fn()}
      />
    );

    const dialog = await screen.findByRole('dialog', { name: '修正这条记忆' });
    const valueInput = within(dialog).getByLabelText('正确内容');
    fireEvent.change(valueInput, { target: { value: '简洁' } });
    const submit = within(dialog).getByRole('button', { name: '保存修正' });
    fireEvent.click(submit);
    fireEvent.click(submit);

    expect(memoryApi.applyCorrection).toHaveBeenCalledTimes(1);
    expect(valueInput).toBeDisabled();
    expect(submit).toBeDisabled();

    resolveRequest?.(correctionResponse());
    expect(await within(dialog).findByText('已经按你的意思修正')).toBeInTheDocument();
  });

  it('reuses one request id for an unchanged network retry and rotates it after an edit', async () => {
    vi.mocked(memoryApi.applyCorrection)
      .mockRejectedValueOnce(new Error('network unavailable'))
      .mockRejectedValueOnce(new Error('network unavailable'))
      .mockResolvedValueOnce(correctionResponse({
        current_claim: { trait_value: '更简洁' },
      }));
    const user = userEvent.setup();

    render(
      <MemoryCorrectionDialog
        open
        target={assertionTarget}
        onOpenChange={vi.fn()}
      />
    );

    const dialog = await screen.findByRole('dialog', { name: '修正这条记忆' });
    const valueInput = within(dialog).getByLabelText('正确内容');
    await user.clear(valueInput);
    await user.type(valueInput, '简洁');
    await user.click(within(dialog).getByRole('button', { name: '保存修正' }));
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('你填写的内容还在');

    await user.click(within(dialog).getByRole('button', { name: '保存修正' }));
    await waitFor(() => expect(memoryApi.applyCorrection).toHaveBeenCalledTimes(2));
    const firstRequestId = vi.mocked(memoryApi.applyCorrection).mock.calls[0][0].request_id;
    const retryRequestId = vi.mocked(memoryApi.applyCorrection).mock.calls[1][0].request_id;
    expect(retryRequestId).toBe(firstRequestId);

    await user.clear(valueInput);
    await user.type(valueInput, '更简洁');
    await user.click(within(dialog).getByRole('button', { name: '保存修正' }));
    await waitFor(() => expect(memoryApi.applyCorrection).toHaveBeenCalledTimes(3));
    expect(vi.mocked(memoryApi.applyCorrection).mock.calls[2][0].request_id).not.toBe(firstRequestId);
  });

  it.each([404, 409])('treats HTTP %s as a changed target instead of a retryable save failure', async (status) => {
    vi.mocked(memoryApi.applyCorrection).mockRejectedValue(apiError(status));
    const onConflict = vi.fn();
    const user = userEvent.setup();

    render(
      <MemoryCorrectionDialog
        open
        target={assertionTarget}
        onOpenChange={vi.fn()}
        onConflict={onConflict}
      />
    );

    const dialog = await screen.findByRole('dialog', { name: '修正这条记忆' });
    const input = within(dialog).getByLabelText('正确内容');
    await user.clear(input);
    await user.type(input, '简洁');
    await user.click(within(dialog).getByRole('button', { name: '保存修正' }));

    expect(await within(dialog).findByRole('alert')).toHaveTextContent('当前内容不会被覆盖');
    expect(within(dialog).getByRole('button', { name: '查看最新内容' })).toBeInTheDocument();
    expect(onConflict).toHaveBeenCalledOnce();
  });

  it('explains when the selected change time predates the memory', async () => {
    vi.mocked(memoryApi.applyCorrection).mockRejectedValue({
      isAxiosError: true,
      message: 'HTTP 422',
      response: {
        status: 422,
        data: {
          detail: {
            code: 'effective_at_before_target',
            message: 'effective_at cannot be earlier than the assertion start time',
          },
        },
      },
    });
    const user = userEvent.setup();

    render(
      <MemoryCorrectionDialog
        open
        target={assertionTarget}
        onOpenChange={vi.fn()}
      />
    );

    const dialog = await screen.findByRole('dialog', { name: '修正这条记忆' });
    await user.click(within(dialog).getByRole('button', { name: /以前是这样，现在变了/ }));
    const valueInput = within(dialog).getByLabelText('正确内容');
    await user.clear(valueInput);
    await user.type(valueInput, '简洁');
    fireEvent.change(within(dialog).getByLabelText('从什么时候开始变化？'), {
      target: { value: '2020-01-01T08:00' },
    });
    await user.click(within(dialog).getByRole('button', { name: '保存修正' }));

    expect(await within(dialog).findByRole('alert')).toHaveTextContent(
      '变化时间不能早于这条记忆开始生效的时间'
    );
  });

  it('can find and select a relationship object that was not in the initial page', async () => {
    const target: MemoryCorrectionUiTarget = {
      ...relationshipTarget,
      entityOptions: [{ id: 'tool:magi', name: 'Magi', type: 'software' }],
    };
    vi.mocked(memoryApi.getL2Entities).mockImplementation(async (params) => ({
      items: params?.query === 'Codex'
        ? [{
            entity_id: 'tool:codex',
            canonical_name: 'Codex',
            entity_type: 'software',
            aliases: [],
          }]
        : [],
      total: params?.query === 'Codex' ? 1 : 0,
      limit: params?.limit ?? 100,
      offset: params?.offset ?? 0,
    }));
    vi.mocked(memoryApi.applyCorrection).mockResolvedValue(correctionResponse({
      correction: {
        ...correctionResponse().correction,
        target_kind: 'edge',
        target_id: 'edge-1',
        before: { object_id: 'tool:magi' },
        replacement: { object_id: 'tool:codex', object_type: 'software' },
        replacement_target_id: 'edge-2',
      },
      current_claim: { object_id: 'tool:codex' },
    }));
    const user = userEvent.setup();

    render(
      <MemoryCorrectionDialog
        open
        target={target}
        onOpenChange={vi.fn()}
      />
    );

    const dialog = await screen.findByRole('dialog', { name: '修正这条记忆' });
    const searchInput = within(dialog).getByLabelText('搜索关系对象');
    const objectSelect = within(dialog).getByLabelText('正确的关系对象');
    await user.type(searchInput, 'Codex');
    await waitFor(() => expect(memoryApi.getL2Entities).toHaveBeenLastCalledWith({
      limit: 50,
      query: 'Codex',
    }));
    expect(within(objectSelect).getByRole('option', { name: 'Codex · Other' })).toBeInTheDocument();
    await user.selectOptions(objectSelect, 'tool:codex');
    await user.clear(searchInput);
    await waitFor(() => expect(memoryApi.getL2Entities).toHaveBeenLastCalledWith({ limit: 100 }));
    expect(objectSelect).toHaveValue('tool:codex');
    await user.click(within(dialog).getByRole('button', { name: '保存修正' }));

    await waitFor(() => expect(memoryApi.applyCorrection).toHaveBeenCalledTimes(1));
    expect(memoryApi.applyCorrection).toHaveBeenCalledWith(expect.objectContaining({
      target: { kind: 'edge', id: 'edge-1' },
      replacement: { object_id: 'tool:codex', object_type: 'software' },
    }));
  });

  it('describes rejecting a pending understanding without claiming it was replaced', async () => {
    vi.mocked(memoryApi.applyCorrection).mockResolvedValue(correctionResponse({
      correction: {
        ...correctionResponse().correction,
        before: { trait_value: '直白', status: 'shadow' },
        replacement: null,
        replacement_target_id: undefined,
      },
      current_claim: null,
    }));
    const user = userEvent.setup();

    render(
      <MemoryCorrectionDialog
        open
        target={assertionTarget}
        initialRecordErrorAction="remove"
        onOpenChange={vi.fn()}
      />
    );

    const dialog = await screen.findByRole('dialog', { name: '修正这条记忆' });
    await user.click(within(dialog).getByRole('button', { name: '确认不再使用' }));

    expect(await within(dialog).findByText('已经把这条待确认内容标为不准确，之后不会用它来了解你。'))
      .toBeInTheDocument();
  });
});

describe('MemoryCorrectionHistory request safety', () => {
  const correction = {
    correction_id: 'correction-latest',
    request_id: 'request-original',
    actor_id: 'user:self',
    target_kind: 'assertion' as const,
    target_id: 'assertion-1',
    slot_key: 'slot-1',
    claim_fingerprint: 'claim-1',
    correction_kind: 'record_error' as const,
    before: { trait_value: '直白' },
    replacement: { value: '简洁' },
    created_at: 1719301300,
    state: 'active' as const,
  };

  it('reuses one request id when reverting is retried after a network failure', async () => {
    vi.mocked(memoryApi.getCorrectionHistory).mockResolvedValue({
      target: { kind: 'assertion', id: 'assertion-1' },
      versions: [],
      corrections: [correction],
    });
    vi.mocked(memoryApi.revertCorrection)
      .mockRejectedValueOnce(new Error('response lost'))
      .mockResolvedValueOnce(correctionResponse({
        correction: { ...correction, state: 'reverted', reverted_at: 1719301400 },
        current_claim: { trait_value: '直白' },
        created: false,
      }));
    const user = userEvent.setup();

    render(<MemoryCorrectionHistory target={assertionTarget} />);

    await user.click(await screen.findByRole('button', { name: '撤销这次修正' }));
    await user.click(screen.getByRole('button', { name: '确认撤销' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('暂时没能撤销');
    await user.click(screen.getByRole('button', { name: '确认撤销' }));

    await waitFor(() => expect(memoryApi.revertCorrection).toHaveBeenCalledTimes(2));
    expect(vi.mocked(memoryApi.revertCorrection).mock.calls[1][1]).toBe(
      vi.mocked(memoryApi.revertCorrection).mock.calls[0][1]
    );
  });

  it.each([404, 409])('reloads history after an HTTP %s revert response', async (status) => {
    vi.mocked(memoryApi.getCorrectionHistory).mockResolvedValue({
      target: { kind: 'assertion', id: 'assertion-1' },
      versions: [],
      corrections: [correction],
    });
    vi.mocked(memoryApi.revertCorrection).mockRejectedValue(apiError(status));
    const onConflict = vi.fn();
    const user = userEvent.setup();

    render(
      <MemoryCorrectionHistory
        target={assertionTarget}
        onConflict={onConflict}
      />
    );

    await user.click(await screen.findByRole('button', { name: '撤销这次修正' }));
    await user.click(screen.getByRole('button', { name: '确认撤销' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('已经发生变化或不再存在');
    expect(onConflict).toHaveBeenCalledOnce();
    await waitFor(() => expect(memoryApi.getCorrectionHistory).toHaveBeenCalledTimes(2));
  });

  it('uses unique React keys for multiple versions of the same relationship', async () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    vi.mocked(memoryApi.getCorrectionHistory).mockResolvedValue({
      target: { kind: 'edge', id: 'edge-1' },
      versions: [
        {
          version_id: 'version-1',
          triple_id: 'edge-1',
          subject_id: 'user:self',
          predicate: 'USES',
          object_id: 'tool:magi',
          status: 'deprecated',
          valid_from: 1719300000,
          valid_to: 1719301200,
        },
        {
          version_id: 'version-2',
          triple_id: 'edge-1',
          subject_id: 'user:self',
          predicate: 'USES',
          object_id: 'tool:codex',
          status: 'active',
          valid_from: 1719301200,
        },
      ],
      corrections: [],
    });

    render(<MemoryCorrectionHistory target={relationshipTarget} />);

    await screen.findByText('还没有修正过这条记忆。');
    fireEvent.click(screen.getByText('查看内容变化'));
    expect(screen.getByText('你 使用 Magi')).toBeInTheDocument();
    expect(screen.getByText('你 使用 Codex')).toBeInTheDocument();
    expect(consoleError.mock.calls.flat().join(' ')).not.toContain('same key');
  });

  it('uses the saved summary or object id instead of a vague historical object label', async () => {
    const target: MemoryCorrectionUiTarget = {
      ...relationshipTarget,
      entityOptions: [{ id: 'tool:magi', name: 'Magi', type: 'software' }],
    };
    vi.mocked(memoryApi.getCorrectionHistory).mockResolvedValue({
      target: { kind: 'edge', id: 'edge-1' },
      versions: [{
        version_id: 'version-legacy',
        triple_id: 'edge-1',
        object_id: 'tool:legacy',
        natural_summary: '你 使用 Legacy Tool',
        valid_from: 1719300000,
        valid_to: 1719301200,
      }, {
        version_id: 'version-deleted',
        triple_id: 'edge-1',
        object_id: 'tool:deleted',
        valid_from: 1719301200,
        valid_to: 1719301400,
      }],
      corrections: [],
    });

    render(<MemoryCorrectionHistory target={target} />);

    await screen.findByText('还没有修正过这条记忆。');
    fireEvent.click(screen.getByText('查看内容变化'));
    expect(screen.getByText('你 使用 Legacy Tool')).toBeInTheDocument();
    expect(screen.getByText('你 使用 对象 tool:deleted')).toBeInTheDocument();
    expect(screen.queryByText(/另一个对象/)).not.toBeInTheDocument();
    expect(memoryApi.getL2Entities).not.toHaveBeenCalled();
  });

  it('labels a future correction as waiting instead of currently effective', async () => {
    const now = Date.now() / 1000;
    vi.mocked(memoryApi.getCorrectionHistory).mockResolvedValue({
      target: { kind: 'assertion', id: 'assertion-1' },
      versions: [],
      corrections: [{
        ...correction,
        correction_kind: 'situation_changed',
        effective_at: now + 3600,
      }],
    });

    render(<MemoryCorrectionHistory target={assertionTarget} />);

    expect(await screen.findByText('等待生效')).toBeInTheDocument();
    expect(screen.queryByText('当前有效')).not.toBeInTheDocument();
  });

  it('labels a future change as scheduled while keeping the old value current', async () => {
    const now = Date.now() / 1000;
    vi.mocked(memoryApi.getCorrectionHistory).mockResolvedValue({
      target: { kind: 'assertion', id: 'assertion-1' },
      versions: [
        {
          assertion_id: 'assertion-1',
          trait_value: '直白',
          status: 'superseded',
          valid_from: now - 3600,
          valid_to: now + 3600,
        },
        {
          assertion_id: 'assertion-2',
          trait_value: '简洁',
          status: 'stable',
          valid_from: now + 3600,
        },
      ],
      corrections: [],
    });

    render(<MemoryCorrectionHistory target={assertionTarget} />);

    await screen.findByText('还没有修正过这条记忆。');
    fireEvent.click(screen.getByText('查看内容变化'));
    expect(screen.getByText(/当前版本/)).toBeInTheDocument();
    expect(screen.getByText(/计划生效/)).toBeInTheDocument();
  });

  it('does not label a future-starting version as scheduled after it already ended', async () => {
    const now = Date.now() / 1000;
    vi.mocked(memoryApi.getCorrectionHistory).mockResolvedValue({
      target: { kind: 'assertion', id: 'assertion-1' },
      versions: [{
        assertion_id: 'assertion-future-reverted',
        trait_value: '简洁',
        status: 'archived',
        valid_from: now + 3600,
        valid_to: now - 60,
      }],
      corrections: [],
    });

    render(<MemoryCorrectionHistory target={assertionTarget} />);

    await screen.findByText('还没有修正过这条记忆。');
    fireEvent.click(screen.getByText('查看内容变化'));
    expect(screen.getByText(/历史版本/)).toBeInTheDocument();
    expect(screen.queryByText(/计划生效/)).not.toBeInTheDocument();
  });
});
