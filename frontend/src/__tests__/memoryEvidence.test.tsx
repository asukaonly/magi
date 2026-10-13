import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { memoryApi } from '@/api/modules/memory';
import { manualEntriesApi } from '@/api/modules/manualEntries';
import { MemoryEvidenceRecords } from '@/components/memory/evidence/MemoryEvidenceRecords';
import { MemoryEvidenceButton } from '@/components/memory/evidence/MemoryEvidenceButton';
import { normalizeRecalledMemories } from '@/domain/chat/state.history';

const { translate } = vi.hoisted(() => ({ translate: (key: string) => key }));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: translate, i18n: { language: 'en' } }) }));
vi.mock('@/api/modules/memory', () => ({ memoryApi: {
  getL1Events: vi.fn(), getL2Assertions: vi.fn(), getL2Relations: vi.fn(), deleteL1Event: vi.fn(),
} }));
vi.mock('@/api/modules/manualEntries', () => ({ manualEntriesApi: { get: vi.fn(), remove: vi.fn() } }));
vi.mock('@/components/memory/correction/MemoryCorrectionDialog', () => ({
  MemoryCorrectionDialog: ({ open, target }: { open: boolean; target: unknown }) => open ? <div data-testid="correction-target">{JSON.stringify(target)}</div> : null,
}));

const event = (id: string) => ({ event_id: id, content: `Original ${id}`, timestamp: 1700000000, source: 'user_authored', event_type: 'manual' });
const page = (id: string) => ({ items: [event(id)], total: 1, limit: 1, offset: 0 });

beforeEach(() => { vi.clearAllMocks(); });

