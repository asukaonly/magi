import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { memoryApi, type MemoryCorrectionCommandResponse } from '@/api/modules/memory';
import MemoryCorrectionDialog from '@/components/memory/correction/MemoryCorrectionDialog';
import MemoryCorrectionHistory from '@/components/memory/correction/MemoryCorrectionHistory';
import type { MemoryCorrectionUiTarget } from '@/components/memory/correction/memoryCorrectionModel';

const projectContextId = (character: string) => `ctx_project_${character.repeat(64)}`;
const MAGI_CONTEXT_ID = projectContextId('a');
const WEBSITE_CONTEXT_ID = projectContextId('b');
const OLD_CONTEXT_ID = projectContextId('c');
const NEW_CONTEXT_ID = projectContextId('d');
const FRESH_CONTEXT_ID = projectContextId('e');
const STALE_CONTEXT_ID = projectContextId('f');

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
    getCorrectionContextOptions: vi.fn(),
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
  vi.mocked(memoryApi.getCorrectionContextOptions).mockResolvedValue({
    items: [{
      context_id: MAGI_CONTEXT_ID,
      dimension: 'project',
      label: 'Magi',
    }],
  });
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

  it('focuses the first visible relationship error before the change time', async () => {
    const user = userEvent.setup();

    render(
      <MemoryCorrectionDialog
        open
        target={relationshipTarget}
        onOpenChange={vi.fn()}
      />
    );

    const dialog = await screen.findByRole('dialog', { name: '修正这条记忆' });
    await user.click(within(dialog).getByRole('button', { name: /以前是这样，现在变了/ }));
    const objectSelect = within(dialog).getByLabelText('正确的关系对象');
    await user.click(within(dialog).getByRole('button', { name: '保存修正' }));

    expect(await within(dialog).findByText('请选择一个与当前不同的对象。')).toBeInTheDocument();
    expect(within(dialog).getByText('请选择变化开始的时间。')).toBeInTheDocument();
    await waitFor(() => expect(objectSelect).toHaveFocus());
  });

  it('wraps a long unbroken memory statement inside the dialog', async () => {
    const statement = `记忆${'x'.repeat(600)}`;

    render(
      <MemoryCorrectionDialog
        open
        target={{ ...assertionTarget, statement }}
        onOpenChange={vi.fn()}
      />
    );

    const dialog = await screen.findByRole('dialog', { name: '修正这条记忆' });
    expect(within(dialog).getByText(statement)).toHaveClass('break-words');
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

  it('shows backend-disambiguated project names and sends only the selected stable id', async () => {
    vi.mocked(memoryApi.getCorrectionContextOptions).mockResolvedValue({
      items: [{
        context_id: MAGI_CONTEXT_ID,
        dimension: 'project',
        label: 'magi · first',
      }, {
        context_id: WEBSITE_CONTEXT_ID,
        dimension: 'project',
        label: 'magi · second',
      }],
    });
    vi.mocked(memoryApi.applyCorrection).mockResolvedValue(correctionResponse({
      correction: {
        ...correctionResponse().correction,
        correction_kind: 'scope_refinement',
        replacement: { value: '直白' },
        scope: { all_of: [{ dimension: 'project', context_id: WEBSITE_CONTEXT_ID }] },
      },
      current_claim: {
        trait_value: '直白',
        scope: { all_of: [{ dimension: 'project', context_id: WEBSITE_CONTEXT_ID }] },
      },
    }));
    const user = userEvent.setup();

    render(
      <MemoryCorrectionDialog open target={assertionTarget} onOpenChange={vi.fn()} />
    );

    const dialog = await screen.findByRole('dialog', { name: '修正这条记忆' });
    await user.click(within(dialog).getByRole('button', { name: /只在某些情况下是这样/ }));
    expect(within(dialog).queryByLabelText('情况类型')).not.toBeInTheDocument();
    expect(within(dialog).queryByLabelText('具体情况')).not.toBeInTheDocument();
    const search = await within(dialog).findByLabelText('搜索项目');
    const projectSelect = within(dialog).getByLabelText('选择项目');
    expect(within(projectSelect).getByRole('option', { name: 'magi · first' })).toBeInTheDocument();
    expect(within(projectSelect).getByRole('option', { name: 'magi · second' })).toBeInTheDocument();
    await user.type(search, 'second');
    expect(within(projectSelect).queryByRole('option', { name: 'magi · first' })).not.toBeInTheDocument();
    expect(within(projectSelect).getByRole('option', { name: 'magi · second' })).toBeInTheDocument();
    await user.selectOptions(projectSelect, WEBSITE_CONTEXT_ID);
    await user.click(within(dialog).getByRole('button', { name: '保存修正' }));

    await waitFor(() => expect(memoryApi.applyCorrection).toHaveBeenCalledOnce());
    const payload = vi.mocked(memoryApi.applyCorrection).mock.calls[0][0];
    expect(payload.scope).toEqual({
      all_of: [{ dimension: 'project', context_id: WEBSITE_CONTEXT_ID }],
    });
    expect(JSON.stringify(payload.scope)).not.toContain('magi · second');
    expect(await within(dialog).findByText(/项目[:：] magi · second/)).toBeInTheDocument();
  });

  it('does not load relationship objects when only the project scope changes', async () => {
    render(
      <MemoryCorrectionDialog
        open
        target={relationshipTarget}
        initialCorrectionKind="scope_refinement"
        onOpenChange={vi.fn()}
      />
    );

    const dialog = await screen.findByRole('dialog', { name: '修正这条记忆' });
    expect(await within(dialog).findByLabelText('选择项目')).toBeInTheDocument();
    expect(within(dialog).queryByLabelText('正确的关系对象')).not.toBeInTheDocument();
    expect(memoryApi.getL2Entities).not.toHaveBeenCalled();
  });

  it('keeps scoped correction unavailable until a failed project load is retried', async () => {
    vi.mocked(memoryApi.getCorrectionContextOptions)
      .mockRejectedValueOnce(new Error('temporarily unavailable'))
      .mockResolvedValueOnce({
        items: [{
          context_id: MAGI_CONTEXT_ID,
          dimension: 'project',
          label: 'Magi',
        }],
      });
    const user = userEvent.setup();

    render(
      <MemoryCorrectionDialog open target={assertionTarget} onOpenChange={vi.fn()} />
    );

    const dialog = await screen.findByRole('dialog', { name: '修正这条记忆' });
    await user.click(within(dialog).getByRole('button', { name: /只在某些情况下是这样/ }));
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('暂时无法读取项目列表');
    expect(within(dialog).getByRole('button', { name: '保存修正' })).toBeDisabled();
    await user.click(within(dialog).getByRole('button', { name: '重试' }));
    expect(await within(dialog).findByLabelText('选择项目')).toBeInTheDocument();
    expect(memoryApi.getCorrectionContextOptions).toHaveBeenCalledTimes(2);
    await waitFor(() => expect(within(dialog).getByLabelText('选择项目')).toHaveFocus());
  });

  it('returns focus to the retry control when project loading fails again', async () => {
    vi.mocked(memoryApi.getCorrectionContextOptions)
      .mockRejectedValueOnce(new Error('temporarily unavailable'))
      .mockRejectedValueOnce(new Error('still unavailable'));
    const user = userEvent.setup();

    render(
      <MemoryCorrectionDialog open target={assertionTarget} onOpenChange={vi.fn()} />
    );

    const dialog = await screen.findByRole('dialog', { name: '修正这条记忆' });
    await user.click(within(dialog).getByRole('button', { name: /只在某些情况下是这样/ }));
    const retry = await within(dialog).findByRole('button', { name: '重试' });
    await user.click(retry);

    await waitFor(() => expect(within(dialog).getByRole('button', { name: '重试' })).toHaveFocus());
    expect(memoryApi.getCorrectionContextOptions).toHaveBeenCalledTimes(2);
  });

  it('moves focus to the empty project explanation after a successful retry', async () => {
    vi.mocked(memoryApi.getCorrectionContextOptions)
      .mockRejectedValueOnce(new Error('temporarily unavailable'))
      .mockResolvedValueOnce({ items: [] });
    const user = userEvent.setup();

    render(
      <MemoryCorrectionDialog open target={assertionTarget} onOpenChange={vi.fn()} />
    );

    const dialog = await screen.findByRole('dialog', { name: '修正这条记忆' });
    await user.click(within(dialog).getByRole('button', { name: /只在某些情况下是这样/ }));
    await user.click(await within(dialog).findByRole('button', { name: '重试' }));

    const emptyStatus = await within(dialog).findByRole('status');
    expect(emptyStatus).toHaveTextContent('还没有可选项目');
    await waitFor(() => expect(emptyStatus).toHaveFocus());
  });

  it('explains when no workspace project can be selected', async () => {
    vi.mocked(memoryApi.getCorrectionContextOptions).mockResolvedValue({ items: [] });
    const user = userEvent.setup();

    render(
      <MemoryCorrectionDialog open target={assertionTarget} onOpenChange={vi.fn()} />
    );

    const dialog = await screen.findByRole('dialog', { name: '修正这条记忆' });
    await user.click(within(dialog).getByRole('button', { name: /只在某些情况下是这样/ }));
    expect(await within(dialog).findByText(/还没有可选项目/)).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: '保存修正' })).toBeDisabled();
  });

  it('refreshes projects and clears the selection when the server rejects a stale context', async () => {
    vi.mocked(memoryApi.getCorrectionContextOptions)
      .mockResolvedValueOnce({
        items: [{
          context_id: OLD_CONTEXT_ID,
          dimension: 'project',
          label: '旧项目',
        }],
      })
      .mockResolvedValueOnce({
        items: [{
          context_id: NEW_CONTEXT_ID,
          dimension: 'project',
          label: '新项目',
        }],
      });
    vi.mocked(memoryApi.applyCorrection).mockRejectedValue({
      isAxiosError: true,
      message: 'HTTP 422',
      response: {
        status: 422,
        data: { detail: { code: 'context_scope_unknown' } },
      },
    });
    const user = userEvent.setup();

    render(
      <MemoryCorrectionDialog open target={assertionTarget} onOpenChange={vi.fn()} />
    );

    const dialog = await screen.findByRole('dialog', { name: '修正这条记忆' });
    await user.click(within(dialog).getByRole('button', { name: /只在某些情况下是这样/ }));
    const projectSelect = await within(dialog).findByLabelText('选择项目');
    await user.type(within(dialog).getByLabelText('搜索项目'), '旧');
    await user.selectOptions(projectSelect, OLD_CONTEXT_ID);
    await user.click(within(dialog).getByRole('button', { name: '保存修正' }));

    expect(await within(dialog).findByRole('alert')).toHaveTextContent('项目列表已经更新');
    await waitFor(() => expect(memoryApi.getCorrectionContextOptions).toHaveBeenCalledTimes(2));
    const refreshedSelect = await within(dialog).findByLabelText('选择项目');
    expect(within(dialog).getByLabelText('搜索项目')).toHaveValue('');
    expect(refreshedSelect).toHaveValue('');
    expect(within(refreshedSelect).getByRole('option', { name: '新项目' })).toBeInTheDocument();
  });

  it('ignores a project response that arrives after the dialog closes', async () => {
    let resolveFirstRequest: ((value: Awaited<ReturnType<typeof memoryApi.getCorrectionContextOptions>>) => void) | undefined;
    const firstRequest = new Promise<Awaited<ReturnType<typeof memoryApi.getCorrectionContextOptions>>>((resolve) => {
      resolveFirstRequest = resolve;
    });
    vi.mocked(memoryApi.getCorrectionContextOptions)
      .mockReturnValueOnce(firstRequest)
      .mockResolvedValueOnce({
        items: [{
          context_id: FRESH_CONTEXT_ID,
          dimension: 'project',
          label: '当前项目',
        }],
      });
    const { rerender } = render(
      <MemoryCorrectionDialog
        open
        target={assertionTarget}
        initialCorrectionKind="scope_refinement"
        onOpenChange={vi.fn()}
      />
    );

    expect(await screen.findByText('正在读取可选项目…')).toBeInTheDocument();
    rerender(
      <MemoryCorrectionDialog
        open={false}
        target={assertionTarget}
        initialCorrectionKind="scope_refinement"
        onOpenChange={vi.fn()}
      />
    );
    rerender(
      <MemoryCorrectionDialog
        open
        target={assertionTarget}
        initialCorrectionKind="scope_refinement"
        onOpenChange={vi.fn()}
      />
    );

    const projectSelect = await screen.findByLabelText('选择项目');
    expect(within(projectSelect).getByRole('option', { name: '当前项目' })).toBeInTheDocument();
    resolveFirstRequest?.({
      items: [{
        context_id: STALE_CONTEXT_ID,
        dimension: 'project',
        label: '过期项目',
      }],
    });
    await waitFor(() => expect(within(projectSelect).queryByRole('option', { name: '过期项目' })).not.toBeInTheDocument());
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

  it('shows project names for structured scopes in corrections and versions', async () => {
    vi.mocked(memoryApi.getCorrectionHistory).mockResolvedValue({
      target: { kind: 'assertion', id: 'assertion-1' },
      versions: [{
        assertion_id: 'assertion-scoped',
        trait_value: '直白',
        status: 'stable',
        scope: { all_of: [{ dimension: 'project', context_id: MAGI_CONTEXT_ID }] },
      }],
      corrections: [{
        ...correction,
        correction_kind: 'scope_refinement',
        scope: { all_of: [{ dimension: 'project', context_id: MAGI_CONTEXT_ID }] },
      }],
      context_labels: { [MAGI_CONTEXT_ID]: 'Magi · archived' },
    });

    render(<MemoryCorrectionHistory target={assertionTarget} />);

    expect(await screen.findAllByText(/项目[:：] Magi · archived/)).toHaveLength(2);
    expect(screen.queryByText('原来：')).not.toBeInTheDocument();
    expect(screen.queryByText('改为：')).not.toBeInTheDocument();
    expect(document.body).not.toHaveTextContent(MAGI_CONTEXT_ID);
    expect(memoryApi.getCorrectionContextOptions).not.toHaveBeenCalled();
  });

  it('moves focus into and back out of the inline revert confirmation', async () => {
    vi.mocked(memoryApi.getCorrectionHistory).mockResolvedValue({
      target: { kind: 'assertion', id: 'assertion-1' },
      versions: [],
      corrections: [correction],
      context_labels: {},
    });
    const user = userEvent.setup();

    render(<MemoryCorrectionHistory target={assertionTarget} />);

    const revertButton = await screen.findByRole('button', { name: '撤销这次修正' });
    await user.click(revertButton);
    expect(screen.getByRole('alertdialog', { name: '确认撤销这次修正？' })).toBeInTheDocument();
    const cancelButton = screen.getByRole('button', { name: '取消' });
    await waitFor(() => expect(cancelButton).toHaveFocus());
    await user.click(cancelButton);

    await waitFor(() => expect(screen.getByRole('button', { name: '撤销这次修正' })).toHaveFocus());
  });

  it('hides internal context ids when a historical label is unavailable', async () => {
    vi.mocked(memoryApi.getCorrectionHistory).mockResolvedValue({
      target: { kind: 'assertion', id: 'assertion-1' },
      versions: [],
      corrections: [{
        ...correction,
        correction_kind: 'scope_refinement',
        scope: { all_of: [{ dimension: 'project', context_id: MAGI_CONTEXT_ID }] },
      }],
      context_labels: {},
    });

    render(<MemoryCorrectionHistory target={assertionTarget} />);

    expect(await screen.findByText(/项目[:：] 名称暂不可用/)).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent(MAGI_CONTEXT_ID);
    expect(memoryApi.getCorrectionContextOptions).not.toHaveBeenCalled();
  });

  it('wraps long correction reasons and historical values', async () => {
    const longReason = `说明${'r'.repeat(600)}`;
    const longValue = `内容${'v'.repeat(600)}`;
    vi.mocked(memoryApi.getCorrectionHistory).mockResolvedValue({
      target: { kind: 'assertion', id: 'assertion-1' },
      versions: [{
        assertion_id: 'assertion-long',
        trait_value: longValue,
        status: 'stable',
      }],
      corrections: [{ ...correction, reason: longReason }],
      context_labels: {},
    });

    render(<MemoryCorrectionHistory target={assertionTarget} />);

    expect(await screen.findByText(`说明：${longReason}`)).toHaveClass('break-words');
    expect(screen.getByText(longValue)).toHaveClass('break-words');
  });

  it('does not load project names for history without scoped records', async () => {
    vi.mocked(memoryApi.getCorrectionHistory).mockResolvedValue({
      target: { kind: 'assertion', id: 'assertion-1' },
      versions: [],
      corrections: [correction],
      context_labels: {},
    });

    render(<MemoryCorrectionHistory target={assertionTarget} />);

    expect(await screen.findByText('当前有效')).toBeInTheDocument();
    expect(memoryApi.getCorrectionContextOptions).not.toHaveBeenCalled();
  });

  it('reuses one request id when reverting is retried after a network failure', async () => {
    vi.mocked(memoryApi.getCorrectionHistory).mockResolvedValue({
      target: { kind: 'assertion', id: 'assertion-1' },
      versions: [],
      corrections: [correction],
      context_labels: {},
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
    const retryRevert = screen.getByRole('button', { name: '撤销这次修正' });
    await waitFor(() => expect(retryRevert).toHaveFocus());
    await user.click(retryRevert);
    await user.click(screen.getByRole('button', { name: '确认撤销' }));

    await waitFor(() => expect(memoryApi.revertCorrection).toHaveBeenCalledTimes(2));
    expect(vi.mocked(memoryApi.revertCorrection).mock.calls[1][1]).toBe(
      vi.mocked(memoryApi.revertCorrection).mock.calls[0][1]
    );
  });

  it('does not report a successful revert as failed when follow-up refreshes fail', async () => {
    vi.mocked(memoryApi.getCorrectionHistory)
      .mockResolvedValueOnce({
        target: { kind: 'assertion', id: 'assertion-1' },
        versions: [],
        corrections: [correction],
        context_labels: {},
      })
      .mockRejectedValueOnce(new Error('history refresh failed'));
    vi.mocked(memoryApi.revertCorrection).mockResolvedValue(correctionResponse({
      correction: { ...correction, state: 'reverted', reverted_at: 1719301400 },
      current_claim: { trait_value: '直白' },
      created: false,
    }));
    const onReverted = vi.fn().mockRejectedValue(new Error('parent refresh failed'));
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const user = userEvent.setup();

    render(<MemoryCorrectionHistory target={assertionTarget} onReverted={onReverted} />);

    await user.click(await screen.findByRole('button', { name: '撤销这次修正' }));
    await user.click(screen.getByRole('button', { name: '确认撤销' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('暂时没能读取修改记录');
    expect(screen.queryByText('暂时没能撤销这次修正，请稍后重试。')).not.toBeInTheDocument();
    expect(memoryApi.revertCorrection).toHaveBeenCalledOnce();
    expect(onReverted).toHaveBeenCalledOnce();
    expect(consoleError).toHaveBeenCalledWith(
      'Failed to refresh memory after successful correction revert',
      expect.any(Error)
    );
  });

  it('allows only one project correction to be reverted at a time', async () => {
    const secondCorrection = {
      ...correction,
      correction_id: 'correction-second-project',
      request_id: 'request-second-project',
      target_id: 'assertion-second-project',
      claim_fingerprint: 'claim-second-project',
      replacement_target_id: 'assertion-second-project-new',
      created_at: correction.created_at + 1,
      scope: { all_of: [{ dimension: 'project' as const, context_id: WEBSITE_CONTEXT_ID }] },
    };
    const firstCorrection = {
      ...correction,
      target_id: 'assertion-first-project',
      replacement_target_id: 'assertion-first-project-new',
      scope: { all_of: [{ dimension: 'project' as const, context_id: MAGI_CONTEXT_ID }] },
    };
    vi.mocked(memoryApi.getCorrectionHistory).mockResolvedValue({
      target: { kind: 'assertion', id: 'assertion-1' },
      versions: [],
      corrections: [firstCorrection, secondCorrection],
      context_labels: {
        [MAGI_CONTEXT_ID]: 'Magi',
        [WEBSITE_CONTEXT_ID]: 'Website',
      },
    });
    let resolveRevert: (value: MemoryCorrectionCommandResponse) => void = () => undefined;
    vi.mocked(memoryApi.revertCorrection).mockImplementation(() => new Promise((resolve) => {
      resolveRevert = resolve;
    }));
    const user = userEvent.setup();

    render(<MemoryCorrectionHistory target={assertionTarget} />);

    const revertButtons = await screen.findAllByRole('button', { name: '撤销这次修正' });
    expect(revertButtons).toHaveLength(2);
    await user.click(revertButtons[0]);
    const confirmButton = screen.getByRole('button', { name: '确认撤销' });
    fireEvent.click(confirmButton);
    fireEvent.click(confirmButton);

    await waitFor(() => expect(memoryApi.revertCorrection).toHaveBeenCalledTimes(1));
    expect(screen.getByRole('button', { name: '撤销这次修正' })).toBeDisabled();

    resolveRevert(correctionResponse({
      correction: { ...secondCorrection, state: 'reverted', reverted_at: 1719301400 },
      current_claim: { trait_value: '直白' },
      created: false,
    }));
    await waitFor(() => expect(memoryApi.getCorrectionHistory).toHaveBeenCalledTimes(2));
  });

  it.each([404, 409])('reloads history after an HTTP %s revert response', async (status) => {
    vi.mocked(memoryApi.getCorrectionHistory).mockResolvedValue({
      target: { kind: 'assertion', id: 'assertion-1' },
      versions: [],
      corrections: [correction],
      context_labels: {},
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
      context_labels: {},
    });

    render(<MemoryCorrectionHistory target={relationshipTarget} />);

    await screen.findByText('还没有修正过这条记忆。');
    fireEvent.click(screen.getByText('查看内容变化'));
    expect(screen.getByText('你 使用 Magi')).toBeInTheDocument();
    expect(screen.getByText('你 使用 Codex')).toBeInTheDocument();
    expect(consoleError.mock.calls.flat().join(' ')).not.toContain('same key');
  });

  it('uses the saved summary or a neutral fallback without exposing object ids', async () => {
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
      context_labels: {},
    });

    render(<MemoryCorrectionHistory target={target} />);

    await screen.findByText('还没有修正过这条记忆。');
    fireEvent.click(screen.getByText('查看内容变化'));
    expect(screen.getByText('你 使用 Legacy Tool')).toBeInTheDocument();
    expect(screen.getByText('你 使用 另一个对象')).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent('tool:deleted');
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
      context_labels: {},
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
      context_labels: {},
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
      context_labels: {},
    });

    render(<MemoryCorrectionHistory target={assertionTarget} />);

    await screen.findByText('还没有修正过这条记忆。');
    fireEvent.click(screen.getByText('查看内容变化'));
    expect(screen.getByText(/历史版本/)).toBeInTheDocument();
    expect(screen.queryByText(/计划生效/)).not.toBeInTheDocument();
  });
});
