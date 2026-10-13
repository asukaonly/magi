import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { L2PagedKnowledgeBrowser } from '@/components/memory/l2/L2PagedKnowledgeBrowser';
import type { KnowledgePageState, MemoryKnowledgePages } from '@/hooks/useMemoryKnowledge';
import type { L2Relation } from '@/api/modules/memory';

const page = <T,>(items: T[] = [], overrides: Partial<KnowledgePageState<T>> = {}): KnowledgePageState<T> => ({
  items, total: items.length, loading: false, loadingMore: false, error: false,
  loadMore: vi.fn().mockResolvedValue(undefined), retry: vi.fn().mockResolvedValue(undefined), reload: vi.fn().mockResolvedValue(undefined),
  ...overrides,
});
const t = (key: string, options?: Record<string, unknown>) => {
  if (key === 'memory.pages.knowledge.readable.relation') return `${options?.subject} ${options?.object}`;
  if (key === 'memory.pages.knowledge.pagination.total') return `total:${options?.count}`;
  return key;
};
const renderPages = (pages: MemoryKnowledgePages) => render(<L2PagedKnowledgeBrowser
  pages={pages} selfEntityAliases={new Set(['user:self'])} actionLoading={false}
  evidenceEventsById={new Map()} loadingEvidenceIds={{}} onLoadEvidenceEvents={vi.fn()}
  t={t}
/>);

describe('paged knowledge browser', () => {
  it('shows independent loading, failure and successful empty states', async () => {
    const user = userEvent.setup();
    const relations = page<L2Relation>([], { total: null, error: true });
    renderPages({ relations, assertions: page([], { total: null, loading: true }), entities: page() });
    const relationshipSection = screen.getByRole('region', { name: 'memory.pages.knowledge.pagination.relations' });
    expect(within(relationshipSection).getByRole('alert')).toBeInTheDocument();
    expect(within(relationshipSection).queryByText('memory.pages.knowledge.emptyKnowledge')).not.toBeInTheDocument();
    const assertionSection = screen.getByRole('region', { name: 'memory.pages.knowledge.pagination.assertions' });
    expect(within(assertionSection).getByRole('status')).toBeInTheDocument();
    expect(within(assertionSection).queryByText('memory.pages.knowledge.emptyKnowledge')).not.toBeInTheDocument();
    expect(within(screen.getByRole('region', { name: 'memory.pages.knowledge.pagination.entities' })).getByText('memory.pages.knowledge.emptyKnowledge')).toBeInTheDocument();
    await user.click(within(relationshipSection).getByRole('button', { name: 'memory.pages.knowledge.pagination.retry' }));
    expect(relations.retry).toHaveBeenCalledOnce();
  });

  it('keeps canonical names readable outside the entity page and provides load more', async () => {
    const user = userEvent.setup();
    const relations = page<L2Relation>([{
      triple_id: 'relation:old', subject_id: 'person:opaque', subject_name: '小王', subject_type: 'person',
      predicate: 'LIVES_IN', object_id: 'place:opaque', object_name: '京都', object_type: 'place',
      confidence: 0.9, evidence_event_ids: [], observation_count: 1, first_observed_at: 1, last_observed_at: 1, status: 'superseded',
    }], { total: 51 });
    renderPages({ relations, assertions: page(), entities: page() });
    const section = screen.getByRole('region', { name: 'memory.pages.knowledge.pagination.relations' });
    expect(within(section).getByText('total:51')).toBeInTheDocument();
    expect(within(section).getByText('小王 京都')).toBeInTheDocument();
    expect(within(section).getByText(/memory\.pages\.knowledge\.statusOptions\.deprecated/)).toBeInTheDocument();
    await user.click(within(section).getByRole('button', { name: 'memory.pages.knowledge.pagination.loadMore' }));
    expect(relations.loadMore).toHaveBeenCalledOnce();
  });
});
