import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { useState } from 'react';
import { SystemSuggestionTopBar } from '../components/chat/SystemSuggestionTopBar';
import { SystemSuggestionSideCard } from '../components/chat/SystemSuggestionSideCard';
import { useSystemSuggestions } from '../hooks/useSystemSuggestions';
import type { SuggestionProposal } from '../api/modules/systemSuggestions';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: 'zh-CN' } }),
}));

const mockCheck = vi.fn();
const mockDismiss = vi.fn();
vi.mock('../api/modules/systemSuggestions', () => ({
  checkSystemSuggestions: (args: any) => mockCheck(args),
  dismissSystemSuggestion: (args: any) => mockDismiss(args),
}));

const mockUseAvailability = vi.fn();
vi.mock('../hooks/useAvailability', () => ({
  useAvailability: (...args: any[]) => mockUseAvailability(...args),
}));

// Shim host that mirrors Chat.tsx's composition (top bar + side card)
function ChatSuggestionsHost({ triggerText }: { triggerText: string }) {
  const { proposals, dismiss } = useSystemSuggestions({ triggerText, locale: 'zh' });
  const [card, setCard] = useState<SuggestionProposal | null>(null);
  const top = proposals.length > 0 ? proposals[0] : null;
  return (
    <>
      <SystemSuggestionTopBar
        proposal={top}
        onOpen={setCard}
        onDismiss={(k, kind) => dismiss(k, kind)}
      />
      {card && (
        <SystemSuggestionSideCard
          proposal={card}
          onClose={() => setCard(null)}
          onDecline={(k) => { void dismiss(k, 'explicit'); setCard(null); }}
          onActivated={() => setCard(null)}
        />
      )}
    </>
  );
}

describe('Chat suggestions integration', () => {
  beforeEach(() => {
    mockCheck.mockReset();
    mockDismiss.mockReset();
    mockUseAvailability.mockReset();
  });

  it('renders top bar; click opens side card', async () => {
    mockCheck.mockResolvedValue([
      {
        dedupe_key: 'browser_history',
        category: 'browser_history',
        plugins: [{ plugin_id: 'chrome-history', name: 'Chrome History', name_i18n: {}, icon: 'brand:googlechrome', installed: true }],
        confidence: 0.9,
        rationale: { zh: '想看你的浏览', en: 'see your browsing' },
      },
    ]);
    mockUseAvailability.mockReturnValue({
      entries: [{ plugin_id: 'chrome-history', available: true, reason: 'available', detail: null, checked_at: 'now' }],
      byId: {}, loading: false, error: null, refresh: vi.fn(),
    });

    render(<ChatSuggestionsHost triggerText="我看了什么浏览" />);
    await waitFor(() => expect(screen.getByText(/想看你的浏览/)).toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: /想看你的浏览/ }));
    await waitFor(() => expect(screen.getAllByText(/想看你的浏览/).length).toBeGreaterThan(1));
  });

  it('dismiss × on top bar fires dismiss(transient)', async () => {
    mockCheck.mockResolvedValue([
      {
        dedupe_key: 'browser_history',
        category: 'browser_history',
        plugins: [{ plugin_id: 'chrome-history', name: 'Chrome History', name_i18n: {}, icon: 'brand:googlechrome', installed: true }],
        confidence: 0.9,
        rationale: { zh: '想看你的浏览', en: 'see your browsing' },
      },
    ]);
    mockDismiss.mockResolvedValue({ dedupe_key: 'browser_history', dismissed: true });
    mockUseAvailability.mockReturnValue({
      entries: [], byId: {}, loading: false, error: null, refresh: vi.fn(),
    });

    render(<ChatSuggestionsHost triggerText="我看了什么浏览" />);
    await waitFor(() => expect(screen.getByText(/想看你的浏览/)).toBeInTheDocument());
    await userEvent.click(screen.getAllByRole('button', { name: /systemSuggestion.dismiss|关闭|×/i })[0]);
    await waitFor(() => {
      expect(mockDismiss).toHaveBeenCalledWith({
        dedupe_key: 'browser_history',
        kind: 'transient',
      });
    });
  });
});
