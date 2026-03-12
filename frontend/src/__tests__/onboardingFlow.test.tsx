import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { DEFAULT_SYSTEM_CONFIG } from '@/api/modules/config';
import OnboardingFlow from '@/components/onboarding/OnboardingFlow';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: {
      resolvedLanguage: 'zh-CN',
      language: 'zh-CN',
      changeLanguage: vi.fn(),
      on: vi.fn(),
      off: vi.fn(),
    },
  }),
}));

vi.mock('react-router-dom', () => ({
  useNavigate: () => vi.fn(),
}));

describe('OnboardingFlow', () => {
  it('uses a viewport-filling frame layout', () => {
    vi.stubGlobal('localStorage', {
      getItem: vi.fn(() => null),
      setItem: vi.fn(),
      removeItem: vi.fn(),
    });

    const { container } = render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);

    expect(container.innerHTML).toContain('min-h-[clamp(560px,78vh,760px)]');
    expect(screen.getByText('steps.language')).toBeInTheDocument();
  });
});
