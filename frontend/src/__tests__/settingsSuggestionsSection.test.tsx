import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { SettingsSuggestionsSection } from '@/components/settings/SettingsSuggestionsSection';
import * as api from '@/api/modules/systemSuggestions';

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (k: string) => k }) }));

describe('SettingsSuggestionsSection', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(api, 'listDismissals').mockResolvedValue([
      { dedupe_key: 'browser_history', dismissed_at: 'x', kind: 'explicit' },
    ]);
    vi.spyOn(api, 'clearDismissal').mockResolvedValue();
  });

  it('lists dismissed suggestions and restores one', async () => {
    render(<SettingsSuggestionsSection />);
    expect(await screen.findByText('browser_history')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /settings\.suggestions\.restore/i }));
    await waitFor(() => expect(api.clearDismissal).toHaveBeenCalledWith('browser_history'));
  });
});
