import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { LLMStatisticsSection } from '@/components/settings/LLMStatisticsSection';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

describe('LLMStatisticsSection', () => {
  it('renders the shared statistics frame regions', () => {
    render(<LLMStatisticsSection />);

    expect(screen.getByTestId('statistics-page-toolbar')).toBeInTheDocument();
    expect(screen.getByTestId('statistics-page-signal-ribbon')).toBeInTheDocument();
    expect(screen.getByTestId('statistics-page-main-canvas')).toBeInTheDocument();
    expect(screen.getByTestId('statistics-page-summary-rail')).toBeInTheDocument();
  });
});
