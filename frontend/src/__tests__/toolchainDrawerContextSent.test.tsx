import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import ToolchainDrawer from '@/components/chat/ToolchainDrawer';
import { normalizeTraceSnapshot } from '@/domain/chat/state';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      if (!opts) return key;
      return Object.entries(opts).reduce(
        (acc, [k, v]) => `${acc} ${k}=${String(v)}`,
        key,
      );
    },
    i18n: { language: 'en' },
  }),
}));

describe('P1-D2 ToolchainDrawer Context Sent panel', () => {
  it('renders a collapsible Context Sent panel showing provider, redaction, brief, memory, and sections', () => {
    const snapshot = normalizeTraceSnapshot({
      turn_id: 'turn-1',
      user_id: 'local_user',
      session_id: 'sess-1',
      status: 'completed',
      mode: 'function_calling',
      summary: {
        turn_id: 'turn-1',
        mode: 'function_calling',
        status: 'completed',
        headline: 'Answered',
        active_steps: 0,
        completed_steps: 1,
        failed_steps: 0,
        duration_seconds: 1.2,
        trace_available: true,
        total_input_tokens: 400,
        total_output_tokens: 120,
      },
      root: {
        id: 'root-1',
        kind: 'root',
        label: 'Turn',
        status: 'completed',
        metadata: {},
        children: [
          {
            id: 'llm-1',
            kind: 'llm_call',
            label: 'LLM',
            status: 'completed',
            metadata: { provider: 'anthropic', model: 'claude-sonnet-4-6' },
            children: [],
          },
        ],
      },
      context_sent: {
        provider: 'anthropic',
        model: 'claude-sonnet-4-6',
        is_local_provider: false,
        redacted: true,
        excluded_local_only_count: 2,
        recent_life_brief_items: ['Browsing: Rust Async Book [chrome_history | evt-1]'],
        recalled_memory_items: ['Prefers concise TypeScript replies'],
        system_prompt_sections: [
          {
            title: 'System Definition',
            preview: 'Be grounded and truthful.',
            char_count: 25,
          },
        ],
        working_context_sections: [
          {
            title: 'Recent Authorized Activity (Background Only)',
            preview: '- Browsing: Rust Async Book',
            char_count: 27,
          },
        ],
        message_count: 2,
        captured_at: 1_760_000_000,
      },
    });

    expect(snapshot?.contextSent?.provider).toBe('anthropic');
    expect(snapshot?.contextSent?.redacted).toBe(true);

    render(
      <ToolchainDrawer
        open={true}
        onOpenChange={() => {}}
        loading={false}
        snapshot={snapshot}
        title="Call Trace"
        subtitle="Trace subtitle"
      />,
    );

    const toggleButton = screen.getByRole('button', { name: /chat\.trace\.contextSent\.title/i });
    expect(toggleButton).toHaveAttribute('aria-expanded', 'false');
    expect(screen.getByText('anthropic / claude-sonnet-4-6')).toBeInTheDocument();
    expect(screen.getByText('chat.trace.contextSent.cloudProvider')).toBeInTheDocument();
    expect(screen.getByText('chat.trace.contextSent.redactedBadge')).toBeInTheDocument();
    expect(screen.getByText(/chat\.trace\.contextSent\.excludedCount count=2/)).toBeInTheDocument();
    expect(screen.queryByText(/Rust Async Book/)).not.toBeInTheDocument();

    fireEvent.click(toggleButton);
    expect(toggleButton).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getAllByText(/Rust Async Book/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/Prefers concise TypeScript replies/)).toBeInTheDocument();
    expect(screen.getByText('System Definition')).toBeInTheDocument();
    expect(screen.getByText('Recent Authorized Activity (Background Only)')).toBeInTheDocument();
  });
});
