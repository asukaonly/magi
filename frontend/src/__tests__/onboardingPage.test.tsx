import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import OnboardingPage from '@/pages/Onboarding';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

vi.mock('sonner', () => ({
  toast: {
    error: vi.fn(),
  },
}));

vi.mock('@/components/onboarding/OnboardingFlow', () => ({
  default: () => <div>onboarding-flow</div>,
}));

vi.mock('@/api/modules/config', async () => {
  const actual = await vi.importActual<typeof import('@/api/modules/config')>('@/api/modules/config');
  return {
    ...actual,
    configApi: {
      ...actual.configApi,
      getOnboardingTemplate: vi.fn().mockResolvedValue({
        data: {
          config: actual.DEFAULT_SYSTEM_CONFIG,
        },
      }),
    },
  };
});

describe('OnboardingPage', () => {
  it('centers the onboarding surface within the viewport', async () => {
    vi.stubGlobal('localStorage', {
      getItem: vi.fn(() => null),
      setItem: vi.fn(),
      removeItem: vi.fn(),
    });

    const { container } = render(<OnboardingPage />);

    await screen.findByText('onboarding-flow');

    const root = container.firstElementChild as HTMLElement | null;

    expect(root?.className).toContain('items-center');
    expect(root?.className).toContain('justify-center');
  });
});
