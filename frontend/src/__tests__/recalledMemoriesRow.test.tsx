import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { RecalledMemoriesRow } from '@/components/chat/RecalledMemoriesRow';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (_key: string, options?: Record<string, unknown>) => {
      const template = String(options?.defaultValue ?? _key);
      return template.replace(/\{\{(\w+)\}\}/g, (_, name: string) => String(options?.[name] ?? ''));
    },
    i18n: { language: 'zh-CN' },
  }),
}));

const memory = {
  kind: 'event',
  sourceLayer: 'L1',
  statement: 'Visited example.com',
  topic: 'example.com',
  feedbackRef: 'event:event-1',
};

const scrollIntoViewMock = vi.fn();

describe('RecalledMemoriesRow', () => {
  beforeEach(() => {
    scrollIntoViewMock.mockClear();
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
      configurable: true,
      value: scrollIntoViewMock,
    });
  });

  it('keeps memory details collapsed until the summary is expanded', () => {
    render(<RecalledMemoriesRow memories={[memory]} />);

    const trigger = screen.getByRole('button', { name: '1 条记忆引用' });
    expect(trigger).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByText('Visited example.com')).not.toBeInTheDocument();

    fireEvent.click(trigger);

    expect(trigger).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText('Visited example.com')).toBeInTheDocument();
    expect(screen.getByTestId('recalled-memories-detail')).toHaveClass('mt-1', 'pb-4');
    expect(scrollIntoViewMock).toHaveBeenCalledWith({
      behavior: 'smooth',
      block: 'nearest',
    });

    fireEvent.click(trigger);

    expect(trigger).toHaveAttribute('aria-expanded', 'false');
    expect(scrollIntoViewMock).toHaveBeenCalledTimes(1);
  });

  it('keeps the visible disclosure close while preserving its click area', () => {
    render(<RecalledMemoriesRow memories={[memory]} />);

    const row = screen.getByTestId('recalled-memories-row');
    const trigger = screen.getByRole('button', { name: '1 条记忆引用' });

    expect(row).not.toHaveClass('mt-2');
    expect(trigger).toHaveClass(
      'relative',
      'items-center',
      'py-1',
      'after:-inset-y-1.5',
      "after:content-['']",
    );
  });

  it('separates expandable reference count from exhaustive coverage', () => {
    render(
      <RecalledMemoriesRow
        memories={[memory]}
        summary={{
          coverageKind: 'exhaustive',
          canClaimTotal: true,
          totalCount: 12,
          domain: 'browser',
        }}
      />,
    );

    const trigger = screen.getByRole('button', { name: '1 条记忆引用' });
    expect(screen.queryByText('共找到 12 条相关记录，本次引用 1 条')).not.toBeInTheDocument();

    fireEvent.click(trigger);

    expect(screen.getByText('共找到 12 条相关记录，本次引用 1 条')).toBeInTheDocument();
  });

  it('shows exhaustive coverage without an expand affordance when no references are available', () => {
    render(
      <RecalledMemoriesRow
        memories={[]}
        summary={{
          coverageKind: 'exhaustive',
          canClaimTotal: true,
          totalCount: 12,
          domain: 'browser',
        }}
      />,
    );

    expect(screen.getByText('已完整统计 12 条相关记录')).toBeInTheDocument();
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });

  it('starts item-level and answer-level rechecks with the targeted message', () => {
    const onStartFeedback = vi.fn();
    render(
      <RecalledMemoriesRow
        memories={[memory]}
        targetMessageId="assistant-1"
        targetMessageExcerpt="Previous answer"
        onStartFeedback={onStartFeedback}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: '1 条记忆引用' }));
    fireEvent.click(screen.getByRole('button', { name: 'chat.recallFeedback.itemAction' }));

    expect(onStartFeedback).toHaveBeenLastCalledWith({
      kind: 'item_irrelevant',
      targetMessageId: 'assistant-1',
      targetMessageExcerpt: 'Previous answer',
      findingRef: 'event:event-1',
      findingLabel: 'Visited example.com',
    });

    fireEvent.click(screen.getByRole('button', { name: 'chat.recallFeedback.answerAction' }));
    expect(onStartFeedback).toHaveBeenLastCalledWith({
      kind: 'answer_evidence_mismatch',
      targetMessageId: 'assistant-1',
      targetMessageExcerpt: 'Previous answer',
    });
  });

  it('keeps long cited records compact when starting a recheck', () => {
    const onStartFeedback = vi.fn();
    const longStatement = `A ${'very '.repeat(40)}long record`;
    render(
      <RecalledMemoriesRow
        memories={[{ ...memory, statement: longStatement }]}
        targetMessageId="assistant-1"
        onStartFeedback={onStartFeedback}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: '1 条记忆引用' }));
    fireEvent.click(screen.getByRole('button', { name: 'chat.recallFeedback.itemAction' }));

    const findingLabel = onStartFeedback.mock.calls[0][0].findingLabel as string;
    expect(findingLabel).toHaveLength(120);
    expect(findingLabel.endsWith('…')).toBe(true);
  });
});