describe('shared memory evidence', () => {
  it('loads true sources only on demand and opens correction with the stored value', async () => {
    vi.mocked(memoryApi.getL2Assertions).mockResolvedValue({ items: [{
      assertion_id: 'fact', trait_name: 'preference.affinity', trait_value: 'like', display_text: 'You like jazz.', display_status: 'complete', evidence_events: ['source'], updated_at: 123, value_options: ['like', 'dislike'], status: 'active',
    }], total: 1, limit: 1, offset: 0 } as never);
    vi.mocked(memoryApi.getL1Events).mockResolvedValue(page('source') as never);
    render(<MemoryEvidenceButton target={{ title: 'Old display', recordRef: { kind: 'assertion', id: 'fact' } }} />);
    expect(memoryApi.getL2Assertions).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: 'memory.evidence.open' }));
    expect(await screen.findByText('Original source')).toBeInTheDocument();
    expect(screen.getByText('You like jazz.')).toBeInTheDocument();
    expect(memoryApi.getL2Assertions).toHaveBeenCalledWith({ assertion_id: 'fact', include_inactive: true, limit: 1 });
    await userEvent.click(screen.getByRole('button', { name: 'memory.evidence.correct' }));
    const target = JSON.parse(screen.getByTestId('correction-target').textContent || '{}');
    expect(target).toMatchObject({ id: 'fact', editableValue: 'like', displaySentence: 'You like jazz.', expectedUpdatedAt: 123 });
  });

  it('distinguishes missing sources from failures and paginates all references', async () => {
    vi.mocked(memoryApi.getL1Events).mockImplementation(async (params) => {
      if (params?.event_id === '2') throw new Error('Offline');
      if (params?.event_id === '3') return { items: [], total: 0, offset: 0, limit: 1 };
      return page(params?.event_id || '') as never;
    });
    render(<MemoryEvidenceRecords eventIds={['1', '2', '3', '4', '5', '6']} />);
    expect(await screen.findByText('Original 1')).toBeInTheDocument();
    expect(screen.getByText('memory.evidence.loadFailed')).toBeInTheDocument();
    expect(screen.getByText('memory.evidence.unavailable')).toBeInTheDocument();
    expect(memoryApi.getL1Events).toHaveBeenCalledTimes(5);
    await userEvent.click(screen.getByRole('button', { name: 'memory.evidence.next' }));
    expect(await screen.findByText('Original 6')).toBeInTheDocument();
    expect(screen.queryByText('Original 1')).not.toBeInTheDocument();
  });

  it('requires explicit source-forgetting confirmation and keeps evidence on failure', async () => {
    vi.mocked(memoryApi.getL1Events).mockResolvedValue(page('source') as never);
    vi.mocked(memoryApi.deleteL1Event).mockRejectedValueOnce(new Error('Offline')).mockResolvedValueOnce({} as never);
    const onChanged = vi.fn();
    render(<MemoryEvidenceRecords eventIds={['source']} onChanged={onChanged} />);
    await screen.findByText('Original source');
    await userEvent.click(screen.getByRole('button', { name: 'memory.evidence.forgetSource' }));
    expect(memoryApi.deleteL1Event).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: 'memory.evidence.confirmForget' }));
    expect(await screen.findByText('memory.evidence.forgetFailed')).toBeInTheDocument();
    expect(screen.getByText('Original source')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'memory.evidence.confirmForget' }));
    await waitFor(() => expect(onChanged).toHaveBeenCalledOnce());
    expect(screen.queryByText('Original source')).not.toBeInTheDocument();
    expect(memoryApi.deleteL1Event).toHaveBeenLastCalledWith('source');
  });

  it('does not show an old request after the selected evidence changes', async () => {
    let resolveOld: (value: unknown) => void = () => undefined;
    vi.mocked(memoryApi.getL1Events).mockImplementation((params) => params?.event_id === 'old'
      ? new Promise((resolve) => { resolveOld = resolve; }) as never
      : Promise.resolve(page('new')) as never);
    const view = render(<MemoryEvidenceRecords eventIds={['old']} />);
    view.rerender(<MemoryEvidenceRecords eventIds={['new']} />);
    await screen.findByText('Original new');
    await act(async () => { resolveOld(page('old')); });
    expect(screen.queryByText('Original old')).not.toBeInTheDocument();
  });

  it('deletes a manual source through its owning entry workflow after verifying its identity', async () => {
    vi.mocked(memoryApi.getL1Events).mockResolvedValue({ ...page('source'), items: [{ ...event('source'), source: 'manual_entry', source_item_id: 'entry' }] } as never);
    vi.mocked(manualEntriesApi.get).mockResolvedValue({ entry_id: 'entry', l1_event_id: 'source', deleted_at: null, revision: 'a'.repeat(64), body: 'Current manual entry' } as never);
    vi.mocked(manualEntriesApi.remove).mockResolvedValue(undefined);
    render(<MemoryEvidenceRecords eventIds={['source']} />);
    await screen.findByText('Original source');
    await userEvent.click(screen.getByRole('button', { name: 'memory.evidence.forgetSource' }));
    expect(await screen.findByText('Current manual entry')).toBeInTheDocument();
    expect(manualEntriesApi.get).toHaveBeenCalledWith('entry');
    expect(manualEntriesApi.remove).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: 'memory.governance.destructiveConfirm.confirmManualEntry' }));
    await waitFor(() => expect(manualEntriesApi.remove).toHaveBeenCalledWith('entry'));
    expect(memoryApi.deleteL1Event).not.toHaveBeenCalled();
  });

  it('does not offer a permanently failing delete for a manual source without its owner', async () => {
    vi.mocked(memoryApi.getL1Events).mockResolvedValue({ ...page('source'), items: [{ ...event('source'), source: 'manual_entry', source_item_id: null }] } as never);
    render(<MemoryEvidenceRecords eventIds={['source']} />);
    expect(await screen.findByText('memory.evidence.ownerUnavailable')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'memory.evidence.forgetSource' })).not.toBeInTheDocument();
  });

  it('explains that forgetting chat-derived memory retains the original chat message', async () => {
    vi.mocked(memoryApi.getL1Events).mockResolvedValue({ ...page('source'), items: [{ ...event('source'), source: 'chat' }] } as never);
    render(<MemoryEvidenceRecords eventIds={['source']} />);
    await screen.findByText('Original source');
    await userEvent.click(screen.getByRole('button', { name: 'memory.governance.destructiveConfirm.confirmChatEvent' }));
    expect(screen.getByText('memory.governance.destructiveConfirm.chatEventDescription')).toBeInTheDocument();
    expect(screen.queryByText('memory.evidence.forgetConfirm')).not.toBeInTheDocument();
  });

  it('never invents a source reference from legacy feedback refs or invalid data', () => {
    const normalized = normalizeRecalledMemories([
      { statement: 'Legacy', feedback_ref: 'assertion:old' },
      { statement: 'Invalid', record_ref: { kind: 'procedure', id: 'p' }, evidence_event_ids: [1, 'event'] },
      { statement: 'Current', record_ref: { kind: 'assertion', id: 'a' }, evidence_event_ids: ['s', 's'] },
    ]);
    expect(normalized?.[0].recordRef).toBeUndefined();
    expect(normalized?.[1].recordRef).toBeUndefined();
    expect(normalized?.[1].evidenceEventIds).toEqual(['event']);
    expect(normalized?.[2].recordRef).toEqual({ kind: 'assertion', id: 'a' });
    expect(normalized?.[2].evidenceEventIds).toEqual(['s']);
  });
});
