import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { AssistantRuntimePanel } from '@/components/chat/AssistantRuntimePanel';

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));

const statuses = [
  { source: 'assistant_tool_call', content: 'I will check the sources.' },
  { source: 'assistant_tool_call', content: 'The dates differ. I will check the original.' },
];
const reasoning = [{ source: 'chat', content: 'Compare the publication dates.' }];

describe('AssistantRuntimePanel', () => {
  it('shows only the latest narration and keeps reasoning and tools collapsed', async () => {
    render(<AssistantRuntimePanel streaming runtimeStatuses={statuses} reasoning={reasoning}
      toolCalls={[{ toolName: 'web-search', status: 'running', toolArgsText: 'private query' }]} />);

    expect(screen.getByRole('status')).toHaveTextContent(statuses[1].content);
    expect(screen.queryByText(statuses[0].content)).not.toBeInTheDocument();
    expect(screen.queryByText(reasoning[0].content)).not.toBeInTheDocument();
    expect(screen.queryByText('private query')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'chat.runtime.expand' }));
    expect(screen.getAllByText(statuses[1].content)).toHaveLength(1);
    expect(screen.getByText(statuses[0].content)).toBeInTheDocument();
    expect(screen.getByText(reasoning[0].content)).toBeInTheDocument();
    expect(screen.getByText('private query')).toBeInTheDocument();
  });

  it('uses dots for reasoning or internal status without promoting either to a progress note', () => {
    render(<AssistantRuntimePanel streaming reasoning={reasoning}
      runtimeStatuses={[{ source: 'completion_repair', content: 'Internal completion check' }]} shouldReduceMotion />);
    expect(screen.getByRole('status', { name: 'chat.runtime.preparing' })).toBeInTheDocument();
    expect(screen.queryByText(reasoning[0].content)).not.toBeInTheDocument();
    expect(screen.queryByText('Internal completion check')).not.toBeInTheDocument();
  });

  it('does not reopen manually collapsed details on incoming events and collapses on completion', async () => {
    const { rerender } = render(<AssistantRuntimePanel streaming runtimeStatuses={statuses} reasoning={reasoning} />);
    await userEvent.click(screen.getByRole('button', { name: 'chat.runtime.expand' }));
    await userEvent.click(screen.getByRole('button', { name: 'chat.runtime.collapse' }));
    rerender(<AssistantRuntimePanel streaming runtimeStatuses={statuses} reasoning={[...reasoning, { source: 'chat', content: 'More reasoning' }]} />);
    expect(screen.getByRole('button', { name: 'chat.runtime.expand' })).toHaveAttribute('aria-expanded', 'false');
    await userEvent.click(screen.getByRole('button', { name: 'chat.runtime.expand' }));
    rerender(<AssistantRuntimePanel streaming={false} runtimeStatuses={statuses} reasoning={reasoning} />);
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
    expect(screen.queryByText(statuses[1].content)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'chat.runtime.expand' })).toHaveAttribute('aria-expanded', 'false');
    await userEvent.click(screen.getByRole('button', { name: 'chat.runtime.expand' }));
    expect(screen.getByText(statuses[1].content)).toBeInTheDocument();
  });

  it('hides the summary when reply text starts without discarding activity', () => {
    const { rerender } = render(<AssistantRuntimePanel streaming runtimeStatuses={statuses} />);
    rerender(<AssistantRuntimePanel streaming showProgress={false} runtimeStatuses={statuses} />);
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
    expect(screen.queryByText(statuses[1].content)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'chat.runtime.expand' })).toBeInTheDocument();
  });
});
