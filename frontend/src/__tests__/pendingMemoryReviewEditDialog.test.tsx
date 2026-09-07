import { describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { L2PendingReview } from '@/api/modules/memory';
import { PendingMemoryReviewEditDialog } from '@/pages/memory-pages/pending/PendingMemoryReviewEditDialog';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      const labels: Record<string, string> = {
        'memory.pending.reviewEdit.title': '修改后确认',
        'memory.pending.reviewEdit.description': '确认记录的事实',
        'memory.pending.reviewEdit.currentFact': '当前待确认事实',
        'memory.pending.reviewEdit.valueLabel': '记忆内容',
        'memory.pending.reviewEdit.confirm': '确认并写入',
        'memory.correction.values.like': '喜欢',
        'memory.correction.values.dislike': '不喜欢',
        'memory.correction.values.interested': '感兴趣',
        'memory.correction.values.unavailable': '当前选项暂不可用',
        'memory.facts.unavailable': '完整事实暂不可用',
      };
      return labels[key] ?? opts?.defaultValue ?? key;
    },
  }),
}));

const review: L2PendingReview = {
  review_id: 'review-strawberry',
  subject_id: 'user:self',
  kind: 'materialization',
  slot_key: 'preference.affinity',
  value_fingerprint: 'fingerprint',
  semantic_lineage_key: 'lineage',
  claim_ids: ['claim-strawberry'],
  reason_code: 'pending_confirmation',
  proposed: {
    trait_name: 'preference.affinity',
    trait_value: 'like',
    target_entity_id: 'food:strawberry',
    target_entity_name: '草莓',
    natural_summary: '用户喜欢草莓。',
    display_text: '用户喜欢草莓。',
    value_options: ['like', 'dislike'],
  },
  route_contract_version: 7,
  evidence_rule_version: 2,
  source_generation: 0,
  status: 'pending',
  version: 1,
  created_at: 1710000000,
  updated_at: 1710000000,
};

describe('PendingMemoryReviewEditDialog semantic values', () => {
  it('shows a complete read-only fact and only submits the selected structured value', async () => {
    const onSubmit = vi.fn();
    const user = userEvent.setup();
    render(<PendingMemoryReviewEditDialog review={review} busy={false} onOpenChange={vi.fn()} onSubmit={onSubmit} />);
    const dialog = screen.getByRole('dialog');
    expect(within(dialog).getByText('用户喜欢草莓。')).toBeInTheDocument();
    expect(within(dialog).queryByRole('textbox')).not.toBeInTheDocument();
    const select = within(dialog).getByRole('combobox', { name: '记忆内容' });
    expect(within(select).getByRole('option', { name: '喜欢' })).toBeInTheDocument();
    expect(dialog).not.toHaveTextContent(/\blike\b|food:strawberry/);
    await user.selectOptions(select, 'dislike');
    await user.click(within(dialog).getByRole('button', { name: '确认并写入' }));
    expect(onSubmit).toHaveBeenCalledWith({ trait_value: 'dislike' });
  });

  it('keeps a literal address in its structured input without replacing it with the summary', async () => {
    const onSubmit = vi.fn();
    const user = userEvent.setup();
    render(<PendingMemoryReviewEditDialog
      review={{ ...review, proposed: {
        trait_name: 'communication.address.preferred',
        trait_value: '小夏',
        natural_summary: '用户希望被称呼为小夏。',
        value_options: null,
      } }}
      busy={false}
      onOpenChange={vi.fn()}
      onSubmit={onSubmit}
    />);
    expect(screen.getByText('用户希望被称呼为小夏。')).toBeInTheDocument();
    const input = screen.getByRole('textbox', { name: '记忆内容' });
    expect(input).toHaveValue('小夏');
    await user.clear(input);
    await user.type(input, '夏夏');
    await user.click(screen.getByRole('button', { name: '确认并写入' }));
    expect(onSubmit).toHaveBeenCalledWith({ trait_value: '夏夏' });
  });

  it('shows an honest fallback for an unresolved fact without displaying semantic codes or IDs', () => {
    render(<PendingMemoryReviewEditDialog
      review={{ ...review, proposed: {
        trait_name: 'interest.attention',
        trait_value: 'interested',
        target_entity_id: 'entity:unresolved',
        value_options: ['interested'],
      } }}
      busy={false}
      onOpenChange={vi.fn()}
      onSubmit={vi.fn()}
    />);
    expect(screen.getByText('完整事实暂不可用')).toBeInTheDocument();
    expect(screen.getByRole('option', { name: '感兴趣' })).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent(/\binterested\b|entity:unresolved/);
  });
});
