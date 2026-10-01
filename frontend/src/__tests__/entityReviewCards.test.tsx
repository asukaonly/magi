import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { EntityTypeReviewCards } from '@/components/memory/identity/EntityTypeReviewCards';
import type { EntityTypeReviewGroup } from '@/api/modules/entityIdentity';

vi.mock('react-i18next', async () => {
  const { default: zh } = await import('@/i18n/locales/zh-CN/app.json');
  const t = (key: string, opts?: Record<string, unknown>) => {
    const value = key.split('.').reduce<unknown>((v, part) => v && typeof v === 'object' ? Reflect.get(v, part) : undefined, zh);
    return String(value ?? key).replace(/\{\{(\w+)\}\}/g, (_, name: string) => String(opts?.[name] ?? ''));
  };
  return { useTranslation: () => ({ t }) };
});
vi.mock('@/components/memory/identity/EntityEvidence', () => ({ EntityEvidence: () => <p>Fixture evidence</p> }));

function group(id: string, types: string[]): EntityTypeReviewGroup {
  const entity = { entity_id: id, canonical_name: 'Atlas', entity_type: 'other' };
  return { entity, fingerprint: 'a'.repeat(64), proposals: types.map((type, index) => ({
    entity, review_id: `${id}-${index}`, proposed_type: type, evidence_event_ids: ['same-event'], version: 1,
  })) };
}

describe('grouped classification decisions', () => {
  it('requires a choice among conflicting proposals and shares duplicate evidence', async () => {
    const item = group('one', ['software', 'organization']);
    const inspect = vi.fn();
    render(<EntityTypeReviewCards reviews={[item]} busy={false} onInspect={inspect} onReject={vi.fn()} />);
    expect(screen.getByRole('button', {name: '选择建议分类'})).toBeDisabled();
    expect(screen.getByRole('button', {name: '来源依据 · 1 条'})).toBeInTheDocument();
    await userEvent.click(screen.getByRole('radio', {name: '组织'}));
    await userEvent.click(screen.getByRole('button', {name: '采纳“组织”…'}));
    expect(inspect).toHaveBeenCalledWith(item.proposals[1]);
  });

  it('keeps namesakes independent and rejects the complete chosen identity group', async () => {
    const first = group('one', ['software', 'organization']);
    const second = group('two', ['media']);
    const keep = vi.fn().mockResolvedValue(undefined);
    render(<EntityTypeReviewCards reviews={[first, second]} busy={false} onInspect={vi.fn()} onReject={keep} />);
    expect(screen.getAllByText('同名的不同记录')).toHaveLength(2);
    const articles = screen.getAllByRole('article');
    await userEvent.click(within(articles[1]).getByRole('button', {name: '保留“其他”'}));
    expect(keep).toHaveBeenCalledExactlyOnceWith(second);
  });

  it('disables decisions while another write is pending', () => {
    render(<EntityTypeReviewCards reviews={[group('one', ['software'])]} busy onInspect={vi.fn()} onReject={vi.fn()} />);
    expect(screen.getByRole('button', {name: '采纳“软件”…'})).toBeDisabled();
    expect(screen.getByRole('button', {name: '保留“其他”'})).toBeDisabled();
  });
});
